"""agents, their sessions/turns/spans and turn evaluations/judgements

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("declared_model", sa.String(300), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("token_hash", sa.String(100), nullable=False),
        sa.Column("token_prefix", sa.String(16), nullable=False),
        sa.Column("eval_config", sa.JSON, nullable=False),
        sa.Column("rubric", sa.JSON, nullable=True),
        sa.Column("provider_acks", sa.JSON, nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "agent_session",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("agent_id", sa.Integer, sa.ForeignKey("agent.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("agent_id", "external_id", name="uq_agent_session_external"),
    )
    op.create_index("ix_agent_session_agent_id", "agent_session", ["agent_id"])
    op.create_table(
        "agent_turn",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("agent_id", sa.Integer, sa.ForeignKey("agent.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("agent_session.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False, server_default="0"),
        sa.Column("input", sa.Text, nullable=False, server_default=""),
        sa.Column("output", sa.Text, nullable=False, server_default=""),
        sa.Column("reference", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("models", sa.JSON, nullable=False),
        sa.Column("models_unknown", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("truncated", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Float, nullable=True),
        sa.Column("prompt_tokens", sa.Integer, nullable=True),
        sa.Column("completion_tokens", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("agent_id", "external_id", name="uq_agent_turn_external"),
    )
    op.create_index("ix_agent_turn_agent_id", "agent_turn", ["agent_id"])
    op.create_index("ix_agent_turn_session_id", "agent_turn", ["session_id"])
    op.create_index("ix_agent_turn_status", "agent_turn", ["status"])
    op.create_index("ix_agent_turn_agent_ended", "agent_turn", ["agent_id", "ended_at"])
    op.create_table(
        "agent_span",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("turn_id", sa.Integer, sa.ForeignKey("agent_turn.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("model", sa.String(300), nullable=True),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("input", sa.JSON, nullable=False),
        sa.Column("output", sa.Text, nullable=False, server_default=""),
        sa.Column("thinking", sa.Text, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Float, nullable=True),
        sa.Column("ttft_ms", sa.Float, nullable=True),
        sa.Column("prompt_tokens", sa.Integer, nullable=True),
        sa.Column("completion_tokens", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("turn_id", "external_id", name="uq_agent_span_external"),
    )
    op.create_index("ix_agent_span_turn_id", "agent_span", ["turn_id"])
    op.create_table(
        "turn_evaluation",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("turn_id", sa.Integer, sa.ForeignKey("agent_turn.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt_no", sa.Integer, nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("skip_reason", sa.String(50), nullable=True),
        sa.Column("rubric", sa.JSON, nullable=False),
        sa.Column("evaluators", sa.JSON, nullable=False),
        sa.Column("value", sa.Float, nullable=True),
        sa.Column("detail", sa.JSON, nullable=False),
        sa.Column("reference_result", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("turn_id", "attempt_no", name="uq_turn_evaluation_attempt"),
    )
    op.create_index("ix_turn_evaluation_turn_id", "turn_evaluation", ["turn_id"])
    op.create_index("ix_turn_evaluation_status", "turn_evaluation", ["status"])
    op.create_table(
        "turn_judgement",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "evaluation_id", sa.Integer, sa.ForeignKey("turn_evaluation.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("judge_model", sa.String(300), nullable=False),
        sa.Column("value", sa.Float, nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("detail", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_turn_judgement_evaluation_id", "turn_judgement", ["evaluation_id"])


def downgrade() -> None:
    op.drop_index("ix_turn_judgement_evaluation_id", table_name="turn_judgement")
    op.drop_table("turn_judgement")
    op.drop_index("ix_turn_evaluation_status", table_name="turn_evaluation")
    op.drop_index("ix_turn_evaluation_turn_id", table_name="turn_evaluation")
    op.drop_table("turn_evaluation")
    op.drop_index("ix_agent_span_turn_id", table_name="agent_span")
    op.drop_table("agent_span")
    op.drop_index("ix_agent_turn_agent_ended", table_name="agent_turn")
    op.drop_index("ix_agent_turn_status", table_name="agent_turn")
    op.drop_index("ix_agent_turn_session_id", table_name="agent_turn")
    op.drop_index("ix_agent_turn_agent_id", table_name="agent_turn")
    op.drop_table("agent_turn")
    op.drop_index("ix_agent_session_agent_id", table_name="agent_session")
    op.drop_table("agent_session")
    op.drop_table("agent")
