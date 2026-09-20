"""Sequential, model-grouped run worker (design D3).

One background task drains a FIFO queue, so at most one job touches Ollama at a time and measurements
are never disturbed by concurrent requests. Order: for model -> warm-up -> for case -> for repeat.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import repo
from app.config import Settings
from app.core.events import EventHub
from app.core.metrics import StreamCollector
from app.core.model_discovery import ModelDiscovery
from app.core.scoring import service as scoring
from app.core.scoring.thinking import split_thinking
from app.core.templates import build_messages, build_prompt
from app.models import ModelSnapshot, Run, RunCase
from app.ollama.client import OllamaClient, OllamaError, OllamaUnreachable
from app.schemas import RunConfig

log = logging.getLogger(__name__)

TERMINAL_STATUSES = ("completed", "cancelled", "failed")
WARMUP_PROMPT = "Reply with the single word: OK"
DELTA_INTERVAL_S = 0.1


class CancelledRun(Exception):
    pass


class RunAborted(Exception):
    """Unrecoverable failure (e.g. Ollama unreachable after retries); completed results are kept."""


@dataclass
class Job:
    kind: str  # "eval" | "rescore"
    run_id: int
    judge_model: str | None = None
    judge_reasoning: bool = False
    judge_mode: str | None = None  # none | single | cross_model (None = inferred from judge_model)


class Runner:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        ollama: OllamaClient,
        discovery: ModelDiscovery,
        hub: EventHub,
        settings: Settings,
    ):
        self.sf = session_factory
        self.ollama = ollama
        self.discovery = discovery
        self.hub = hub
        self.settings = settings
        self.queue: asyncio.Queue[Job] = asyncio.Queue()
        self._cancel: dict[int, asyncio.Event] = {}
        self._task: asyncio.Task | None = None
        self._running = 0
        self.max_concurrent_jobs = 0  # observed; must stay 1

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        with self.sf() as session:  # runs interrupted by a restart cannot resume
            for run in session.scalars(select(Run).where(Run.status.in_(("queued", "running")))):
                repo.set_run_status(session, run.id, "failed", error="Interrupted: the application restarted")
            session.commit()
        self._task = asyncio.create_task(self._worker(), name="eval-runner")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    def submit(self, job: Job) -> None:
        self._cancel[job.run_id] = asyncio.Event()
        self.hub.begin(job.run_id)
        self.hub.publish(job.run_id, "queued", {"kind": job.kind, "position": self.queue.qsize() + 1})
        self.queue.put_nowait(job)

    def is_busy(self, run_id: int) -> bool:
        return run_id in self._cancel

    def cancel(self, run_id: int) -> str:
        """Returns 'cancelled' (was queued), 'cancelling' (in flight) or 'inactive'."""
        ev = self._cancel.get(run_id)
        if ev is None:
            return "inactive"
        ev.set()
        with self.sf() as session:
            run = repo.get_run(session, run_id)
            if run.status == "queued":
                repo.set_run_status(session, run_id, "cancelled")
                session.commit()
                self.hub.publish(run_id, "run_finished", {"status": "cancelled"})
                return "cancelled"
        return "cancelling"

    # ------------------------------------------------------------------ worker
    async def _worker(self) -> None:
        while True:
            job = await self.queue.get()
            self._running += 1
            self.max_concurrent_jobs = max(self.max_concurrent_jobs, self._running)
            try:
                await self._run_job(job)
            except asyncio.CancelledError:
                raise
            except Exception:  # never let one job kill the worker
                log.exception("job %s failed unexpectedly", job)
            finally:
                self._running -= 1
                self._cancel.pop(job.run_id, None)
                self.queue.task_done()

    async def _run_job(self, job: Job) -> None:
        with self.sf() as session:
            if job.kind == "eval":
                await self._execute_eval(session, job)
            else:
                await self._execute_rescore(session, job)

    def _cancelled(self, run_id: int) -> bool:
        ev = self._cancel.get(run_id)
        return bool(ev and ev.is_set())

    # ------------------------------------------------------------------ eval
    async def _execute_eval(self, session: Session, job: Job) -> None:
        run_id = job.run_id
        run = repo.get_run(session, run_id)
        if run.status != "queued":  # cancelled while waiting
            return
        cfg = RunConfig(**run.config)
        cases = list(run.cases)
        snaps = repo.run_snapshots(session, run)
        total = len(snaps) * len(cases) * cfg.repeats
        attempt = repo.create_attempt(session, run_id, run.judge_model, run.judge_mode)
        repo.set_run_status(session, run_id, "running")
        try:
            run.ollama_version = await self.ollama.version()
        except OllamaError:
            pass
        session.commit()
        self.hub.publish(
            run_id, "run_started", {"total": total, "models": [s.name for s in snaps], "cases": len(cases)}
        )

        status, error = "completed", None
        completed = 0
        try:
            for idx, snap in enumerate(snaps):
                if self._cancelled(run_id):
                    raise CancelledRun()
                if idx > 0:
                    await self._unload_quietly(snaps[idx - 1].name)
                self.hub.publish(run_id, "model_started", {"model": snap.name, "index": idx, "of": len(snaps)})
                footprint_done = False
                if cfg.warmup:
                    await self._warmup(run_id, snap, cfg)
                    await self._record_footprint(session, run_id, snap)
                    footprint_done = True
                for case in cases:
                    for rep in range(cfg.repeats):
                        if self._cancelled(run_id):
                            raise CancelledRun()
                        await self._one_request(session, run, attempt.id, snap, case, rep, cfg)
                        completed += 1
                        self.hub.publish(run_id, "progress", {"completed": completed, "total": total})
                        if not footprint_done:
                            await self._record_footprint(session, run_id, snap)
                            footprint_done = True
            # ---- judge stage (after all generation)
            self.hub.publish(run_id, "scoring_started", {"judge_model": run.judge_model, "judge_mode": run.judge_mode})
            finished = await self._judge_stage(session, run, attempt.id, cfg)
            if not finished:
                raise CancelledRun()
        except CancelledRun:
            status = "cancelled"
        except (RunAborted, OllamaUnreachable) as exc:
            status, error = "failed", str(exc)
        except Exception as exc:  # noqa: BLE001
            log.exception("run %s crashed", run_id)
            status, error = "failed", f"Unexpected error: {exc}"
        session.rollback()
        repo.set_run_status(session, run_id, status, error=error)
        session.commit()
        self.hub.publish(run_id, "run_finished", {"status": status, "error": error})

    async def _unload_quietly(self, name: str) -> None:
        try:
            await self.ollama.unload(name)
        except OllamaError as exc:
            log.warning("could not unload %s: %s", name, exc)

    async def _warmup(self, run_id: int, snap: ModelSnapshot, cfg: RunConfig) -> None:
        """Loads the model with the run's exact options (a different num_ctx would force a reload)."""
        think = False if "thinking" in snap.capabilities else None
        try:
            agen = self.ollama.chat_stream(
                model=snap.name,
                messages=build_messages(None, WARMUP_PROMPT),
                options=self._options(cfg, num_predict=16),
                think=think,
            )
            async for _ in agen:
                pass
        except OllamaUnreachable:
            raise
        except OllamaError as exc:
            log.warning("warm-up of %s failed: %s", snap.name, exc)
            self.hub.publish(run_id, "warning", {"model": snap.name, "message": f"warm-up failed: {exc}"})

    async def _record_footprint(self, session: Session, run_id: int, snap: ModelSnapshot) -> None:
        try:
            loaded = await self.ollama.ps()
        except OllamaError:
            return
        for m in loaded:
            if m.get("name") == snap.name or m.get("model") == snap.name:
                run = repo.get_run(session, run_id)
                run.footprints = {
                    **run.footprints,
                    str(snap.id): {"size": m.get("size"), "size_vram": m.get("size_vram")},
                }
                session.commit()
                return

    @staticmethod
    def _options(cfg: RunConfig, num_predict: int | None = None) -> dict:
        return {
            "temperature": cfg.temperature,
            "seed": cfg.seed,
            "num_predict": num_predict or cfg.max_output_tokens,
            "num_ctx": cfg.num_ctx,
        }

    async def _one_request(
        self, session: Session, run: Run, attempt_id: int, snap: ModelSnapshot, case: RunCase, rep: int, cfg: RunConfig
    ) -> None:
        """Execute, persist and score one request; raises RunAborted if Ollama became unreachable."""
        run_id = run.id
        self.hub.publish(
            run_id,
            "request_started",
            {"model": snap.name, "case_id": case.id, "case_title": case.title or case.prompt[:60], "repeat": rep},
        )
        sent, version = build_prompt(case.category, case.prompt, case.config)
        fields = await self._generate(run_id, snap, case, sent, cfg)
        fatal = fields.pop("fatal", None)
        m = fields["metrics"]
        result = repo.add_result(
            session,
            run_id=run_id,
            model_snapshot_id=snap.id,
            run_case_id=case.id,
            repeat_idx=rep,
            sent_prompt=sent,
            template_version=version,
            is_cold=m.get("is_cold", False),
            latency_ms=m.get("latency_ms"),
            ttft_ms=m.get("ttft_ms"),
            tokens_per_s=m.get("tokens_per_s"),
            output_tokens=m.get("output_tokens"),
            **fields,
        )
        scores = scoring.score_live(session, attempt_id, case, result)
        session.commit()
        primary = next((s for s in scores if s.kind == scoring.primary_kind(case.category)), None)
        self.hub.publish(
            run_id,
            "result_completed",
            {
                "result_id": result.id,
                "model": snap.name,
                "case_id": case.id,
                "repeat": rep,
                "status": result.status,
                "outcome": primary.outcome if primary else None,
                "value": primary.value if primary else None,
                "latency_ms": result.latency_ms,
                "tokens_per_s": result.tokens_per_s,
                "is_cold": result.is_cold,
                "error": result.error,
            },
        )
        if fatal:
            raise RunAborted(fatal)

    async def _generate(self, run_id: int, snap: ModelSnapshot, case: RunCase, sent: str, cfg: RunConfig) -> dict:
        """Stream one chat request. Returns Result fields; never raises for per-request failures.
        Connection loss is retried, then reported via `fatal`."""
        think = cfg.think if "thinking" in snap.capabilities else None
        timeout = cfg.request_timeout_s or self.settings.request_timeout_s
        messages = build_messages(case.system_prompt, sent)
        retries = 0
        while True:
            col = StreamCollector()
            try:
                async with asyncio.timeout(timeout):
                    agen = self.ollama.chat_stream(
                        model=snap.name, messages=messages, options=self._options(cfg), think=think
                    )
                    last_pub = 0.0
                    pending: dict[str, str] = {"answer": "", "thinking": ""}
                    try:
                        async for chunk in agen:
                            col.feed(chunk)
                            msg = chunk.get("message") or {}
                            pending["answer"] += msg.get("content") or ""
                            pending["thinking"] += msg.get("thinking") or ""
                            now = time.monotonic()
                            if now - last_pub >= DELTA_INTERVAL_S and (pending["answer"] or pending["thinking"]):
                                self.hub.publish(run_id, "token", {"model": snap.name, "case_id": case.id, **pending})
                                pending, last_pub = {"answer": "", "thinking": ""}, now
                            if self._cancelled(run_id):
                                raise CancelledRun()
                        if pending["answer"] or pending["thinking"]:
                            self.hub.publish(run_id, "token", {"model": snap.name, "case_id": case.id, **pending})
                    finally:
                        await agen.aclose()
                if col.final is None:
                    raise OllamaError("stream ended without a final chunk")
                answer, trace = split_thinking(col.text, col.thinking_text)
                return {"status": "ok", "output": answer, "thinking": trace, "error": None, "metrics": col.finish()}
            except CancelledRun:
                raise
            except TimeoutError:
                return self._error_fields(col, f"Request timed out after {timeout:g}s")
            except OllamaUnreachable as exc:
                retries += 1
                if retries <= self.settings.max_retries:
                    await asyncio.sleep(self.settings.retry_backoff_s * retries)
                    continue
                out = self._error_fields(col, str(exc))
                out["fatal"] = f"Ollama unreachable after {retries} attempts: {exc}"
                return out
            except OllamaError as exc:
                return self._error_fields(col, str(exc))

    @staticmethod
    def _error_fields(col: StreamCollector, message: str) -> dict:
        answer, trace = split_thinking(col.text, col.thinking_text)
        return {"status": "error", "output": answer, "thinking": trace, "error": message, "metrics": col.failed()}

    # ------------------------------------------------------------------ judge stage / rescore
    async def _think_map(self, names: list[str]) -> dict[str, bool | None]:
        """`think` setting per judge: off for thinking-capable models (fast, structured JSON), else unset."""
        out: dict[str, bool | None] = dict.fromkeys(names)
        try:
            for m in await self.discovery.list_models():
                if m.name in out and m.thinking:
                    out[m.name] = False
        except OllamaError:
            pass
        return out

    async def _judge_names(self, session: Session, run_id: int, mode: str, judge_model: str | None) -> list[str]:
        if mode == "cross_model":
            return [s.name for s in repo.run_snapshots(session, repo.get_run(session, run_id))]
        return [judge_model] if judge_model else []

    async def _judge_stage(self, session: Session, run: Run, attempt_id: int, cfg: RunConfig) -> bool:
        run_id = run.id

        async def progress(done: int, total: int) -> None:
            self.hub.publish(run_id, "scoring_progress", {"done": done, "total": total})

        return await scoring.judge_run(
            session,
            self.ollama,
            run_id=run_id,
            attempt_id=attempt_id,
            judge_mode=run.judge_mode,
            judge_model=run.judge_model,
            judge_think=await self._think_map(
                await self._judge_names(session, run_id, run.judge_mode, run.judge_model)
            ),
            judge_reasoning=cfg.judge_reasoning,
            cancelled=lambda: self._cancelled(run_id),
            on_progress=progress,
            unload=self._unload_quietly,
        )

    async def _execute_rescore(self, session: Session, job: Job) -> None:
        run_id = job.run_id
        mode = job.judge_mode or repo.default_judge_mode(job.judge_model)
        self.hub.publish(run_id, "rescore_started", {"judge_model": job.judge_model, "judge_mode": mode})
        attempt_id, error = None, None
        try:

            async def progress(done: int, total: int) -> None:
                self.hub.publish(run_id, "scoring_progress", {"done": done, "total": total})

            attempt_id = await scoring.rescore_run(
                session,
                self.ollama,
                run_id=run_id,
                judge_mode=mode,
                judge_model=job.judge_model,
                judge_think=await self._think_map(await self._judge_names(session, run_id, mode, job.judge_model)),
                judge_reasoning=job.judge_reasoning,
                cancelled=lambda: self._cancelled(run_id),
                on_progress=progress,
                unload=self._unload_quietly,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("rescore of run %s failed", run_id)
            session.rollback()
            error = str(exc)
        self.hub.publish(run_id, "rescore_finished", {"attempt_id": attempt_id, "error": error})
