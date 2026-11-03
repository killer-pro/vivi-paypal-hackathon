"""chiffrement au repos des clés API des réglages

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-25
"""
import sqlalchemy as sa
from alembic import op

from app.app_settings import SECRET_KEYS
from app.crypto import decrypt, encrypt

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def _convert(convert) -> None:
    settings = sa.table("settings", sa.column("key", sa.String), sa.column("value", sa.Text))
    bind = op.get_bind()
    for key, value in bind.execute(sa.select(settings.c.key, settings.c.value).where(settings.c.key.in_(SECRET_KEYS))):
        bind.execute(settings.update().where(settings.c.key == key).values(value=convert(value)))


def upgrade() -> None:
    _convert(encrypt)


def downgrade() -> None:
    _convert(decrypt)
