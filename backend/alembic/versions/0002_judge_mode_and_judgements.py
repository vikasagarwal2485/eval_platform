"""judging mode on runs and scoring attempts, and per-judge judgements

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("run", "scoring_attempt"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("judge_mode", sa.String(20), nullable=False, server_default="none"))
        # Everything created before this revision used at most one judge model.
        op.execute(f"UPDATE {table} SET judge_mode = 'single' WHERE judge_model IS NOT NULL")

    op.create_table(
        "judgement",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("attempt_id", sa.Integer, sa.ForeignKey("scoring_attempt.id", ondelete="CASCADE"), nullable=False),
        sa.Column("result_id", sa.Integer, sa.ForeignKey("result.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("judge_model", sa.String(200), nullable=False),
        sa.Column("value", sa.Float, nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("detail", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_judgement_attempt_id", "judgement", ["attempt_id"])
    op.create_index("ix_judgement_result_id", "judgement", ["result_id"])


def downgrade() -> None:
    op.drop_index("ix_judgement_result_id", table_name="judgement")
    op.drop_index("ix_judgement_attempt_id", table_name="judgement")
    op.drop_table("judgement")
    for table in ("scoring_attempt", "run"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("judge_mode")
