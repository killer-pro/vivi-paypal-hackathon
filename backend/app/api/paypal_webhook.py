from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.app_settings import AppSettings
from app.db import get_session
from app.services import payments
from app.services.paypal_client import PayPalAPI, PayPalError, get_paypal

router = APIRouter(tags=["billing"])


@router.post("/paypal/webhook")
async def paypal_webhook(request: Request, session: AsyncSession = Depends(get_session),
                         paypal: PayPalAPI = Depends(get_paypal)) -> dict:
    """Webhook PayPal : ouvert (pas de session), signature vérifiée par PayPal. Filet de sécurité de la capture et de
    l'abonnement : un client qui ferme l'onglet avant le retour est tout de même crédité, sans double crédit (même identifiant
    de capture, même cycle d'abonnement)."""
    try:
        event = await request.json()
    except ValueError as e:
        raise HTTPException(400, "Événement illisible") from e
    if not isinstance(event, dict):
        raise HTTPException(400, "Événement illisible")
    try:
        valid = await paypal.verify_webhook({k.lower(): v for k, v in request.headers.items()}, event)
    except PayPalError as e:
        raise HTTPException(502, f"Vérification indisponible : {e}") from e
    if not valid:
        raise HTTPException(400, "Signature invalide")
    try:
        added = await payments.handle_paypal_event(session, event, paypal, AppSettings(session))
    except PayPalError as e:  # PayPal rejoue l'événement : on ne l'acquitte pas tant que l'abonnement n'a pas pu être lu
        raise HTTPException(502, f"Lecture de l'abonnement indisponible : {e}") from e
    await session.commit()
    return {"received": True, "credited": added}
