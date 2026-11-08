"""abonnement PayPal : identifiant de l'abonnement PayPal du compte

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-05
"""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("paypal_subscription_id", sa.String(80), nullable=True, unique=True))


def downgrade() -> None:
    op.drop_column("users", "paypal_subscription_id")
