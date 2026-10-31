"""drop agent.handoff_agent_name (add-agent-playground)

`handoff_agent_names` (migration 0018) is now read/written by every code path - this drops the
now-unused singular column. Downgrade restores it from `handoff_agent_names[0]` when non-empty,
else NULL, so a rollback after this migration still has a sensible value rather than losing data
outright (mirrors migration 0007's identical downgrade for `declared_model`).

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent") as batch:
        batch.drop_column("handoff_agent_name")


def downgrade() -> None:
    with op.batch_alter_table("agent") as batch:
        batch.add_column(sa.Column("handoff_agent_name", sa.String(200), nullable=True))
    op.execute(
        "UPDATE agent SET handoff_agent_name = json_extract(handoff_agent_names, '$[0]') "
        "WHERE json_array_length(handoff_agent_names) > 0"
    )
