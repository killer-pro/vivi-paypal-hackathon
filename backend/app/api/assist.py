from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import current_user
from app.api.projects import ensure_access, get_registry
from app.app_settings import AppSettings
from app.db import get_session
from app.models import Scene, User
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry
from app.services import assist as assistant
from app.services.credits import credit_hold
from app.services.pricing import load_pricing

router = APIRouter(prefix="/ai", tags=["ai"])


class AssistIn(BaseModel):
    field_kind: str
    mode: str = "generate"
    text: str = ""
    instruction: str = ""
    project_id: int | None = None
    scene_id: int | None = None
    duration_s: float | None = None  # durée du brouillon de scène (non enregistrée), prioritaire sur celle en base


def validate(body: AssistIn) -> None:
    """Contrôles avec des messages français (422), avant tout appel payant."""
    problems = []
    if body.field_kind not in assistant.FIELD_KINDS:
        problems.append(f"Champ inconnu : « {body.field_kind} » (attendu : {', '.join(assistant.FIELD_KINDS)})")
    if body.mode not in assistant.MODES:
        problems.append(f"Mode inconnu : « {body.mode} » (attendu : generate ou rewrite)")
    if body.mode == "rewrite" and not body.text.strip():
        problems.append("Texte à reformuler vide : saisissez un texte ou utilisez « Générer »")
    if len(body.text) > assistant.MAX_TEXT:
        problems.append(f"Texte trop long ({len(body.text)} caractères, maximum {assistant.MAX_TEXT})")
    if len(body.instruction) > assistant.MAX_INSTRUCTION:
        problems.append(f"Consigne trop longue ({len(body.instruction)} caractères, maximum {assistant.MAX_INSTRUCTION})")
    if body.scene_id is not None and body.project_id is None:
        problems.append("Une scène se précise avec son projet (project_id)")
    if body.duration_s is not None and not 0 < body.duration_s <= 600:
        problems.append("Durée de scène invalide (entre 0 et 600 s)")
    if problems:
        raise HTTPException(422, " ; ".join(problems))


@router.post("/assist")
async def assist(body: AssistIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                 registry: ProviderRegistry = Depends(get_registry)) -> dict:
    """Propose un texte pour un champ de l'admin (générer ou reformuler) avec le LLM actif. Rien n'est enregistré."""
    validate(body)
    project = await ensure_access(session, body.project_id, user) if body.project_id is not None else None
    scene = None
    if body.scene_id is not None:
        scene = await session.get(Scene, body.scene_id)
        if scene is None or project is None or scene.project_id != project.id:
            raise HTTPException(404, "Scène introuvable")
    # Facturé à l'appelant, projet ou non ; les rollback du gestionnaire expirent les objets : identifiants lus avant
    project_id = project.id if project else None
    async with credit_hold(session, user, await load_pricing(AppSettings(session)), project_id=project_id,
                           step="assist", reason="Assistant IA"):
        try:
            text = await assistant.assist(session, registry, kind=body.field_kind, mode=body.mode, text=body.text,
                                          instruction=body.instruction, project=project, scene=scene,
                                          duration_s=body.duration_s)
        except ProviderError as e:
            raise HTTPException(502, f"Assistant IA indisponible : {e}") from e
    return {"text": text}
