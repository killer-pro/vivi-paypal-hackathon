"""étape story (histoire et éléments suivis) : éléments visibles par scène, étape validée et vide pour les projets existants

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-26
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scenes", sa.Column("elements", sa.JSON(), nullable=False, server_default="[]"))
    # Un projet existant garde l'ancien chemin du script : sa story est validée et vide.
    op.execute("INSERT INTO steps (project_id, name, status, params, result) "
               "SELECT id, 'story', 'approved', '{}', '{}' FROM projects")


def downgrade() -> None:
    op.execute("DELETE FROM steps WHERE name = 'story'")
    op.drop_column("scenes", "elements")
