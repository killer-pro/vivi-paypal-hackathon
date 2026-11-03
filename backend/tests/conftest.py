import os
from contextlib import AsyncExitStack
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ["DATABASE_URL"] = "postgresql+asyncpg://vv:vv@localhost:5432/video_virale_test"
os.environ["FAKE_PROVIDERS"] = "true"

from app.api.auth import make_session_cookie  # noqa: E402
from app.app_settings import AppSettings  # noqa: E402
from app.db import get_session  # noqa: E402
from app.mailer import FakeMailer, get_mailer  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, User  # noqa: E402
from app.providers.registry import ProviderRegistry  # noqa: E402
from app.queue import get_enqueue  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.pipeline import PipelineContext  # noqa: E402
from app.storage import get_storage  # noqa: E402


class MemStorage:
    def __init__(self):
        self.files = {}
        self.types = {}  # type MIME enregistré par clé

    async def put(self, key, data, content_type):
        self.files[key] = data
        self.types[key] = content_type

    async def get(self, key):
        return self.files[key]

    async def exists(self, key):
        return key in self.files

    async def delete_prefix(self, prefix):
        for key in [k for k in self.files if k.startswith(prefix)]:
            del self.files[key]

    async def delete_many(self, keys):
        for key in keys:
            self.files.pop(key, None)

    def presign(self, key, expires=3600, download=None):
        return f"http://mem/{key}" + (f"?download={download}" if download else "")


@pytest.fixture(autouse=True)
def fresh_login_throttle():
    from app.api.auth import signup_throttle, throttle
    throttle.reset()
    signup_throttle.reset()


@pytest.fixture
async def session():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


ADMIN_EMAIL = "admin@example.com"
PASSWORD = "motdepasse1"


async def add_user(session, email, role="user", verified=True) -> User:
    user = User(email=email, password_hash=hash_password(PASSWORD), role=role,
                email_verified_at=datetime.now(UTC) if verified else None)
    session.add(user)
    await session.commit()
    return user


async def ensure_admin(session) -> User:
    """L'administrateur de la base de test (créé au premier appel) : propriétaire des projets semés par les tests."""
    found = (await session.execute(select(User).where(User.email == ADMIN_EMAIL))).scalar_one_or_none()
    return found or await add_user(session, ADMIN_EMAIL, role="admin")


@pytest.fixture
async def admin(session):
    return await ensure_admin(session)


@pytest.fixture
def make_user(session):
    """Fabrique d'utilisateurs : `await make_user("a@b.fr", role="user", verified=True)`."""
    async def make(email, role="user", verified=True):
        return await add_user(session, email, role, verified)
    return make


@pytest.fixture
def mailer():
    """Faux serveur d'e-mails : `mailer.outbox` liste les messages envoyés par l'API."""
    fake = FakeMailer()
    app.dependency_overrides[get_mailer] = lambda: fake
    return fake


@pytest.fixture
async def api_as(session, mailer):
    """Fabrique de clients HTTP : `await api_as(user)` donne un client connecté en tant que `user` (`None` : anonyme).
    Session de test, file d'attente enregistrée dans `c.enqueued` (timeouts des jobs dans `c.timeouts`), stockage
    mémoire et boîte d'envoi partagés par tous les clients du test."""
    calls, timeouts = [], []

    async def enqueue(project_id, step, scene_id=None, overrides=None, *, timeout=None):
        calls.append((project_id, step, scene_id) + ((overrides,) if overrides else ()))
        timeouts.append(timeout)

    storage = MemStorage()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_enqueue] = lambda: enqueue
    app.dependency_overrides[get_storage] = lambda: storage
    async with AsyncExitStack() as stack:
        async def make(user):
            cookies = {"session": make_session_cookie(user.id, user.session_epoch)} if user else {}
            c = await stack.enter_async_context(
                AsyncClient(transport=ASGITransport(app=app), base_url="http://t", cookies=cookies))
            c.enqueued, c.timeouts, c.storage, c.mailer = calls, timeouts, storage, mailer
            return c
        yield make
    app.dependency_overrides.clear()


@pytest.fixture
async def api(api_as, admin):
    """Client HTTP connecté en tant qu'administrateur."""
    return await api_as(admin)


@pytest.fixture
async def ctx(session):
    events = []

    async def publish(e):
        events.append(e)

    c = PipelineContext(session, MemStorage(), ProviderRegistry(AppSettings(session)), AppSettings(session), publish)
    c.events = events
    return c


@pytest.fixture
def fund(session):
    """`await fund(user, 500)` : crédite des crédits rechargés (réglage de test, hors octroi d'inscription)."""
    async def grant(user, amount, bucket="topup"):
        from app.services import credits
        await credits.grant(session, user.id, amount, bucket=bucket, kind="adjust", reason="test")
        await session.commit()
    return grant
