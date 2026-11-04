import asyncio
import contextlib
import random
import weakref
from collections.abc import Sequence

import httpx

from app.providers.base import (
    Availability,
    GenerationResult,
    ProviderError,
    ensure_non_empty,
    plain_prompt,
    raise_for_provider,
    split_prompt,
)
from app.providers.profiles import PROFILES, ModelFile, flux_files, get_profile, required_files
from app.providers.workflows import i2v_workflow, keyframe_workflow, kontext_workflow, t2v_workflow

# Génération locale (Wan 2.2 sur Mac : de 5 à 46 min par clip) : timeout d'un appel bien plus long que pour un
# provider cloud. Profil le plus lent (`max`, 480x832 + upscale ESRGAN) : 3 s = 1106 s mesurées ; pire cas 5 s estimé à
# ~2760 s (2510 s mesurées sans upscale + ~250 s d'upscale pour 81 images) ; 1 h 35 = environ x2. Le polling (toutes
# les 2 s) couvre au moins ce délai.
CLIP_TIMEOUT_S = 5700
MAX_POLLS = CLIP_TIMEOUT_S // 2
# Prompt absent de l'historique ET de la file pendant ce nombre de polls consécutifs : ComfyUI a redémarré (ou le prompt
# a été supprimé), inutile d'attendre jusqu'au timeout.
MISSING_POLLS = 3
CANCEL_TIMEOUT_S = 10  # annulation best-effort du prompt quand l'appel est abandonné
OUTPUT_KINDS = ("gifs", "videos", "images")
# {{FRAMES}} : nombre d'images à la cadence native de Wan 2.2 14B (16 fps). Wan exige 4n+1 images, 5 s au plus (81
# images) : au-delà, le montage tient la dernière image jusqu'à la fin de la voix.
FPS = 16
MAX_CLIP_S = 5
UNREACHABLE = "ComfyUI injoignable"
BUSY = "ComfyUI ne répond pas (occupé ?)"  # pas de réponse dans le délai, ex. longue génération avec swap saturé
# Disponibilité (`GET /providers/models`, chaque lancement des clips, sous le verrou du projet) : délai total court,
# au lieu des 120 s du client, pour qu'un ComfyUI qui ne répond plus ne bloque pas l'API ; santé : même délai.
AVAILABILITY_TIMEOUT_S = 3
# Pas de connexion possible : réseau, délai dépassé, ou URL invalide (`InvalidURL` n'est pas une `TransportError`).
CONNECTION_ERRORS = (httpx.TransportError, httpx.InvalidURL)
# Image de départ (profil Précision) : un seul fichier dans `input/` de ComfyUI, réécrit à chaque run (rien ne s'y
# accumule). `LoadImage` hache le contenu du fichier (`IS_CHANGED`) : une image réécrite sous le même nom n'est jamais
# servie depuis le cache. Le worker traite deux jobs à la fois (`max_jobs`) : le verrou garde ensemble l'envoi de
# l'image et l'animation qui la lit, pour qu'un autre run ne la remplace pas entre-temps (un seul worker par ComfyUI).
KEYFRAME_UPLOAD_NAME = "vv_keyframe.png"
REFERENCE_UPLOAD_NAME = "vv_reference.png"  # image de référence envoyée à Flux Kontext (profil Fidèle), sous le même verrou
# Consigne d'édition de Flux Kontext : l'identité (visage, tenue, produit, logo) vient de l'image, la scène du prompt.
KONTEXT_PREFIX = ("Keep exactly the same character, outfit, product and logo as in the input image, unchanged identity "
                  "and branding. Show them in this new scene: ")
_keyframe_slots: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = weakref.WeakKeyDictionary()


def _keyframe_slot() -> asyncio.Lock:
    """Verrou de l'image de départ, un par boucle d'événements (le worker n'en a qu'une ; un `asyncio.Lock` ne sert
    qu'à la boucle qui l'a utilisée la première)."""
    return _keyframe_slots.setdefault(asyncio.get_running_loop(), asyncio.Lock())


def frames_for(duration_s: float) -> int:
    return min(round(duration_s * FPS) // 4 * 4 + 1, MAX_CLIP_S * FPS + 1)


def _choices(info: dict, node: str, field: str) -> list[str]:
    """Fichiers proposés par l'entrée `field` du nœud dans `GET /object_info/<node>` : `[[fichiers], {…}]`, ou
    `["COMBO", {"options": [fichiers]}]` dans les versions récentes de ComfyUI. Réponse d'une autre forme : aucun
    fichier (le profil est grisé plutôt que la liste des modèles en erreur)."""
    try:
        inputs = info[node]["input"]
        spec = {**inputs.get("optional", {}), **inputs.get("required", {})}[field]
        files = spec[1]["options"] if spec[0] == "COMBO" else spec[0]
    except (KeyError, IndexError, TypeError, AttributeError):
        return []
    return files if isinstance(files, list) else []


def _execution_error(history: dict) -> str | None:
    """Message d'échec d'un prompt terminé en erreur (`status.status_str == "error"`), sinon None."""
    status = history.get("status") or {}
    if status.get("status_str") != "error":
        return None
    for event, data in status.get("messages") or []:
        if event == "execution_error" and isinstance(data, dict):
            return f"{data.get('node_type', '?')} : {data.get('exception_message', '').strip()}"
        if event == "execution_interrupted":
            return "génération interrompue"
    return "erreur inconnue"


def _seed() -> int:
    return random.randrange(2**32)  # nouveau seed à chaque clip


def _first_output(history: dict) -> dict:
    for node in history["outputs"].values():
        for kind in OUTPUT_KINDS:
            if node.get(kind):
                return node[kind][0]
    raise ProviderError("comfyui: aucune sortie dans l'historique")


class ComfyUIProvider:
    """Wan 2.2 14B local, un modèle par profil de génération (`profiles.PROFILES`)."""

    name = "comfyui"
    models = [p.id for p in PROFILES]

    def __init__(self, base_url: str, client: httpx.AsyncClient, poll_interval: float = 2.0):
        self._base = base_url.rstrip("/")
        self._c = client
        self._poll = poll_interval
        # Image Flux d'un run dont l'animation a échoué, par (profil, prompt) : la nouvelle tentative de `tracked_call`
        # (même provider, même prompt) la reprend au lieu de refaire ≈ 2 min de Flux ; oubliée dès que le clip est fait.
        # Durée de vie bornée : le cache vit avec l'instance, une par job (`registry.video`), qui génère ses clips
        # ComfyUI un à un (`CLIP_CONCURRENCY["comfyui"] = 1`) ; il garde au plus l'image de la scène en cours.
        self._keyframes: dict[tuple[str, str], bytes] = {}

    def estimate_cost(self, model: str, duration_s: float) -> float:
        return 0.0

    async def _queued(self) -> tuple[list[str], list[str]]:
        """Identifiants des prompts en cours et en attente (`GET /queue`)."""
        r = await self._c.get(f"{self._base}/queue")
        raise_for_provider(r, "comfyui")
        q = r.json()
        return ([item[1] for item in q.get("queue_running", [])], [item[1] for item in q.get("queue_pending", [])])

    async def _wait_history(self, prompt_id: str) -> dict:
        missing = 0
        for _ in range(MAX_POLLS):
            r = await self._c.get(f"{self._base}/history/{prompt_id}")
            raise_for_provider(r, "comfyui")
            history = r.json()
            if prompt_id in history:
                if error := _execution_error(history[prompt_id]):
                    raise ProviderError(f"comfyui: échec du workflow ({error})")
                return history[prompt_id]
            running, pending = await self._queued()
            missing = 0 if prompt_id in running + pending else missing + 1
            if missing >= MISSING_POLLS:
                raise ProviderError("comfyui: prompt introuvable dans l'historique et la file (ComfyUI redémarré ?)")
            await asyncio.sleep(self._poll)
        raise ProviderError("comfyui: timeout de polling")

    async def _cancel(self, prompt_id: str) -> None:
        """Retire le prompt de la file, ou l'interrompt s'il tourne (jamais le prompt d'un autre)."""
        running, pending = await self._queued()
        if prompt_id in pending:
            await self._c.post(f"{self._base}/queue", json={"delete": [prompt_id]})
        elif prompt_id in running:
            await self._c.post(f"{self._base}/interrupt", json={"prompt_id": prompt_id})

    async def _wait_or_cancel(self, prompt_id: str) -> dict:
        """Attente du résultat ; si l'appel est abandonné (timeout/annulation, erreur de polling), le prompt est retiré
        de ComfyUI (best-effort, protégé de l'annulation) pour ne pas occuper la machine pour rien."""
        try:
            return await self._wait_history(prompt_id)
        except BaseException:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(asyncio.shield(self._cancel(prompt_id)), CANCEL_TIMEOUT_S)
            raise

    async def _run(self, workflow: dict, what: str) -> bytes:
        """Soumet le workflow, attend sa fin (annulé côté ComfyUI si l'appel est abandonné) et télécharge sa sortie."""
        r = await self._c.post(f"{self._base}/prompt", json={"prompt": workflow})
        raise_for_provider(r, "comfyui")
        output = _first_output(await self._wait_or_cancel(r.json()["prompt_id"]))
        params = {k: output.get(k, "") for k in ("filename", "subfolder", "type")}
        v = await self._c.get(f"{self._base}/view", params=params)
        raise_for_provider(v, "comfyui")
        await self._free()
        return ensure_non_empty(v.content, what)

    async def _free(self) -> None:
        """Décharge les modèles de ComfyUI (best-effort) : sans cela, ceux de l'étape qui vient de finir (Kontext, puis les
        deux UNets Wan, ≈ 24 Go) restent en cache pendant que la suivante charge les siens, et la RAM de 36 Go swappe."""
        with contextlib.suppress(Exception):
            await self._c.post(f"{self._base}/free", json={"unload_models": True, "free_memory": True},
                               timeout=AVAILABILITY_TIMEOUT_S)

    async def _upload(self, png: bytes, name: str = KEYFRAME_UPLOAD_NAME) -> str:
        """Dépose une image dans `input/` de ComfyUI (à la place de la précédente du même nom) ; renvoie le nom à donner
        à `LoadImage`."""
        files = {"image": (name, png, "image/png")}
        r = await self._c.post(f"{self._base}/upload/image", files=files, data={"overwrite": "true"})
        raise_for_provider(r, "comfyui")
        body = r.json()
        if not body.get("name"):
            raise ProviderError("comfyui: envoi de l'image de départ sans nom de fichier en retour")
        return f"{body['subfolder']}/{body['name']}" if body.get("subfolder") else body["name"]

    async def _keyframe(self, profile, prompt: str, reference: bytes | None, extras: Sequence[bytes] = ()) -> bytes:
        """Image de départ d'une scène : avec une image de référence, Kontext la replace dans la scène (mêmes
        personnages et marques) ; sans, Flux dev l'invente depuis le prompt (profil Précision seulement). L'envoi et le
        calcul restent sous le verrou de l'image envoyée."""
        if reference is None:
            return await self._run(keyframe_workflow(profile, prompt, _seed()), "image de départ")
        async with _keyframe_slot():
            names = [await self._upload(reference, REFERENCE_UPLOAD_NAME)]
            for n, extra in enumerate(extras, 2):
                names.append(await self._upload(extra, f"vv_reference_{n}.png"))
            return await self._run(kontext_workflow(KONTEXT_PREFIX + prompt, _seed(), names), "image de la scène")

    async def generate(self, prompt, *, model, duration_s, image=None, references=(), start_image=None):
        """`start_image` : image de départ déjà composée (ex. par Gemini) : elle remplace Kontext, Wan I2V l'anime telle quelle."""
        try:
            profile = get_profile(model)
        except KeyError:
            raise ProviderError(f"comfyui: profil inconnu : {model}") from None
        frames = frames_for(duration_s)
        keyframe = None
        still, motion = split_prompt(prompt)  # image fixe pour Flux/Kontext, mouvement pour l'animation à partir d'une image
        try:
            if profile.keyframe or image is not None or start_image is not None:  # image de départ, puis animation Wan I2V
                key = (profile.id, still)
                keyframe = start_image or self._keyframes.get(key) or await self._keyframe(profile, still, image, list(references))
                self._keyframes[key] = keyframe
                async with _keyframe_slot():
                    data = await self._run(i2v_workflow(profile, motion or still, _seed(), frames,
                                                        await self._upload(keyframe)), "clip")
                self._keyframes.pop(key, None)  # déjà oubliée si un autre appel au même prompt a fini avant
            else:
                data = await self._run(t2v_workflow(profile, plain_prompt(prompt), _seed(), frames), "clip")
        except CONNECTION_ERRORS as e:
            raise ProviderError(f"{UNREACHABLE} ({e})") from e
        return GenerationResult(data, "video/mp4", 0.0, profile.id, keyframe)

    async def _object_info(self, node: str) -> dict:
        """Description d'un nœud ; vide s'il n'est pas installé (ComfyUI répond 404)."""
        r = await self._c.get(f"{self._base}/object_info/{node}", timeout=AVAILABILITY_TIMEOUT_S)
        return r.json() if r.status_code == 200 else {}

    async def _responds(self) -> bool:
        return (await self._c.get(f"{self._base}/system_stats", timeout=AVAILABILITY_TIMEOUT_S)).status_code == 200

    async def availability(self) -> dict[str, Availability]:
        """Un profil est disponible si ComfyUI répond et que chacun de ses fichiers de modèle est installé (sans image
        de référence : voir `reference_availability`)."""
        return await self._availability({p.id: required_files(p) for p in PROFILES})

    async def reference_availability(self, model: str) -> Availability:
        """Disponibilité du profil quand le projet a une image de référence : il faut alors aussi Wan I2V et Kontext."""
        profile = get_profile(model)
        return (await self._availability({profile.id: required_files(profile, reference=True)}))[profile.id]

    async def _availability(self, wanted: dict[str, list[ModelFile]]) -> dict[str, Availability]:
        info = None
        try:
            async with asyncio.timeout(AVAILABILITY_TIMEOUT_S):  # tout l'appel, nœuds chargeurs interrogés ensemble
                if await self._responds():
                    nodes = sorted({f.node for files in wanted.values() for f in files})
                    info = dict(zip(nodes, await asyncio.gather(*map(self._object_info, nodes)), strict=True))
        except (TimeoutError, httpx.TimeoutException):  # avant CONNECTION_ERRORS, dont TimeoutException fait partie
            # Occupé n'est pas en panne : lançable (le job attend son tour), avec l'avertissement.
            return {key: Availability(True, BUSY) for key in wanted}
        except (*CONNECTION_ERRORS, ValueError):  # ValueError : réponse qui n'est pas du JSON
            pass
        if info is None:
            return {key: Availability(False, UNREACHABLE) for key in wanted}
        report = {}
        for key, files in wanted.items():
            missing = next((f.filename for f in files if f.filename not in _choices(info[f.node], f.node, f.field)), None)
            report[key] = Availability(False, f"Modèle manquant : {missing}") if missing else Availability(True)
        return report

    async def health(self) -> bool:
        try:
            return await self._responds()
        except CONNECTION_ERRORS:
            return False


class ComfyUIImage:
    """Image de référence générée par Flux dev sur votre ComfyUI (même graphe que l'image de départ du profil
    Précision, 576×1008) : gratuite, mais ≈ 2 min par image sur un Mac."""

    name = "comfyui"
    MODEL = "flux-dev"

    def __init__(self, comfy: ComfyUIProvider):
        self._comfy = comfy

    async def generate(self, prompt, *, model, references=()):
        still, _ = split_prompt(prompt)
        png = await self._comfy._run(keyframe_workflow(get_profile(PROFILES[0].id), still, _seed()), "image de référence")
        return GenerationResult(png, "image/png", 0.0, model)

    async def image_availability(self) -> dict[str, Availability]:
        return await self._comfy._availability({self.MODEL: flux_files()})

    async def health(self) -> bool:
        return await self._comfy.health()
