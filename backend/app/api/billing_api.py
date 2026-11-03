from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import current_user
from app.app_settings import AppSettings
from app.config import settings
from app.db import get_session
from app.models import User
from app.services import payments
from app.services.billing import Plan, load_billing
from app.services.paypal_client import ORDER_ID, PayPalAPI, PayPalError, get_paypal
from app.services.stripe_client import StripeAPI, StripeError, get_stripe

router = APIRouter(prefix="/billing", tags=["billing"])


class CheckoutIn(BaseModel):
    kind: Literal["subscription", "topup"]
    pack_id: str | None = None


def _plan_out(plan: Plan, paypal_ready: bool) -> dict:
    return {"credits": plan.credits, "label": plan.label, "purchasable": plan.purchasable,
            "paypal_purchasable": paypal_ready and plan.paypal_purchasable}


@router.get("")
async def get_billing(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    """Offre (abonnement et recharges avec leur libellé) et état du compte. `purchasable` : prix Stripe renseigné ; `paypal_purchasable` : montant PayPal ET identifiants PayPal saisis ;
    `manageable` : le compte a un client Stripe, donc un portail où gérer ses achats."""
    app_settings = AppSettings(session)
    config = await load_billing(app_settings)
    paypal_ready = settings.fake_providers or bool(await app_settings.get("paypal_client_id")
                                                   and await app_settings.get("paypal_client_secret"))
    return {
        "subscription": _plan_out(config.subscription, paypal_ready),
        "packs": [{"id": p.id, **_plan_out(p, paypal_ready)} for p in config.packs],
        "subscribed": user.is_subscribed, "subscription_ends_at": user.subscription_ends_at,
        "manageable": user.stripe_customer_id is not None,
    }


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
        plan, mode = config.subscription, "subscription"
        if user.subscription_ends_at is not None and user.is_subscribed:
            raise HTTPException(409, "Vous êtes déjà abonné : gérez votre abonnement depuis le portail")
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
            success_url=f"{settings.public_url}/credits?checkout=success",
            cancel_url=f"{settings.public_url}/credits?checkout=cancelled", client_reference_id=str(user.id),
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
        return {"url": await stripe.create_portal(user.stripe_customer_id, f"{settings.public_url}/credits")}
    except StripeError as e:
        raise HTTPException(502, f"Portail indisponible : {e}") from e


class PayPalOrderIn(BaseModel):
    pack_id: str


class PayPalCaptureIn(BaseModel):
    order_id: str = Field(pattern=f"^{ORDER_ID.pattern}$")


@router.post("/paypal/order")
async def paypal_order(body: PayPalOrderIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                       paypal: PayPalAPI = Depends(get_paypal)) -> dict:
    """Commande PayPal d'une recharge : renvoie l'`url` d'approbation. Rien n'est crédité ici : les crédits arrivent à la
    capture (retour sur `/credits`) ou par le webhook, une fois le paiement confirmé."""
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
            return_url=f"{settings.public_url}/credits?paypal=success", cancel_url=f"{settings.public_url}/credits?paypal=cancelled")
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
