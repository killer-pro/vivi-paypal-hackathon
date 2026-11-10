import json
import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from app.providers.base import Availability, GenerationResult, ProviderError, TextResult, ensure_non_empty

_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360f8cfc0f01f0005000201a52ef4770000000049454e44ae426082"
)


def _ffmpeg(*args: str, suffix: str) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / f"out{suffix}"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args, str(out)], check=True)
        return out.read_bytes()


# Réponses de l'assistant de rédaction en mode fake (walkthrough, captures) : un exemple plausible par champ.
FAKE_ASSIST = {
    "project_title": "Sommeil : 3 erreurs du soir",
    "theme": "3 erreurs du soir qui ruinent ton sommeil, ton direct et complice, public 18-30 ans",
    "hint": "Partir d'une habitude que tout le monde croit inoffensive",
    "angle": "Et si ton téléphone n'était pas le vrai coupable ? En 30 secondes, on démonte trois réflexes du soir "
             "qui sabotent ton sommeil, avec une chute qui donne envie de tester dès ce soir.",
    "bible": "Lea, 28, shoulder-length brown hair, grey wool sweater, tired eyes. Phone: black smartphone with a "
             "cracked corner. Setting: small bedroom, warm bedside lamp, navy and amber palette, photorealistic.",
    "voice_text": "Tu dors mal ? Et si ce n'était pas ton téléphone ?",
    "visual_prompt": "Close-up of a young woman awake in bed at night, cold blue phone light on her face, slow push-in, "
                     "moody cinematic lighting, shallow depth of field, vertical 9:16",
    "reference_prompt": "Moody bedroom at night, soft blue and amber light, cinematic film still, vertical 9:16",
    "title": "3 erreurs du soir qui ruinent ton sommeil",
    "description": "Tu dors mal sans savoir pourquoi ? Ces 3 réflexes du soir pourraient être en cause. Lequel fais-tu ?",
    "hashtags": "#sommeil #astuce #santé #routine #fyp",
}


def _fake_assist(prompt: str) -> str | None:
    """Réponse déterministe à un prompt de l'assistant (lignes `Champ :` / `Mode :`) ; None pour un autre prompt."""
    kind = re.search(r"^Champ : (\w+)$", prompt, re.M)
    if not kind:
        return None
    current = re.search(r"Texte actuel :\n<<<\n(.*?)\n>>>", prompt, re.S)
    if "Mode : rewrite" in prompt and current and kind.group(1) != "hashtags":
        return f"{current.group(1)} (version reformulée)"
    return FAKE_ASSIST.get(kind.group(1), "Texte proposé par l'IA")


def _fake_plan_chat(prompt: str) -> str | None:
    """Réponse du chat du plan en mode fake : « Modifie… » change la voix de la première scène, le reste est une simple
    réponse ; None pour un autre prompt."""
    plan = re.search(r"Plan actuel \(JSON[^\n]*:\n<<<\n(.*?)\n>>>", prompt, re.S)
    message = re.search(r"Message de l'utilisateur : (.*)\Z", prompt, re.S)
    if not (plan and message):
        return None
    if not message.group(1).lower().startswith("modifie"):
        return json.dumps({"reply": "Le plan me semble cohérent ; dites-moi ce que vous voulez changer."})
    data = json.loads(plan.group(1))
    data["scenes"][0]["voice_text"] += " (modifiée par l'IA)"
    return json.dumps({"reply": "J'ai modifié la première scène.", "plan": data})


# Histoire en mode fake (passes histoire, inventaire et prompt visuel par scène) : un personnage, un accessoire dont
# l'état change, un lieu sans image, des scènes enchaînées et coupées, pour exercer l'écran Plan sans clé API.
FAKE_STORY = {"beats": [
    {"summary": "Léa court vers la gare, le sac doré serré contre elle.", "voice_text": "Trois minutes pour attraper le dernier train.", "duration_s": 8, "continuity": "cut"},
    {"summary": "Sur le quai, la fermeture du sac se bloque.", "voice_text": "Et bien sûr, la fermeture se bloque.", "duration_s": 7, "continuity": "continue"},
    {"summary": "Le train part sans elle ; elle s'assoit sur un banc.", "voice_text": "Le train part. Sans elle.", "duration_s": 8, "continuity": "cut"},
    {"summary": "Elle force la fermeture : le billet était dedans.", "voice_text": "Le billet était dans le sac depuis le début.", "duration_s": 7, "continuity": "continue"},
]}
FAKE_INVENTORY = {
    "bible": "Night train station, wet platform, neon blue and amber palette, photorealistic, cinematic.",
    "elements": [
        {"id": "lea", "kind": "character", "name": "Léa", "descriptor": "young woman, short black hair, red raincoat",
         "prompt": "young woman, short black hair, red raincoat, plain grey background"},
        {"id": "sac", "kind": "prop", "name": "Sac doré", "descriptor": "small golden leather handbag with a zipper",
         "prompt": "small golden leather handbag with a zipper, plain grey background"},
        {"id": "gare", "kind": "place", "name": "Gare", "descriptor": "", "prompt": ""},
    ],
    "beats": [
        {"elements": [{"id": "lea", "state": ""}, {"id": "sac", "state": "closed"}], "speaker": ""},
        {"elements": [{"id": "lea", "state": ""}, {"id": "sac", "state": "zipper jammed"}, {"id": "gare", "state": ""}], "speaker": ""},
        {"elements": [{"id": "lea", "state": "hair messy"}, {"id": "gare", "state": ""}], "speaker": ""},
        {"elements": [{"id": "lea", "state": "hair messy"}, {"id": "sac", "state": "open"}], "speaker": ""},
    ],
}


def _fake_story(prompt: str) -> str | None:
    """Réponse des passes de la story et du prompt visuel d'une scène ; None pour un autre prompt."""
    if 'Réponds avec {"beats"' in prompt:
        return json.dumps(FAKE_STORY)
    if 'Réponds avec {"bible": "...", "elements"' in prompt:
        return json.dumps(FAKE_INVENTORY)
    if 'Réponds avec {"visual_prompt"' in prompt:
        return json.dumps({"visual_prompt": "Night train platform, slow push-in, cinematic lighting, vertical 9:16"})
    return None


class FakeLLM:
    name = "fake-llm"

    async def complete(self, system: str, prompt: str, *, max_tokens: int = 4000,
                       json_schema: dict | None = None) -> TextResult:
        if (assisted := _fake_assist(prompt)) is not None:
            return TextResult(assisted, 0.001, "fake-llm")
        if (chat := _fake_plan_chat(prompt)) is not None:
            return TextResult(chat, 0.001, "fake-llm")
        if (story := _fake_story(prompt)) is not None:
            return TextResult(story, 0.001, "fake-llm")
        if "scènes" in prompt:
            scenes = [{"voice_text": f"Scène {i}", "visual_prompt": f"plan {i}", "duration_s": 3} for i in (1, 2)]
            return TextResult(json.dumps({"scenes": scenes}), 0.001, "fake-llm")
        if "hashtags" in prompt:  # métadonnées de l'étape final
            metadata = {"title": "Titre de test", "description": "Description de test", "hashtags": ["#test", "#fake"]}
            return TextResult(json.dumps(metadata), 0.001, "fake-llm")
        return TextResult("ok", 0.001, "fake-llm")

    async def health(self) -> bool:
        return True


class FakeImage:
    """`models` : catalogue d'images du provider simulé (le mode fake propose les mêmes modèles que le vrai)."""

    name = "fake-image"

    def __init__(self, models: list[str] | None = None):
        self.models = models or ["fake-image"]

    async def generate(self, prompt: str, *, model: str, references=()) -> GenerationResult:
        return GenerationResult(_PNG, "image/png", 0.01, model)

    async def image_availability(self) -> dict[str, Availability]:
        return dict.fromkeys(self.models, Availability(True))

    async def health(self) -> bool:
        return True


class FakeVideo:
    """`models` : catalogue du provider simulé (le mode fake propose les mêmes modèles que le vrai) ; `keyframe` : image
    de départ renvoyée avec chaque clip, comme un profil ComfyUI `keyframe`."""

    name = "fake-video"

    def __init__(self, fail_with: ProviderError | None = None, models: list[str] | None = None,
                 keyframe: bytes | None = None, cost: Callable[[str, float], float] | None = None):
        self.fail_with = fail_with
        self.models = models or ["fake-video"]
        self.keyframe = keyframe
        self.cost = cost

    def estimate_cost(self, model: str, duration_s: float) -> float:
        return self.cost(model, duration_s) if self.cost else round(0.05 * duration_s, 4)

    async def generate(self, prompt, *, model, duration_s, image=None, references=(), start_image=None) -> GenerationResult:
        if self.fail_with:
            raise self.fail_with
        data = _ffmpeg("-f", "lavfi", "-i", "color=c=blue:s=320x568:d=1:r=30", "-pix_fmt", "yuv420p", suffix=".mp4")
        return GenerationResult(ensure_non_empty(data, "clip"), "video/mp4", self.estimate_cost(model, duration_s), model,
                                self.keyframe)

    async def talk(self, prompt, *, model, audio, duration_s, image=None, references=(), start_image=None) -> GenerationResult:
        """Avatar parlant simulé : un clip de la durée de la voix."""
        if self.fail_with:
            raise self.fail_with
        data = _ffmpeg("-f", "lavfi", "-i", f"color=c=green:s=320x568:d={duration_s:.2f}:r=16", "-pix_fmt", "yuv420p",
                       suffix=".mp4")
        return GenerationResult(ensure_non_empty(data, "avatar parlant"), "video/mp4",
                                self.estimate_cost(model, duration_s), model, self.keyframe)

    async def availability(self) -> dict[str, Availability]:
        return dict.fromkeys(self.models, Availability(True))

    async def reference_availability(self, model: str) -> Availability:
        return Availability(True)

    async def health(self) -> bool:
        return True


class FakeVoice:
    name = "fake-voice"

    async def voices(self) -> list[dict[str, str]]:
        return [{"id": "voix_a", "name": "Camille"}, {"id": "voix_b", "name": "Hugo"}]

    async def synthesize(self, text: str, *, voice_id: str) -> GenerationResult:
        seconds = max(1.0, len(text) / 15)
        data = _ffmpeg("-f", "lavfi", "-i", f"sine=frequency=220:duration={seconds}", suffix=".mp3")
        return GenerationResult(ensure_non_empty(data, "voix"), "audio/mpeg", 0.0002 * len(text), "fake-voice")

    async def health(self) -> bool:
        return True
