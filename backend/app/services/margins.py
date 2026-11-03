from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CreditReservation, Project, ProviderCall, User
from app.services.pricing import Pricing


def _action(step: str) -> str:
    """Action facturée d'un appel : les appels de l'assistant (`assist:titre`…) se facturent sous `assist`."""
    return step.split(":")[0]


def _row(step: str, cost: float, credits: int, usd_per_credit: float) -> dict:
    revenue = round(credits * usd_per_credit, 6)
    return {"step": step, "cost_usd": round(cost, 6), "credits": credits, "revenue_usd": revenue,
            "ratio": round(revenue / cost, 4) if cost > 0 else None}


async def report(session: AsyncSession, pricing: Pricing, since: datetime | None) -> list[dict]:
    """Coût de revient (appels des projets de clients) face aux crédits réglés, par action. Le revenu est estimé au
    prix nominal du crédit ; les projets de l'administrateur, non facturés, sont exclus."""
    clients = select(User.id).where(User.role != "admin")
    calls = (select(ProviderCall.step, func.sum(ProviderCall.cost_usd))
             .join(Project, Project.id == ProviderCall.project_id).where(Project.user_id.in_(clients)))
    billed = (select(CreditReservation.step, func.sum(CreditReservation.used))
              .where(CreditReservation.status == "closed", CreditReservation.user_id.in_(clients)))
    if since is not None:
        calls = calls.where(ProviderCall.created_at >= since)
        billed = billed.where(CreditReservation.created_at >= since)
    cost: dict[str, float] = {}
    for step, total in await session.execute(calls.group_by(ProviderCall.step)):
        cost[_action(step)] = cost.get(_action(step), 0.0) + float(total or 0)
    used: dict[str, int] = {}
    for step, credits in await session.execute(billed.group_by(CreditReservation.step)):
        used[_action(step)] = used.get(_action(step), 0) + int(credits or 0)
    usd = float(pricing.usd_per_credit)
    return [_row(step, cost.get(step, 0.0), used.get(step, 0), usd) for step in sorted(cost.keys() | used.keys())]


def totals(rows: list[dict], usd_per_credit: float) -> dict:
    total = _row("", sum(r["cost_usd"] for r in rows), sum(r["credits"] for r in rows), usd_per_credit)
    return {key: value for key, value in total.items() if key != "step"}
