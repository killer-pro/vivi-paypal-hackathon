from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.app_settings import AppSettings
from app.models import CreditBalance, CreditEntry, CreditReservation, Step, User
from app.services.flow import RUN_ASSET_KIND, produced_in_run
from app.services.pricing import Pricing

# Ordre de consommation : les crédits d'abonnement d'abord, puis les rechargés.
BUCKETS = ("subscription", "topup")


@dataclass
class Balance:
    subscription: int
    topup: int

    @property
    def total(self) -> int:
        return self.subscription + self.topup


class CreditsRefused(HTTPException):
    """Lancement refusé faute de crédits (base de `InsufficientCredits` et de la limite de clips simultanés)."""

    def __init__(self, detail: str):
        super().__init__(status_code=409, detail=detail)


class ParallelLimit(CreditsRefused):
    def __init__(self):
        super().__init__("Une génération de clips est déjà en cours sur un autre de vos projets : attendez sa fin")


class InsufficientCredits(CreditsRefused):
    def __init__(self, needed: int, available: Balance):
        self.needed, self.available = needed, available.total
        super().__init__(f"Crédits insuffisants : il vous faut {needed} crédits, il vous en reste {available.total} "
                         f"({available.subscription} d'abonnement, {available.topup} rechargés)")


async def _locked_balance(session: AsyncSession, user_id: int) -> CreditBalance:
    """Ligne de solde du compte (créée à la demande) verrouillée jusqu'à la fin de la transaction."""
    await session.execute(pg_insert(CreditBalance).values(user_id=user_id).on_conflict_do_nothing())
    row = (await session.execute(select(CreditBalance).where(CreditBalance.user_id == user_id)
                                 .with_for_update().execution_options(populate_existing=True))).scalar_one()
    return row


async def lock_account(session: AsyncSession, user_id: int) -> None:
    """Sérialise les lancements d'un même compte (verrou du solde, levé au commit) : à prendre avant de compter ses
    générations en cours."""
    await _locked_balance(session, user_id)


def _entry(user_id: int, bucket: str, amount: int, kind: str, reason: str, *, reservation_id: int | None = None,
           project_id: int | None = None, step: str | None = None) -> CreditEntry:
    return CreditEntry(user_id=user_id, bucket=bucket, amount=amount, kind=kind, reason=reason,
                       reservation_id=reservation_id, project_id=project_id, step=step)


async def balance(session: AsyncSession, user_id: int) -> Balance:
    row = await session.get(CreditBalance, user_id, populate_existing=True)
    return Balance(row.subscription, row.topup) if row else Balance(0, 0)


async def grant(session: AsyncSession, user_id: int, amount: int, *, bucket: str, kind: str, reason: str,
                project_id: int | None = None) -> None:
    """Ajoute des crédits à un lot. Ne fait pas de `commit`."""
    if amount <= 0:
        raise ValueError("Un octroi de crédits doit être strictement positif")
    row = await _locked_balance(session, user_id)
    setattr(row, bucket, getattr(row, bucket) + amount)
    session.add(_entry(user_id, bucket, amount, kind, reason, project_id=project_id))
    await session.flush()


async def adjust(session: AsyncSession, user_id: int, delta: int, *, bucket: str, reason: str) -> None:
    """Ajustement manuel (admin) : crédite ou débite un lot, jamais en dessous de zéro. Ne fait pas de `commit`."""
    if delta == 0:
        raise ValueError("Un ajustement de crédits ne peut pas être nul")
    if delta > 0:
        return await grant(session, user_id, delta, bucket=bucket, kind="adjust", reason=reason)
    row = await _locked_balance(session, user_id)
    held = getattr(row, bucket)
    if -delta > held:
        raise CreditsRefused(f"Le lot « {bucket} » ne contient que {held} crédits : impossible d'en retirer {-delta}")
    setattr(row, bucket, held + delta)
    session.add(_entry(user_id, bucket, delta, "adjust", reason))
    await session.flush()


async def reserve(session: AsyncSession, user_id: int, amount: int, *, project_id: int | None, step: str,
                  run_id: str | None = None, scene_prices: dict[int, int] | None = None,
                  reason: str) -> CreditReservation:
    """Retient `amount` crédits (abonnement d'abord) de façon atomique : le verrou de la ligne de solde sérialise les
    lancements simultanés d'un même compte. Lève `InsufficientCredits` sans rien écrire si le solde ne suffit pas."""
    row = await _locked_balance(session, user_id)
    available = Balance(row.subscription, row.topup)
    if amount > available.total:
        raise InsufficientCredits(amount, available)
    parts = {"subscription": min(amount, row.subscription)}
    parts["topup"] = amount - parts["subscription"]
    reservation = CreditReservation(user_id=user_id, project_id=project_id, step=step, run_id=run_id, amount=amount,
                                    parts=parts, scene_prices={str(k): v for k, v in (scene_prices or {}).items()},
                                    status="open")
    session.add(reservation)
    await session.flush()
    for bucket in BUCKETS:
        if parts[bucket]:
            setattr(row, bucket, getattr(row, bucket) - parts[bucket])
            session.add(_entry(user_id, bucket, -parts[bucket], "reserve", reason, reservation_id=reservation.id,
                               project_id=project_id, step=step))
    await session.flush()
    return reservation


async def close(session: AsyncSession, reservation: CreditReservation, used: int) -> int:
    """Règle `used` crédits et rend le reste à leur lot d'origine ; renvoie le montant rendu. Idempotent : une
    réservation déjà fermée ne bouge plus (fin du job, annulation et balayeur peuvent se croiser). Ne fait pas de `commit`."""
    await session.refresh(reservation, with_for_update=True)
    if reservation.status == "closed":
        return 0
    used = max(0, min(used, reservation.amount))
    row = await _locked_balance(session, reservation.user_id)
    consumed = {"subscription": min(used, reservation.parts["subscription"])}
    consumed["topup"] = used - consumed["subscription"]
    refunded = 0
    for bucket in BUCKETS:
        back = reservation.parts[bucket] - consumed[bucket]
        if back:
            setattr(row, bucket, getattr(row, bucket) + back)
            refunded += back
            session.add(_entry(reservation.user_id, bucket, back, "refund", "Crédits rendus", reservation_id=reservation.id,
                               project_id=reservation.project_id, step=reservation.step))
    reservation.status, reservation.used, reservation.closed_at = "closed", used, datetime.now(UTC)
    await session.flush()
    return refunded


async def refund_all(session: AsyncSession, reservation: CreditReservation) -> int:
    return await close(session, reservation, 0)


async def grant_signup_credits(session: AsyncSession, user: User, app_settings: AppSettings) -> bool:
    """Crédits offerts à l'inscription : une seule fois par compte, et seulement une fois l'adresse vérifiée. Le verrou
    du solde sérialise deux vérifications simultanées (lien puis réinitialisation). Ne fait pas de `commit`."""
    if user.email_verified_at is None:
        return False
    amount = int(await app_settings.get("credits_signup_grant"))
    await _locked_balance(session, user.id)
    already = (await session.execute(select(CreditEntry.id).where(CreditEntry.user_id == user.id,
                                                                  CreditEntry.kind == "signup_grant"))).first()
    if already or amount <= 0:
        return False
    await grant(session, user.id, amount, bucket="topup", kind="signup_grant", reason="Crédits offerts à l'inscription")
    return True


async def _settled_credits(session: AsyncSession, reservation: CreditReservation, completed: bool) -> int:
    """Crédits à régler à la fermeture : étape par scène, le prix des scènes réellement produites par le lancement (réussi
    ou non, une scène en échec n'est pas facturée) ; autres étapes, le prix plein si l'étape a abouti, rien sinon."""
    if reservation.project_id is not None and reservation.step in RUN_ASSET_KIND:
        produced = await produced_in_run(session, reservation.project_id, reservation.step, reservation.run_id)
        return sum(price for scene_id, price in reservation.scene_prices.items() if int(scene_id) in produced)
    return reservation.amount if completed else 0


async def close_for_step(session: AsyncSession, project_id: int, step_name: str, *, completed: bool) -> int:
    """Ferme la réservation ouverte de l'étape (fin du job, annulation, échec, redémarrage du worker) et renvoie les
    crédits rendus ; sans réservation ouverte (compte administrateur, étape gratuite, déjà fermée), ne fait rien.
    Ne fait pas de `commit` : la fermeture vit dans la transaction qui change le statut de l'étape."""
    open_ones = (await session.scalars(select(CreditReservation).where(
        CreditReservation.project_id == project_id, CreditReservation.step == step_name,
        CreditReservation.status == "open").order_by(CreditReservation.id.desc()))).all()
    refunded = 0
    for i, reservation in enumerate(open_ones):  # la plus récente seule peut avoir abouti, les autres sont orphelines
        refunded += await close(session, reservation, await _settled_credits(session, reservation, completed and i == 0))
    return refunded


async def sweep_stale(session: AsyncSession, older_than: timedelta) -> int:
    """Ferme comme un échec les réservations ouvertes depuis plus de `older_than` dont l'étape ne tourne plus : le job qui
    les tenait est mort sans les régler. Une étape encore `running` garde sa réservation (un job de clips légitime dure
    des heures ; son timeout, l'annulation et le redémarrage du worker la ferment). Renvoie leur nombre."""
    running = select(Step.id).where(Step.project_id == CreditReservation.project_id, Step.name == CreditReservation.step,
                                    Step.status == "running").exists()
    stale = (await session.scalars(select(CreditReservation).where(
        CreditReservation.status == "open", CreditReservation.created_at < datetime.now(UTC) - older_than, ~running)
        .order_by(CreditReservation.id))).all()
    for reservation in stale:
        await close(session, reservation, await _settled_credits(session, reservation, False))
    return len(stale)


@asynccontextmanager
async def credit_hold(session: AsyncSession, user: User, pricing: Pricing, *, project_id: int | None, step: str,
                      reason: str) -> AsyncIterator[None]:
    """Facture un appel LLM isolé (assistant IA, chat du plan) : le prix est retenu avant l'appel (409
    `InsufficientCredits` sans l'appeler), réglé à la sortie normale, rendu en entier si le bloc lève. Compte
    administrateur : rien. Entrée et sortie sont commitées ici pour que la réservation soit visible pendant l'appel ;
    à employer hors d'une transaction qui tient un verrou (projet)."""
    if user.is_admin:
        yield
        return
    user_id, amount = user.id, pricing.action_credits("assist")  # lus avant tout rollback, qui expire `user`
    reservation = await reserve(session, user_id, amount, project_id=project_id, step=step, reason=reason)
    await session.commit()
    try:
        yield
    except BaseException:
        await session.rollback()
        await refund_all(session, reservation)
        await session.commit()
        raise
    await close(session, reservation, amount)
    await session.commit()


async def set_subscription_quota(session: AsyncSession, user_id: int, quota: int, reason: str) -> None:
    """Remet le lot d'abonnement au quota du mois : le reliquat expire (entrée `expire`), le quota est accordé (entrée
    `subscription_grant`). Les réservations ouvertes ne comptent plus sur ce lot : leur part d'abonnement passe sur le lot
    rechargé, où elle sera réglée ou rendue (jamais de solde négatif). `quota` 0 : fin d'abonnement, le lot expire.
    Ne fait pas de `commit`."""
    row = await _locked_balance(session, user_id)
    if row.subscription:
        session.add(_entry(user_id, "subscription", -row.subscription, "expire", "Crédits d'abonnement expirés"))
    row.subscription = quota
    if quota:
        session.add(_entry(user_id, "subscription", quota, "subscription_grant", reason))
    open_ones = (await session.scalars(select(CreditReservation).where(
        CreditReservation.user_id == user_id, CreditReservation.status == "open"))).all()
    for reservation in open_ones:
        reservation.parts = {"subscription": 0, "topup": reservation.parts["subscription"] + reservation.parts["topup"]}
    await session.flush()
