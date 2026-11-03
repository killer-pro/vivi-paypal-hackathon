"""Lecture et mise à jour de l'état du flow d'un projet (étapes, péremption, statut), partagées par l'API et le worker."""
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import Result, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, Project, Scene, Step
from app.state import OPTIONAL_STEPS, STEP_NAMES, dependents

COMPLETED = {"approved", "awaiting_validation"}
EMPTY_IS_SKIPPED = OPTIONAL_STEPS | {"story"}  # sans résultat : ignorée (référence passée, ou projet existant sans story)


async def load_steps(session: AsyncSession, project_ids: list[int]) -> list[Step]:
    """Étapes dans l'ordre du flow ; populate_existing car le worker a pu les modifier entre-temps."""
    steps = (await session.scalars(select(Step).where(Step.project_id.in_(project_ids))
                                   .execution_options(populate_existing=True))).all()
    return sorted(steps, key=lambda s: STEP_NAMES.index(s.name))


def plan_until(steps: list[Step]) -> str:
    """Étape après laquelle s'arrête la génération du plan : `story` (à relire avant l'écriture des scènes), sauf pour un
    projet existant dont la story est validée et vide : il garde l'ancien chemin et s'arrête sur `script`."""
    legacy = any(s.name == "story" and s.status == "approved" and not s.result for s in steps)
    return "script" if legacy else "story"


def mark_stale(steps: list[Step], names) -> None:
    """Les étapes `names` déjà produites (approuvées ou à valider) deviennent `stale` ; leurs assets sont conservés.
    `failed`/`pending`/`running` restent inchangés (un `running` ne doit pas redevenir réclamable).
    Une étape optionnelle ignorée, ou la story vide d'un projet existant (validée sans résultat), n'a rien produit :
    elle reste validée."""
    for s in steps:
        skipped = s.name in EMPTY_IS_SKIPPED and not s.result
        if s.name in names and s.status in COMPLETED and not skipped:
            s.status = "stale"


def script_stale_names(before: dict | None, after: dict | None) -> list[str]:
    """Étapes à périmer après une modification du script : les images de référence ne dépendent que des éléments
    (`references`) ; si ceux-ci sont inchangés (texte, fiche visuelle…), `reference` reste valide."""
    names = dependents("script")
    if ((before or {}).get("references") or []) != ((after or {}).get("references") or []):
        return list(names)
    return [n for n in names if n != "reference"]


async def sync_status(session: AsyncSession, project_id: int, steps: list[Step]) -> None:
    """Statut du projet après une action sur ses étapes : `done` dès que l'étape `final` est validée, `draft` sinon
    (ex. final périmée ou relancée)."""
    project = await session.get(Project, project_id)
    assert project is not None
    project.status = "done" if any(s.name == "final" and s.status == "approved" for s in steps) else "draft"


class StepBusy(HTTPException):
    """409 : une génération en cours bloque la demande, qui peut attendre son tour dans la file (`queue_runs`)."""

    def __init__(self, detail: str):
        super().__init__(409, detail)


def ensure_not_running(steps: list[Step], names) -> None:
    """409 si une étape de `names` tourne : son job lit les données qu'on s'apprête à modifier ou invalider."""
    running = [s.name for s in steps if s.name in names and s.status == "running"]
    if running:
        raise StepBusy(f"Génération en cours ({', '.join(running)}) : attendez sa fin avant de modifier "
                       "ou relancer cette étape")


def current_step(steps: list[Step]) -> Step | None:
    """Première étape non approuvée ; une étape optionnelle encore en `pending` est ignorée (miroir de l'admin)."""
    return next((s for s in steps
                 if s.status != "approved" and not (s.name in OPTIONAL_STEPS and s.status == "pending")), None)


# Étapes qui produisent un asset par scène, et le type d'asset produit : seules elles se reprennent après un échec.
RUN_ASSET_KIND = {"clips": "clip", "voice": "voice"}


# `Step.run_id` d'un lancement qui ne concerne qu'une scène : « scene:<id>:<aléa> » (pas un lancement complet, donc pas
# de reprise ; l'aléa distingue deux lancements successifs de la même scène).
SCENE_RUN_PREFIX = "scene:"


def scene_run_id(scene_id: int) -> str:
    return f"{SCENE_RUN_PREFIX}{scene_id}:{uuid4().hex[:8]}"


def target_scene(step: Step, scene_ids: set[int]) -> int | None:
    """Scène visée par le dernier lancement d'une étape par scène, s'il n'en visait qu'une, qu'il soit en cours ou en
    échec : l'interface dit « scène N » (et « Relancer » ne refait que celle-là, jamais toute la vidéo : un clip ComfyUI
    prend des minutes). `None` pour un lancement complet, une étape à l'arrêt ou une scène disparue."""
    if step.status not in ("running", "failed") or not step.run_id or not step.run_id.startswith(SCENE_RUN_PREFIX):
        return None
    scene = int(step.run_id.split(":")[1])
    return scene if scene in scene_ids else None


async def done_in_run(session: AsyncSession, project_id: int, step_name: str, run_id: str | None) -> dict[int, int]:
    """Scènes déjà produites par le lancement complet `run_id` d'une étape par scène : {scène: dernier asset de ce
    lancement}. Un lancement d'une seule scène n'est pas repris."""
    if not run_id or run_id.startswith(SCENE_RUN_PREFIX):
        return {}
    rows = await session.execute(select(Asset.scene_id, Asset.id).where(
        Asset.project_id == project_id, Asset.kind == RUN_ASSET_KIND[step_name], Asset.scene_id.is_not(None),
        Asset.meta["run"].as_string() == run_id).order_by(Asset.id))
    return _last_per_scene(rows)


async def produced_in_run(session: AsyncSession, project_id: int, step_name: str, run_id: str | None) -> set[int]:
    """Scènes qui ont un asset du type de l'étape marqué du lancement `run_id`, y compris le lancement d'une seule scène
    (`scene:<id>:…`) que `done_in_run` ignore : ce sont elles que le lancement a réellement produites (facturation)."""
    if not run_id:
        return set()
    rows = await session.scalars(select(Asset.scene_id).where(
        Asset.project_id == project_id, Asset.kind == RUN_ASSET_KIND[step_name], Asset.scene_id.is_not(None),
        Asset.meta["run"].as_string() == run_id))
    return {scene_id for scene_id in rows.all() if scene_id is not None}


def _last_per_scene(rows: Result) -> dict[int, int]:
    """{scène: asset} à partir de lignes triées par asset : le dernier de chaque scène l'emporte."""
    return {scene_id: asset_id for scene_id, asset_id in rows.all() if scene_id is not None}


async def latest_by_scene(session: AsyncSession, project_id: int, kind: str, scene_ids) -> dict[int, int]:
    """Dernier asset du type de chaque scène de `scene_ids` qui en a un : {scène: asset}."""
    if not scene_ids:
        return {}
    rows = await session.execute(select(Asset.scene_id, Asset.id).where(
        Asset.project_id == project_id, Asset.kind == kind, Asset.scene_id.in_(scene_ids)).order_by(Asset.id))
    return _last_per_scene(rows)


async def run_progress(session: AsyncSession, project_id: int, steps: list[Step], status: str,
                       include_empty: bool = False) -> dict[str, dict[str, int]]:
    """Pour chaque étape par scène au statut `status` lancée pour toutes les scènes : {étape: {done, total}}, scènes déjà
    produites par ce lancement. `failed` : de quoi reprendre ; `running` : avancement affiché. Sans scène produite, une
    étape n'apparaît que si `include_empty`."""
    scene_ids = set((await session.scalars(select(Scene.id).where(Scene.project_id == project_id))).all())
    out = {}
    for step in steps:
        if step.name in RUN_ASSET_KIND and step.status == status and step.run_id:
            done = len(scene_ids & set(await done_in_run(session, project_id, step.name, step.run_id)))
            if done or (include_empty and not step.run_id.startswith(SCENE_RUN_PREFIX)):
                out[step.name] = {"done": done, "total": len(scene_ids)}
    return out
