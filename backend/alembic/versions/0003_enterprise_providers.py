"""enterprise providers, their registered models, and snapshot source columns

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(40), nullable=False, unique=True),
        sa.Column("key_env", sa.String(64), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=True),
        sa.Column("ack_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "registered_model",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("provider_id", sa.Integer, sa.ForeignKey("provider.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("reasoning", sa.Boolean, nullable=False),
        sa.UniqueConstraint("provider_id", "model_id", name="uq_registered_model_provider_model"),
    )
    op.create_index("ix_registered_model_provider_id", "registered_model", ["provider_id"])
    with op.batch_alter_table("model_snapshot") as batch:
        batch.add_column(sa.Column("provider_kind", sa.String(20), nullable=True))
        batch.add_column(sa.Column("source", sa.String(10), nullable=False, server_default="local"))


def downgrade() -> None:
    with op.batch_alter_table("model_snapshot") as batch:
        batch.drop_column("source")
        batch.drop_column("provider_kind")
    op.drop_index("ix_registered_model_provider_id", table_name="registered_model")
    op.drop_table("registered_model")
    op.drop_table("provider")
