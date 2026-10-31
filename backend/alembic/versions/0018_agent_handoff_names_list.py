"""agent.handoff_agent_names (add-agent-playground)

Replaces the single `handoff_agent_name` (migration 0016) with a list - the platform places no
limit on how many hand-off targets a router-kind agent may declare, even though today's one
reference router script only ever consumes the first one. Backfills every existing agent's single
value into a one-element array (or an empty one). `handoff_agent_name` itself is dropped in
migration 0019, once every code path reads `handoff_agent_names` only (same two-step pattern
migration 0006/0007 used for `declared_model` -> `declared_models` - an early rollback needs no
data recovery).

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent") as batch:
        batch.add_column(sa.Column("handoff_agent_names", sa.JSON, nullable=False, server_default="[]"))
    # SQLite's json_array()/json_quote() backfill every row in one statement - no per-row Python loop needed.
    op.execute(
        "UPDATE agent SET handoff_agent_names = "
        "CASE WHEN handoff_agent_name IS NOT NULL THEN json_array(handoff_agent_name) ELSE '[]' END"
    )


def downgrade() -> None:
    with op.batch_alter_table("agent") as batch:
        batch.drop_column("handoff_agent_names")
