"""scènes : locuteur (personnage qui prononce la voix off, vide pour le narrateur)

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-26
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scenes", sa.Column("speaker", sa.String(30), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("scenes", "speaker")
