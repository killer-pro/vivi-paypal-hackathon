from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import current_user
from app.db import get_session
from app.models import CreditEntry, User
from app.services import credits

router = APIRouter(tags=["credits"])

ENTRIES_LIMIT, MAX_ENTRIES_LIMIT = 50, 200
ENTRY_FIELDS = ("id", "kind", "bucket", "amount", "reason", "project_id", "step", "created_at")


async def ledger_page(session: AsyncSession, user_id: int, limit: int, before_id: int | None) -> dict:
    """Une page du registre d'un compte, du mouvement le plus récent au plus ancien ; `next_before_id` est à passer en
    `before_id` pour la page suivante."""
    query = select(CreditEntry).where(CreditEntry.user_id == user_id).order_by(CreditEntry.id.desc()).limit(limit + 1)
    if before_id is not None:
        query = query.where(CreditEntry.id < before_id)
    rows = list((await session.execute(query)).scalars())
    page = rows[:limit]
    return {"entries": [{field: getattr(entry, field) for field in ENTRY_FIELDS} for entry in page],
            "next_before_id": page[-1].id if len(rows) > limit else None}


def balance_json(balance: credits.Balance) -> dict:
    return {"subscription": balance.subscription, "topup": balance.topup, "total": balance.total}


@router.get("/credits")
async def get_credits(limit: int = Query(ENTRIES_LIMIT, ge=1, le=MAX_ENTRIES_LIMIT), before_id: int | None = None,
                      user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    """Solde et registre du compte connecté. `unlimited` : compte administrateur, que le solde ne limite pas."""
    return {"unlimited": user.is_admin, "balance": balance_json(await credits.balance(session, user.id)),
            **await ledger_page(session, user.id, limit, before_id)}
