"""provider.last_test_{status,message,at} (add-provider-availability-gating)

Lets "available" mean "the last connection test didn't fail", not just "a key is present" - a
present-but-wrong key or an unreachable Ollama server couldn't be told apart from a working one
before this.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("provider") as batch:
        batch.add_column(sa.Column("last_test_status", sa.String(30), nullable=True))
        batch.add_column(sa.Column("last_test_message", sa.String(500), nullable=True))
        batch.add_column(sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("provider") as batch:
        batch.drop_column("last_test_at")
        batch.drop_column("last_test_message")
        batch.drop_column("last_test_status")
