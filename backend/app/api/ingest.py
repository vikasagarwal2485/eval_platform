"""POST /api/ingest/v1/events - the versioned event batch endpoint agents stream into (spec `trace-ingestion`).

Never calls a model: it validates, stores, optionally queues an evaluation row (sampling only - the actual
evaluation runs later in the `EvaluationWorker`), and returns. See design D1/D2.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import repo
from app.api.deps import get_session
from app.core.events import agent_channel
from app.traces.schemas import SpanEvent, TurnEndEvent, TurnStartEvent, UnsupportedSchemaVersion, validate_batch

router = APIRouter(prefix="/api/ingest")


def _err(status: int, code: str, message: str, **extra):
    return JSONResponse(status_code=status, content={"detail": {"code": code, "message": message, **extra}})


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization[7:].strip() or None


@router.post("/v1/events")
async def ingest_events(
    request: Request,
    events: list[dict] = Body(...),
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
):
    token = _bearer_token(authorization)
    agent = repo.verify_agent_token(session, token)
    if agent is None:
        return _err(401, "unauthorized", "Unknown or missing ingest token.")
    if agent.status == "paused":
        return _err(403, "agent_paused", "This agent is paused; stop sending events until it is resumed.")

    try:
        result = validate_batch(events)
    except UnsupportedSchemaVersion as exc:
        return _err(400, "unsupported_version", str(exc), version=exc.version)
    except ValueError as exc:
        return _err(400, "batch_too_large", str(exc))

    hub = request.app.state.hub
    channel = agent_channel(agent.id)
    accepted_new = 0
    duplicates = 0
    for event, was_truncated in zip(result.accepted, result.was_truncated, strict=True):
        sess_row = repo.get_or_create_agent_session(session, agent, event.session_id)
        turn = repo.get_or_create_turn(session, agent, sess_row, event.turn_id)
        if isinstance(event, TurnStartEvent):
            dup = repo.apply_turn_start(session, turn, event, was_truncated=was_truncated)
            if not dup:
                hub.publish(channel, "turn_started", {"turn_id": turn.id, "input": turn.input})
        elif isinstance(event, SpanEvent):
            dup = repo.apply_span(session, turn, event, was_truncated=was_truncated)
            if not dup:
                hub.publish(channel, "span_added", {"turn_id": turn.id, "kind": event.kind, "model": event.model})
        elif isinstance(event, TurnEndEvent):
            dup = repo.apply_turn_end(session, turn, event, was_truncated=was_truncated)
            if not dup:
                hub.publish(channel, "turn_finished", {"turn_id": turn.id, "status": turn.status})
                if turn.status == "ok":
                    repo.maybe_queue_evaluation(session, agent, turn)
        else:  # pragma: no cover - validate_batch only yields the three known types
            dup = True
        if dup:
            duplicates += 1
        else:
            accepted_new += 1
    repo.touch_agent_liveness(session, agent)
    session.commit()
    return {
        "accepted": accepted_new,
        "duplicates": duplicates,
        "rejected": [r.model_dump() for r in result.rejected],
    }
