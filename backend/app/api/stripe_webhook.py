import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.app_settings import AppSettings
from app.db import get_session
from app.services import payments
from app.services.stripe_client import verify_signature

router = APIRouter(tags=["billing"])


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request, session: AsyncSession = Depends(get_session)) -> dict:
    """Webhook Stripe : ouvert (pas de session), protégé par la signature `Stripe-Signature`. Un événement déjà traité
    est acquitté sans effet ; l'enregistrement de l'événement et ses effets partagent une transaction : en cas d'échec rien
    n'est marqué et Stripe rejoue."""
    payload = await request.body()
    app_settings = AppSettings(session)
    if not verify_signature(payload, request.headers.get("Stripe-Signature", ""), await app_settings.get("stripe_webhook_secret")):
        raise HTTPException(400, "Signature invalide")
    try:
        event = json.loads(payload)
    except ValueError as e:
        raise HTTPException(400, "Événement illisible") from e
    if not isinstance(event, dict) or not isinstance(event.get("id"), str):
        raise HTTPException(400, "Événement illisible")
    if not await payments.record_event(session, event["id"], str(event.get("type", ""))):
        return {"received": True, "duplicate": True}
    try:
        await payments.handle_event(session, event, app_settings)
    except Exception:
        await session.rollback()
        raise
    await session.commit()
    return {"received": True, "duplicate": False}
