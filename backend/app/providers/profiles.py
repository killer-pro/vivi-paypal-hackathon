from dataclasses import dataclass


@dataclass(frozen=True)
class ModelFile:
    """Fichier requis côté ComfyUI, listé par l'entrée `field` du nœud chargeur `node`."""

    node: str
    field: str
    filename: str


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    description: str
    speed: float  # 1 à 5, pas de 0,5
    quality: float  # 1 à 5, pas de 0,5
    minutes_per_clip: float  # clip de 3 s, M4 Max, RAM libérée
    width: int  # résolution native du modèle (avant mise à 720×1248)
    height: int
    esrgan: bool = False
    keyframe: bool = False  # Flux (image) puis Wan I2V


PROFILES = (
    Profile("fast", "Rapide", "Wan 2.2 14B, 320×576 : le meilleur compromis.", 4, 3.5, 5, 320, 576),
    Profile("balanced", "Équilibré", "Wan 2.2 14B, 384×672 : image plus détaillée.", 3, 4, 7.5, 384, 672),
    Profile(
        "precision", "Précision", "Image Flux puis animation Wan 2.2 I2V : le plus net.",
        2, 5, 11, 384, 672, keyframe=True,
    ),
    Profile("max", "Maximum", "Wan 2.2 14B, 480×832 + upscale ESRGAN : qualité maximale.", 1, 5, 18, 480, 832, esrgan=True),
)
DEFAULT_PROFILE = "fast"
LEGACY_NAMES = {"workflow": "max"}  # ancien nom du modèle ComfyUI unique


def get_profile(model: str) -> Profile:
    model = LEGACY_NAMES.get(model, model)
    for profile in PROFILES:
        if profile.id == model:
            return profile
    raise KeyError(model)


def required_files(profile: Profile, *, reference: bool = False) -> list[ModelFile]:
    """Fichiers d'un profil. `reference` : avec une image de référence, toute scène part d'une image de départ
    (Flux Kontext replace la référence dans la scène) puis de l'animation Wan I2V, quel que soit le profil."""
    kind = "i2v" if profile.keyframe or reference else "t2v"
    files = [
        ModelFile("UnetLoaderGGUF", "unet_name", f"Wan2.2-{kind.upper()}-A14B-{level}Noise-Q4_K_M.gguf")
        for level in ("High", "Low")
    ]
    lora = f"wan2.2_{kind}_lightx2v_4steps_lora_v1{'' if kind == 'i2v' else '.1'}"
    files += [ModelFile("LoraLoaderModelOnly", "lora_name", f"{lora}_{level}_noise.safetensors") for level in ("high", "low")]
    files += [
        ModelFile("CLIPLoader", "clip_name", "umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
        ModelFile("VAELoader", "vae_name", "wan_2.1_vae.safetensors"),
    ]
    if profile.keyframe or reference:
        flux = "flux1-kontext-dev-Q4_K_S.gguf" if reference else "flux1-dev-Q4_K_S.gguf"
        files += [
            ModelFile("UnetLoaderGGUF", "unet_name", flux),
            ModelFile("DualCLIPLoader", "clip_name1", "clip_l.safetensors"),
            ModelFile("DualCLIPLoader", "clip_name2", "t5xxl_fp8_e4m3fn.safetensors"),
            ModelFile("VAELoader", "vae_name", "ae.safetensors"),
        ]
    if profile.esrgan:
        files.append(ModelFile("UpscaleModelLoader", "model_name", "ESRGAN/4x-UltraSharp.pth"))
    return files
