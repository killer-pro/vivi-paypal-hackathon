"""Effets des événements Stripe sur les comptes (appelé par le webhook signé, dans sa transaction). Les crédits et l'état
d'abonnement ne changent que par ici."""
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.app_settings import AppSettings
from app.models import StripeEvent, User
from app.services import credits
from app.services.billing import load_billing

logger = logging.getLogger("app.payments")


async def record_event(session: AsyncSession, event_id: str, event_type: str) -> bool:
    """Marque un événement de paiement (Stripe, PayPal) comme traité ; `False` s'il l'était déjà. Ne fait pas de `commit` :
    l'enregistrement et les effets de l'événement partagent la transaction de l'appelant."""
    recorded = await session.execute(pg_insert(StripeEvent).values(id=event_id, type=event_type)
                                     .on_conflict_do_nothing().returning(StripeEvent.id))
    return recorded.first() is not None


async def _user_by_customer(session: AsyncSession, customer_id: str | None) -> User | None:
    if not customer_id:
        return None
    return await session.scalar(select(User).where(User.stripe_customer_id == customer_id))


async def grant_topup(session: AsyncSession, user: User, amount: int) -> None:
    await credits.grant(session, user.id, amount, bucket="topup", kind="topup", reason=f"Recharge de {amount} crédits")


async def _checkout_completed(session: AsyncSession, obj: dict) -> None:
    reference = str(obj.get("client_reference_id") or "")
    user = await session.get(User, int(reference)) if reference.isdigit() else None
    if user is None:
        logger.warning("Paiement Stripe sans compte connu (client_reference_id=%r) : ignoré", reference)
        return
    if obj.get("customer") and not user.stripe_customer_id:
        user.stripe_customer_id = obj["customer"]
    sold = str((obj.get("metadata") or {}).get("credits") or "")
    if obj.get("mode") == "payment" and obj.get("payment_status") == "paid" and sold.isdigit() and int(sold) > 0:
        await grant_topup(session, user, int(sold))


async def _invoice_paid(session: AsyncSession, obj: dict, app_settings: AppSettings) -> None:
    user = await _user_by_customer(session, obj.get("customer"))
    if user is None or not obj.get("subscription"):  # facture ponctuelle, ou client inconnu
        logger.warning("Facture Stripe sans abonnement ni compte connu (client %r) : ignorée", obj.get("customer"))
        return
    lines = (obj.get("lines") or {}).get("data") or []
    end = max((int(line["period"]["end"]) for line in lines if (line.get("period") or {}).get("end")), default=None)
    if end is not None:  # une facture plus ancienne rejouée ne raccourcit jamais la période
        ends_at = datetime.fromtimestamp(end, UTC)
        user.subscription_ends_at = max(ends_at, user.subscription_ends_at or ends_at)
    quota = (await load_billing(app_settings)).subscription.credits
    await credits.set_subscription_quota(session, user.id, quota, f"Crédits d'abonnement du mois ({quota})")


async def _subscription_deleted(session: AsyncSession, obj: dict) -> None:
    user = await _user_by_customer(session, obj.get("customer"))
    if user is None:
        logger.warning("Fin d'abonnement Stripe pour un client inconnu (%r) : ignorée", obj.get("customer"))
        return
    now = datetime.now(UTC)
    user.subscription_ends_at = min(user.subscription_ends_at or now, now)
    await credits.set_subscription_quota(session, user.id, 0, "Fin d'abonnement")


async def handle_event(session: AsyncSession, event: dict, app_settings: AppSettings) -> None:
    """Applique un événement Stripe vérifié ; les types non gérés sont ignorés. Ne fait pas de `commit`."""
    obj = (event.get("data") or {}).get("object") or {}
    match event.get("type"):
        case "checkout.session.completed":
            await _checkout_completed(session, obj)
        case "invoice.paid":
            await _invoice_paid(session, obj, app_settings)
        case "customer.subscription.deleted":
            await _subscription_deleted(session, obj)


async def apply_paypal_capture(session: AsyncSession, capture: dict, app_settings: AppSettings) -> int:
    """Crédite la recharge d'une capture PayPal terminée ; renvoie les crédits ajoutés (0 : déjà traitée ou refusée). Le
    `custom_id` (`<compte>:<pack>`) est posé par nous à la création de la commande ; le montant capturé doit être celui du
    pack. Ne fait pas de `commit`."""
    user_id, _, pack_id = str(capture.get("custom_id") or "").partition(":")
    user = await session.get(User, int(user_id)) if user_id.isdigit() else None
    pack = (await load_billing(app_settings)).pack(pack_id)
    amount = capture.get("amount") or {}
    if (capture.get("status") != "COMPLETED" or user is None or pack is None or not pack.paypal_purchasable
            or amount.get("currency_code") != "USD" or amount.get("value") != pack.paypal_amount):
        logger.warning("Capture PayPal ignorée (statut, compte, pack ou montant inattendu) : %r", capture.get("id"))
        return 0
    if not await record_event(session, f"paypal:{capture['id']}", "capture"):
        return 0
    await grant_topup(session, user, pack.credits)
    return pack.credits
