from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import repo
from app.api.deps import get_session
from app.core.runner import TERMINAL_STATUSES, Job
from app.core.scoring.judging import resolve_judging
from app.core.scoring.service import primary_kind
from app.core.summary import build_summary, parse_weights
from app.models import Result, Run
from app.ollama.client import OllamaError, OllamaUnreachable
from app.repo import CaseSource
from app.schemas import CaseIn, RunConfig, RunCreate

router = APIRouter(prefix="/api")


def _err(status: int, code: str, message: str, **extra):
    return JSONResponse(status_code=status, content={"detail": {"code": code, "message": message, **extra}})


async def _installed(request: Request):
    try:
        return {m.name: m for m in await request.app.state.discovery.list_models()}
    except OllamaUnreachable as exc:
        raise HTTPException(
            503,
            detail={
                "code": "ollama_unreachable",
                "message": str(exc),
                "base_url": request.app.state.settings.ollama_base_url,
            },
        ) from None


def _progress(session: Session, run: Run) -> dict:
    done = session.scalar(select(func.count()).select_from(Result).where(Result.run_id == run.id)) or 0
    cfg = RunConfig(**run.config)
    return {"completed": done, "total": len(run.model_ids) * len(run.cases) * cfg.repeats}


def run_out(session: Session, run: Run, *, detail: bool = False, request: Request | None = None) -> dict:
    snaps = repo.run_snapshots(session, run)
    out = {
        "id": run.id,
        "name": run.name,
        "status": run.status,
        "config": run.config,
        "judge_model": run.judge_model,
        "judge_mode": run.judge_mode,
        "models": [
            {
                "id": s.id,
                "name": s.name,
                "digest": s.digest,
                "parameter_size": s.parameter_size,
                "quantization": s.quantization,
                "family": s.family,
                "size_bytes": s.size_bytes,
                "thinking": "thinking" in (s.capabilities or []),
                "memory": run.footprints.get(str(s.id)),
            }
            for s in snaps
        ],
        "case_count": len(run.cases),
        "progress": _progress(session, run),
        "error": run.error,
        "ollama_version": run.ollama_version,
        "parent_run_id": run.parent_run_id,
        "created_at": run.created_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
    if detail:
        out["cases"] = [
            {
                "id": c.id,
                "position": c.position,
                "category": c.category,
                "title": c.title,
                "prompt": c.prompt,
                "system_prompt": c.system_prompt,
                "expected": c.expected,
                "config": c.config,
                "rubric": c.rubric,
            }
            for c in run.cases
        ]
        if request is not None:
            out["current"] = request.app.state.hub.current(run.id)
            out["busy"] = request.app.state.runner.is_busy(run.id)
    return out


def _collect_cases(session: Session, body: RunCreate) -> list[CaseSource]:
    seen: set[int] = set()
    out: list[CaseSource] = []

    def add(row) -> None:
        if row.id not in seen:
            seen.add(row.id)
            out.append(CaseSource(CaseIn.from_row(row), row.id))

    excluded = set(body.exclude_case_ids)
    for sid in body.suite_ids:
        for c in repo.get_suite(session, sid).cases:
            if c.id not in excluded:
                add(c)
    for cid in body.case_ids:
        add(repo.get_case(session, cid))
    out.extend(CaseSource(a, None) for a in body.adhoc_cases)
    return out


@router.post("/runs", status_code=201)
async def create_run(body: RunCreate, request: Request, session: Session = Depends(get_session)):
    names = list(dict.fromkeys(body.models))
    if not names:
        return _err(422, "no_models", "Select at least one model.")
    try:
        mode, judge_model = resolve_judging(body.judge_mode, body.judge_model, names)
    except ValueError as exc:
        return _err(422, "invalid_judging", str(exc))
    cases = _collect_cases(session, body)
    if not cases:
        return _err(422, "no_cases", "Select at least one test case or enter an ad-hoc prompt.")
    installed = await _installed(request)
    missing = [n for n in names + ([judge_model] if judge_model else []) if n not in installed]
    if missing:
        return _err(422, "model_not_installed", f"Not installed in Ollama: {', '.join(missing)}", models=missing)
    snaps = [repo.get_or_create_snapshot(session, installed[n]) for n in names]
    try:
        version = await request.app.state.ollama.version()
    except OllamaError:
        version = None
    run = repo.create_run(
        session,
        name=body.name,
        config=body.config.model_dump(),
        judge_model=judge_model,
        judge_mode=mode,
        snapshots=snaps,
        cases=cases,
        ollama_version=version,
    )
    run.name = run.name or f"Run #{run.id}"
    session.commit()  # the worker reads it from another connection: commit before submitting
    request.app.state.runner.submit(Job("eval", run.id))
    return run_out(session, run, detail=True, request=request)


@router.get("/runs")
def list_runs(session: Session = Depends(get_session)):
    return [run_out(session, r) for r in repo.list_runs(session)]


@router.get("/runs/{run_id}")
def get_run(run_id: int, request: Request, session: Session = Depends(get_session)):
    return run_out(session, repo.get_run(session, run_id), detail=True, request=request)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: int, request: Request, session: Session = Depends(get_session)):
    repo.get_run(session, run_id)
    outcome = request.app.state.runner.cancel(run_id)
    if outcome == "inactive":
        raise repo.Conflict("Run is not queued or running")
    return {"status": outcome}


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(run_id: int, request: Request, session: Session = Depends(get_session)):
    run = repo.get_run(session, run_id)
    if request.app.state.runner.is_busy(run_id) or run.status in ("queued", "running"):
        raise repo.Conflict("Cancel the run before deleting it")
    repo.delete_run(session, run_id)


@router.post("/runs/{run_id}/rerun", status_code=201)
async def rerun(run_id: int, request: Request, session: Session = Depends(get_session)):
    """New run with the same models, frozen cases, configuration and judge; linked via parent_run_id."""
    orig = repo.get_run(session, run_id)
    installed = await _installed(request)
    names = [s.name for s in repo.run_snapshots(session, orig)]
    missing = [n for n in names + ([orig.judge_model] if orig.judge_model else []) if n not in installed]
    if missing:
        raise repo.Conflict(f"Cannot re-run: no longer installed: {', '.join(missing)}")
    snaps = [repo.get_or_create_snapshot(session, installed[n]) for n in names]
    cases = [CaseSource(CaseIn.from_row(c), c.source_case_id) for c in orig.cases]
    run = repo.create_run(
        session,
        name="",
        config=dict(orig.config),
        judge_model=orig.judge_model,
        judge_mode=orig.judge_mode,
        snapshots=snaps,
        cases=cases,
        parent_run_id=orig.id,
        ollama_version=orig.ollama_version,
    )
    run.name = f"{orig.name} (re-run)"
    session.commit()
    request.app.state.runner.submit(Job("eval", run.id))
    return run_out(session, run, detail=True, request=request)


class RescoreBody(BaseModel):
    judge_model: str | None = None
    judge_reasoning: bool = False
    judge_mode: Literal["none", "single", "cross_model"] | None = None


@router.post("/runs/{run_id}/rescore", status_code=202)
async def rescore(run_id: int, body: RescoreBody, request: Request, session: Session = Depends(get_session)):
    """New scoring attempt over the stored outputs; results and performance metrics are untouched."""
    run = repo.get_run(session, run_id)
    if run.status not in TERMINAL_STATUSES or request.app.state.runner.is_busy(run_id):
        raise repo.Conflict("Only finished runs that are not being processed can be re-scored")
    names = [s.name for s in repo.run_snapshots(session, run)]
    try:
        mode, judge_model = resolve_judging(body.judge_mode, body.judge_model, names)
    except ValueError as exc:
        return _err(422, "invalid_judging", str(exc))
    if judge_model:
        if judge_model not in await _installed(request):
            return _err(422, "model_not_installed", f"Not installed in Ollama: {judge_model}", models=[judge_model])
    request.app.state.runner.submit(Job("rescore", run_id, judge_model, body.judge_reasoning, mode))
    return {"status": "queued"}


@router.get("/runs/{run_id}/events")
async def run_events(run_id: int, request: Request, after: int = 0):
    """Server-Sent Events. Hints only - the source of truth is GET /api/runs/{id}."""
    hub, factory = request.app.state.hub, request.app.state.session_factory
    with factory() as session:
        run = repo.get_run(session, run_id)
        state = {
            "status": run.status,
            "progress": _progress(session, run),
            "current": hub.current(run_id),
            "busy": request.app.state.runner.is_busy(run_id),
        }
    try:
        after = max(after, int(request.headers.get("last-event-id", 0)))
    except ValueError:
        pass

    async def stream():
        yield f"event: state\ndata: {json.dumps(state)}\n\n"
        async for ev in hub.subscribe(run_id, after):
            yield f"id: {ev.id}\nevent: {ev.type}\ndata: {json.dumps(ev.data)}\n\n"

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.get("/runs/{run_id}/results")
def run_results(
    run_id: int,
    attempt: int | None = None,
    model: str | None = None,
    category: str | None = None,
    outcome: str | None = None,
    session: Session = Depends(get_session),
):
    run = repo.get_run(session, run_id)
    att = (
        next((a for a in repo.list_attempts(session, run_id) if a.id == attempt), None)
        if attempt
        else repo.latest_attempt(session, run_id)
    )
    scores: dict[int, list] = {}
    if att:
        for s in repo.list_scores(session, run_id, att.id):
            scores.setdefault(s.result_id, []).append(s)
    cases = {c.id: c for c in run.cases}
    names = {s.id: s.name for s in repo.run_snapshots(session, run)}
    out = []
    for r in repo.list_results(session, run_id):
        case = cases[r.run_case_id]
        if model and names[r.model_snapshot_id] != model or category and case.category != category:
            continue
        rs = scores.get(r.id, [])
        prim = next((s for s in rs if s.kind == primary_kind(case.category)), None)
        if outcome and (prim.outcome if prim else "unscored") != outcome:
            continue
        out.append(
            {
                "id": r.id,
                "model": names[r.model_snapshot_id],
                "model_id": r.model_snapshot_id,
                "case_id": case.id,
                "category": case.category,
                "repeat": r.repeat_idx,
                "status": r.status,
                "output": r.output,
                "thinking": r.thinking,
                "error": r.error,
                "is_cold": r.is_cold,
                "sent_prompt": r.sent_prompt,
                "template_version": r.template_version,
                "latency_ms": r.latency_ms,
                "ttft_ms": r.ttft_ms,
                "tokens_per_s": r.tokens_per_s,
                "output_tokens": r.output_tokens,
                "metrics": r.metrics,
                "scores": [{"kind": s.kind, "value": s.value, "outcome": s.outcome, "detail": s.detail} for s in rs],
                "primary": {"value": prim.value, "outcome": prim.outcome}
                if prim
                else {"value": None, "outcome": "unscored"},
            }
        )
    return {"attempt_id": att.id if att else None, "results": out}


@router.get("/runs/{run_id}/summary")
def run_summary(
    run_id: int,
    weights: str | None = None,
    attempt: int | None = None,
    include_cold: bool = False,
    session: Session = Depends(get_session),
):
    run = repo.get_run(session, run_id)
    try:
        w = parse_weights(weights)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return build_summary(session, run, attempt_id=attempt, weights=w, include_cold=include_cold)
