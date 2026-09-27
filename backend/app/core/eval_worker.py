"""Background worker that turns pending turn evaluations into judgements (design D7, spec `live-evaluation`).

One tick: sweep abandoned turns, apply the backlog cap, then - only when no benchmark run is measuring - evaluate
whatever has cleared its quiet period, one evaluator call at a time, grouped by evaluator so each is loaded once.
Every judgement is committed as it completes; aggregates are rebuilt in a `finally` so a crash or cancellation
mid-tick keeps whatever was already judged (mirrors `judge_run` for benchmark runs).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from app import repo
from app.core.eval_context import build_judge_call
from app.core.eval_resolution import resolve_evaluators
from app.core.model_discovery import ModelDiscovery
from app.core.scoring.judge import run_judge
from app.models import AgentTurn
from app.ollama.client import OllamaUnreachable
from app.providers.backend import ModelRouter
from app.providers.errors import ModelBackendError
from app.providers.refs import is_cloud_ref

log = logging.getLogger(__name__)

IsMeasuring = Callable[[], bool]


@dataclass
class TickStats:
    evaluated: int = 0
    skipped: int = 0
    backlog_skipped: int = 0
    abandoned: int = 0
    deferred_measuring: bool = False


@dataclass
class _Task:
    evaluation_id: int
    turn_id: int
    judge_model: str


class EvaluationWorker:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        router: ModelRouter,
        discovery: ModelDiscovery,
        *,
        is_measuring: IsMeasuring = lambda: False,
        tick_interval_s: float = 2.0,
        batch_limit: int = 50,
        backlog_cap: int = 500,
        on_event: Callable[[int, str, dict], Awaitable[None]] | None = None,
    ):
        self.sf = session_factory
        self.router = router
        self.discovery = discovery
        self.is_measuring = is_measuring
        self.tick_interval_s = tick_interval_s
        self.batch_limit = batch_limit
        self.backlog_cap = backlog_cap
        self.on_event = on_event
        self._task: asyncio.Task | None = None
        self._pending_events: list[tuple[int, str, dict]] = []
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        with self.sf() as session:
            repo.reset_running_evaluations(session)  # an evaluation interrupted mid-run retries, not stuck
            session.commit()
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="eval-worker")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # never let one bad tick kill the worker
                log.exception("evaluation tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.tick_interval_s)
            except TimeoutError:
                pass

    # ------------------------------------------------------------------ one tick (public: tests call it directly)
    async def tick(self) -> TickStats:
        stats = TickStats()
        self._pending_events: list[tuple[int, str, dict]] = []
        with self.sf() as session:
            stats.abandoned = len(repo.sweep_abandoned_turns(session))
            session.commit()

        if self.is_measuring():
            stats.deferred_measuring = True
            return stats

        with self.sf() as session:
            stats.backlog_skipped = repo.apply_evaluation_backlog_cap(session, cap=self.backlog_cap)
            session.commit()
            ready = repo.list_ready_pending_evaluations(session, limit=self.batch_limit)
            if not ready:
                return stats

            installed, digests, thinking = await self._model_facts()
            tasks, touched_ids, order = self._plan(session, ready, stats, installed=installed, digests=digests)
            await self._run_tasks(session, order, tasks, thinking, stats)
            self._finalize(session, touched_ids)
            session.commit()
        if self.on_event:
            for agent_id, type_, data in self._pending_events:
                await self.on_event(agent_id, type_, data)
        return stats

    async def _model_facts(self) -> tuple[set[str], dict[str, str], dict[str, bool]]:
        try:
            infos = await self.discovery.list_models()
        except Exception:  # Ollama unreachable: local evaluators become unavailable this tick, not fatal
            infos = []
        return ({m.name for m in infos}, {m.name: m.digest for m in infos}, {m.name: m.thinking for m in infos})

    def _plan(self, session, ready, stats, *, installed, digests):
        tasks: list[_Task] = []
        touched_ids: list[int] = []
        order: list[str] = []
        for ev in ready:
            turn = ev.turn
            repo.set_evaluation_status(session, ev.id, "running")
            resolved = resolve_evaluators(
                self.router,
                ev.evaluators,
                turn.models,
                models_unknown=turn.models_unknown,
                digest_of=digests.get,
                installed_local=installed,
            )
            if resolved.skip_reason:
                repo.set_evaluation_status(session, ev.id, "skipped", skip_reason=resolved.skip_reason)
                stats.skipped += 1
                self._pending_events.append(
                    (turn.agent_id, "evaluation_finished", {"turn_id": turn.id, "status": "skipped"})
                )
                continue
            touched_ids.append(ev.id)
            for name in resolved.available:
                tasks.append(_Task(ev.id, turn.id, name))
                if name not in order:
                    order.append(name)
        session.commit()
        return tasks, touched_ids, order

    async def _run_tasks(self, session: Session, order: list[str], tasks: list[_Task], thinking: dict, stats: TickStats):
        by_model: dict[str, list[_Task]] = {}
        for t in tasks:
            by_model.setdefault(t.judge_model, []).append(t)

        previous: str | None = None
        for name in order:
            if self._stop.is_set():
                break
            if previous is not None:
                await self._unload_quietly(previous)
            previous = name
            think = None if is_cloud_ref(name) else (False if thinking.get(name) else None)
            for t in by_model.get(name, []):
                if self._stop.is_set():
                    break
                try:
                    await self._run_one(session, t, name, think)
                except OllamaUnreachable as exc:
                    log.warning("evaluator %s unreachable, pausing until next tick: %s", name, exc)
                    return
                stats.evaluated += 1

    async def _run_one(self, session: Session, t: _Task, judge_model: str, think: bool | None) -> None:
        ev = repo.get_evaluation(session, t.evaluation_id)
        turn: AgentTurn = repo.get_turn(session, t.turn_id)
        agent = turn.agent
        context_turns = int((agent.eval_config or {}).get("context_turns", 4))
        prior = repo.list_prior_turns(session, turn, limit=context_turns)
        call = build_judge_call(turn, prior, ev.rubric, context_turns=context_turns)
        score, metrics = await run_judge(self.router, judge_model, call, think=think)
        score.detail["judge_metrics"] = metrics
        repo.add_turn_judgement(
            session, t.evaluation_id, judge_model=judge_model, value=score.value, outcome=score.outcome,
            detail=score.detail,
        )
        session.commit()
        if self.on_event:
            await self.on_event(
                turn.agent_id, "evaluation_progress",
                {"turn_id": turn.id, "evaluation_id": ev.id, "judge_model": judge_model},
            )

    def _finalize(self, session: Session, touched_ids: list[int]) -> None:
        """Rebuilds the aggregate for every evaluation that got at least one judgement this tick; an evaluation
        that made no progress at all (e.g. an unreachable evaluator on its very first task) goes back to pending
        so the next tick retries it, rather than being stranded as `running` (design D7)."""
        for eid in touched_ids:
            ev = repo.get_evaluation(session, eid)
            if ev.status != "running":
                continue
            if repo.list_turn_judgements(session, eid):
                ev = repo.rebuild_evaluation_aggregate(session, eid)
                self._pending_events.append(
                    (ev.turn.agent_id, "evaluation_finished", {"turn_id": ev.turn_id, "status": ev.status, "value": ev.value})
                )
            else:
                repo.set_evaluation_status(session, eid, "pending")

    async def _unload_quietly(self, name: str) -> None:
        try:
            await self.router.unload(name)
        except ModelBackendError as exc:
            log.warning("could not unload evaluator %s: %s", name, exc)
