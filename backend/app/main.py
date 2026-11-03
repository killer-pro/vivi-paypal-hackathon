import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI

from app.api import (
    access_api,
    admin_api,
    assist,
    auth,
    billing_api,
    costs_api,
    credits_api,
    events,
    music,
    paypal_webhook,
    plan,
    projects,
    providers_api,
    steps,
    stripe_webhook,
    styles,
)
from app.api.auth import ADMIN_ONLY, current_user
from app.api.projects import require_project_access
from app.config import insecure_defaults, settings
from app.queue import close_connections
from app.services import langfuse
from app.storage import get_storage

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    insecure = insecure_defaults(settings)
    if insecure and settings.is_prod:
        raise RuntimeError(f"{', '.join(insecure)} à la valeur par défaut : refus de démarrer avec APP_ENV="
                           f"{settings.app_env} (définir des secrets dans backend/.env)")
    if insecure:  # avertissement seulement : le poste de développement reste utilisable sans configuration
        logger.warning("%s à la valeur par défaut : à changer hors poste de développement (backend/.env)",
                       ", ".join(insecure))
    try:
        await get_storage().ensure_bucket()
    except Exception as e:  # MinIO absent : l'API démarre quand même, le worker le recrée aussi au démarrage
        logger.error("Bucket MinIO indisponible : %s", e)
    yield
    langfuse.shutdown()
    await close_connections()


# En production, ni /docs, ni /redoc, ni /openapi.json : le schéma de l'API n'est pas public.
DOCS_OFF: dict[str, Any] = {"docs_url": None, "redoc_url": None, "openapi_url": None} if settings.is_prod else {}
app = FastAPI(title="Vivi", lifespan=lifespan, **DOCS_OFF)

app.include_router(auth.router, prefix="/api")
app.include_router(stripe_webhook.router, prefix="/api")  # ouvert : protégé par la signature de Stripe
app.include_router(paypal_webhook.router, prefix="/api")  # ouvert : signature vérifiée par PayPal
app.include_router(admin_api.router, prefix="/api/admin", dependencies=ADMIN_ONLY)
for module in (events, music, providers_api, costs_api, credits_api, access_api, billing_api, assist, styles):
    app.include_router(module.router, prefix="/api", dependencies=[Depends(current_user)])
# Routes `{project_id}` : réservées au propriétaire du projet (ou à l'admin), 404 sinon.
for module in (projects, steps, plan):
    app.include_router(module.router, prefix="/api", dependencies=[Depends(require_project_access)])


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
