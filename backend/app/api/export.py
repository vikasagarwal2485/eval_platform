from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import repo
from app.api.deps import get_session
from app.core import export as export_core
from app.core.summary import build_summary, compare_runs, parse_weights

router = APIRouter(prefix="/api")


@router.get("/runs/compare")
def compare(a: int, b: int, weights: str | None = None, session: Session = Depends(get_session)):
    """Deltas (B - A) for models and cases present in both runs. Registered before /runs/{id}."""
    try:
        w = parse_weights(weights)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return compare_runs(session, repo.get_run(session, a), repo.get_run(session, b), w)


@router.get("/runs/{run_id}/export")
def export_run(run_id: int, format: str = "csv", attempt: int | None = None, session: Session = Depends(get_session)):
    if format not in ("csv", "json"):
        raise HTTPException(422, "format must be csv or json")
    run = repo.get_run(session, run_id)
    rows = export_core.export_rows(session, run, attempt)
    fname = f"run-{run.id}.{format}"
    headers = {"Content-Disposition": f'attachment; filename="{fname}"'}
    if format == "csv":
        return Response(export_core.to_csv(rows), media_type="text/csv", headers=headers)
    import json

    payload = {
        "run": {
            "id": run.id,
            "name": run.name,
            "status": run.status,
            "config": run.config,
            "judge_model": run.judge_model,
            "ollama_version": run.ollama_version,
        },
        "summary": build_summary(session, run, attempt_id=attempt),
        "results": rows,
    }
    return Response(json.dumps(payload, indent=2, default=str), media_type="application/json", headers=headers)
