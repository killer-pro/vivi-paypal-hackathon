from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models import Project, ProviderCall
from app.services import credits, margins
from app.services.pricing import Pricing


def _pricing() -> Pricing:
    return Pricing(Decimal("0.05"), Decimal("2.5"), {}, {}, {})


async def _project(session, owner) -> int:
    p = Project(user_id=owner.id, title="p", theme="t")
    session.add(p)
    await session.commit()
    return p.id


async def _call(session, project_id, step, cost, when=None):
    session.add(ProviderCall(project_id=project_id, step=step, provider="x", model="m", cost_usd=cost, status="ok",
                             **({"created_at": when} if when else {})))
    await session.commit()


async def _bill(session, user, pid, step, used):
    await credits.grant(session, user.id, 100, bucket="topup", kind="adjust", reason="t")
    r = await credits.reserve(session, user.id, used, project_id=pid, step=step, reason="t")
    await credits.close(session, r, used=used)
    await session.commit()


async def test_ratio_is_revenue_over_cost(session, make_user):
    u = await make_user("a@x.fr")
    pid = await _project(session, u)
    await _call(session, pid, "clips", 0.10)
    await _bill(session, u, pid, "clips", 6)
    rows = {r["step"]: r for r in await margins.report(session, _pricing(), None)}
    assert rows["clips"] == {"step": "clips", "cost_usd": 0.1, "credits": 6, "revenue_usd": 0.3, "ratio": 3.0}


async def test_zero_cost_gives_no_ratio_and_assist_steps_merge(session, make_user):
    u = await make_user("a@x.fr")
    pid = await _project(session, u)
    await _call(session, pid, "assist:title", 0.0)
    await _call(session, pid, "assist:hook", 0.0)
    await _bill(session, u, pid, "assist", 2)
    rows = {r["step"]: r for r in await margins.report(session, _pricing(), None)}
    assert rows["assist"]["ratio"] is None and rows["assist"]["credits"] == 2


async def test_admin_projects_are_not_counted_and_since_filters(session, make_user, admin):
    u = await make_user("a@x.fr")
    mine, theirs = await _project(session, u), await _project(session, admin)
    await _call(session, theirs, "clips", 5.0)
    await _call(session, mine, "clips", 1.0, when=datetime.now(UTC) - timedelta(days=40))
    await _call(session, mine, "clips", 0.2)
    rows = await margins.report(session, _pricing(), datetime.now(UTC) - timedelta(days=30))
    assert [(r["step"], r["cost_usd"]) for r in rows] == [("clips", 0.2)]
