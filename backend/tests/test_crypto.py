from sqlalchemy import text

from app import crypto
from app.app_settings import AppSettings
from app.config import settings
from app.crypto import PREFIX, decrypt, encrypt
from tests.test_migration import MIG_URL, alembic


def test_encrypt_roundtrip_and_idempotence():
    token = encrypt("sk-abc")
    assert token.startswith(PREFIX) and "sk-abc" not in token
    assert decrypt(token) == "sk-abc" and encrypt(token) == token
    assert encrypt("") == "" and decrypt("legacy-plain") == "legacy-plain"


def test_changed_secret_key_makes_value_unreadable(monkeypatch):
    token = encrypt("sk-abc")
    monkeypatch.setattr(settings, "secret_key", "another-secret")
    assert decrypt(token) == ""


async def test_api_keys_are_stored_encrypted_and_read_back(session):
    s = AppSettings(session)
    await s.set_many({"fal_key": "abcdef1234", "comfyui_url": "http://x"})
    stored = {k: v for k, v in (await session.execute(text("select key, value from settings"))).all()}
    assert stored["fal_key"].startswith(crypto.PREFIX) and stored["comfyui_url"] == "http://x"
    assert await s.get("fal_key") == "abcdef1234"


async def test_stored_key_unreadable_after_secret_key_change_counts_as_absent(session, monkeypatch):
    s = AppSettings(session)
    await s.set("fal_key", "abcdef1234")
    monkeypatch.setattr(settings, "secret_key", "another-secret")
    assert await s.get("fal_key") == ""


async def test_migration_encrypts_existing_plaintext_keys_and_downgrade_restores_them():
    from sqlalchemy.ext.asyncio import create_async_engine

    alembic("downgrade", "base")
    alembic("upgrade", "0010")
    engine = create_async_engine(MIG_URL)
    async with engine.begin() as conn:
        await conn.execute(text("insert into settings (key, value) values ('fal_key', 'plain-1234'), ('comfyui_url', 'http://x')"))
    alembic("upgrade", "0011")
    async with engine.connect() as conn:
        rows = dict((await conn.execute(text("select key, value from settings"))).all())
    assert rows["fal_key"].startswith(PREFIX) and decrypt(rows["fal_key"]) == "plain-1234"
    assert rows["comfyui_url"] == "http://x"
    alembic("downgrade", "0010")
    async with engine.connect() as conn:
        assert (await conn.execute(text("select value from settings where key='fal_key'"))).scalar() == "plain-1234"
    await engine.dispose()
    alembic("downgrade", "base")
    alembic("upgrade", "head")
