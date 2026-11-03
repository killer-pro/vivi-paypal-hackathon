from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_insecure_defaults_are_detected():
    from app.config import Settings, insecure_defaults

    assert insecure_defaults(Settings(admin_password="change-me", secret_key="dev-secret")) == ["ADMIN_PASSWORD", "SECRET_KEY"]
    assert insecure_defaults(Settings(admin_password="x9!Kq", secret_key="change-me-too")) == ["SECRET_KEY"]
    assert insecure_defaults(Settings(admin_password="x9!Kq", secret_key="long-random")) == []


async def test_startup_warns_on_defaults_and_ensures_bucket(monkeypatch, caplog):
    from app import main
    from app.config import Settings

    created = []

    class Bucket:
        async def ensure_bucket(self):
            created.append(True)

    monkeypatch.setattr(main, "settings", Settings(admin_password="change-me", secret_key="long-random"))
    monkeypatch.setattr(main, "get_storage", Bucket)
    async with main.lifespan(main.app):
        pass
    assert created == [True]
    assert "ADMIN_PASSWORD" in caplog.text and "SECRET_KEY" not in caplog.text


def test_admin_email_is_normalized(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("ADMIN_EMAIL", "  Admin@Site.COM ")
    assert Settings().admin_email == "admin@site.com"
