"""result.trace_id (add-otel-tracing)

Correlates a Result with the OTel trace the Runner emitted for that request, so the frontend can
fetch its span tree from Tempo by id. Nullable: tracing is best-effort and never required for a
run to complete, so a pre-existing row (or one from a run where tracing failed) simply has none.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("result") as batch:
        batch.add_column(sa.Column("trace_id", sa.String(32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("result") as batch:
        batch.drop_column("trace_id")
