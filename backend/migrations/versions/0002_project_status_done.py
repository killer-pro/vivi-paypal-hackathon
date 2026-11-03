"""project status done : projets dont l'étape final est déjà validée

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE projects SET status = 'done' WHERE id IN "
               "(SELECT project_id FROM steps WHERE name = 'final' AND status = 'approved')")


def downgrade() -> None:
    op.execute("UPDATE projects SET status = 'draft' WHERE status = 'done'")
