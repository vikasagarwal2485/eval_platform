"""provider.health_check_path, and the new "custom" provider kind (add-custom-model-provider-kind)

`kind` itself needs no schema change - it's already a free String(20); this migration only adds the
column used by a `custom`-kind provider's "Test connection" (a health-check path, not a chat call).

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("provider") as batch:
        batch.add_column(sa.Column("health_check_path", sa.String(200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("provider") as batch:
        batch.drop_column("health_check_path")
