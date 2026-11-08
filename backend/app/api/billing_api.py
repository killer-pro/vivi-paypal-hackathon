from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import current_user
from app.app_settings import AppSettings
from app.config import settings
from app.db import get_session
from app.models import User
from app.services import access, payments
from app.services.billing import PAYPAL_ID, BillingConfig, Pack, Tier, load_billing
from app.services.paypal_client import PayPalAPI, PayPalError, get_paypal
from app.services.pricing import load_pricing, video_credits
from app.services.stripe_client import StripeAPI, StripeError, get_stripe

router = APIRouter(prefix="/billing", tags=["billing"])


class CheckoutIn(BaseModel):
    kind: Literal["subscription", "topup"]
    pack_id: str | None = None
    tier_id: str | None = None


def _plan_out(plan: Pack, paypal_ready: bool) -> dict:
    on_paypal = plan.paypal_subscribable if isinstance(plan, Tier) else plan.paypal_purchasable
    return {"credits": plan.credits, "label": plan.label, "purchasable": plan.purchasable,
            "paypal_purchasable": paypal_ready and on_paypal}


@router.get("")
async def get_billing(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    """Offre (forfaits avec leurs avantages, niveau gratuit, recharges) et état du compte. `purchasable` : prix Stripe
    renseigné ; `paypal_purchasable` : montant (recharge) ou plan (forfait) PayPal ET identifiants PayPal saisis ;
    `videos_30s` : vidéos de 30 s en Rapide que paient les crédits du forfait ; `current_tier` : forfait de l'abonné ;
    `manageable` : le compte a un client Stripe, donc un portail où gérer ses achats ; `paypal_cancellable` : le compte
    a un abonnement PayPal en cours, annulable depuis l'écran."""
    app_settings = AppSettings(session)
    config = await load_billing(app_settings)
    paypal_ready = settings.fake_providers or bool(await app_settings.get("paypal_client_id")
                                                   and await app_settings.get("paypal_client_secret"))
    tier, video = await access.current_tier(app_settings, user), video_credits(await load_pricing(app_settings))
    return {
        "tiers": [{"id": t.id, "name": t.name, **_plan_out(t, paypal_ready), "videos_30s": t.credits // video,
                   "perks": t.perks.to_json()}
                  for t in config.tiers],
        "free": {"perks": config.free.to_json()},
        "packs": [{"id": p.id, **_plan_out(p, paypal_ready)} for p in config.packs],
        "current_tier": tier.id if tier else None,
        "subscribed": user.is_subscribed, "subscription_ends_at": user.subscription_ends_at,
        "manageable": user.stripe_customer_id is not None,
        "paypal_cancellable": user.paypal_subscription_id is not None and user.is_subscribed,
    }


def _tier_or_404(config: BillingConfig, tier_id: str | None) -> Tier:
    if not tier_id:
        raise HTTPException(422, "Choisissez un forfait (tier_id)")
    tier = config.tier(tier_id)
    if tier is None:
        raise HTTPException(404, "Forfait inconnu")
    return tier


def _ensure_not_subscribed(user: User, where: str) -> None:
    if user.subscription_ends_at is not None and user.is_subscribed:
        raise HTTPException(409, f"Vous êtes déjà abonné : gérez votre abonnement depuis {where}")


async def _customer(session: AsyncSession, stripe: StripeAPI, user: User) -> str:
    """Client Stripe du compte, créé au premier achat."""
    if user.stripe_customer_id is None:
        user.stripe_customer_id = await stripe.create_customer(user.email, user.id)
        await session.commit()
    return user.stripe_customer_id


@router.post("/checkout")
async def checkout(body: CheckoutIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                   stripe: StripeAPI = Depends(get_stripe)) -> dict:
    """Page de paiement Stripe de l'abonnement ou d'une recharge : renvoie son `url`. Rien n'est crédité ici : les crédits
    arrivent par le webhook signé, une fois le paiement confirmé."""
    if user.email_verified_at is None:
        raise HTTPException(403, "Confirmez votre adresse e-mail avant d'acheter")
    config = await load_billing(AppSettings(session))
    if body.kind == "subscription":
        plan: Pack = _tier_or_404(config, body.tier_id)
        mode = "subscription"
        _ensure_not_subscribed(user, "le portail")
    else:
        if not body.pack_id:
            raise HTTPException(422, "Choisissez une recharge (pack_id)")
        found = config.pack(body.pack_id)
        if found is None:
            raise HTTPException(404, "Recharge inconnue")
        plan, mode = found, "payment"
    if not plan.purchasable:
        raise HTTPException(409, "Cette offre n'est pas encore disponible à l'achat")
    try:
        url = await stripe.create_checkout(
            customer_id=await _customer(session, stripe, user), mode=mode, price_id=plan.price_id,
            success_url=f"{settings.public_url}/plans?checkout=success",
            cancel_url=f"{settings.public_url}/plans?checkout=cancelled", client_reference_id=str(user.id),
            metadata={"credits": str(plan.credits), "plan": plan.id, "user_id": str(user.id)})
    except StripeError as e:
        raise HTTPException(502, f"Paiement indisponible : {e}") from e
    return {"url": url}


@router.post("/portal")
async def portal(user: User = Depends(current_user), stripe: StripeAPI = Depends(get_stripe)) -> dict:
    """Portail client Stripe du compte (moyens de paiement, factures, annulation de l'abonnement)."""
    if user.stripe_customer_id is None:
        raise HTTPException(409, "Aucun achat à gérer pour ce compte")
    try:
        return {"url": await stripe.create_portal(user.stripe_customer_id, f"{settings.public_url}/plans")}
    except StripeError as e:
        raise HTTPException(502, f"Portail indisponible : {e}") from e


class PayPalOrderIn(BaseModel):
    pack_id: str


class PayPalCaptureIn(BaseModel):
    order_id: str = Field(pattern=f"^{PAYPAL_ID.pattern}$")


@router.post("/paypal/order")
async def paypal_order(body: PayPalOrderIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                       paypal: PayPalAPI = Depends(get_paypal)) -> dict:
    """Commande PayPal d'une recharge : renvoie l'`url` d'approbation. Rien n'est crédité ici : les crédits arrivent à la
    capture (retour sur `/plans`) ou par le webhook, une fois le paiement confirmé."""
    if user.email_verified_at is None:
        raise HTTPException(403, "Confirmez votre adresse e-mail avant d'acheter")
    pack = (await load_billing(AppSettings(session))).pack(body.pack_id)
    if pack is None:
        raise HTTPException(404, "Recharge inconnue")
    if not pack.paypal_purchasable:
        raise HTTPException(409, "Cette offre n'est pas disponible par PayPal")
    try:
        _, url = await paypal.create_order(
            amount=pack.paypal_amount, custom_id=f"{user.id}:{pack.id}", description=f"Vivi : {pack.credits} crédits",
            return_url=f"{settings.public_url}/plans?paypal=success", cancel_url=f"{settings.public_url}/plans?paypal=cancelled")
    except PayPalError as e:
        raise HTTPException(502, f"Paiement indisponible : {e}") from e
    return {"url": url}


@router.post("/paypal/capture")
async def paypal_capture(body: PayPalCaptureIn, user: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session), paypal: PayPalAPI = Depends(get_paypal)) -> dict:
    """Capture la commande approuvée par le client au retour de PayPal et crédite la recharge (une seule fois, même si le
    webhook arrive aussi). Renvoie les crédits ajoutés (0 si la recharge était déjà créditée)."""
    try:
        result = await paypal.capture_order(body.order_id)
    except PayPalError as e:
        if e.issue == "ORDER_ALREADY_CAPTURED":  # capture déjà faite (double appel, webhook passé avant) : rien à créditer
            return {"credited": 0}
        raise HTTPException(502, f"Paiement indisponible : {e}") from e
    capture: dict = next((c for unit in result.get("purchase_units", []) for c in (unit.get("payments") or {}).get("captures", [])), {})
    if str(capture.get("custom_id", "")).partition(":")[0] != str(user.id):
        raise HTTPException(403, "Cette commande n'appartient pas à ce compte")
    added = await payments.apply_paypal_capture(session, capture, AppSettings(session))
    await session.commit()
    return {"credited": added}


class PayPalSubscriptionIn(BaseModel):
    tier_id: str


class PayPalSubscriptionConfirmIn(BaseModel):
    subscription_id: str = Field(pattern=f"^{PAYPAL_ID.pattern}$")


@router.post("/paypal/subscription")
async def paypal_subscription(body: PayPalSubscriptionIn, user: User = Depends(current_user),
                              session: AsyncSession = Depends(get_session), paypal: PayPalAPI = Depends(get_paypal)) -> dict:
    """Abonnement mensuel PayPal au forfait `tier_id` : renvoie l'`url` d'approbation. Rien n'est crédité ici : les
    crédits arrivent à la confirmation (retour sur `/plans`) ou par le webhook, une fois le premier mois prélevé. Un
    abonné peut changer de forfait : le nouvel abonnement remplace l'ancien une fois son premier mois payé (voir
    `payments.apply_paypal_subscription`) ; tant qu'il n'est pas approuvé, l'abonnement en cours ne change pas."""
    if user.email_verified_at is None:
        raise HTTPException(403, "Confirmez votre adresse e-mail avant d'acheter")
    plan = _tier_or_404(await load_billing(AppSettings(session)), body.tier_id)
    if not plan.paypal_subscribable:
        raise HTTPException(409, "Cette offre n'est pas disponible par PayPal")
    if user.is_subscribed and user.paypal_subscription_id is not None and user.plan_id == plan.id:
        raise HTTPException(409, "C'est déjà votre forfait")
    try:
        _, url = await paypal.create_subscription(
            plan_id=plan.paypal_plan_id, custom_id=str(user.id), return_url=f"{settings.public_url}/plans?paypal_sub=success",
            cancel_url=f"{settings.public_url}/plans?paypal_sub=cancelled")
    except PayPalError as e:
        raise HTTPException(502, f"Abonnement indisponible : {e}") from e
    return {"url": url}


@router.post("/paypal/subscription/confirm")
async def paypal_subscription_confirm(body: PayPalSubscriptionConfirmIn, user: User = Depends(current_user),
                                      session: AsyncSession = Depends(get_session),
                                      paypal: PayPalAPI = Depends(get_paypal)) -> dict:
    """Au retour de PayPal : lit l'abonnement approuvé et, si le premier mois est prélevé, crédite le quota (une seule fois
    par mois payé, même si le webhook arrive aussi). `activated` faux : le prélèvement n'est pas encore confirmé, le webhook
    terminera."""
    try:
        subscription = await paypal.get_subscription(body.subscription_id)
    except PayPalError as e:
        raise HTTPException(502, f"Abonnement indisponible : {e}") from e
    if str(subscription.get("custom_id", "")) != str(user.id):
        raise HTTPException(403, "Cet abonnement n'appartient pas à ce compte")
    added = await payments.apply_paypal_subscription(session, subscription, AppSettings(session), paypal)
    await session.commit()
    return {"activated": subscription.get("status") == "ACTIVE" and payments.cycles_completed(subscription) >= 1,
            "credited": added}


@router.post("/paypal/subscription/cancel")
async def paypal_subscription_cancel(user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                                     paypal: PayPalAPI = Depends(get_paypal)) -> dict:
    """Annule l'abonnement PayPal du compte : plus de renouvellement, la période déjà payée reste acquise."""
    if user.paypal_subscription_id is None:
        raise HTTPException(409, "Aucun abonnement PayPal à annuler")
    try:
        await paypal.cancel_subscription(user.paypal_subscription_id, "Annulé par le client depuis Vivi")
    except PayPalError as e:
        raise HTTPException(502, f"Annulation indisponible : {e}") from e
    user.paypal_subscription_id = None
    await session.commit()
    return {"cancelled": True}
