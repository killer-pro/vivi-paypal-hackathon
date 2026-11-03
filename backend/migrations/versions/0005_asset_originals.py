"""assets : nom de fichier d'origine des imports, gardé à part (donnée affichée, jamais dans une clé de stockage)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-22
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asset_originals",
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("asset_id"),
    )


def downgrade() -> None:
    op.drop_table("asset_originals")
