"""Banc d'essai du prompt de script : python scripts/eval_script.py [modèle Gemini] — idée puis script sur des thèmes fixes.

Usage (depuis backend/, clé dans l'environnement) :
    GEMINI_API_KEY=... python scripts/eval_script.py [modèle Gemini] [--pipeline old|new|both]
`old` : un seul appel (étape script d'avant la story) ; `new` : story en deux passes puis un prompt par scène ; `both`
(défaut) : les deux, thème par thème, pour les comparer.
Ancien pipeline, pour chaque thème : réponse structurée valide, écart de durée, voix off trop longue, appel à l'engagement, descripteurs,
présence du paragraphe « Motion: », longueur des prompts, tokens. Sert à comparer deux versions du prompt ou deux modèles
sur les mêmes entrées (mesure indicative : une seule réponse par thème, le LLM n'est pas déterministe).
Nouveau pipeline : accessoires orphelins, ids inconnus, descripteurs absents des prompts avant l'ajout du serveur,
défauts du scénario (`story_problems` et `script_problems`), nombre d'appels LLM, durée.
Script de mesure : il n'est pas importé par l'application, n'écrit rien en base et coûte quelques appels Gemini.
"""
import asyncio
import json
import os
import sys
import time

import httpx

from app.models import Project
from app.providers.base import ProviderError
from app.providers.gemini import DEFAULT_MODEL, GeminiLLM
from app.services.llm_json import json_value, scene_text
from app.services.pipeline import (
    IDEA_SYSTEM,
    SCENE_MAX_TOKENS,
    SCENE_SCHEMA,
    SCENES_SCHEMA,
    SCRIPT_SYSTEM,
    STORY_SYSTEM,
    apply_descriptors,
    inventory_prompt,
    parse_references,
    parse_scenes,
    project_brief,
    scene_prompt,
    script_max_tokens,
    script_problems,
    script_prompt,
    story_prompt,
)
from app.services.story import (
    INVENTORY_SCHEMA,
    STORY_SCHEMA,
    elements_in,
    parse_story,
    story_problems,
)

THEMES = [  # (thème, durée cible, style)
    ("cree moi une video ou la femme est entrain de saboter la tenue de son amie", 60, "anime"),
    ("L'histoire de la création de McDonald's par Ray Kroc", 30, "realistic"),
    ("3 erreurs du soir qui ruinent ton sommeil", 30, "realistic"),
    ("Un chat qui juge tes plantes d'intérieur", 20, "anime"),
    ("Pourquoi le café Starbucks coûte si cher", 45, "illustration"),
    ("Le secret des cuisiniers pour des oeufs brouillés parfaits", 30, ""),
]


async def make_angle(llm: GeminiLLM, project: Project) -> str:
    idea = f"{project_brief(project)}\nPropose un angle direct pour cette vidéo : 2 à 4 phrases, sans markdown."
    return (await llm.complete(IDEA_SYSTEM, idea)).text.strip()


async def evaluate_new(llm: GeminiLLM, project: Project, angle: str) -> dict:
    """Pipeline avec story : deux passes (histoire, inventaire), puis un prompt visuel par beat, sans relance."""
    theme, target = project.theme, project.target_duration_s
    started, calls = time.monotonic(), 2
    try:
        budget = script_max_tokens(target)
        beats_text = (await llm.complete(STORY_SYSTEM, story_prompt(project, angle), max_tokens=budget,
                                         json_schema=STORY_SCHEMA)).text
        beats = parse_story(beats_text, "", target)["beats"]
        inventory = (await llm.complete(STORY_SYSTEM, inventory_prompt(project, beats), max_tokens=budget,
                                        json_schema=INVENTORY_SCHEMA)).text
        story = parse_story(beats_text, inventory, target)
    except ProviderError as e:
        return {"theme": theme, "pipeline": "new", "valid": False, "error": str(e)}
    problems = story_problems(story)
    missing_descriptors = 0
    for i, beat in enumerate(story["beats"], 1):
        present = elements_in(beat, story["elements"])
        previous = story["beats"][i - 2]["summary"] if i > 1 else ""
        prompt = scene_prompt(project, story["bible"], beat, present, previous, i, len(story["beats"]))
        answer = (await llm.complete(SCRIPT_SYSTEM, prompt, max_tokens=SCENE_MAX_TOKENS, json_schema=SCENE_SCHEMA)).text
        data = json_value(answer)
        visual = plain(scene_text(data.get("visual_prompt")) if isinstance(data, dict) else "")
        missing_descriptors += sum(bool(e["descriptor"]) and plain(e["descriptor"]) not in visual for e in present)
        calls += 1
    return {"theme": theme, "pipeline": "new", "valid": True, "beats": len(story["beats"]), "elements": len(story["elements"]),
            "orphan_props": sum("accessoire" in p for p in problems),
            "unknown_ids": sum("absent de la liste" in p for p in problems), "story_problems": problems,
            "script_problems": script_problems(story["beats"], target, "beat", "le dernier beat"),
            "descriptors_missing_before_server": missing_descriptors, "llm_calls": calls,
            "seconds": round(time.monotonic() - started)}


def plain(text: str) -> str:
    return " ".join("".join(c if c.isalnum() else " " for c in text.lower()).split())


async def evaluate(llm: GeminiLLM, project: Project, angle: str) -> dict:
    theme, target = project.theme, project.target_duration_s
    prompt = script_prompt(project, angle)
    try:
        answer = (await llm.complete(SCRIPT_SYSTEM, prompt, max_tokens=script_max_tokens(target),
                                     json_schema=SCENES_SCHEMA)).text
        scenes = parse_scenes(answer, target)
    except ProviderError as e:
        return {"theme": theme, "pipeline": "old", "valid": False, "error": str(e)}
    references = parse_references(answer)
    raw = [s["visual_prompt"] for s in scenes]
    apply_descriptors(scenes, references)
    return {
        "theme": theme, "pipeline": "old", "valid": True, "scenes": len(scenes), "problems": script_problems(scenes, target),
        "refs": len(references), "descriptors_added": sum(a != b["visual_prompt"] for a, b in zip(raw, scenes, strict=True)),
        "motion_paragraph": sum("\nMotion:" in p for p in raw), "words_visual": [len(p.split()) for p in raw],
    }


async def main(model: str, pipeline: str) -> None:
    async with httpx.AsyncClient(timeout=120) as client:
        llm = GeminiLLM(os.environ["GEMINI_API_KEY"], client, model)
        for theme, target, style in THEMES:
            project = Project(title=theme, theme=theme, target_duration_s=target, style=style)
            angle = await make_angle(llm, project)  # le même angle pour les deux pipelines
            if pipeline in ("old", "both"):
                print(json.dumps(await evaluate(llm, project, angle), ensure_ascii=False))
            if pipeline in ("new", "both"):
                print(json.dumps(await evaluate_new(llm, project, angle), ensure_ascii=False))


if __name__ == "__main__":
    args = sys.argv[1:]
    mode = args[args.index("--pipeline") + 1] if "--pipeline" in args else "both"
    names = [a for a in args if not a.startswith("--") and a != mode]
    asyncio.run(main(names[0] if names else DEFAULT_MODEL, mode))
