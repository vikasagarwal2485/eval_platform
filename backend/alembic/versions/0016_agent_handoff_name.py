"""Agent.handoff_agent_name (add-agent-playground)

A router-kind agent's hand-off target, named by the target agent's own unique, user-facing name -
discovered as a real gap while wiring the playground's spawn command: `classifier_router_agent.py`
requires its hand-off target's own ingest token/gateway key as required CLI flags, unconditionally,
and nothing in the registry recorded which agent that target even is.

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent") as batch:
        batch.add_column(sa.Column("handoff_agent_name", sa.String(200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent") as batch:
        batch.drop_column("handoff_agent_name")
