"""`/api/agents/**` - registry, turns, evaluation and monitoring (specs `agent-registry`, `agent-monitoring`,
`live-evaluation`)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from app import repo
from app.api.deps import get_session
from app.core.agent_export import export_rows, to_csv
from app.core.agent_summary import build_agent_summary, list_needs_attention
from app.core.events import agent_channel
from app.models import Agent, AgentSpan, AgentTurn, TurnEvaluation, TurnJudgement, utcnow
from app.schemas import AgentCreate, AgentSettingsUpdate, BulkReevaluateRequest, EvaluateTurnRequest

router = APIRouter(prefix="/api/agents")


def _err(status: int, code: str, message: str, **extra):
    return JSONResponse(status_code=status, content={"detail": {"code": code, "message": message, **extra}})


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=UTC)


def _iso(dt: datetime | None) -> str | None:
    dt = _aware(dt)
    return dt.isoformat() if dt else None


def _liveness(agent: Agent) -> str:
    if agent.status == "paused":
        return "paused"
    seen = _aware(agent.last_seen_at)
    if seen is None:
        return "offline"
    idle_s = (utcnow() - seen).total_seconds()
    if idle_s < 60:
        return "live"
    if idle_s < 900:
        return "idle"
    return "offline"


def _agent_out(agent: Agent) -> dict:
    return {
        "id": agent.id,
        "name": agent.name,
        "kind": agent.kind,
        "declared_model": agent.declared_model,
        "status": agent.status,
        "liveness": _liveness(agent),
        "token_prefix": agent.token_prefix,
        "eval_config": agent.eval_config,
        "rubric": agent.rubric,
        "provider_acks": sorted((agent.provider_acks or {}).keys()),
        "last_seen_at": _iso(agent.last_seen_at),
        "created_at": _iso(agent.created_at),
    }


def _span_out(s: AgentSpan) -> dict:
    return {
        "id": s.id,
        "kind": s.kind,
        "model": s.model,
        "name": s.name,
        "input": s.input,
        "output": s.output,
        "thinking": s.thinking,
        "error": s.error,
        "started_at": _iso(s.started_at),
        "ended_at": _iso(s.ended_at),
        "latency_ms": s.latency_ms,
        "ttft_ms": s.ttft_ms,
        "prompt_tokens": s.prompt_tokens,
        "completion_tokens": s.completion_tokens,
    }


def _judgement_out(j: TurnJudgement) -> dict:
    return {"judge_model": j.judge_model, "value": j.value, "outcome": j.outcome, "detail": j.detail}


def _evaluation_out(session: Session, ev: TurnEvaluation) -> dict:
    return {
        "id": ev.id,
        "attempt_no": ev.attempt_no,
        "status": ev.status,
        "skip_reason": ev.skip_reason,
        "evaluators": ev.evaluators,
        "rubric": ev.rubric,
        "value": ev.value,
        "detail": ev.detail,
        "reference_result": ev.reference_result,
        "judgements": [_judgement_out(j) for j in repo.list_turn_judgements(session, ev.id)],
        "created_at": _iso(ev.created_at),
        "finished_at": _iso(ev.finished_at),
    }


def _turn_out(session: Session, turn: AgentTurn, *, detail: bool = False) -> dict:
    out = {
        "id": turn.id,
        "external_id": turn.external_id,
        "session_id": turn.session.external_id if turn.session else None,
        "seq": turn.seq,
        "status": turn.status,
        "input": turn.input,
        "output": turn.output,
        "reference": turn.reference,
        "error": turn.error,
        "models": turn.models,
        "models_unknown": turn.models_unknown,
        "truncated": turn.truncated,
        "latency_ms": turn.latency_ms,
        "prompt_tokens": turn.prompt_tokens,
        "completion_tokens": turn.completion_tokens,
        "started_at": _iso(turn.started_at),
        "ended_at": _iso(turn.ended_at),
    }
    if detail:
        out["spans"] = [_span_out(s) for s in turn.spans]
        evals = repo.list_turn_evaluations(session, turn.id)
        out["evaluations"] = [_evaluation_out(session, e) for e in evals]
        out["latest_evaluation"] = out["evaluations"][-1] if out["evaluations"] else None
    else:
        latest = repo.latest_turn_evaluation(session, turn.id)
        out["latest_evaluation"] = {"status": latest.status, "value": latest.value} if latest else None
    return out


def _get_owned_turn(session: Session, agent_id: int, turn_id: int) -> AgentTurn:
    turn = repo.get_turn(session, turn_id)
    if turn.agent_id != agent_id:
        raise repo.NotFound(f"turn {turn_id} not found for agent {agent_id}")
    return turn


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, f"'{value}' is not a valid ISO-8601 timestamp") from None


# ------------------------------------------------------------------ registry (spec agent-registry)
@router.post("", status_code=201)
def create_agent(body: AgentCreate, session: Session = Depends(get_session)):
    try:
        agent, token = repo.create_agent(
            session,
            name=body.name,
            kind=body.kind,
            declared_model=body.declared_model,
            eval_config=body.eval_config,
            rubric=[c.model_dump() for c in body.rubric] if body.rubric else None,
            provider_acks=body.provider_acks,
        )
    except repo.Conflict as exc:
        raise HTTPException(409, str(exc)) from None
    except repo.AckRequired as exc:
        return _err(422, "ack_required", str(exc), provider=exc.provider)
    except ValueError as exc:
        return _err(422, "invalid_settings", str(exc))
    out = _agent_out(agent)
    out["token"] = token  # shown once
    return out


@router.get("")
def list_agents(session: Session = Depends(get_session)):
    return [_agent_out(a) for a in repo.list_agents(session)]


@router.get("/{agent_id}")
def get_agent(agent_id: int, session: Session = Depends(get_session)):
    return _agent_out(repo.get_agent(session, agent_id))


@router.patch("/{agent_id}")
def update_agent(agent_id: int, body: AgentSettingsUpdate, session: Session = Depends(get_session)):
    try:
        agent = repo.update_agent_settings(session, agent_id, body)
    except repo.AckRequired as exc:
        return _err(422, "ack_required", str(exc), provider=exc.provider)
    except ValueError as exc:
        return _err(422, "invalid_settings", str(exc))
    return _agent_out(agent)


@router.post("/{agent_id}/pause")
def pause_agent(agent_id: int, session: Session = Depends(get_session)):
    return _agent_out(repo.set_agent_status(session, agent_id, "paused"))


@router.post("/{agent_id}/resume")
def resume_agent(agent_id: int, session: Session = Depends(get_session)):
    return _agent_out(repo.set_agent_status(session, agent_id, "active"))


@router.post("/{agent_id}/rotate-token")
def rotate_token(agent_id: int, session: Session = Depends(get_session)):
    agent, token = repo.rotate_agent_token(session, agent_id)
    out = _agent_out(agent)
    out["token"] = token
    return out


@router.delete("/{agent_id}", status_code=204)
def delete_agent(agent_id: int, session: Session = Depends(get_session)):
    repo.delete_agent(session, agent_id)


# ------------------------------------------------------------------ turns and conversations (spec agent-monitoring)
@router.get("/{agent_id}/turns")
def list_turns(
    agent_id: int,
    session_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    repo.get_agent(session, agent_id)
    turns = repo.list_turns(session, agent_id, session_external_id=session_id, status=status, limit=limit, offset=offset)
    return [_turn_out(session, t) for t in turns]


@router.get("/{agent_id}/turns/{turn_id}")
def get_turn(agent_id: int, turn_id: int, session: Session = Depends(get_session)):
    turn = _get_owned_turn(session, agent_id, turn_id)
    return _turn_out(session, turn, detail=True)


# ------------------------------------------------------------------ evaluation (spec live-evaluation)
@router.post("/{agent_id}/turns/{turn_id}/evaluate", status_code=202)
def evaluate_turn(agent_id: int, turn_id: int, body: EvaluateTurnRequest, session: Session = Depends(get_session)):
    turn = _get_owned_turn(session, agent_id, turn_id)
    if turn.status != "ok":
        return _err(422, "turn_not_evaluable", "Only a successfully finished turn can be evaluated.")
    ev = repo.reevaluate_turn(
        session, turn, evaluators=body.evaluators, rubric=[c.model_dump() for c in body.rubric] if body.rubric else None
    )
    return _evaluation_out(session, ev)


@router.post("/{agent_id}/reevaluate", status_code=202)
def reevaluate_bulk(agent_id: int, body: BulkReevaluateRequest, session: Session = Depends(get_session)):
    agent = repo.get_agent(session, agent_id)
    queued = repo.reevaluate_agent_turns(
        session,
        agent,
        below_score=body.below_score,
        since=_parse_dt(body.since),
        until=_parse_dt(body.until),
        evaluators=body.evaluators,
    )
    return {"queued": len(queued)}


# ------------------------------------------------------------------ monitoring (spec agent-monitoring)
@router.get("/{agent_id}/summary")
def agent_summary(agent_id: int, window: str = "24h", session: Session = Depends(get_session)):
    agent = repo.get_agent(session, agent_id)
    return build_agent_summary(session, agent, window=window)


@router.get("/{agent_id}/attention")
def agent_attention(agent_id: int, window: str = "24h", limit: int = 20, session: Session = Depends(get_session)):
    agent = repo.get_agent(session, agent_id)
    return list_needs_attention(session, agent, window=window, limit=limit)


@router.get("/{agent_id}/events")
async def agent_events(agent_id: int, request: Request, after: int = 0):
    """Server-Sent Events, open-ended (no terminal event - see EventHub.subscribe_open)."""
    hub = request.app.state.hub
    with request.app.state.session_factory() as session:
        agent = repo.get_agent(session, agent_id)
        state = {"status": agent.status, "liveness": _liveness(agent)}
    try:
        after = max(after, int(request.headers.get("last-event-id", 0)))
    except ValueError:
        pass

    async def stream():
        yield f"event: state\ndata: {json.dumps(state)}\n\n"
        async for ev in hub.subscribe_open(agent_channel(agent_id), after):
            yield f"id: {ev.id}\nevent: {ev.type}\ndata: {json.dumps(ev.data)}\n\n"

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.get("/{agent_id}/export")
def export_agent(
    agent_id: int, format: str = "csv", since: str | None = None, until: str | None = None,
    session: Session = Depends(get_session),
):
    if format not in ("csv", "json"):
        raise HTTPException(422, "format must be csv or json")
    agent = repo.get_agent(session, agent_id)
    rows = export_rows(session, agent, since=_parse_dt(since), until=_parse_dt(until))
    fname = f"agent-{agent.id}.{format}"
    headers = {"Content-Disposition": f'attachment; filename="{fname}"'}
    if format == "csv":
        return Response(to_csv(rows), media_type="text/csv", headers=headers)
    return Response(json.dumps({"agent": agent.name, "turns": rows}, indent=2), media_type="application/json", headers=headers)
