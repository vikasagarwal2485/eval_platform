"""agent playground eligibility + encrypted spawn credentials (add-agent-playground)

Adds `Agent.playground_eligible`, `flavor`, `playground_ingest_token_enc`, `playground_gateway_key_enc` -
all nullable/defaulted, so every existing row stays non-eligible and untouched by this migration.

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent") as batch:
        batch.add_column(sa.Column("playground_eligible", sa.Boolean, nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("flavor", sa.String(40), nullable=True))
        batch.add_column(sa.Column("playground_ingest_token_enc", sa.LargeBinary, nullable=True))
        batch.add_column(sa.Column("playground_gateway_key_enc", sa.LargeBinary, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent") as batch:
        batch.drop_column("playground_gateway_key_enc")
        batch.drop_column("playground_ingest_token_enc")
        batch.drop_column("flavor")
        batch.drop_column("playground_eligible")
