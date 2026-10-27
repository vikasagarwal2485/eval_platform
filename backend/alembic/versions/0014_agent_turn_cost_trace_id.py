"""agent_turn.cost, trace_id, thinking (add-otel-tracing)

`turn.end` now reports a turn's cost, OTel trace id, and reasoning trace directly (alongside the
`models`/token totals it already reported) rather than the backend deriving them from aggregated
`span` events - that event type is retired. All three nullable: none is fabricated when the agent
doesn't report it.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_turn") as batch:
        batch.add_column(sa.Column("cost", sa.Float, nullable=True))
        batch.add_column(sa.Column("trace_id", sa.String(32), nullable=True))
        batch.add_column(sa.Column("thinking", sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_turn") as batch:
        batch.drop_column("thinking")
        batch.drop_column("trace_id")
        batch.drop_column("cost")
