"""paiement Stripe : client Stripe du compte et événements déjà traités (idempotence des webhooks)

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("stripe_customer_id", sa.String(80), nullable=True, unique=True))
    op.create_table(
        "stripe_events",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("type", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("stripe_events")
    op.drop_column("users", "stripe_customer_id")
