"""drop agent.declared_model (add-agent-multi-model-registry, task 4.2)

`declared_models` (migration 0006) is now read/written by every code path - this drops the
now-unused singular column. Downgrade restores it from `declared_models["default"]` when that key
exists, else empty string, so a rollback after this migration still has a sensible value rather
than losing data outright.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent") as batch:
        batch.drop_column("declared_model")


def downgrade() -> None:
    with op.batch_alter_table("agent") as batch:
        batch.add_column(sa.Column("declared_model", sa.String(300), nullable=False, server_default=""))
    op.execute(
        "UPDATE agent SET declared_model = COALESCE(json_extract(declared_models, '$.default'), '')"
    )
