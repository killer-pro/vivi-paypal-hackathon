"""Chat du plan : l'utilisateur parle à l'IA, qui répond et, si besoin, renvoie le plan complet modifié.

Le serveur valide puis applique le plan (titre, fiche visuelle, scènes) ; l'instantané d'avant est gardé sur le message
de l'IA pour annuler. Rien n'est écrit si l'appel ou la réponse échoue. L'appel passe par `tracked_call`.
"""
import json

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.steps import SceneIn, replace_scenes
from app.app_settings import AppSettings
from app.models import PlanMessage, Project, Scene, Step, User
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry
from app.services import langfuse
from app.services.budget import ensure_within_budget
from app.services.costs import tracked_call
from app.services.flow import ensure_not_running, load_steps, mark_stale, script_stale_names, sync_status
from app.services.pipeline import ENGAGEMENT_RULE, VISUAL_PROMPT_GUIDE, project_brief
from app.services.steps import lock_project
from app.services.styles import directive
from app.state import STEP_NAMES

MAX_PLAN_SCENES = 30
HISTORY_MESSAGES = 10
MAX_TOKENS = 8000  # réflexion comprise (Gemini) ; le plan complet est renvoyé à chaque modification
ATTEMPTS = 2
TIMEOUT_S = 120

CHAT_SYSTEM = (
    "Tu es le co-scénariste d'un studio de vidéos verticales virales. Tu discutes avec l'utilisateur du plan de sa "
    "vidéo (titre, fiche visuelle, scènes). Tu réponds en français, court et concret. Si sa demande change le plan, "
    "tu renvoies dans `plan` le plan COMPLET modifié (toutes les scènes, pas seulement celles qui changent) ; sinon tu "
    "n'envoies pas `plan`. Tu ne modifies que ce qui est demandé."
)
_SCENE_PROPS = {"id": {"type": "INTEGER", "nullable": True}, "voice_text": {"type": "STRING"},
                "visual_prompt": {"type": "STRING"}, "duration_s": {"type": "NUMBER"}}
PLAN_CHAT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "reply": {"type": "STRING"},
        "plan": {"type": "OBJECT", "properties": {
            "title": {"type": "STRING"}, "bible": {"type": "STRING"},
            "scenes": {"type": "ARRAY", "items": {
                "type": "OBJECT", "properties": _SCENE_PROPS,
                "required": ["id", "voice_text", "visual_prompt", "duration_s"], "propertyOrdering": list(_SCENE_PROPS)}}},
            "required": ["title", "bible", "scenes"], "propertyOrdering": ["title", "bible", "scenes"]}},
    "required": ["reply"], "propertyOrdering": ["reply", "plan"],
}


async def _script_step(session: AsyncSession, project_id: int) -> Step:
    return (await session.execute(select(Step).where(Step.project_id == project_id, Step.name == "script"))).scalar_one()


async def snapshot(session: AsyncSession, project: Project) -> dict:
    """Plan courant : titre, fiche visuelle et scènes dans l'ordre."""
    scenes = (await session.scalars(select(Scene).where(Scene.project_id == project.id).order_by(Scene.position))).all()
    bible = ((await _script_step(session, project.id)).result or {}).get("bible", "")
    return {"title": project.title, "bible": bible,
            "scenes": [{"id": s.id, "voice_text": s.voice_text, "visual_prompt": s.visual_prompt,
                        "duration_s": s.duration_s} for s in scenes]}


async def _apply(session: AsyncSession, project: Project, plan: dict, steps: list[Step]) -> None:
    """Remplace titre, fiche visuelle et scènes ; les étapes aval déjà produites deviennent périmées."""
    scenes = [SceneIn(**s) for s in plan["scenes"]]
    await replace_scenes(session, project.id, scenes)
    project.title = plan["title"]
    script = next(s for s in steps if s.name == "script")
    result_before = script.result
    script.result = {**(script.result or {}), "bible": plan["bible"]}
    mark_stale(steps, script_stale_names(result_before, script.result))
    await sync_status(session, project.id, steps)


def _parse(answer: str, current: dict) -> tuple[str, dict | None]:
    """Réponse de l'IA : (message, plan complet validé ou None). `ProviderError` si elle est inexploitable."""
    try:
        data = json.loads(answer)
        reply = str(data["reply"]).strip()
        plan = data.get("plan")
        if plan is None:
            return reply, None
        scenes = [SceneIn(**s).model_dump() for s in plan["scenes"]]
        title = str(plan.get("title") or "").strip() or current["title"]
        bible = plan["bible"] if isinstance(plan.get("bible"), str) else current["bible"]
    except (ValueError, KeyError, TypeError, AttributeError, ValidationError) as e:
        raise ProviderError(f"réponse du plan invalide ({type(e).__name__}: {e})", retryable=False) from e
    ids = [s["id"] for s in scenes if s["id"] is not None]
    if not reply:
        raise ProviderError("réponse sans message", retryable=False)
    if not 1 <= len(scenes) <= MAX_PLAN_SCENES:
        raise ProviderError(f"le plan doit compter de 1 à {MAX_PLAN_SCENES} scènes ({len(scenes)} reçues)", retryable=False)
    if len(ids) != len(set(ids)):
        raise ProviderError("une même scène apparaît deux fois dans le plan", retryable=False)
    return reply, {"title": title, "bible": bible, "scenes": scenes}


async def history(session: AsyncSession, project_id: int) -> list[PlanMessage]:
    return list((await session.scalars(select(PlanMessage).where(PlanMessage.project_id == project_id)
                                       .order_by(PlanMessage.id))).all())


def undoable(messages: list[PlanMessage]) -> PlanMessage | None:
    """Seul le dernier message qui a modifié le plan s'annule, et une seule fois."""
    changing = [m for m in messages if m.before is not None]
    return changing[-1] if changing and not changing[-1].undone else None


def _prompt(project: Project, plan: dict, messages: list[PlanMessage], message: str) -> str:
    style = directive(project.style)
    lines = [project_brief(project)] + ([f"Style visuel imposé : {style}"] if style else [])
    lines.append(f"Plan actuel (JSON ; garde les `id` des scènes conservées, `null` pour une nouvelle scène) :\n<<<\n"
                 f"{json.dumps(plan, ensure_ascii=False, indent=1)}\n>>>")
    if past := messages[-HISTORY_MESSAGES:]:
        lines.append("Conversation jusqu'ici :\n" + "\n".join(
            f"{'Utilisateur' if m.role == 'user' else 'IA'} : {m.content}" for m in past))
    lines.append(f"Règles : voix off en français, visual_prompt en anglais ({VISUAL_PROMPT_GUIDE}), "
                 f"1 à {MAX_PLAN_SCENES} scènes, durées en secondes > 0, aucun champ vide. {ENGAGEMENT_RULE}, sauf si "
                 "l'utilisateur demande autre chose.")
    lines.append(f"Message de l'utilisateur : {message}")
    return "\n\n".join(lines)


async def chat(session: AsyncSession, registry: ProviderRegistry, project: Project, message: str) -> list[PlanMessage]:
    """Un tour de conversation : refusé (409) si une étape tourne ou si le budget est atteint ; `ProviderError` si
    l'IA échoue ou répond mal (rien n'est alors écrit). Renvoie le message de l'utilisateur et celui de l'IA."""
    await lock_project(session, project.id)
    ensure_not_running(await load_steps(session, [project.id]), STEP_NAMES)
    owner = await session.get(User, project.user_id)
    if owner is not None and owner.is_admin:  # budget en dollars : projets de l'admin seulement, les crédits couvrent les autres
        await ensure_within_budget(session, project.id, AppSettings(session))
    plan = await snapshot(session, project)
    prompt = _prompt(project, plan, await history(session, project.id), message)
    llm = await registry.llm()
    result = await tracked_call(session, project_id=project.id, step="plan_chat", provider=llm.name,
                                model=getattr(llm, "model", llm.name),
                                fn=lambda: llm.complete(CHAT_SYSTEM, prompt, max_tokens=MAX_TOKENS,
                                                        json_schema=PLAN_CHAT_SCHEMA),
                                attempts=ATTEMPTS, timeout=TIMEOUT_S, input=langfuse.messages(prompt, CHAT_SYSTEM))
    reply, new_plan = _parse(result.text, plan)
    project = await lock_project(session, project.id)  # relu : le plan a pu changer pendant l'appel
    steps = await load_steps(session, [project.id])
    ensure_not_running(steps, STEP_NAMES)
    if new_plan is not None:
        await _apply(session, project, new_plan, steps)
    created = [PlanMessage(project_id=project.id, role="user", content=message),
               PlanMessage(project_id=project.id, role="assistant", content=reply,
                           before=plan if new_plan is not None else None)]
    session.add_all(created)
    await session.commit()
    return created


async def undo(session: AsyncSession, project: Project, message_id: int) -> None:
    """Rétablit le plan d'avant le message `message_id` (409 s'il n'est pas le dernier changement, ou si une étape
    tourne)."""
    await lock_project(session, project.id)
    steps = await load_steps(session, [project.id])
    ensure_not_running(steps, STEP_NAMES)
    last = undoable(await history(session, project.id))
    if last is None or last.id != message_id:
        raise HTTPException(409, "Seul le dernier changement du plan peut être annulé")
    await _apply(session, project, last.before or {}, steps)
    last.undone = True
    await session.commit()
