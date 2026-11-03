from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.credits_api import ENTRIES_LIMIT, MAX_ENTRIES_LIMIT, balance_json, ledger_page
from app.app_settings import AppSettings
from app.db import get_session
from app.models import CreditBalance, CreditReservation, User
from app.services import credits, margins
from app.services.pricing import load_pricing

router = APIRouter(tags=["admin"])

CUSTOMERS_LIMIT, MAX_CUSTOMERS_LIMIT = 50, 200


class AdjustIn(BaseModel):
    amount: int = Field(ge=-1_000_000, le=1_000_000)
    bucket: Literal["subscription", "topup"]
    reason: str = Field(max_length=300)

    @field_validator("amount")
    @classmethod
    def _amount(cls, value: int) -> int:
        if value == 0:
            raise ValueError("Le montant ne peut pas être nul")
        return value

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Le motif est obligatoire")
        return value.strip()


def _customer(user: User, balance: credits.Balance, spent: int) -> dict:
    return {"id": user.id, "email": user.email, "role": user.role, "verified": user.email_verified_at is not None,
            "subscribed": user.is_subscribed, "subscription_ends_at": user.subscription_ends_at,
            "created_at": user.created_at, "balance": balance_json(balance), "spent": spent}


async def _spent(session: AsyncSession, user_ids: list[int]) -> dict[int, int]:
    """Crédits réglés par compte : somme des `used` des réservations fermées."""
    rows = await session.execute(select(CreditReservation.user_id, func.coalesce(func.sum(CreditReservation.used), 0))
                                 .where(CreditReservation.user_id.in_(user_ids), CreditReservation.status == "closed")
                                 .group_by(CreditReservation.user_id))
    return {uid: int(total or 0) for uid, total in rows}


@router.get("/customers")
async def list_customers(q: str = "", limit: int = Query(CUSTOMERS_LIMIT, ge=1, le=MAX_CUSTOMERS_LIMIT),
                         offset: int = Query(0, ge=0), session: AsyncSession = Depends(get_session)) -> dict:
    """Comptes (les plus récents d'abord) avec offre, solde et crédits réglés ; `q` filtre sur l'adresse e-mail."""
    where = [User.email.ilike(f"%{q.strip().replace('%', '').replace('_', '')}%")] if q.strip() else []
    users = (await session.scalars(select(User).where(*where).order_by(User.id.desc()).limit(limit).offset(offset))).all()
    total = await session.scalar(select(func.count()).select_from(User).where(*where))
    ids = [u.id for u in users]
    balances = {b.user_id: credits.Balance(b.subscription, b.topup) for b in
                (await session.scalars(select(CreditBalance).where(CreditBalance.user_id.in_(ids)))).all()}
    spent = await _spent(session, ids)
    return {"total": total, "customers": [_customer(u, balances.get(u.id, credits.Balance(0, 0)), spent.get(u.id, 0))
                                          for u in users]}


async def _user_or_404(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Compte introuvable")
    return user


@router.get("/customers/{user_id}")
async def customer(user_id: int, limit: int = Query(ENTRIES_LIMIT, ge=1, le=MAX_ENTRIES_LIMIT),
                   before_id: int | None = None, session: AsyncSession = Depends(get_session)) -> dict:
    """Un compte avec son registre de crédits (paginé comme `GET /api/credits`)."""
    user = await _user_or_404(session, user_id)
    return {"customer": _customer(user, await credits.balance(session, user_id), (await _spent(session, [user_id])).get(user_id, 0)),
            **await ledger_page(session, user_id, limit, before_id)}


@router.post("/customers/{user_id}/credits")
async def adjust_credits(user_id: int, body: AdjustIn, session: AsyncSession = Depends(get_session)) -> dict:
    """Ajustement manuel d'un lot (positif ou négatif), tracé dans le registre avec son motif."""
    user = await _user_or_404(session, user_id)
    if user.is_admin:
        raise HTTPException(409, "Le compte administrateur n'est pas limité par ses crédits")
    try:
        await credits.adjust(session, user_id, body.amount, bucket=body.bucket, reason=body.reason)
    except credits.CreditsRefused:
        await session.rollback()
        raise
    await session.commit()
    return {"balance": balance_json(await credits.balance(session, user_id))}


@router.get("/margins")
async def get_margins(since: datetime | None = None, session: AsyncSession = Depends(get_session)) -> dict:
    """Coût de revient et crédits facturés par action (clients seulement) : `ratio` = revenu estimé ÷ coût, à comparer
    à la marge visée."""
    pricing = await load_pricing(AppSettings(session))
    rows = await margins.report(session, pricing, since)
    usd = float(pricing.usd_per_credit)
    return {"usd_per_credit": usd, "margin": float(pricing.margin), "rows": rows, "totals": margins.totals(rows, usd)}
