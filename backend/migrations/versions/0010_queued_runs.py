"""file d'attente des générations demandées pendant qu'une autre tourne

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "queued_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step", sa.String(30), nullable=False),
        sa.Column("scene_id", sa.Integer, nullable=True),
        sa.Column("request", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("queued_runs")
