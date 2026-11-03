"""Workflows ComfyUI (format API) paramétrés par profil : un JSON par type de graphe, jamais une copie par profil."""
import json
from pathlib import Path

from app.providers.profiles import Profile

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / "workflows"
ESRGAN_MODEL = "ESRGAN/4x-UltraSharp.pth"
ESRGAN_SCALE_NODE = "17"  # ImageScale final (720×1248), qui lit le décodage ou, avec ESRGAN, l'agrandissement
VIDEO_COMBINE_NODE = "18"
# Part de l'agrandissement classique (lanczos) mêlée à celui d'ESRGAN : 4x-UltraSharp seul durcit les contours et lisse
# la peau comme une peinture ; le mélange garde le gain de netteté sans cet aspect.
PLAIN_SHARE = 0.5


def _load(name: str, numbers: dict[str, int], prompt: str, image: str | None = None) -> dict:
    """Charge `comfyui-<name>.json` et remplace les marqueurs. Le prompt (texte libre) est inséré en dernier : un
    « {{SEED}} » qu'il contiendrait reste littéral."""
    raw = (WORKFLOWS_DIR / f"comfyui-{name}.json").read_text(encoding="utf-8")
    for key, value in numbers.items():
        raw = raw.replace(f'"{{{{{key}}}}}"', str(value))
    if image is not None:
        raw = raw.replace("{{IMAGE}}", json.dumps(image)[1:-1])
    return json.loads(raw.replace("{{PROMPT}}", json.dumps(prompt)[1:-1]))


def _with_esrgan(workflow: dict) -> dict:
    """Insère l'agrandissement ESRGAN x4 entre le décodage VAE et la mise à 720×1248, puis le mêle à la simple mise à
    l'échelle du décodage (`PLAIN_SHARE`)."""
    scale = workflow[ESRGAN_SCALE_NODE]["inputs"]
    workflow["20"] = {**workflow[ESRGAN_SCALE_NODE], "_meta": {"title": "Plain 720x1248 (lanczos)"},
                      "inputs": dict(scale)}
    workflow["15"] = {
        "class_type": "UpscaleModelLoader",
        "_meta": {"title": "Load upscale model (4x-UltraSharp)"},
        "inputs": {"model_name": ESRGAN_MODEL},
    }
    workflow["16"] = {
        "class_type": "ImageUpscaleWithModel",
        "_meta": {"title": "Upscale x4 (ESRGAN)"},
        "inputs": {"upscale_model": ["15", 0], "image": scale["image"]},
    }
    scale["image"] = ["16", 0]
    workflow["21"] = {
        "class_type": "ImageBlend",
        "_meta": {"title": "Blend ESRGAN / plain"},
        "inputs": {"image1": [ESRGAN_SCALE_NODE, 0], "image2": ["20", 0], "blend_factor": PLAIN_SHARE,
                   "blend_mode": "normal"},
    }
    workflow[VIDEO_COMBINE_NODE]["inputs"]["images"] = ["21", 0]
    return workflow


def _video(name: str, profile: Profile, prompt: str, seed: int, frames: int, image: str | None = None) -> dict:
    numbers = {"WIDTH": profile.width, "HEIGHT": profile.height, "FRAMES": frames, "SEED": seed}
    workflow = _load(name, numbers, prompt, image)
    return _with_esrgan(workflow) if profile.esrgan else workflow


def t2v_workflow(profile: Profile, prompt: str, seed: int, frames: int) -> dict:
    return _video("wan22-14b-t2v", profile, prompt, seed, frames)


def i2v_workflow(profile: Profile, prompt: str, seed: int, frames: int, image_name: str) -> dict:
    return _video("wan22-14b-i2v", profile, prompt, seed, frames, image_name)


def keyframe_workflow(profile: Profile, prompt: str, seed: int) -> dict:
    """Image de départ Flux, taille fixe 576×1008 (indépendante du profil, dont `width`/`height` sont ceux de l'I2V)."""
    return _load("flux-keyframe", {"SEED": seed}, prompt)


KONTEXT_TEXT_NODE, KONTEXT_FIRST_LATENT_NODE, KONTEXT_SCALE_NODE, KONTEXT_GUIDANCE_NODE = "7", "8", "5", "9"
EXTRA_IMAGE_NODES = 10  # numéros de nœud réservés à chaque image en plus (à partir de 100)


def kontext_workflow(prompt: str, seed: int, image_names: list[str]) -> dict:
    """Image de départ d'une scène : Flux Kontext replace les images de référence (576×1008) dans la scène du prompt. La
    première image est celle du graphe de base ; chaque image en plus (au plus quelques-unes : le temps de calcul croît
    avec leur nombre) ajoute LoadImage → ImageScale → VAEEncode → ReferenceLatent, enchaîné au précédent."""
    workflow = _load("flux-kontext", {"SEED": seed}, prompt, image_names[0])
    latent = KONTEXT_FIRST_LATENT_NODE
    for n, name in enumerate(image_names[1:]):
        base = 100 + n * EXTRA_IMAGE_NODES
        load, scale, encode, reference = (str(base + i) for i in range(4))
        workflow[load] = {"class_type": "LoadImage", "inputs": {"image": name}}
        workflow[scale] = {"class_type": "ImageScale",
                           "inputs": {**workflow[KONTEXT_SCALE_NODE]["inputs"], "image": [load, 0]}}
        workflow[encode] = {"class_type": "VAEEncode", "inputs": {"pixels": [scale, 0], "vae": ["3", 0]}}
        workflow[reference] = {"class_type": "ReferenceLatent",
                               "inputs": {"conditioning": [latent, 0], "latent": [encode, 0]}}
        latent = reference
    workflow[KONTEXT_GUIDANCE_NODE]["inputs"]["conditioning"] = [latent, 0]
    return workflow
