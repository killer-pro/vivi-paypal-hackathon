"""projets : style visuel choisi à la création

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-22
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("style", sa.String(30), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("projects", "style")
