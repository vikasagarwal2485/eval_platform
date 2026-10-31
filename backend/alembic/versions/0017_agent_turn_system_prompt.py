"""agent_turn.system_prompt (add-agent-playground)

Reported directly by `turn.start` - the system prompt actually in effect for that turn (after any
skill instructions were prepended), whether launched from a terminal or the platform's own
Playground. Nullable: absent for a pre-existing turn or an agent that sends no system message.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_turn") as batch:
        batch.add_column(sa.Column("system_prompt", sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_turn") as batch:
        batch.drop_column("system_prompt")
