from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects import get_registry, project_or_404
from app.app_settings import AppSettings
from app.db import get_session
from app.models import User
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry
from app.services import plan_chat
from app.services.credits import credit_hold
from app.services.pricing import load_pricing

MAX_MESSAGE_CHARS = 2000

router = APIRouter(prefix="/projects/{project_id}/plan", tags=["plan"])


class ChatIn(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_CHARS)]


def message_out(message, undoable) -> dict:
    return {"id": message.id, "role": message.role, "content": message.content,
            "can_undo": undoable is not None and message.id == undoable.id,
            "created_at": message.created_at}


@router.get("/messages")
async def list_messages(project_id: int, session: AsyncSession = Depends(get_session)) -> list[dict]:
    """Historique du chat ; `can_undo` : vrai pour le seul dernier message de l'IA qui a modifié le plan."""
    await project_or_404(session, project_id)
    messages = await plan_chat.history(session, project_id)
    last = plan_chat.undoable(messages)
    return [message_out(m, last) for m in messages]


@router.post("/chat")
async def chat(project_id: int, body: ChatIn, session: AsyncSession = Depends(get_session),
               registry: ProviderRegistry = Depends(get_registry)) -> dict:
    """Un message à l'IA : elle répond et peut modifier le plan. 409 si une étape tourne ou si le budget est atteint,
    502 si l'IA échoue ou renvoie un plan invalide (rien n'est alors modifié)."""
    project = await project_or_404(session, project_id)
    owner = await session.get(User, project.user_id)  # facturé au propriétaire du projet, comme les générations
    assert owner is not None
    async with credit_hold(session, owner, await load_pricing(AppSettings(session)), project_id=project_id,
                           step="plan_chat", reason="Chat du plan"):
        try:
            created = await plan_chat.chat(session, registry, project, body.message)
        except ProviderError as e:
            raise HTTPException(502, f"Assistant IA indisponible : {e}") from e
    last = plan_chat.undoable(created)
    return {"messages": [message_out(m, last) for m in created], "plan_changed": created[1].before is not None}


@router.post("/messages/{message_id}/undo", status_code=204)
async def undo(project_id: int, message_id: int, session: AsyncSession = Depends(get_session)) -> Response:
    """Annule la dernière modification du plan faite par l'IA."""
    project = await project_or_404(session, project_id)
    await plan_chat.undo(session, project, message_id)
    return Response(status_code=204)
