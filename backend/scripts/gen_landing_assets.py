"""Génère les visuels de la landing (`admin/public/landing/`) avec ComfyUI local : des images Flux dev (scènes verticales
9:16 de cas d'usage et de styles viraux, puis neuf images 16:9 : une par étape du pipeline et la conclusion), et un clip
de 3 s par scène verticale avec Wan 2.2 (profil « fast »). Un fichier déjà présent est sauté : le supprimer pour le
régénérer.

Usage (depuis backend/, ComfyUI lancé) :
    .venv/bin/python scripts/gen_landing_assets.py            # tout
    .venv/bin/python scripts/gen_landing_assets.py images     # images seulement (verticales et larges)
Script d'outillage : il n'est pas importé par l'application.
"""
import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

from app.config import settings
from app.providers.comfyui import ComfyUIProvider, frames_for
from app.providers.profiles import get_profile
from app.providers.workflows import i2v_workflow, keyframe_workflow

OUT = Path(__file__).resolve().parents[2] / "admin" / "public" / "landing"
CLIP_S = 3
PROFILE = "fast"
SEED = 20261101

LATENT_NODE = "7"  # EmptySD3LatentImage du graphe Flux : sa taille fixe le format de l'image
SIZES = {"9:16": (576, 1008), "16:9": (1024, 576)}

STYLE = "premium commercial cinematography, natural soft light, rich depth of field, high detail, no text, no logo, no watermark"
# Scènes verticales : image fixe puis mouvement du clip. Le mouvement nomme chaque élément qui doit bouger, sinon
# Wan n'anime que la caméra et laisse le reste figé.
SCENES = {
    "sneaker-packshot": (
        "A white and neon-orange running sneaker floating above a glossy dark studio floor, rim light, soft reflections, "
        "floating dust particles",
        "The camera orbits slowly around the sneaker, the shoe rotates gently in mid-air, light reflections slide along "
        "the glossy floor, dust particles drift.",
    ),
    "sneaker-detail": (
        "Extreme close-up of the same white and neon-orange sneaker mesh and laces, water droplets on the fabric, "
        "shallow depth of field, studio lighting",
        "A water droplet rolls down the mesh, the camera pushes in slowly, the laces sway slightly, the light glints.",
    ),
    "sneaker-street": (
        "A runner wearing the same white and neon-orange sneakers sprinting across a wet city street at golden hour, "
        "low angle, motion energy",
        "The runner sprints forward, feet splashing water, the camera tracks low alongside, city lights streak behind.",
    ),
    "immobilier": (
        "A bright modern apartment living room at sunrise, floor-to-ceiling windows, linen sofa, oak floor, "
        "plants, warm light",
        "The camera glides slowly forward through the room, sunlight moves across the floor, curtains and plant leaves "
        "stir in a light breeze.",
    ),
    "restaurant": (
        "A chef plating a seared scallop dish with tweezers in a warm restaurant kitchen, steam rising, "
        "copper pans in the background",
        "The chef's hands place a herb leaf with tweezers, steam rises from the plate, the camera pushes in slowly.",
    ),
    "mode": (
        "A fashion model in a flowing emerald silk coat walking on a minimalist concrete runway, editorial lighting, "
        "wind in the fabric",
        "The model walks toward the camera, the silk coat flows and billows behind, hair moves in the wind, "
        "the camera drifts backward.",
    ),
    "voyage": (
        "A turquoise lagoon seen from a wooden jetty at sunrise, a small traditional boat, palm trees, "
        "mist over the water",
        "The boat glides across the lagoon leaving a wake, ripples spread on the water, palm leaves sway, "
        "the camera drifts forward over the jetty.",
    ),
    "app": (
        "A hand holding a smartphone showing a colorful productivity app dashboard, cozy desk, coffee steam, "
        "bokeh lights",
        "The thumb scrolls the phone screen, interface cards slide and glow, coffee steam curls up, "
        "bokeh lights shimmer.",
    ),
}
# Formats viraux (TikTok, Reels, Shorts), chacun dans un style très différent : le style fait partie du sujet.
VIRAL_STYLE = "vertical short-form video frame, sharp subject, vivid colors, high detail, no text, no logo, no watermark"
VIRAL = {
    "style-anime": (
        "Anime style, a girl with a red scarf standing on a rooftop at dusk, city lights below, cherry blossom petals "
        "in the air, detailed cel shading",
        "Her scarf and hair flutter in the wind, cherry blossom petals swirl past, city lights twinkle, "
        "the camera slowly pushes in.",
    ),
    "style-pixar": (
        "3D animated movie style, a cute small robot chef stirring a steaming pot in a cozy colorful kitchen, "
        "big expressive eyes, soft studio lighting",
        "The robot stirs the pot with a ladle, steam billows up, its eyes blink, the camera pushes in slowly.",
    ),
    "style-vhs": (
        "Retro 90s VHS camcorder footage, a teenage skateboarder in baggy clothes in a sunny parking lot, film grain, "
        "washed colors, date stamp feel",
        "The skater rolls forward and does a small jump, the camera shakes like a handheld camcorder, "
        "the image flickers with VHS noise.",
    ),
    "style-cyberpunk": (
        "Cyberpunk neon alley in heavy rain, a courier on a glowing motorbike, holographic signs in pink and cyan, "
        "wet reflective street",
        "The motorbike speeds toward the camera, rain streaks fall, neon signs flicker, reflections ripple "
        "on the wet street.",
    ),
    "style-claymation": (
        "Stop-motion claymation style, a tiny clay astronaut walking on a cheese moon, handmade textures, "
        "fingerprints in the clay, warm lighting",
        "The clay astronaut waddles forward step by step, its antenna wobbles, the camera drifts sideways "
        "with a stop-motion jitter.",
    ),
    "style-aquarelle": (
        "Watercolor painting style, a seaside village at dawn with small boats, soft bleeding pastel washes, "
        "paper texture",
        "Boats rock gently on the water, ripples spread, smoke curls from a chimney, birds cross the sky, "
        "colors shimmer.",
    ),
    "asmr": (
        "Macro satisfying ASMR shot, a hand pressing a glossy pink slime and glitter with a metal spoon, "
        "soft studio light",
        "The spoon sinks into the slime and lifts it in a stretching strand, glitter sparkles, "
        "the camera pushes in slowly.",
    ),
    "mystere": (
        "Cinematic horror storytime scene, a lone person with a flashlight in a foggy pine forest at night, "
        "cold blue tones, volumetric light",
        "The flashlight beam sweeps across the trees, thick fog rolls past, the person walks forward slowly, "
        "branches sway.",
    ),
    "sport": (
        "Gritty fitness motivation shot, a boxer hitting a heavy bag in a dark gym, sweat flying, "
        "dramatic rim light",
        "The boxer throws fast punches, the heavy bag swings, sweat drops fly, the camera shakes slightly.",
    ),
    "fantasy": (
        "Epic fantasy scene, a huge dragon flying over a stone castle at sunset, golden clouds, "
        "cinematic matte painting",
        "The dragon beats its wings and glides past the camera, clouds drift, the castle flags wave.",
    ),
    "street-food": (
        "Night market street food, a cook tossing noodles in a flaming wok, steam and sparks, warm lanterns "
        "in the background",
        "Flames flare up around the wok, the cook tosses the noodles into the air, steam rises, "
        "the camera pushes in.",
    ),
    "science": (
        "Educational science visual, a glowing galaxy and a ringed planet in deep space with colorful nebula, "
        "ultra detailed",
        "The camera flies slowly toward the planet, nebula clouds swirl, stars twinkle, the rings rotate.",
    ),
    "beaute": (
        "Beauty close-up, a makeup brush sweeping golden glitter eyeshadow over an eyelid, glossy skin, "
        "soft ring light",
        "The brush sweeps across the eyelid leaving glitter, the eye blinks, the light glints on the skin.",
    ),
    "auto": (
        "A matte black sports car drifting around a corner on a wet mountain road at night, headlights "
        "and tire smoke",
        "The car slides sideways, tire smoke billows, water sprays, the camera tracks alongside.",
    ),
    "chiot": (
        "A golden retriever puppy in a yellow raincoat jumping in a puddle on a sunny street, joyful, "
        "shallow depth of field",
        "The puppy jumps and splashes water, its ears flap, its tail wags, the camera follows low.",
    ),
    "concert": (
        "A DJ on stage with hands up in front of a cheering crowd, laser beams and colorful smoke, "
        "festival night",
        "Laser beams sweep across the crowd, smoke swirls, the DJ raises both hands, the crowd jumps.",
    ),
}
# Une image large par étape du pipeline, plus la conclusion : l'atelier où naît la vidéo.
STEPS = {
    "idee": "A designer's desk at night with a notebook of rough ideas, sneaker sketches and a perfume bottle, "
            "a glowing lamp, warm amber and deep blue",
    "script": "A wall of pinned storyboard panels sketching a product commercial in six frames, "
              "warm studio light, shallow depth of field",
    "references": "A moodboard wall of consistent photographs of the same sneaker and the same model "
                  "in different settings, soft light, teal and orange",
    "clips": "Glowing film frames streaming out of a cinema camera across a dark studio, "
             "motion trails, deep blue and orange",
    "voix": "A studio microphone with luminous sound waves rippling outward, silver and violet, dark background",
    "musique": "A turntable and headphones with a glowing equalizer pulsing in the dark, teal and gold",
    "montage": "A video editing suite with several screens showing a timeline of glowing clips, "
               "a hand on a mixing console, warm amber",
    "export": "A smartphone floating in a dark studio showing a finished vertical video, soft halo of light, "
              "pink and gold",
    "conclusion": "A vast sunrise over a calm bay seen from a studio balcony, a camera on a tripod in the foreground, "
                  "pink and gold sky, hopeful",
}


async def make_stills(comfy: ComfyUIProvider, subjects: dict[str, str], prefix: str, aspect_ratio: str,
                      style: str) -> None:
    for i, (name, subject) in enumerate(subjects.items()):
        path = OUT / f"{prefix}{name}.jpg"
        if path.exists():
            continue
        workflow = keyframe_workflow(get_profile(PROFILE), f"{subject}, {style}", SEED + i)
        workflow[LATENT_NODE]["inputs"]["width"], workflow[LATENT_NODE]["inputs"]["height"] = SIZES[aspect_ratio]
        png = await comfy._run(workflow, "image")
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            Path(tmp.name).write_bytes(png)
            subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "88", tmp.name, "--out", str(path)],
                           check=True, capture_output=True)
        print(f"image {path.name} : {path.stat().st_size // 1024} Ko", flush=True)


async def make_clips(comfy: ComfyUIProvider) -> None:
    """Anime chaque image telle quelle (Wan I2V). `generate()` passerait d'abord par Kontext, qui réinterprète l'image :
    le clip ne partirait plus de celle affichée en affiche. D'où `_upload` et `_run`, privés mais utilisés ici seulement."""
    for name, (_, motion) in {**SCENES, **VIRAL}.items():
        path = OUT / f"{name}.mp4"
        if path.exists():
            continue
        uploaded = await comfy._upload((OUT / f"{name}.jpg").read_bytes(), f"landing_{name}.jpg")
        workflow = i2v_workflow(get_profile(PROFILE), motion, SEED, frames_for(CLIP_S), uploaded)
        path.write_bytes(await comfy._run(workflow, "clip"))
        print(f"clip {path.name} : {path.stat().st_size // 1024} Ko", flush=True)


async def main(only_images: bool) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=httpx.Timeout(900)) as client:
        comfy = ComfyUIProvider(settings.comfyui_url, client)
        await make_stills(comfy, {name: subject for name, (subject, _) in VIRAL.items()}, "", "9:16", VIRAL_STYLE)
        await make_stills(comfy, {name: subject for name, (subject, _) in SCENES.items()}, "", "9:16", STYLE)
        await make_stills(comfy, STEPS, "wide-", "16:9", STYLE)
        if not only_images:
            await make_clips(comfy)


asyncio.run(main(only_images=sys.argv[1:] == ["images"]))
