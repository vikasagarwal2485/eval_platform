"""CSV/JSON export of an agent's turns and their evaluations (spec `agent-monitoring`)."""

from __future__ import annotations

import csv
import io
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import repo
from app.models import Agent, AgentTurn

COLUMNS = [
    "turn_id",
    "external_id",
    "status",
    "input",
    "output",
    "reference",
    "models",
    "latency_ms",
    "evaluation_status",
    "evaluated_value",
    "judges",
]


def _judge_cell(j: dict) -> str:
    return f"{j['judge_model']}={j['value']:.3f}" if j.get("outcome") == "judged" and j.get("value") is not None else f"{j['judge_model']}=error"


def export_rows(session: Session, agent: Agent, *, since: datetime | None = None, until: datetime | None = None) -> list[dict]:
    q = select(AgentTurn).where(AgentTurn.agent_id == agent.id).order_by(AgentTurn.id)
    if since is not None:
        q = q.where(AgentTurn.ended_at >= since)
    if until is not None:
        q = q.where(AgentTurn.ended_at <= until)
    rows = []
    for t in session.scalars(q):
        latest = repo.latest_turn_evaluation(session, t.id)
        judgements = repo.list_turn_judgements(session, latest.id) if latest else []
        rows.append(
            {
                "turn_id": t.id,
                "external_id": t.external_id,
                "status": t.status,
                "input": t.input,
                "output": t.output,
                "reference": t.reference,
                "models": ",".join(t.models or []),
                "latency_ms": t.latency_ms,
                "evaluation_status": latest.status if latest else "not_sampled",
                "evaluated_value": latest.value if latest else None,
                "judges": "; ".join(_judge_cell({"judge_model": j.judge_model, "value": j.value, "outcome": j.outcome}) for j in judgements),
            }
        )
    return rows


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    for row in rows:
        w.writerow({k: ("" if row[k] is None else row[k]) for k in COLUMNS})
    return buf.getvalue()
