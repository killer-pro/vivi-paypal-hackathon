"""avatar parlant : génération en lip-sync des scènes où parle un personnage visible

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("lipsync", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("projects", "lipsync")
