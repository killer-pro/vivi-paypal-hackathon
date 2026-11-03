"""comptes : utilisateurs, jetons e-mail, propriété des projets (les projets existants vont à l'administrateur)

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-01
"""
import sqlalchemy as sa
from alembic import op

from app.config import settings
from app.security import hash_password

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    users = op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(200), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="user"),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_epoch", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "email_tokens",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("projects", sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True))
    admin_id = op.get_bind().execute(
        sa.insert(users).values(email=settings.admin_email, password_hash=hash_password(settings.admin_password),
                                role="admin", email_verified_at=sa.func.now()).returning(users.c.id)
    ).scalar_one()
    op.execute(sa.text("UPDATE projects SET user_id = :id").bindparams(id=admin_id))
    op.alter_column("projects", "user_id", nullable=False)
    op.create_index("ix_projects_user_id", "projects", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_projects_user_id", table_name="projects")
    op.drop_column("projects", "user_id")
    op.drop_table("email_tokens")
    op.drop_table("users")
