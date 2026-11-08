import pytest
from sqlalchemy import select

from app.models import CreditEntry, CreditReservation
from app.services import credits


@pytest.fixture
async def admin_client(api_as, admin):
    return await api_as(admin)


async def _fund(session, user, amount, bucket="topup"):
    await credits.grant(session, user.id, amount, bucket=bucket, kind="adjust", reason="test")
    await session.commit()


@pytest.mark.parametrize("method,path", [("get", "/api/admin/customers"), ("get", "/api/admin/customers/1"), ("get", "/api/admin/margins"),
                                         ("post", "/api/admin/customers/1/credits")])
async def test_admin_routes_refuse_clients(api_as, make_user, method, path):
    c = await api_as(await make_user("a@x.fr"))
    r = await getattr(c, method)(path, **({"json": {"amount": 1, "bucket": "topup", "reason": "x"}} if method == "post" else {}))
    assert r.status_code == 403


async def test_customers_list_shows_balance_spent_and_filters(admin_client, session, make_user):
    a = await make_user("alice@x.fr")
    await make_user("bob@x.fr")
    await _fund(session, a, 100)
    r = await credits.reserve(session, a.id, 30, project_id=None, step="clips", reason="t")
    await credits.close(session, r, used=20)
    await session.commit()
    body = (await admin_client.get("/api/admin/customers")).json()
    by_email = {c["email"]: c for c in body["customers"]}
    assert by_email["alice@x.fr"]["balance"] == {"subscription": 0, "topup": 80, "total": 80}
    assert by_email["alice@x.fr"]["spent"] == 20 and by_email["bob@x.fr"]["spent"] == 0
    assert by_email["bob@x.fr"]["subscribed"] is False and by_email["admin@example.com"]["role"] == "admin"
    found = (await admin_client.get("/api/admin/customers", params={"q": "ALI"})).json()
    assert [c["email"] for c in found["customers"]] == ["alice@x.fr"] and found["total"] == 1


async def test_customer_detail_has_ledger_page(admin_client, session, make_user):
    u = await make_user("a@x.fr")
    for _ in range(3):
        await _fund(session, u, 5)
    body = (await admin_client.get(f"/api/admin/customers/{u.id}", params={"limit": 2})).json()
    assert body["customer"]["email"] == "a@x.fr" and len(body["entries"]) == 2 and body["next_before_id"]
    assert (await admin_client.get("/api/admin/customers/9999")).status_code == 404


async def test_adjust_adds_entry_with_reason(admin_client, session, make_user):
    u = await make_user("a@x.fr")
    r = await admin_client.post(f"/api/admin/customers/{u.id}/credits",
                                json={"amount": 50, "bucket": "topup", "reason": "Geste commercial"})
    assert r.status_code == 200 and r.json()["balance"]["topup"] == 50
    entry = (await session.execute(select(CreditEntry).where(CreditEntry.user_id == u.id))).scalar_one()
    assert (entry.kind, entry.amount, entry.reason) == ("adjust", 50, "Geste commercial")


async def test_adjust_rejections(admin_client, admin, session, make_user):
    u = await make_user("a@x.fr")
    uid, admin_id = u.id, admin.id  # un rollback expire les objets de la session
    await _fund(session, u, 10)
    url = f"/api/admin/customers/{uid}/credits"
    assert (await admin_client.post(url, json={"amount": -11, "bucket": "topup", "reason": "x"})).status_code == 409
    assert (await admin_client.post(url, json={"amount": 5, "bucket": "topup", "reason": "  "})).status_code == 422
    assert (await admin_client.post(url, json={"amount": 0, "bucket": "topup", "reason": "x"})).status_code == 422
    assert (await admin_client.post(url, json={"amount": 5, "bucket": "autre", "reason": "x"})).status_code == 422
    assert (await admin_client.post(f"/api/admin/customers/{admin_id}/credits",
                                    json={"amount": 5, "bucket": "topup", "reason": "x"})).status_code == 409
    assert (await admin_client.post("/api/admin/customers/9999/credits",
                                    json={"amount": 5, "bucket": "topup", "reason": "x"})).status_code == 404
    assert (await credits.balance(session, uid)).total == 10
    assert not (await session.execute(select(CreditReservation))).scalars().all()


async def test_margins_route(admin_client):
    body = (await admin_client.get("/api/admin/margins")).json()
    assert body["rows"] == [] and body["usd_per_credit"] == 0.01 and body["margin"] == 3
    assert body["totals"] == {"cost_usd": 0, "credits": 0, "revenue_usd": 0, "ratio": None}
