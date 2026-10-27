from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.tempo.client import TempoError, TempoUnreachable

router = APIRouter(prefix="/api")


@router.get("/traces/{trace_id}")
async def get_trace(request: Request, trace_id: str):
    """Proxies Tempo's own trace-query API (`add-otel-tracing` decision 4) - the browser never talks
    to Tempo directly. Each outcome is a clear, distinguishable response so the frontend can render
    "no trace available" (`trace-observability`, graceful degradation) without treating any of
    these as a hard error affecting anything else."""
    tempo = request.app.state.tempo
    if tempo is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "tempo_not_configured", "message": "Tempo is not configured for this backend"},
        )
    try:
        trace = await tempo.get_trace(trace_id)
    except TempoUnreachable as exc:
        raise HTTPException(status_code=503, detail={"code": "tempo_unreachable", "message": str(exc)}) from exc
    except TempoError as exc:
        raise HTTPException(status_code=502, detail={"code": "tempo_error", "message": str(exc)}) from exc
    if trace is None:
        raise HTTPException(
            status_code=404, detail={"code": "trace_not_found", "message": f"no trace with id '{trace_id}'"}
        )
    return trace
