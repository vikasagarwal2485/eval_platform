"""azure openai provider support: provider api_version, model reasoning_effort

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("provider") as batch:
        batch.add_column(sa.Column("api_version", sa.String(50), nullable=True))
    with op.batch_alter_table("registered_model") as batch:
        batch.add_column(sa.Column("reasoning_effort", sa.String(20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("registered_model") as batch:
        batch.drop_column("reasoning_effort")
    with op.batch_alter_table("provider") as batch:
        batch.drop_column("api_version")
