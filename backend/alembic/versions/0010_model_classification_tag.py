"""registered_model.classification (add-model-classification-tag)

Mirrors `reasoning`: tags a registered model as fit for the classification task, independent of
`reasoning` - a model may be tagged for both, either, or neither (plain generation).

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("registered_model") as batch:
        batch.add_column(sa.Column("classification", sa.Boolean, nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("registered_model") as batch:
        batch.drop_column("classification")
