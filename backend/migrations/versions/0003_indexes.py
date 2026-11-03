"""index : lectures par projet (assets, scènes, appels providers) et journal des coûts

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-20
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_assets_project_kind_scene", "assets", ["project_id", "kind", "scene_id"])
    op.create_index("ix_scenes_project_position", "scenes", ["project_id", "position"])
    op.create_index("ix_provider_calls_project_id", "provider_calls", ["project_id"])
    op.create_index("ix_provider_calls_created_at", "provider_calls", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_provider_calls_created_at", table_name="provider_calls")
    op.drop_index("ix_provider_calls_project_id", table_name="provider_calls")
    op.drop_index("ix_scenes_project_position", table_name="scenes")
    op.drop_index("ix_assets_project_kind_scene", table_name="assets")
