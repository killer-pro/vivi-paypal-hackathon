import pytest

from app.app_settings import AppSettings
from app.services import credits
from tests.test_api_auth import NEW_PASSWORD, link_token, register


async def _signup(api_as, mailer, email="a@x.com"):
    anon = await api_as(None)
    await register(anon, email)
    return anon, link_token(mailer.outbox[-1], "/verify")


async def _balance(c) -> dict:
    return (await c.get("/api/credits")).json()


async def test_verify_grants_signup_credits_once(api_as, session, mailer):
    anon, token = await _signup(api_as, mailer)
    assert (await anon.post("/api/auth/verify", json={"token": token})).status_code == 200
    from tests.test_api_auth import user_by_email
    user = await user_by_email(session, "a@x.com")
    c = await api_as(user)
    body = await _balance(c)
    assert body["balance"] == {"subscription": 0, "topup": 200, "total": 200}
    assert [(e["kind"], e["amount"], e["bucket"]) for e in body["entries"]] == [("signup_grant", 200, "topup")]
    # la réinitialisation vérifie aussi l'adresse : pas de second octroi
    await anon.post("/api/auth/forgot", json={"email": "a@x.com"})
    await anon.post("/api/auth/reset", json={"token": link_token(mailer.outbox[-1], "/reset"), "password": NEW_PASSWORD})
    await session.refresh(user)  # la réinitialisation révoque les sessions : nouveau cookie
    assert (await _balance(await api_as(user)))["balance"]["total"] == 200


async def test_reset_of_unverified_account_grants_when_it_verifies(api_as, session, mailer):
    anon, _ = await _signup(api_as, mailer)
    from tests.test_api_auth import user_by_email
    user = await user_by_email(session, "a@x.com")
    c = await api_as(user)
    assert (await _balance(c))["balance"]["total"] == 0
    await anon.post("/api/auth/forgot", json={"email": "a@x.com"})
    await anon.post("/api/auth/reset", json={"token": link_token(mailer.outbox[-1], "/reset"), "password": NEW_PASSWORD})
    await session.refresh(user)
    assert (await _balance(await api_as(user)))["balance"]["total"] == 200


async def test_unverified_account_has_zero_credits(api_as, make_user, session):
    user = await make_user("u@x.fr", verified=False)
    assert await credits.grant_signup_credits(session, user, AppSettings(session)) is False
    assert (await _balance(await api_as(user)))["balance"]["total"] == 0


async def test_signup_grant_amount_follows_setting(api_as, make_user, session):
    await AppSettings(session).set("credits_signup_grant", "30")
    user = await make_user("u@x.fr")
    assert await credits.grant_signup_credits(session, user, AppSettings(session)) is True
    assert await credits.grant_signup_credits(session, user, AppSettings(session)) is False
    await session.commit()
    assert (await _balance(await api_as(user)))["balance"]["total"] == 30


async def test_zero_signup_grant_setting_grants_nothing(make_user, session):
    await AppSettings(session).set("credits_signup_grant", "0")
    user = await make_user("u@x.fr")
    assert await credits.grant_signup_credits(session, user, AppSettings(session)) is False


async def test_credits_endpoint_lists_own_entries_only(api_as, make_user, fund):
    a, b = await make_user("a@x.fr"), await make_user("b@x.fr")
    await fund(a, 40)
    await fund(b, 70)
    body = await _balance(await api_as(a))
    assert body["balance"]["total"] == 40 and [e["amount"] for e in body["entries"]] == [40]
    assert body["unlimited"] is False and body["next_before_id"] is None


async def test_credits_pagination(api_as, make_user, fund):
    user = await make_user("a@x.fr")
    for _ in range(51):
        await fund(user, 1)
    c = await api_as(user)
    page1 = (await c.get("/api/credits")).json()
    assert len(page1["entries"]) == 50 and page1["next_before_id"] == page1["entries"][-1]["id"]
    page2 = (await c.get(f"/api/credits?before_id={page1['next_before_id']}")).json()
    assert len(page2["entries"]) == 1 and page2["next_before_id"] is None
    assert page2["entries"][0]["id"] < page1["entries"][-1]["id"]
    assert (await c.get("/api/credits?limit=0")).status_code == 422


async def test_admin_is_unlimited_flag(api, admin, session):
    body = await _balance(api)
    assert body["unlimited"] is True and body["balance"]["total"] == 0


async def test_anonymous_cannot_read_credits(api_as):
    assert (await (await api_as(None)).get("/api/credits")).status_code == 401


@pytest.mark.parametrize("field", ["id", "kind", "bucket", "amount", "reason", "project_id", "step", "created_at"])
async def test_entry_shape(api_as, make_user, fund, field):
    user = await make_user("a@x.fr")
    await fund(user, 5)
    assert field in (await _balance(await api_as(user)))["entries"][0]

