"""Budget par projet : garde-fou contre les dépenses de providers qui s'enchaînent (surtout en mode automatique)."""
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.app_settings import AppSettings
from app.models import ProviderCall, Scene
from app.providers.profiles import get_profile
from app.providers.registry import ProviderRegistry
from app.services.pricing import Pricing

# Étapes qui appellent un provider payant. Montage et musique sont gratuits : un projet qui a atteint son budget peut
# toujours les terminer.
PAID_STEPS = {"idea", "story", "script", "reference", "clips", "voice", "final"}


class BudgetExceeded(HTTPException):
    def __init__(self, detail: str):
        super().__init__(409, detail)


async def spent_usd(session: AsyncSession, project_id: int) -> float:
    return float(await session.scalar(select(func.coalesce(func.sum(ProviderCall.cost_usd), 0.0)).where(
        ProviderCall.project_id == project_id)) or 0)


async def spent_by_step(session: AsyncSession, project_id: int) -> dict[str, float]:
    """Dépenses du projet par étape (les appels de l'assistant IA, `assist:<champ>`, sont regroupés sous `assist`) :
    de quoi justifier le total affiché. Seules les étapes qui ont coûté quelque chose y figurent."""
    rows = await session.execute(select(ProviderCall.step, func.sum(ProviderCall.cost_usd)).where(
        ProviderCall.project_id == project_id).group_by(ProviderCall.step))
    totals: dict[str, float] = {}
    for step, total in rows.all():
        name = step.split(":")[0]
        totals[name] = round(totals.get(name, 0.0) + float(total), 6)
    return {name: total for name, total in totals.items() if total > 0}


async def clip_scene_costs_usd(session: AsyncSession, registry: ProviderRegistry, project_id: int, provider: str,
                               model: str, scene_id: int | None = None, skip_scene_ids: frozenset[int] = frozenset(),
                               image_per_scene_usd: float = 0.0, pricing: Pricing | None = None) -> dict[int, float]:
    """Coût de revient de chaque scène à générer {scène: dollars} (une seule scène, ou toutes sauf `skip_scene_ids`,
    déjà produites en cas de reprise). `image_per_scene_usd` : image de départ payante de chaque scène (Gemini).
    `pricing` : pour ComfyUI, coût du forfait local du profil (ComfyUI ne coûte rien en dollars : sans `pricing`, 0).
    `KeyError` : provider ou modèle inconnu."""
    video = await registry.video(provider)
    query = select(Scene.id, Scene.duration_s).where(Scene.project_id == project_id, Scene.id.not_in(skip_scene_ids))
    if scene_id is not None:
        query = query.where(Scene.id == scene_id)
    local = pricing is not None and provider == "comfyui"
    return {sid: (pricing.local_clip_cost_usd(get_profile(model).id, duration) if local and pricing
                  else video.estimate_cost(model, duration)) + image_per_scene_usd
            for sid, duration in (await session.execute(query)).all()}


async def estimate_clips_usd(session: AsyncSession, registry: ProviderRegistry, project_id: int, provider: str,
                             model: str, scene_id: int | None = None, skip_scene_ids: frozenset[int] = frozenset(),
                             image_per_scene_usd: float = 0.0) -> float:
    """Coût estimé en dollars de la génération des clips (budget en dollars des projets de l'admin)."""
    return sum((await clip_scene_costs_usd(session, registry, project_id, provider, model, scene_id, skip_scene_ids,
                                           image_per_scene_usd)).values())


async def ensure_within_budget(session: AsyncSession, project_id: int, app_settings: AppSettings,
                               upcoming_usd: float = 0.0) -> None:
    """409 si les dépenses du projet, plus `upcoming_usd`, dépassent le budget (réglage `project_budget_usd`, 0 = sans
    limite)."""
    budget = await app_settings.budget_usd()
    if budget <= 0:
        return
    spent = await spent_usd(session, project_id)
    if spent + upcoming_usd > budget:
        raise BudgetExceeded(f"Budget de la vidéo atteint : {spent:.2f} $ déjà dépensés"
                             + (f" et {upcoming_usd:.2f} $ à venir" if upcoming_usd else "")
                             + f", maximum {budget:.2f} $. Relevez le budget dans Réglages pour continuer.")
