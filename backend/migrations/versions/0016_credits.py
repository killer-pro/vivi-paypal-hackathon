"""crédits : soldes à deux lots, réservations et registre des mouvements

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credit_balances",
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("subscription", sa.Integer, nullable=False, server_default="0"),
        sa.Column("topup", sa.Integer, nullable=False, server_default="0"),
        sa.CheckConstraint("subscription >= 0 AND topup >= 0", name="ck_credit_balances_non_negative"),
    )
    op.create_table(
        "credit_reservations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("step", sa.String(30), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=True),
        sa.Column("amount", sa.Integer, nullable=False),
        sa.Column("parts", sa.JSON, nullable=False),
        sa.Column("scene_prices", sa.JSON, nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("used", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_credit_reservations_status_created_at", "credit_reservations", ["status", "created_at"])
    op.create_table(
        "credit_entries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bucket", sa.String(20), nullable=False),
        sa.Column("amount", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("reservation_id", sa.Integer, sa.ForeignKey("credit_reservations.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("step", sa.String(30), nullable=True),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_credit_entries_user_id_id", "credit_entries", ["user_id", "id"])
    op.create_index("uq_credit_entries_signup_grant", "credit_entries", ["user_id"], unique=True,
                    postgresql_where=sa.text("kind = 'signup_grant'"))


def downgrade() -> None:
    op.drop_table("credit_entries")
    op.drop_table("credit_reservations")
    op.drop_table("credit_balances")
