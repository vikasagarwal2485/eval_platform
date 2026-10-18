"""provider.key_env nullable, for the new `ollama` provider kind (add-ollama-provider-kind)

An `ollama` provider has no API key at all - unlike `openai`/`anthropic`/`azure-openai`, which all
require one. Downgrade backfills any NULL back to an empty string so the column can go NOT NULL
again without failing on existing `ollama` rows.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("provider") as batch:
        batch.alter_column("key_env", existing_type=sa.String(64), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE provider SET key_env = '' WHERE key_env IS NULL")
    with op.batch_alter_table("provider") as batch:
        batch.alter_column("key_env", existing_type=sa.String(64), nullable=False)
