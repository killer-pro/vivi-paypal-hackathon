"""forfaits : forfait payé par le compte

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-07
"""
import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("plan_id", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "plan_id")
