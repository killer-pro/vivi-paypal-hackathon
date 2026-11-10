import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import select, update

from app.api import auth
from app.api.auth import MAX_LOGIN_FAILURES, LoginThrottle
from app.config import Settings, settings
from app.mailer import get_mailer
from app.main import app, lifespan
from app.models import EmailToken, User
from tests.conftest import PASSWORD

NEW_PASSWORD = "nouveau-secret-42"


def link_token(mail, path: str) -> str:
    """Jeton du lien `{public_url}{path}?token=…` contenu dans un e-mail."""
    link = next(word for word in mail.body.split() if word.startswith(f"{settings.public_url}{path}?token="))
    return parse_qs(urlparse(link).query)["token"][0]


async def register(c, email="a@x.com", password=PASSWORD):
    return await c.post("/api/auth/register", json={"email": email, "password": password})


async def login(c, email="a@x.com", password=PASSWORD):
    return await c.post("/api/auth/login", json={"email": email, "password": password})


async def resend(c, email="a@x.com", password=PASSWORD):
    return await c.post("/api/auth/resend", json={"email": email, "password": password})


async def user_by_email(session, email) -> User | None:
    return (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()


async def test_projects_require_cookie(api_as):
    c = await api_as(None)
    assert (await c.get("/api/projects")).status_code == 401
    assert (await c.get("/api/events")).status_code == 401


async def test_invalid_cookie_is_rejected(api_as):
    c = await api_as(None)
    c.cookies.set("session", "forged")
    assert (await c.get("/api/auth/me")).status_code == 401


async def test_health_is_public(api_as):
    assert (await (await api_as(None)).get("/api/health")).status_code == 200


async def test_register_sends_verification_and_verify_marks_verified(api_as, mailer):
    c = await api_as(None)
    r = await register(c)
    assert r.status_code == 202 and r.json() == {"ok": True}
    [mail] = mailer.outbox
    assert mail.to == "a@x.com" and f"{settings.public_url}/verify?token=" in mail.body
    r = await login(c)
    assert r.status_code == 403 and r.json()["detail"] == auth.UNVERIFIED and "set-cookie" not in r.headers
    r = await c.post("/api/auth/verify", json={"token": link_token(mail, "/verify")})
    assert r.status_code == 200 and r.json()["email_verified"] is True  # le lien connecte directement
    me = (await c.get("/api/auth/me")).json()
    assert me["email"] == "a@x.com" and me["role"] == "user" and me["email_verified"] is True
    assert set(me) == {"id", "email", "role", "email_verified", "subscribed", "subscription_ends_at"}
    assert (await login(c)).status_code == 200


async def test_register_normalizes_email(api_as, session, mailer):
    c = await api_as(None)
    assert (await register(c, "  A@X.com ")).status_code == 202
    assert (await register(c, "a@x.com")).status_code == 202
    assert len((await session.execute(select(User).where(User.email.ilike("%a@x.com%")))).scalars().all()) == 1
    assert (await user_by_email(session, "a@x.com")) is not None
    assert (await login(c, "A@X.COM")).status_code == 403  # compte retrouvé (mot de passe juste), adresse à confirmer


async def test_register_existing_email_same_response(api_as, make_user, mailer):
    await make_user("pris@x.com", verified=True)
    c = await api_as(None)
    new = await register(c, "neuf@x.com")
    taken = await register(c, "pris@x.com", "autre-mot-de-passe")
    assert (taken.status_code, taken.json()) == (new.status_code, new.json()) == (202, {"ok": True})
    assert [m.to for m in mailer.outbox] == ["neuf@x.com"]  # rien pour le compte déjà vérifié
    assert (await login(c, "pris@x.com", "autre-mot-de-passe")).status_code == 401  # mot de passe inchangé


async def test_register_existing_unverified_sends_a_reset_link(api_as, make_user, mailer):
    await make_user("attente@x.com", verified=False)
    c = await api_as(None)
    r = await register(c, "attente@x.com", "autre-mot-de-passe")
    assert (r.status_code, r.json()) == (202, {"ok": True})
    [mail] = mailer.outbox
    assert mail.to == "attente@x.com" and "/reset?token=" in mail.body and "/verify?token=" not in mail.body
    assert (await login(c, "attente@x.com", "autre-mot-de-passe")).status_code == 401  # aucun écrasement


async def test_pre_registration_takeover_is_defeated(api_as, session, mailer):
    """Un attaquant inscrit l'adresse de la victime avec son mot de passe ; la victime refait l'inscription : elle reçoit
    un lien de réinitialisation, qui lui rend le compte et coupe la session de l'attaquant."""
    attacker = await api_as(None)
    assert (await register(attacker, "victime@x.com", "mot-de-l-attaquant")).status_code == 202
    assert (await login(attacker, "victime@x.com", "mot-de-l-attaquant")).status_code == 403  # aucune session
    victim = await api_as(None)
    mailer.outbox.clear()
    assert (await register(victim, "victime@x.com", "mot-de-la-victime")).status_code == 202
    [mail] = mailer.outbox
    assert "/verify?token=" not in mail.body
    r = await victim.post("/api/auth/reset", json={"token": link_token(mail, "/reset"), "password": NEW_PASSWORD})
    assert r.status_code == 200
    assert (await login(victim, "victime@x.com", "mot-de-l-attaquant")).status_code == 401
    assert (await login(victim, "victime@x.com", NEW_PASSWORD)).status_code == 200
    assert (await victim.get("/api/auth/me")).json()["email_verified"] is True
    assert (await user_by_email(session, "victime@x.com")).email_verified_at is not None


async def test_verify_revokes_sessions_opened_before(api_as, make_user, mailer):
    user = await make_user("a@x.com", verified=False)
    old_cookie = auth.make_session_cookie(user.id, user.session_epoch)
    assert (await resend(await api_as(None))).status_code == 202
    r = await (await api_as(None)).post("/api/auth/verify", json={"token": link_token(mailer.outbox[0], "/verify")})
    assert r.status_code == 200 and user.session_epoch == 1
    before = await api_as(None)
    before.cookies.set("session", old_cookie)
    assert (await before.get("/api/auth/me")).status_code == 401


async def test_unverified_session_cookie_is_rejected(api_as, make_user):
    """Un cookie d'avant la règle (compte non vérifié) n'ouvre plus rien."""
    c = await api_as(await make_user("a@x.com", verified=False))
    assert (await c.get("/api/auth/me")).status_code == 401
    assert (await c.get("/api/projects")).status_code == 401


async def test_verify_token_invalid_cases(api_as, session, make_user, mailer):
    c = await api_as(None)
    await register(c)
    user = await user_by_email(session, "a@x.com")
    verify_token = link_token(mailer.outbox[-1], "/verify")
    await c.post("/api/auth/forgot", json={"email": "a@x.com"})
    reset_token = link_token(mailer.outbox[-1], "/reset")

    async def rejected(token):
        r = await c.post("/api/auth/verify", json={"token": token})
        await session.refresh(user)
        return r.status_code == 400 and r.json()["detail"] == "Lien invalide ou expiré" and user.email_verified_at is None

    assert await rejected("falsifie")
    assert await rejected(reset_token)  # jeton de réinitialisation présenté à /verify
    await session.execute(update(EmailToken).where(EmailToken.kind == "verify")
                          .values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    await session.commit()
    assert await rejected(verify_token)  # expiré

    await resend(c)  # nouveau lien (compte non vérifié)
    fresh = link_token(mailer.outbox[-1], "/verify")
    assert (await c.post("/api/auth/verify", json={"token": fresh})).status_code == 200
    await session.refresh(user)
    verified_at = user.email_verified_at
    r = await c.post("/api/auth/verify", json={"token": fresh})  # déjà utilisé
    await session.refresh(user)
    assert r.status_code == 400 and user.email_verified_at == verified_at


async def test_reset_rejects_a_verification_token(api_as, session, mailer):
    c = await api_as(None)
    await register(c)
    r = await c.post("/api/auth/reset", json={"token": link_token(mailer.outbox[-1], "/verify"), "password": NEW_PASSWORD})
    assert r.status_code == 400 and r.json()["detail"] == "Lien invalide ou expiré"
    assert (await login(c)).status_code == 403 and (await login(c, password=NEW_PASSWORD)).status_code == 401


async def test_login_wrong_password_and_unknown_email_same_message(api_as, make_user):
    await make_user("a@x.com")
    c = await api_as(None)
    wrong = await login(c, password="mauvais-mot")
    unknown = await login(c, "inconnu@x.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Email ou mot de passe incorrect"}
    assert "session" not in wrong.cookies and "session" not in unknown.cookies


async def test_unknown_email_still_verifies_a_hash(api_as, monkeypatch):
    calls = []
    real = auth.verify_password
    monkeypatch.setattr(auth, "verify_password", lambda p, h: calls.append(h) or real(p, h))
    assert (await login(await api_as(None), "inconnu@x.com")).status_code == 401
    assert len(calls) == 1 and calls[0].startswith("scrypt$")  # même coût que pour un compte existant


async def test_login_sets_secure_cookie_and_me(api_as, make_user):
    user = await make_user("a@x.com")
    c = await api_as(None)
    r = await login(c)
    assert r.status_code == 200 and r.json()["id"] == user.id
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and f"max-age={30 * 24 * 3600}" in cookie
    assert (await c.get("/api/auth/me")).json()["email"] == "a@x.com"


async def test_unverified_user_cannot_login(api_as, make_user):
    await make_user("a@x.com", verified=False)
    c = await api_as(None)
    r = await login(c)
    assert r.status_code == 403 and r.json()["detail"] == auth.UNVERIFIED and "set-cookie" not in r.headers
    assert (await login(c, password="mauvais-mot-de-passe")).status_code == 401  # rien n'est révélé sans le mot de passe
    assert (await c.get("/api/projects")).status_code == 401


async def test_resend_sends_link_only_when_unverified(api_as, make_user, mailer):
    await make_user("attente@x.com", verified=False)
    await make_user("ok@x.com", verified=True)
    c = await api_as(None)
    assert (await resend(c, "attente@x.com")).status_code == 202
    assert (await resend(c, "ok@x.com")).status_code == 202
    assert [m.to for m in mailer.outbox] == ["attente@x.com"]
    assert "/verify?token=" in mailer.outbox[0].body


async def test_resend_requires_the_password(api_as, make_user, mailer):
    await make_user("attente@x.com", verified=False)
    c = await api_as(None)
    for email, password in (("attente@x.com", "mauvais-mot-de-passe"), ("inconnu@x.com", PASSWORD)):
        r = await resend(c, email, password)
        assert r.status_code == 401 and r.json()["detail"] == auth.BAD_CREDENTIALS
    assert mailer.outbox == []


async def test_resend_is_rate_limited(api_as, make_user):
    await make_user("attente@x.com", verified=False)
    c = await api_as(None)
    for _ in range(auth.signup_throttle.max_failures):
        assert (await resend(c, "attente@x.com")).status_code == 202
    r = await resend(c, "attente@x.com")
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


async def test_logout_revokes_only_that_user(api_as, make_user):
    a, b = await make_user("a@x.com"), await make_user("b@x.com")
    client_a, client_b = await api_as(a), await api_as(b)
    copy_a = await api_as(a)  # cookie de A copié ailleurs
    assert (await client_a.post("/api/auth/logout")).status_code == 200
    assert (await copy_a.get("/api/auth/me")).status_code == 401
    assert (await client_b.get("/api/auth/me")).status_code == 200
    assert (await login(client_a)).status_code == 200  # nouvelle session sur la nouvelle époque
    assert (await client_a.get("/api/auth/me")).status_code == 200


async def test_anonymous_logout_does_not_revoke_sessions(api_as, make_user):
    user = await make_user("a@x.com")
    c = await api_as(user)
    assert (await (await api_as(None)).post("/api/auth/logout")).status_code == 200
    assert (await c.get("/api/auth/me")).status_code == 200 and user.session_epoch == 0


async def test_reset_password_flow(api_as, make_user, mailer):
    user = await make_user("a@x.com")
    old_session = await api_as(user)
    other = await api_as(await make_user("b@x.com"))
    c = await api_as(None)
    assert (await c.post("/api/auth/forgot", json={"email": " A@x.com"})).status_code == 202
    [mail] = mailer.outbox
    assert mail.to == "a@x.com"
    token = link_token(mail, "/reset")
    r = await c.post("/api/auth/reset", json={"token": token, "password": NEW_PASSWORD})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert (await login(c)).status_code == 401
    assert (await login(c, password=NEW_PASSWORD)).status_code == 200
    assert (await old_session.get("/api/auth/me")).status_code == 401
    assert (await other.get("/api/auth/me")).status_code == 200  # les autres comptes gardent leur session
    r = await c.post("/api/auth/reset", json={"token": token, "password": "encore-un-autre"})
    assert r.status_code == 400 and r.json()["detail"] == "Lien invalide ou expiré"


async def test_reset_with_expired_token_changes_nothing(api_as, session, make_user, mailer):
    await make_user("a@x.com")
    c = await api_as(None)
    await c.post("/api/auth/forgot", json={"email": "a@x.com"})
    await session.execute(update(EmailToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    await session.commit()
    r = await c.post("/api/auth/reset", json={"token": link_token(mailer.outbox[0], "/reset"), "password": NEW_PASSWORD})
    assert r.status_code == 400 and (await login(c)).status_code == 200


async def test_forgot_unknown_email_returns_202_without_mail(api_as, mailer):
    r = await (await api_as(None)).post("/api/auth/forgot", json={"email": "inconnu@x.com"})
    assert r.status_code == 202 and r.json() == {"ok": True} and mailer.outbox == []


async def test_password_length_limits(api_as, make_user, mailer, monkeypatch):
    def no_hash(*_):
        raise AssertionError("hachage calculé avant la validation de longueur")

    await make_user("a@x.com")
    c = await api_as(None)
    await c.post("/api/auth/forgot", json={"email": "a@x.com"})
    token = link_token(mailer.outbox[0], "/reset")
    monkeypatch.setattr(auth, "hash_password", no_hash)
    monkeypatch.setattr(auth, "verify_password", no_hash)
    for password in ("x" * 7, "x" * 10_000):
        assert (await register(c, "b@x.com", password)).status_code == 422
        assert (await c.post("/api/auth/reset", json={"token": token, "password": password})).status_code == 422
    assert (await login(c, password="x" * 10_000)).status_code == 422


async def test_email_is_validated(api_as):
    c = await api_as(None)
    for email in ("sans-arobase", "a b@x.com", "a@" + "x" * 250 + ".com"):
        assert (await register(c, email)).status_code == 422


async def test_signup_throttle(api_as):
    c = await api_as(None)
    for i in range(5):
        assert (await register(c, f"u{i}@x.com")).status_code == 202
    r = await register(c, "u5@x.com")
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


async def test_mail_failure_keeps_uniform_response(api_as, make_user, monkeypatch, caplog):
    class Broken:
        async def send(self, mail):
            raise OSError("connexion refusée par smtp.secret.example")

    tokens = []
    real = auth.new_token
    monkeypatch.setattr(auth, "new_token", lambda: tokens.append(real()[0]) or (tokens[-1], auth.token_hash(tokens[-1])))
    app.dependency_overrides[get_mailer] = lambda: Broken()
    c = await api_as(None)
    await make_user("a@x.com", verified=False)
    with caplog.at_level(logging.ERROR, logger="app"):
        responses = [await register(c, "neuf@x.com"), await c.post("/api/auth/forgot", json={"email": "a@x.com"}),
                     await resend(c)]
    assert [(r.status_code, r.json()) for r in responses] == [(202, {"ok": True})] * 3
    assert all("smtp.secret.example" not in r.text for r in responses)
    assert len(tokens) == 3 and len(caplog.records) == 3
    assert not any(token in record.getMessage() for record in caplog.records for token in tokens)


async def test_legacy_cookie_rejected(api_as):
    c = await api_as(None)
    legacy = URLSafeTimedSerializer(settings.secret_key)
    for content in ({"user": "admin", "epoch": 0}, "admin"):
        c.cookies.set("session", legacy.dumps(content))
        assert (await c.get("/api/auth/me")).status_code == 401


async def test_cookie_of_a_deleted_user_is_rejected(api_as, session, make_user):
    user = await make_user("a@x.com")
    c = await api_as(user)
    await session.delete(user)
    await session.commit()
    assert (await c.get("/api/auth/me")).status_code == 401


async def test_login_is_throttled_after_repeated_failures(api_as, make_user):
    await make_user("a@x.com")
    c = await api_as(None)
    for _ in range(MAX_LOGIN_FAILURES):
        assert (await login(c, password="mauvais-mot")).status_code == 401
    blocked = await login(c)
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0
    assert "session" not in blocked.cookies  # même le bon mot de passe est refusé pendant le blocage


async def test_successful_login_resets_the_failure_count(api_as, make_user):
    await make_user("a@x.com")
    c = await api_as(None)
    for _ in range(MAX_LOGIN_FAILURES - 1):
        await login(c, password="mauvais-mot")
    assert (await login(c)).status_code == 200
    assert (await login(c, password="mauvais-mot")).status_code == 401


def test_throttle_window_slides_and_clients_are_independent():
    now = [0.0]
    t = LoginThrottle(max_failures=2, window_s=60, clock=lambda: now[0])
    t.fail("a")
    t.fail("a")
    assert t.retry_after("a") == 61 and t.retry_after("b") == 0
    now[0] = 61
    assert t.retry_after("a") == 0 and t._failures == {}  # fenêtre écoulée : plus rien en mémoire


@pytest.mark.parametrize("env, prod", [("dev", False), ("DEV ", False), ("prod", True), ("staging", True)])
def test_only_dev_is_not_production(env, prod):
    assert Settings(app_env=env).is_prod is prod


async def test_production_refuses_default_secrets(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setattr(settings, "admin_password", "change-me")
    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
        async with lifespan(app):
            pass


async def test_settings_forbidden_for_user(api_as, make_user):
    c = await api_as(await make_user("u@x.com"))
    for r in (await c.get("/api/settings"), await c.put("/api/settings", json={"project_budget_usd": "0"}),
              await c.get("/api/providers/voices")):
        assert (r.status_code, r.json()) == (403, {"detail": "Réservé à l'administrateur"})


async def test_admin_reads_settings(api):
    assert (await api.get("/api/settings")).status_code == 200


async def test_editor_settings_readable_by_user_without_secrets(api_as, make_user, session):
    from app.app_settings import EDITOR_KEYS, SECRET_KEYS, AppSettings
    await AppSettings(session).set_many({"gemini_api_key": "secret-1234", "image_provider": "fal"})
    r = await (await api_as(await make_user("u@x.com"))).get("/api/settings/editor")
    assert r.status_code == 200 and set(r.json()) == EDITOR_KEYS and not EDITOR_KEYS & SECRET_KEYS
    assert r.json()["image_provider"] == "fal" and "secret-1234" not in r.text


async def test_music_write_forbidden_for_user_read_allowed(api_as, make_user, session):
    from app.models import MusicTrack
    session.add(MusicTrack(name="piste", tags=[], duration_s=1.0, key="music/piste.mp3"))
    await session.commit()
    c = await api_as(await make_user("u@x.com"))
    r = await c.get("/api/music")
    assert r.status_code == 200 and [t["name"] for t in r.json()] == ["piste"]
    upload = await c.post("/api/music", files={"file": ("a.mp3", b"x", "audio/mpeg")}, data={"name": "n"})
    delete = await c.delete(f"/api/music/{r.json()[0]['id']}")
    assert upload.status_code == delete.status_code == 403
    assert len((await c.get("/api/music")).json()) == 1


async def test_editor_routes_open_to_user(api_as, make_user):
    c = await api_as(await make_user("u@x.com"))
    for path in ("/api/providers/health", "/api/providers/models", "/api/styles"):
        assert (await c.get(path)).status_code == 200, path
