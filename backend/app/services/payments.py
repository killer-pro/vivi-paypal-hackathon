"""Effets des événements Stripe et PayPal sur les comptes (appelé par les webhooks signés, dans leur transaction). Les
crédits et l'état d'abonnement ne changent que par ici."""
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.app_settings import AppSettings
from app.models import StripeEvent, User
from app.services import credits
from app.services.billing import load_billing
from app.services.paypal_client import PayPalAPI

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
    config = await load_billing(app_settings)
    plan = ((obj.get("subscription_details") or {}).get("metadata") or {}).get("plan")  # posé au paiement (checkout)
    tier = config.tier(plan) or config.tiers[0]
    user.plan_id = tier.id
    await credits.set_subscription_quota(session, user.id, tier.credits, f"Crédits d'abonnement du mois ({tier.credits})")


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


def cycles_completed(subscription: dict) -> int:
    """Mois déjà prélevés d'un abonnement PayPal : un nouveau cycle payé = un nouveau quota de crédits."""
    runs = (subscription.get("billing_info") or {}).get("cycle_executions") or []
    return sum(int(run.get("cycles_completed") or 0) for run in runs if run.get("tenure_type") == "REGULAR")


async def apply_paypal_subscription(session: AsyncSession, subscription: dict, app_settings: AppSettings) -> int:
    """Aligne le compte sur un abonnement PayPal lu par l'API (jamais sur le corps d'un événement) ; renvoie les crédits
    accordés (0 : cycle déjà crédité, pas encore payé, ou abonnement terminé). Le `custom_id` (compte) est posé par nous à la
    création ; le plan PayPal désigne le forfait. Un plan qui n'est plus dans l'offre (abonnement d'avant les forfaits,
    plan recréé) garde le forfait du compte, ou le premier, si l'abonnement est déjà celui du compte ; sinon il est
    ignoré. Une annulation garde la période déjà payée (`subscription_ends_at`) et le forfait, qui ne compte plus une
    fois la période finie ; elle libère seulement l'abonnement. Ne fait pas de `commit`."""
    custom_id, config = str(subscription.get("custom_id") or ""), await load_billing(app_settings)
    user = await session.get(User, int(custom_id)) if custom_id.isdigit() else None
    status, cycles = subscription.get("status"), cycles_completed(subscription)
    if user is not None and status in ("CANCELLED", "EXPIRED"):
        if user.paypal_subscription_id == subscription["id"]:
            user.paypal_subscription_id = None
        return 0
    offer = config.tier_by_paypal_plan(subscription.get("plan_id"))
    if offer is None and user is not None and user.paypal_subscription_id == subscription.get("id"):
        offer = config.tier(user.plan_id) or config.tiers[0]
    if user is None or offer is None:
        logger.warning("Abonnement PayPal ignoré (compte ou plan inattendu) : %r", subscription.get("id"))
        return 0
    if status != "ACTIVE" or cycles < 1:
        return 0
    if not await record_event(session, f"paypal:sub:{subscription['id']}:{cycles}", "subscription"):
        return 0
    user.paypal_subscription_id, user.plan_id = subscription["id"], offer.id
    next_billing = (subscription.get("billing_info") or {}).get("next_billing_time")
    if next_billing:  # une lecture plus ancienne rejouée ne raccourcit jamais la période
        ends_at = datetime.fromisoformat(next_billing)
        user.subscription_ends_at = max(ends_at, user.subscription_ends_at or ends_at)
    await credits.set_subscription_quota(session, user.id, offer.credits, f"Crédits d'abonnement du mois ({offer.credits})")
    return offer.credits


async def handle_paypal_event(session: AsyncSession, event: dict, paypal: PayPalAPI, app_settings: AppSettings) -> int:
    """Applique un événement PayPal vérifié ; renvoie les crédits ajoutés. Les types non gérés sont ignorés. Pour un
    abonnement, l'événement ne sert que de déclencheur : l'état vient de `get_subscription`. Ne fait pas de `commit`."""
    resource: dict = event["resource"] if isinstance(event.get("resource"), dict) else {}
    match event.get("event_type"):
        case "PAYMENT.CAPTURE.COMPLETED":
            return await apply_paypal_capture(session, resource, app_settings)
        case "PAYMENT.SALE.COMPLETED":
            subscription_id = resource.get("billing_agreement_id")
        case "BILLING.SUBSCRIPTION.ACTIVATED" | "BILLING.SUBSCRIPTION.CANCELLED" | "BILLING.SUBSCRIPTION.EXPIRED":
            subscription_id = resource.get("id")
        case _:
            return 0
    if not isinstance(subscription_id, str):
        return 0
    return await apply_paypal_subscription(session, await paypal.get_subscription(subscription_id), app_settings)
