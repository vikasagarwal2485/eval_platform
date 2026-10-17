"""agent declared_models (multi-model registry, add-agent-multi-model-registry)

Adds `declared_models` (one or more models keyed by task type) alongside the existing
`declared_model` string, and backfills every existing agent's single declared model into
`{"default": declared_model}` so no currently-registered agent's data is lost or behaves
differently. `declared_model` itself is dropped in migration 0007, once every code path reads
`declared_models` only (design.md's migration plan: dropping it separately means an early
rollback needs no data recovery).

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent") as batch:
        batch.add_column(sa.Column("declared_models", sa.JSON, nullable=False, server_default="{}"))
    # SQLite's json_object() backfills every row in one statement - no per-row Python loop needed.
    op.execute("UPDATE agent SET declared_models = json_object('default', declared_model)")


def downgrade() -> None:
    with op.batch_alter_table("agent") as batch:
        batch.drop_column("declared_models")
