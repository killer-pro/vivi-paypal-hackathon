import os
import subprocess
import sys

MIG_URL = "postgresql+asyncpg://vv:vv@localhost:5432/video_virale_mig"


def alembic(*args: str) -> None:
    r = subprocess.run([sys.executable, "-m", "alembic", *args], capture_output=True, text=True,
                       env=os.environ | {"DATABASE_URL": MIG_URL}, cwd=".")
    assert r.returncode == 0, r.stderr


def test_alembic_upgrade_head_on_test_db():
    alembic("downgrade", "base")
    alembic("upgrade", "head")


def test_models_and_migrations_declare_the_same_indexes():
    """Les index du modèle (base de test créée par `create_all`) existent aussi après `alembic upgrade head`."""
    import re
    from pathlib import Path

    from app.models import Base

    declared = {i.name for t in Base.metadata.tables.values() for i in t.indexes}
    migrated = set()
    for fichier in ("0003_indexes.py", "0015_users.py", "0016_credits.py"):
        migrated |= set(re.findall(r'create_index\("(\w+)"', Path("migrations/versions", fichier).read_text()))
    assert declared == migrated and len(declared) == 8



async def test_asset_originals_migration_keeps_existing_assets_and_cascades():
    """Base existante (0004, un asset déjà là) : la table des noms d'origine s'ajoute sans toucher aux assets, suit
    leur suppression (ON DELETE CASCADE) et disparaît au downgrade."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    alembic("downgrade", "base")
    alembic("upgrade", "0004")
    engine = create_async_engine(MIG_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("INSERT INTO projects (id, title, theme, platform, target_duration_s, status, "
                                    "metadata_json) VALUES (1, 't', '', 'tiktok', 30, 'draft', '{}')"))
            await conn.execute(text("INSERT INTO assets (id, project_id, kind, key, content_type, variant, meta) "
                                    "VALUES (7, 1, 'clip', 'projects/1/clip/a.mp4', 'video/mp4', 1, '{}')"))
        alembic("upgrade", "head")
        async with engine.begin() as conn:
            assert (await conn.execute(text("SELECT count(*) FROM assets"))).scalar() == 1
            await conn.execute(text("INSERT INTO asset_originals (asset_id, original_name) VALUES (7, 'a.mp4')"))
            await conn.execute(text("DELETE FROM assets WHERE id = 7"))
            assert (await conn.execute(text("SELECT count(*) FROM asset_originals"))).scalar() == 0
        alembic("downgrade", "0004")
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT to_regclass('asset_originals')"))).scalar() is None
    finally:
        await engine.dispose()
        alembic("downgrade", "base")
        alembic("upgrade", "head")


async def test_story_migration_gives_existing_projects_an_approved_empty_story():
    """Base existante (0011, un projet avec ses 8 étapes) : chaque projet reçoit une étape `story` validée et vide (ancien
    chemin du script), les scènes une liste d'éléments vide ; le downgrade retire l'étape et la colonne."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    alembic("downgrade", "base")
    alembic("upgrade", "0011")
    engine = create_async_engine(MIG_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("INSERT INTO projects (id, title, theme, platform, target_duration_s, status, "
                                    "metadata_json) VALUES (1, 't', '', 'tiktok', 30, 'draft', '{}')"))
            await conn.execute(text("INSERT INTO steps (project_id, name, status, params, result) "
                                    "VALUES (1, 'script', 'approved', '{}', '{}')"))
            await conn.execute(text("INSERT INTO scenes (id, project_id, position, voice_text, visual_prompt, "
                                    "duration_s) VALUES (5, 1, 1, 'v', 'p', 4)"))
        alembic("upgrade", "head")
        async with engine.connect() as conn:
            row = (await conn.execute(text("SELECT status, result FROM steps WHERE name = 'story'"))).one()
            assert row.status == "approved" and row.result == {}
            assert (await conn.execute(text("SELECT elements FROM scenes WHERE id = 5"))).scalar() == []
        alembic("downgrade", "0011")
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT count(*) FROM steps WHERE name = 'story'"))).scalar() == 0
            columns = (await conn.execute(text("SELECT column_name FROM information_schema.columns "
                                               "WHERE table_name = 'scenes'"))).scalars().all()
            assert "elements" not in columns
    finally:
        await engine.dispose()
        alembic("downgrade", "base")
        alembic("upgrade", "head")


async def test_continuity_migration_gives_existing_scenes_the_cut_value():
    """Base existante (0012, une scène) : la continuité vaut « cut » (pas de chaînage) ; le downgrade retire la colonne."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    alembic("downgrade", "base")
    alembic("upgrade", "0012")
    engine = create_async_engine(MIG_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("INSERT INTO projects (id, title, theme, platform, target_duration_s, status, "
                                    "metadata_json) VALUES (1, 't', '', 'tiktok', 30, 'draft', '{}')"))
            await conn.execute(text("INSERT INTO scenes (id, project_id, position, voice_text, visual_prompt, "
                                    "duration_s) VALUES (5, 1, 1, 'v', 'p', 4)"))
        alembic("upgrade", "head")
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT continuity FROM scenes WHERE id = 5"))).scalar() == "cut"
        alembic("downgrade", "0012")
        async with engine.connect() as conn:
            columns = (await conn.execute(text("SELECT column_name FROM information_schema.columns "
                                               "WHERE table_name = 'scenes'"))).scalars().all()
            assert "continuity" not in columns
    finally:
        await engine.dispose()
        alembic("downgrade", "base")
        alembic("upgrade", "head")


async def test_speaker_migration_gives_existing_scenes_the_narrator():
    """Base existante (0013, une scène) : le locuteur est vide (le narrateur) ; le downgrade retire la colonne."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    alembic("downgrade", "base")
    alembic("upgrade", "0013")
    engine = create_async_engine(MIG_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("INSERT INTO projects (id, title, theme, platform, target_duration_s, status, "
                                    "metadata_json) VALUES (1, 't', '', 'tiktok', 30, 'draft', '{}')"))
            await conn.execute(text("INSERT INTO scenes (id, project_id, position, voice_text, visual_prompt, "
                                    "duration_s) VALUES (5, 1, 1, 'v', 'p', 4)"))
        alembic("upgrade", "head")
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT speaker FROM scenes WHERE id = 5"))).scalar() == ""
        alembic("downgrade", "0013")
        async with engine.connect() as conn:
            columns = (await conn.execute(text("SELECT column_name FROM information_schema.columns "
                                               "WHERE table_name = 'scenes'"))).scalars().all()
            assert "speaker" not in columns
    finally:
        await engine.dispose()
        alembic("downgrade", "base")
        alembic("upgrade", "head")


async def test_users_migration_attaches_existing_projects_to_the_admin():
    """Base existante (0014, un projet) : un administrateur vérifié est créé avec `settings.admin_email` et reçoit le
    projet ; le downgrade retire la colonne et les tables."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import settings

    alembic("downgrade", "base")
    alembic("upgrade", "0014")
    engine = create_async_engine(MIG_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("INSERT INTO projects (id, title, theme, platform, target_duration_s, status, "
                                    "metadata_json) VALUES (1, 't', '', 'tiktok', 30, 'draft', '{}')"))
        alembic("upgrade", "head")
        async with engine.connect() as conn:
            admin = (await conn.execute(text("SELECT id, email, role, email_verified_at FROM users"))).one()
            assert admin.role == "admin" and admin.email == settings.admin_email and admin.email_verified_at
            assert (await conn.execute(text("SELECT user_id FROM projects WHERE id = 1"))).scalar() == admin.id
        alembic("downgrade", "0014")
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT to_regclass('users')"))).scalar() is None
            assert (await conn.execute(text("SELECT to_regclass('email_tokens')"))).scalar() is None
            columns = (await conn.execute(text("SELECT column_name FROM information_schema.columns "
                                               "WHERE table_name = 'projects'"))).scalars().all()
            assert "user_id" not in columns
    finally:
        await engine.dispose()
        alembic("downgrade", "base")
        alembic("upgrade", "head")


async def test_credits_migration_round_trip_and_single_signup_grant_per_account():
    """0015 → head → 0015 sans erreur ; l'index unique partiel refuse deux crédits d'inscription pour un compte."""
    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import create_async_engine

    alembic("downgrade", "base")
    alembic("upgrade", "head")
    engine = create_async_engine(MIG_URL)
    try:
        async with engine.begin() as conn:
            user_id = (await conn.execute(text("SELECT id FROM users LIMIT 1"))).scalar_one()
            insert = text("INSERT INTO credit_entries (user_id, bucket, amount, kind, reason) "
                          "VALUES (:u, 'topup', 100, :k, 'x')")
            await conn.execute(insert, {"u": user_id, "k": "signup_grant"})
            await conn.execute(insert, {"u": user_id, "k": "adjust"})
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(insert, {"u": user_id, "k": "signup_grant"})
        with pytest.raises(IntegrityError):  # jamais de solde négatif
            async with engine.begin() as conn:
                await conn.execute(text("INSERT INTO credit_balances (user_id, subscription, topup) "
                                        f"VALUES ({user_id}, 0, -1)"))
        alembic("downgrade", "0015")
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT to_regclass('credit_entries')"))).scalar() is None
    finally:
        await engine.dispose()
        alembic("downgrade", "base")
