"""avatar parlant : une scène peut sortir du lip-sync (clip animé, voix hors champ)

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scenes", sa.Column("lipsync", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("scenes", "lipsync")
