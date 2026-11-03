"""abonnement : fin de la période payée du compte

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("subscription_ends_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "subscription_ends_at")
