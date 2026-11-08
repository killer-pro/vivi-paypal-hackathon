from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import current_user
from app.app_settings import AppSettings
from app.db import get_session
from app.models import Asset, AssetOriginal, CreditReservation, Project, ProviderCall, Scene, Step, User
from app.providers.registry import ProviderRegistry
from app.services import access
from app.services.budget import estimate_clips_usd, spent_by_step
from app.services.flow import (
    current_step,
    ensure_not_running,
    load_steps,
    mark_stale,
    reference_elements,
    run_progress,
    sync_status,
    target_scene,
)
from app.services.queue_runs import queued_runs
from app.services.styles import STYLES
from app.state import STEP_NAMES
from app.storage import get_storage
from app.uploads import VIDEO, Upload, UploadKind, download_extension, read_upload

router = APIRouter(prefix="/projects", tags=["projects"])

PROJECT_FIELDS = ("id", "title", "theme", "platform", "target_duration_s", "style", "status", "metadata_json", "autopilot",
                  "created_at")
STEP_FIELDS = ("name", "status", "params", "result", "error")
SCENE_FIELDS = ("id", "position", "voice_text", "visual_prompt", "duration_s", "selected_clip_asset_id", "reference", "elements", "continuity")
ASSET_FIELDS = ("id", "scene_id", "kind", "key", "content_type", "variant", "meta", "created_at")
BRIEF_FIELDS = {"theme", "platform", "target_duration_s", "style"}  # lus dès l'idée ; le titre ne sert qu'au rendu final


def fields(obj, names: tuple[str, ...]) -> dict:
    return {n: getattr(obj, n) for n in names}


def asset_out(asset: Asset, storage, original_name: str | None = None, *, admin: bool = False) -> dict:
    """Asset renvoyé au navigateur : URL présignée et, pour un fichier importé, son nom d'origine (affiché seulement).
    Le coût de génération en dollars (`meta.cost_usd`) n'est gardé que pour l'admin."""
    out = {**fields(asset, ASSET_FIELDS), "url": storage.presign(asset.key), "original_name": original_name}
    if not admin:
        out["meta"] = {k: v for k, v in (asset.meta or {}).items() if k != "cost_usd"}
    return out


async def get_registry(session: AsyncSession = Depends(get_session)) -> AsyncIterator[ProviderRegistry]:
    async with ProviderRegistry(AppSettings(session)) as registry:
        yield registry


async def project_or_404(session: AsyncSession, project_id: int) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Projet introuvable")
    return project


async def ensure_access(session: AsyncSession, project_id: int, user: User) -> Project:
    """Le projet, s'il appartient à `user` (ou si `user` est admin) ; sinon le même 404 que pour un projet absent : on
    ne révèle pas l'existence du projet d'un autre compte."""
    project = await project_or_404(session, project_id)
    if project.user_id != user.id and not user.is_admin:
        raise HTTPException(404, "Projet introuvable")
    return project


async def require_project_access(request: Request, user: User = Depends(current_user),
                                 session: AsyncSession = Depends(get_session)) -> None:
    """Dépendance de routeur : toute route dont le chemin porte `{project_id}` n'atteint que les projets de l'utilisateur
    (tous pour l'admin). Les handlers peuvent ensuite charger le projet avec `project_or_404`."""
    raw = request.path_params.get("project_id")
    if raw is None:
        return
    if not (raw.isascii() and raw.isdigit()):  # validé ici, avant la validation du chemin par FastAPI : même 404 qu'un projet absent
        raise HTTPException(404, "Projet introuvable")
    await ensure_access(session, int(raw), user)


async def costs(session: AsyncSession, project_ids: list[int]) -> dict[int, float]:
    rows = await session.execute(select(ProviderCall.project_id, func.sum(ProviderCall.cost_usd))
                                 .where(ProviderCall.project_id.in_(project_ids)).group_by(ProviderCall.project_id))
    return {pid: round(total, 4) for pid, total in rows.all() if pid is not None}


async def credits_spent(session: AsyncSession, project_ids: list[int]) -> dict[int, int]:
    """Crédits pris par projet : utilisés des réservations fermées, montant retenu des réservations ouvertes."""
    held = case((CreditReservation.status == "open", CreditReservation.amount), else_=func.coalesce(CreditReservation.used, 0))
    rows = await session.execute(select(CreditReservation.project_id, func.sum(held))
                                 .where(CreditReservation.project_id.in_(project_ids)).group_by(CreditReservation.project_id))
    return {pid: int(total) for pid, total in rows.all() if pid is not None}


async def spending(session: AsyncSession, viewer: User, project_ids: list[int]) -> dict[int, dict]:
    """Dépense de chaque projet : en dollars pour l'admin, en crédits pour un client (jamais de dollars devant lui)."""
    if viewer.is_admin:
        cost = await costs(session, project_ids)
        return {pid: {"cost_usd": cost.get(pid, 0.0), "credits_spent": None} for pid in project_ids}
    spent = await credits_spent(session, project_ids)
    return {pid: {"cost_usd": None, "credits_spent": spent.get(pid, 0)} for pid in project_ids}


async def latest_renders(session: AsyncSession, project_ids: list[int]) -> dict[int, tuple[int, str]]:
    """(id, clé) du dernier rendu de chaque projet qui en a un."""
    rows = await session.execute(select(Asset.project_id, Asset.id, Asset.key).where(
        Asset.project_id.in_(project_ids), Asset.kind == "render").order_by(Asset.id))
    return {project_id: (asset_id, key) for project_id, asset_id, key in rows.all()}  # le dernier l'emporte


async def thumbnail_keys(session: AsyncSession, renders: dict[int, tuple[int, str]], project_ids: list[int]
                         ) -> dict[int, str]:
    """Clé de la vignette de chaque projet : dernier rendu, sinon clip choisi de la première scène qui en a un."""
    keys = {project_id: key for project_id, (_, key) in renders.items()}
    clips = await session.execute(select(Scene.project_id, Asset.key)
                                  .join(Asset, Asset.id == Scene.selected_clip_asset_id)
                                  .where(Scene.project_id.in_(project_ids)).order_by(Scene.position))
    for project_id, key in clips.all():
        keys.setdefault(project_id, key)
    return keys


def summary(project: Project, steps: list[Step], money: dict) -> dict:
    current = current_step(steps)
    return {**fields(project, ("id", "title", "status", "autopilot", "created_at")),
            "current_step": current and current.name, "current_status": current and current.status, **money}


MAX_TARGET_DURATION_S = 180  # une vidéo virale verticale ; au-delà, le découpage et les appels payants s'emballent
MAX_THEME_CHARS = 2000
DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE = 24, 100


def known_style(value: str | None) -> str | None:
    if value and value not in STYLES:
        raise ValueError("Style inconnu")
    return value


class ProjectIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    theme: str = Field("", max_length=MAX_THEME_CHARS)
    platform: str = Field("tiktok", max_length=30)
    target_duration_s: int = Field(30, gt=0, le=MAX_TARGET_DURATION_S)
    style: str = Field("", max_length=30)

    _known_style = field_validator("style")(known_style)


class ProjectPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    theme: str | None = Field(None, max_length=MAX_THEME_CHARS)
    platform: str | None = Field(None, max_length=30)
    target_duration_s: int | None = Field(None, gt=0, le=MAX_TARGET_DURATION_S)
    style: str | None = Field(None, max_length=30)

    _known_style = field_validator("style")(known_style)


def like_pattern(text: str) -> str:
    """Motif `ILIKE` « contient » : `%`, `_` et `\\` saisis par l'utilisateur sont littéraux."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("")
async def list_projects(
    q: str = Query("", max_length=100), sort: Literal["recent", "oldest", "title", "cost"] = "recent",
    status: Literal["draft", "done"] | None = None, limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0), user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
    storage=Depends(get_storage),
) -> dict:
    """Une page de projets : `{items, total}` (`total` : tous ceux qui correspondent à la recherche et au filtre).
    `q` cherche dans le titre et le thème ; `status` : `done` (terminés) ou `draft` (en cours) ; `sort` : `recent`
    (défaut), `oldest`, `title` (A→Z) ou `cost` (le plus cher d'abord). Ordre total (id en dernier) : pas de doublon ni
    d'oubli d'une page à l'autre. Seulement les projets de l'utilisateur, admin compris."""
    query = select(Project).where(Project.user_id == user.id)
    if q.strip():
        pattern = like_pattern(q.strip())
        query = query.where(or_(Project.title.ilike(pattern, escape="\\"), Project.theme.ilike(pattern, escape="\\")))
    if status:
        query = query.where(Project.status == status)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    if sort == "cost":
        spent = (select(ProviderCall.project_id, func.sum(ProviderCall.cost_usd).label("spent"))
                 .group_by(ProviderCall.project_id).subquery())
        query = query.outerjoin(spent, spent.c.project_id == Project.id).order_by(
            func.coalesce(spent.c.spent, 0).desc(), Project.id.desc())
    elif sort == "title":
        query = query.order_by(func.lower(Project.title), Project.id)
    elif sort == "oldest":
        query = query.order_by(Project.created_at, Project.id)
    else:
        query = query.order_by(Project.created_at.desc(), Project.id.desc())
    projects = (await session.scalars(query.limit(limit).offset(offset))).all()
    ids = [p.id for p in projects]
    steps, money = await load_steps(session, ids), await spending(session, user, ids)
    renders = await latest_renders(session, ids)
    thumbs = await thumbnail_keys(session, renders, ids)
    items = [{**summary(p, [s for s in steps if s.project_id == p.id], money[p.id]),
              "thumbnail_url": storage.presign(thumbs[p.id]) if p.id in thumbs else None,
              "render_asset_id": renders[p.id][0] if p.id in renders else None} for p in projects]
    return {"items": items, "total": total}


@router.post("", status_code=201)
async def create_project(body: ProjectIn, user: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session)) -> dict:
    app_settings = AppSettings(session)
    await access.require(app_settings, user, "style", body.style)
    await access.require_limit(app_settings, user, "max_duration_s", body.target_duration_s)
    project = Project(**body.model_dump(), user_id=user.id)
    session.add(project)
    await session.flush()
    session.add_all(Step(project_id=project.id, name=name, status="pending") for name in STEP_NAMES)
    await session.commit()
    await session.refresh(project)
    return fields(project, PROJECT_FIELDS)


@router.get("/{project_id}")
async def get_project(project_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                      storage=Depends(get_storage)) -> dict:
    project = await project_or_404(session, project_id)
    steps = await load_steps(session, [project_id])
    scenes = (await session.scalars(select(Scene).where(Scene.project_id == project_id).order_by(Scene.position))).all()
    assets = (await session.scalars(select(Asset).where(Asset.project_id == project_id).order_by(Asset.id))).all()
    originals = dict((await session.execute(select(AssetOriginal.asset_id, AssetOriginal.original_name)
                                            .join(Asset).where(Asset.project_id == project_id))).all())
    resume = await run_progress(session, project_id, steps, "failed")
    progress = await run_progress(session, project_id, steps, "running", include_empty=True)
    scene_ids = {s.id for s in scenes}
    return {**fields(project, PROJECT_FIELDS), **summary(project, steps, (await spending(session, user, [project_id]))[project_id]),
            # Dépenses détaillées par étape et plafond par vidéo (0 = sans limite) : de quoi justifier `cost_usd`. Admin seulement.
            "cost_by_step": await spent_by_step(session, project_id) if user.is_admin else None,
            "budget_usd": await AppSettings(session).budget_usd() if user.is_admin else None,
            "steps": [{**fields(s, STEP_FIELDS), "resume": resume.get(s.name), "progress": progress.get(s.name),
                      "target_scene": target_scene(s, scene_ids),
                      # Début de la génération en cours (la ligne n'est modifiée qu'au lancement et à la fin).
                      "running_since": s.updated_at if s.status == "running" else None}
                      for s in steps],
            "queue": [{"id": q.id, "step": q.step, "scene_id": q.scene_id}
                      for q in await queued_runs(session, project_id)],
            "scenes": [fields(s, SCENE_FIELDS) for s in scenes],
            "assets": [asset_out(a, storage, originals.get(a.id), admin=user.is_admin) for a in assets]}


@router.patch("/{project_id}")
async def edit_project(project_id: int, body: ProjectPatch, session: AsyncSession = Depends(get_session)) -> dict:
    """Modifie le brief. Les étapes produites qui en dépendent passent en `stale` : toutes si thème, plateforme ou
    durée changent, seulement `final` si seul le titre change. 409 si l'une de ces étapes tourne."""
    project = await project_or_404(session, project_id)
    changed = {k for k, v in body.model_dump(exclude_unset=True).items() if v is not None and getattr(project, k) != v}
    if changed:
        steps, dependents = await load_steps(session, [project_id]), STEP_NAMES if changed & BRIEF_FIELDS else ["final"]
        ensure_not_running(steps, dependents)
        mark_stale(steps, dependents)
        await sync_status(session, project_id, steps)
    if changed & {"style", "target_duration_s"}:  # le forfait du propriétaire du projet décide, comme pour les générations
        owner, app_settings = await session.get(User, project.user_id), AppSettings(session)
        assert owner is not None
        if "style" in changed:
            await access.require(app_settings, owner, "style", body.style or "")
        if "target_duration_s" in changed:
            await access.require_limit(app_settings, owner, "max_duration_s", body.target_duration_s or 0)
    for key in changed:
        setattr(project, key, getattr(body, key))
    await session.commit()
    await session.refresh(project)
    return fields(project, PROJECT_FIELDS)


@router.get("/{project_id}/assets/{asset_id}/download")
async def download_asset(project_id: int, asset_id: int, session: AsyncSession = Depends(get_session),
                         storage=Depends(get_storage)) -> RedirectResponse:
    """Redirige vers une URL présignée qui force le téléchargement (`Content-Disposition: attachment`) ; nom de fichier
    entièrement serveur, extension tirée du type MIME de l'asset (jamais de sa clé : un ancien import la tenait du
    client)."""
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.project_id != project_id:
        raise HTTPException(404, "Fichier introuvable")
    name = f"vivi-{project_id}.{download_extension(asset.content_type)}"
    return RedirectResponse(storage.presign(asset.key, download=name))


CLIP_CHOICE_DEPENDENTS = ("montage", "final")
MAX_VIDEO_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 Mo


@router.delete("/{project_id}/assets/{asset_id}", status_code=204)
async def delete_asset(project_id: int, asset_id: int, session: AsyncSession = Depends(get_session),
                       storage=Depends(get_storage)) -> Response:
    """Supprime un asset (ex. variante de clip). Réassigne le clip sélectionné si besoin."""
    await project_or_404(session, project_id)
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.project_id != project_id:
        raise HTTPException(404, "Fichier introuvable")
    steps = await load_steps(session, [project_id])
    ensure_not_running(steps, ("clips", "montage"))

    keys_to_delete = [asset.key]
    if asset.kind == "clip" and asset.scene_id is not None:
        scene = await session.get(Scene, asset.scene_id)
        if scene and scene.selected_clip_asset_id == asset.id:
            other_clip = await session.scalar(
                select(Asset).where(
                    Asset.project_id == project_id,
                    Asset.kind == "clip",
                    Asset.scene_id == scene.id,
                    Asset.id != asset.id,
                ).order_by(Asset.variant.desc())
            )
            scene.selected_clip_asset_id = other_clip.id if other_clip else None
            mark_stale(steps, CLIP_CHOICE_DEPENDENTS)
            await sync_status(session, project_id, steps)

        keyframes = (await session.scalars(
            select(Asset).where(
                Asset.project_id == project_id,
                Asset.kind == "keyframe",
                Asset.scene_id == asset.scene_id,
            )
        )).all()
        for kf in keyframes:
            if (kf.meta or {}).get("clip_asset_id") == asset.id:
                keys_to_delete.append(kf.key)
                await session.delete(kf)

    await session.delete(asset)
    await session.commit()
    await storage.delete_many(keys_to_delete)
    return Response(status_code=204)


async def store_upload(session: AsyncSession, storage, upload: Upload, *, project_id: int, kind: str,
                       **asset_fields) -> Asset:
    """Enregistre un fichier importé : clé générée sous `projects/{id}/{kind}/`, asset (modèle « upload », gratuit) et
    nom d'origine dans `asset_originals` (s'il y en a un). Flush, pas de commit."""
    key = upload.key(f"projects/{project_id}/{kind}")
    await storage.put(key, upload.data, upload.content_type)
    asset = Asset(project_id=project_id, kind=kind, key=key, content_type=upload.content_type,
                  meta={"model": "upload", "cost_usd": 0.0}, **asset_fields)
    session.add(asset)
    await session.flush()
    if upload.original_name:
        session.add(AssetOriginal(asset_id=asset.id, original_name=upload.original_name))
    return asset


@router.post("/{project_id}/scenes/{scene_id}/upload-clip", status_code=201)
async def upload_clip(project_id: int, scene_id: int, file: UploadFile = File(...),
                      session: AsyncSession = Depends(get_session), storage=Depends(get_storage)) -> dict:
    """Upload d'une vidéo locale comme variante de clip pour la scène."""
    await project_or_404(session, project_id)
    scene = await session.get(Scene, scene_id)
    if scene is None or scene.project_id != project_id:
        raise HTTPException(404, "Scène introuvable")

    steps = await load_steps(session, [project_id])
    ensure_not_running(steps, ("clips", "montage"))

    upload = await read_upload(file, VIDEO, MAX_VIDEO_UPLOAD_BYTES)
    last = await session.scalar(select(func.max(Asset.variant)).where(
        Asset.project_id == project_id, Asset.kind == "clip", Asset.scene_id == scene_id))
    asset = await store_upload(session, storage, upload, project_id=project_id, scene_id=scene_id, kind="clip",
                               variant=(last or 0) + 1)

    if scene.selected_clip_asset_id is None:
        scene.selected_clip_asset_id = asset.id
        mark_stale(steps, CLIP_CHOICE_DEPENDENTS)
        await sync_status(session, project_id, steps)

    await session.commit()
    await session.refresh(asset)
    return asset_out(asset, storage, upload.original_name)


MAX_IMAGE_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 Mo
IMAGE = UploadKind("d'image", {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"})


@router.post("/{project_id}/reference/upload", status_code=201)
async def upload_reference(project_id: int, file: UploadFile = File(...), ref: str = Form("", pattern=r"^[a-z0-9_-]{0,30}$"),
                           session: AsyncSession = Depends(get_session), storage=Depends(get_storage)) -> dict:
    """Upload d'une image locale comme image de référence : celle de l'élément `ref` du script, ou du projet entier.
    Autorisé pendant les clips (le job a lu ses images au lancement : la nouvelle sert aux clips suivants) ; refusé
    pendant l'étape reference, qui écrit les mêmes assets."""
    project = await project_or_404(session, project_id)
    owner = await session.get(User, project.user_id)
    assert owner is not None
    # remplacer l'image d'un élément reste permis ; un nouvel élément compte dans la limite du forfait
    await access.require_limit(AppSettings(session), owner, "references_max",
                               len(await reference_elements(session, project_id) | {ref}))
    steps = await load_steps(session, [project_id])
    ensure_not_running(steps, ("reference",))

    upload = await read_upload(file, IMAGE, MAX_IMAGE_UPLOAD_BYTES)
    asset = await store_upload(session, storage, upload, project_id=project_id, kind="reference", variant=1)
    if ref:
        asset.meta = {**asset.meta, "ref": ref}
    for s in steps:
        if s.name == "reference":
            s.status = "approved"
    await sync_status(session, project_id, steps)
    await session.commit()
    await session.refresh(asset)
    return asset_out(asset, storage, upload.original_name)


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: int, session: AsyncSession = Depends(get_session),
                         storage=Depends(get_storage)) -> Response:
    """Supprime le projet et ses fichiers. 409 si une étape tourne : son job continuerait d'appeler des providers payants
    pour un projet disparu."""
    project = await project_or_404(session, project_id)
    ensure_not_running(await load_steps(session, [project_id]), STEP_NAMES)
    keys = (await session.scalars(select(Asset.key).where(Asset.project_id == project_id))).all()
    await session.delete(project)
    await session.commit()
    # Après le commit : un échec de stockage ne ressuscite pas le projet. Le préfixe couvre aussi les segments de montage.
    await storage.delete_many(keys)
    await storage.delete_prefix(f"projects/{project_id}/")
    return Response(status_code=204)


@router.get("/{project_id}/estimate")
async def estimate(project_id: int, provider: str = "", model: str = "", user: User = Depends(current_user),
                   session: AsyncSession = Depends(get_session), registry: ProviderRegistry = Depends(get_registry)) -> dict:
    """Coût estimé des clips en dollars : pour l'admin seulement (`cost_usd` nul pour un client, qui voit un prix en
    crédits par `…/steps/clips/price`)."""
    await project_or_404(session, project_id)
    app_settings = AppSettings(session)
    provider = provider or await app_settings.get("default_video_provider")
    model = model or await app_settings.get("default_video_model")
    try:
        await registry.video(provider)
    except KeyError:
        raise HTTPException(400, f"Provider vidéo inconnu : {provider}") from None
    try:
        cost = await estimate_clips_usd(session, registry, project_id, provider, model)
    except KeyError:
        raise HTTPException(400, f"Modèle vidéo inconnu pour {provider} : {model}") from None
    scene_count = await session.scalar(select(func.count()).select_from(Scene).where(Scene.project_id == project_id))
    return {"provider": provider, "model": model, "scene_count": scene_count,
            "cost_usd": round(cost, 4) if user.is_admin else None}
