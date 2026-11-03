"""scènes : continuité (« continue » : part de la dernière image du clip précédent, « cut » : des références seules)

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-26
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scenes", sa.Column("continuity", sa.String(10), nullable=False, server_default="cut"))


def downgrade() -> None:
    op.drop_column("scenes", "continuity")
