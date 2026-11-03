"""scènes : élément de référence (personnage, produit) dont l'image sert au clip

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scenes", sa.Column("reference", sa.String(30), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("scenes", "reference")
