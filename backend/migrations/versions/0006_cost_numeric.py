"""appels aux providers : coût en NUMERIC(12, 6) (au lieu de FLOAT : plus de dérive d'arrondi dans les totaux)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-22
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("provider_calls", "cost_usd", existing_type=sa.Float(), type_=sa.Numeric(12, 6),
                    existing_nullable=False, postgresql_using="round(cost_usd::numeric, 6)")


def downgrade() -> None:
    op.alter_column("provider_calls", "cost_usd", existing_type=sa.Numeric(12, 6), type_=sa.Float(),
                    existing_nullable=False)
