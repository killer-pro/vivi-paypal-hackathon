import asyncio
import json

import pytest
from sqlalchemy import func, select

from app.app_settings import AppSettings
from app.config import settings
from app.models import Asset, MusicTrack, Project, ProviderCall, Scene, Step
from app.providers.base import GenerationResult, ProviderError, TextResult
from app.providers.fakes import FakeVideo
from app.services.pipeline import (
    CLIP_CONCURRENCY,
    ENGAGEMENT_FALLBACK,
    SCENE_SCHEMA,
    SCENES_SCHEMA,
    VISUAL_PROMPT_GUIDE,
    VOICE_CONCURRENCY,
    apply_descriptors,
    has_engagement,
    parse_references,
    parse_scenes,
    reference_suffix,
    run_step,
    script_max_tokens,
)
from app.services.story import INVENTORY_SCHEMA, STORY_SCHEMA
from app.state import STEP_NAMES
from tests.conftest import ensure_admin


class ScriptedLLM:
    name = "scripted-llm"

    def __init__(self, *texts):
        self.texts = list(texts)  # réponses successives ; la dernière se répète
        self.prompts = []
        self.schemas = []

    async def complete(self, system, prompt, *, max_tokens=4000, json_schema=None):
        self.prompts.append(prompt)
        self.schemas.append(json_schema)
        text = self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]
        return TextResult(text, 0.001, "scripted")


CTA = "Like, commente et partage !"


async def seed(session):
    p = Project(title="t", theme="chats", user_id=(await ensure_admin(session)).id)
    session.add(p)
    await session.flush()
    for n in STEP_NAMES:
        session.add(Step(project_id=p.id, name=n, status="running" if n == "script" else "pending"))
    await session.commit()
    return p


async def get_step(session, project_id, name):
    return await session.scalar(select(Step).where(Step.project_id == project_id, Step.name == name))


async def set_running(session, name, **values):
    await session.execute(Step.__table__.update().where(Step.name == name).values(status="running", **values))
    await session.commit()


def use_llm(ctx, *texts):
    llm = texts[0] if len(texts) == 1 and not isinstance(texts[0], str) else ScriptedLLM(*texts)

    async def factory():
        return llm

    ctx.registry.llm = factory
    return llm


def test_parse_scenes_tolerates_fences_and_text():
    raw = 'Voici :\n```json\n{"scenes":[{"voice_text":"a","visual_prompt":"b","duration_s":3}]}\n```'
    assert parse_scenes(raw)[0]["voice_text"] == "a"


@pytest.mark.parametrize("raw", ["pas du json", '{"scenes":[]}', '{"scenes":[{"voice_text":"","visual_prompt":"b","duration_s":3}]}',
                                 '{"scenes":["texte"]}', '{"scenes": "nope"}'])
def test_parse_scenes_rejects_invalid(raw):
    with pytest.raises(ProviderError):
        parse_scenes(raw)


async def test_idea_step_stores_angle(session, ctx):
    p = await seed(session)
    await set_running(session, "idea")
    llm = use_llm(ctx, "Un chat qui parle aux plantes")
    await run_step(ctx, p.id, "idea")
    step = await get_step(session, p.id, "idea")
    assert step.status == "awaiting_validation" and step.result == {"angle": "Un chat qui parle aux plantes"}
    assert "scènes" not in llm.prompts[0] and "chats" in llm.prompts[0]
    assert "une seule proposition" in llm.prompts[0] and "2 à 4 phrases" in llm.prompts[0]
    assert "sans introduction" in llm.prompts[0] and "sans markdown" in llm.prompts[0]


async def test_script_step_creates_scenes_and_awaits_validation(session, ctx):
    p = await seed(session)
    await run_step(ctx, p.id, "script")
    step = await session.scalar(select(Step).where(Step.project_id == p.id, Step.name == "script"))
    assert step.status == "awaiting_validation"
    assert len((await session.scalars(select(Scene).where(Scene.project_id == p.id))).all()) == 2
    assert ctx.events and ctx.events[-1]["status"] == "awaiting_validation"


async def test_script_replaces_scenes_but_keeps_assets(session, ctx):
    p = await seed(session)
    old = Scene(project_id=p.id, position=1, voice_text="old", visual_prompt="old", duration_s=3)
    session.add(old)
    await session.flush()
    session.add(Asset(project_id=p.id, scene_id=old.id, kind="clip", key="k", content_type="video/mp4"))
    await session.commit()
    await run_step(ctx, p.id, "script")
    scenes = (await session.scalars(select(Scene).where(Scene.project_id == p.id).order_by(Scene.position))).all()
    assert [s.position for s in scenes] == [1, 2] and "old" not in [s.voice_text for s in scenes]
    assert len((await session.scalars(select(Asset))).all()) == 1


async def test_script_invalid_json_fails_readably_and_keeps_scenes(session, ctx):
    p = await seed(session)
    session.add(Scene(project_id=p.id, position=1, voice_text="old", visual_prompt="old", duration_s=3))
    await session.commit()
    use_llm(ctx, "Désolé, je ne peux pas.")
    await run_step(ctx, p.id, "script")
    step = await get_step(session, p.id, "script")
    assert step.status == "failed" and "script" in step.error and "JSON" in step.error
    assert len((await session.scalars(select(Scene))).all()) == 1


async def test_reference_step_creates_asset(session, ctx):
    p = await seed(session)
    await set_running(session, "reference")
    await run_step(ctx, p.id, "reference")
    ref = await session.scalar(select(Asset).where(Asset.kind == "reference"))
    assert ref.key.startswith(f"projects/{p.id}/reference/") and ref.key.endswith(".png")
    assert ctx.storage.files[ref.key]


ELEMENTS = [{"id": "kroc", "prompt": "Ray Kroc, 55, gray hair"}, {"id": "fries", "prompt": "red McDonald's fries box"}]


async def set_script_result(session, project_id, **result):
    await session.execute(Step.__table__.update().where(Step.project_id == project_id, Step.name == "script")
                          .values(result=result))
    await session.commit()


async def test_script_saves_elements_and_keeps_only_known_scene_references(session, ctx):
    p = await seed(session)
    answer = json.dumps({"bible": "b", "references": ELEMENTS, "scenes": [
        {"voice_text": "a", "visual_prompt": "p", "duration_s": 3, "reference": "kroc"},
        {"voice_text": "b", "visual_prompt": "q", "duration_s": 3, "reference": "ghost"},
        {"voice_text": "c", "visual_prompt": "r", "duration_s": 3}]})
    use_llm(ctx, answer)
    await run_step(ctx, p.id, "script")
    scenes = (await session.scalars(select(Scene).order_by(Scene.position))).all()
    assert [s.reference for s in scenes] == ["kroc", "", ""]
    assert (await get_step(session, p.id, "script")).result["references"] == ELEMENTS


async def test_reference_step_makes_one_image_per_element_with_its_prompt(session, ctx):
    p = await seed(session)
    await set_script_result(session, p.id, references=ELEMENTS)
    await set_running(session, "reference", params={"prompts": {"fries": "edited fries prompt"}})
    prompts = []

    class RecordingImage:
        name = "fake-image"

        async def generate(self, prompt, *, model):
            prompts.append(prompt)
            return GenerationResult(b"png", "image/png", 0.01, model)

    async def image(name):
        return RecordingImage()

    ctx.registry.image = image
    await run_step(ctx, p.id, "reference")
    assert [a.meta["ref"] for a in (await session.scalars(select(Asset).order_by(Asset.id))).all()] == ["kroc", "fries"]
    assert prompts[0].startswith("Ray Kroc, 55, gray hair") and prompts[1].startswith("edited fries prompt")
    await set_running(session, "reference")
    prompts.clear()
    ctx.overrides["reference_id"] = "fries"
    await run_step(ctx, p.id, "reference")
    assert len(prompts) == 1 and prompts[0].startswith("edited fries prompt")
    ctx.overrides["reference_id"] = "ghost"
    await set_running(session, "reference")
    await run_step(ctx, p.id, "reference")
    assert "ghost" in (await get_step(session, p.id, "reference")).error


async def test_each_clip_starts_from_its_scene_reference_or_the_project_image(session, ctx):
    p = await seed(session)
    await set_running(session, "clips")
    for position, ref in enumerate(["kroc", "fries", "kroc", ""], 1):
        session.add(Scene(project_id=p.id, position=position, voice_text="a", visual_prompt=f"v{position}", duration_s=3,
                          reference=ref))
    for ref, data in (("kroc", b"KROC"), ("fries", b"FRIES"), ("", b"GLOBAL")):
        key = f"projects/{p.id}/reference/{ref or 'all'}.png"
        ctx.storage.files[key] = data
        session.add(Asset(project_id=p.id, kind="reference", key=key, content_type="image/png",
                          meta={"ref": ref} if ref else {}))
    await session.commit()
    used = {}

    class RecordingVideo(FakeVideo):
        async def generate(self, prompt, *, model, duration_s, image=None):
            used[prompt] = image
            return await super().generate(prompt, model=model, duration_s=duration_s, image=image)

    async def video(name):
        return RecordingVideo()

    ctx.registry.video = video
    await run_step(ctx, p.id, "clips")
    assert used == {"v1": b"KROC", "v2": b"FRIES", "v3": b"KROC", "v4": b"GLOBAL"}


async def test_reference_with_gemini_stores_the_image_and_logs_its_cost(session, ctx):
    """Défaut `image_provider = gemini` : image JPEG enregistrée, appel journalisé (coût par tokens) dans provider_calls."""
    import base64

    import httpx

    from app.providers.gemini import DEFAULT_IMAGE_MODEL, GeminiImage

    body = {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/jpeg",
                                                                   "data": base64.b64encode(b"JPEG").decode()}}]}}],
            "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 1000}}
    gemini = GeminiImage("k", httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))))
    asked = []

    async def image(name):
        asked.append(name)
        return gemini

    ctx.registry.image = image
    p = await seed(session)
    await set_running(session, "reference")
    await run_step(ctx, p.id, "reference")
    ref = await session.scalar(select(Asset).where(Asset.kind == "reference"))
    assert asked == ["gemini"] and ref.key.endswith(".jpg") and ref.content_type == "image/jpeg"
    assert ctx.storage.files[ref.key] == b"JPEG"
    call = await session.scalar(select(ProviderCall).where(ProviderCall.step == "reference"))
    assert (call.provider, call.model, call.status) == ("gemini", DEFAULT_IMAGE_MODEL, "ok")
    assert call.cost_usd == pytest.approx((20 * 0.50 + 1000 * 60.00) / 1_000_000)


async def test_failed_step_records_readable_error_and_no_asset(session, ctx):
    p = await seed(session)
    await session.execute(Step.__table__.update().where(Step.name == "clips").values(status="running"))
    session.add(Scene(project_id=p.id, position=1, voice_text="a", visual_prompt="b", duration_s=3))
    await session.commit()

    async def failing_video(name):
        return FakeVideo(fail_with=ProviderError("quota dépassé"))

    ctx.registry.video = failing_video
    await run_step(ctx, p.id, "clips")
    step = await session.scalar(select(Step).where(Step.project_id == p.id, Step.name == "clips"))
    assert step.status == "failed" and "quota dépassé" in step.error
    assert (await session.scalars(select(Asset))).all() == []
    assert ctx.events[-1] == {"project_id": p.id, "step": "clips", "status": "failed", "error": step.error}


async def test_empty_provider_result_fails_without_asset_or_cost(session, ctx):
    p = await seed(session)
    await set_running(session, "clips")
    session.add(Scene(project_id=p.id, position=1, voice_text="a", visual_prompt="b", duration_s=3))
    await session.commit()

    class EmptyVideo(FakeVideo):
        async def generate(self, prompt, *, model, duration_s, image=None):
            return GenerationResult(b"", "video/mp4", 0.5, model)

    async def empty_video(name):
        return EmptyVideo()

    ctx.registry.video = empty_video
    await run_step(ctx, p.id, "clips")
    step = await get_step(session, p.id, "clips")
    assert step.status == "failed" and "vide" in step.error
    assert (await session.scalars(select(Asset))).all() == []
    assert sum(c.cost_usd for c in (await session.scalars(select(ProviderCall))).all()) == 0


async def test_unexpected_exception_marks_step_failed(session, ctx):
    p = await seed(session)
    await set_running(session, "clips")
    session.add(Scene(project_id=p.id, position=1, voice_text="a", visual_prompt="b", duration_s=3))
    await session.commit()

    async def broken_video(name):
        raise KeyError(name)

    ctx.registry.video = broken_video
    await run_step(ctx, p.id, "clips")
    step = await get_step(session, p.id, "clips")
    assert step.status == "failed" and step.error.startswith("KeyError")


async def test_clips_without_scenes_fails(session, ctx):
    p = await seed(session)
    await set_running(session, "clips")
    await run_step(ctx, p.id, "clips")
    step = await get_step(session, p.id, "clips")
    assert step.status == "failed" and "aucune scène" in step.error


async def test_clips_new_variant_each_run(session, ctx):
    p = await seed(session)
    s = Scene(project_id=p.id, position=1, voice_text="a", visual_prompt="b", duration_s=3)
    session.add(s)
    await session.commit()
    for _ in range(2):
        await session.execute(Step.__table__.update().where(Step.name == "clips").values(status="running"))
        await session.commit()
        await run_step(ctx, p.id, "clips")
    variants = sorted(a.variant for a in (await session.scalars(select(Asset).where(Asset.kind == "clip"))).all())
    assert variants == [1, 2]


async def test_clips_auto_select_first_variant_and_never_override_choice(session, ctx):
    p = await seed(session)
    s = Scene(project_id=p.id, position=1, voice_text="a", visual_prompt="b", duration_s=3)
    kept = Scene(project_id=p.id, position=2, voice_text="c", visual_prompt="d", duration_s=3, selected_clip_asset_id=999)
    session.add_all([s, kept])
    await session.commit()
    for _ in range(2):
        await session.execute(Step.__table__.update().where(Step.name == "clips").values(status="running"))
        await session.commit()
        await run_step(ctx, p.id, "clips")
    await session.refresh(s)
    await session.refresh(kept)
    first = await session.scalar(select(Asset).where(Asset.scene_id == s.id, Asset.variant == 1))
    assert s.selected_clip_asset_id == first.id  # la régénération ne remplace pas la sélection
    assert kept.selected_clip_asset_id == 999


async def test_clips_single_scene_uses_step_params(session, ctx):
    p = await seed(session)
    s1 = Scene(project_id=p.id, position=1, voice_text="a", visual_prompt="b", duration_s=3)
    s2 = Scene(project_id=p.id, position=2, voice_text="c", visual_prompt="d", duration_s=3)
    session.add_all([s1, s2])
    await set_running(session, "clips", params={"provider": "comfyui", "model": "wan"})
    asked = []

    async def video(name):
        asked.append(name)
        return FakeVideo()

    ctx.registry.video = video
    await run_step(ctx, p.id, "clips", scene_id=s2.id)
    clips = (await session.scalars(select(Asset).where(Asset.kind == "clip"))).all()
    assert [c.scene_id for c in clips] == [s2.id] and asked == ["comfyui"]
    call = await session.scalar(select(ProviderCall))
    assert call.model == "wan"


async def test_voice_without_voice_id_fails(session, ctx, monkeypatch):
    monkeypatch.setattr(settings, "fake_providers", False)  # le mode factice a une voix par défaut
    p = await seed(session)
    await set_running(session, "voice")
    session.add(Scene(project_id=p.id, position=1, voice_text="a", visual_prompt="b", duration_s=3))
    await session.commit()
    await run_step(ctx, p.id, "voice")
    step = await get_step(session, p.id, "voice")
    assert step.status == "failed" and "aucune voix" in step.error


@pytest.mark.parametrize("voice_id", ["../v1/user", "a/b", "v.1", "x" * 65])
async def test_voice_rejects_unsafe_voice_id_before_any_call(session, ctx, voice_id):
    p = await seed(session)
    await set_running(session, "voice", params={"voice_id": voice_id})
    session.add(Scene(project_id=p.id, position=1, voice_text="a", visual_prompt="b", duration_s=3))
    await session.commit()
    await run_step(ctx, p.id, "voice")
    step = await get_step(session, p.id, "voice")
    assert step.status == "failed" and "identifiant de voix invalide" in step.error
    assert await session.scalar(select(func.count()).select_from(ProviderCall)) == 0


async def test_music_validates_track(session, ctx):
    p = await seed(session)
    await set_running(session, "music", params={"track_id": 999})
    await run_step(ctx, p.id, "music")
    step = await get_step(session, p.id, "music")
    assert step.status == "failed" and "introuvable" in step.error
    track = MusicTrack(name="beat", key="music/beat.mp3")
    session.add(track)
    await session.flush()
    await set_running(session, "music", params={"track_id": track.id})
    await run_step(ctx, p.id, "music")
    step = await get_step(session, p.id, "music")
    assert step.status == "awaiting_validation" and step.result == {"track_id": track.id}


async def run_clips_and_voice(session, ctx, p):
    await ctx.app_settings.set("default_voice_id", "voix-test")
    for name in ("clips", "voice"):
        await set_running(session, name)
        await run_step(ctx, p.id, name)
        assert (await get_step(session, p.id, name)).status == "awaiting_validation"


async def test_montage_end_to_end_with_fakes(session, ctx):
    p = await seed(session)
    s = Scene(project_id=p.id, position=1, voice_text="Bonjour tout le monde", visual_prompt="b", duration_s=3)
    session.add(s)
    await session.commit()
    await run_clips_and_voice(session, ctx, p)
    await session.refresh(s)
    assert s.selected_clip_asset_id is not None  # sélection automatique du clip généré
    ctx.storage.files["music/beat.mp3"] = ctx.storage.files[
        (await session.scalar(select(Asset).where(Asset.kind == "voice"))).key]
    track = MusicTrack(name="beat", key="music/beat.mp3")
    session.add(track)
    await session.flush()
    await set_running(session, "music", params={"track_id": track.id})
    await run_step(ctx, p.id, "music")
    await set_running(session, "montage")
    await run_step(ctx, p.id, "montage")
    step = await get_step(session, p.id, "montage")
    assert step.status == "awaiting_validation", step.error
    render = await session.scalar(select(Asset).where(Asset.kind == "render"))
    assert render is not None and len(ctx.storage.files[render.key]) > 0
    assert step.result["asset_id"] == render.id and step.result["duration_s"] > 0


async def test_montage_fails_when_scene_has_no_selected_clip(session, ctx):
    p = await seed(session)
    session.add(Scene(project_id=p.id, position=1, voice_text="Bonjour", visual_prompt="b", duration_s=3))
    await session.commit()
    await run_clips_and_voice(session, ctx, p)
    (await session.scalar(select(Scene).where(Scene.project_id == p.id))).selected_clip_asset_id = None
    await session.commit()
    await set_running(session, "montage")
    await run_step(ctx, p.id, "montage")
    step = await get_step(session, p.id, "montage")
    assert step.status == "failed" and "clip" in step.error
    assert (await session.scalars(select(Asset).where(Asset.kind == "render"))).all() == []


async def test_final_parses_fenced_json_with_defaults(session, ctx):
    p = await seed(session)
    await set_running(session, "final")
    llm = use_llm(ctx, 'Voilà :\n```json\n{"title": "Chat star", "hashtags": ["#chat", "#viral"]}\n```')
    await run_step(ctx, p.id, "final")
    step = await get_step(session, p.id, "final")
    await session.refresh(p)
    expected = {"title": "Chat star", "description": "", "hashtags": ["#chat", "#viral"]}
    assert step.status == "awaiting_validation" and p.metadata_json == expected and step.result == expected
    assert "scènes" not in llm.prompts[0]


async def test_final_keeps_autopilot_flag(session, ctx):
    p = await seed(session)
    p.autopilot = True
    await set_running(session, "final")
    use_llm(ctx, '{"title": "T", "description": "D", "hashtags": []}')
    await run_step(ctx, p.id, "final")
    await session.refresh(p)
    assert p.autopilot is True and p.metadata_json["title"] == "T"
    assert "autopilot" not in (await get_step(session, p.id, "final")).result


async def test_final_without_json_fails_readably(session, ctx):
    p = await seed(session)
    await set_running(session, "final")
    use_llm(ctx, "ok")
    await run_step(ctx, p.id, "final")
    step = await get_step(session, p.id, "final")
    assert step.status == "failed" and "final" in step.error and "JSON" in step.error


async def test_final_with_fake_llm_produces_metadata(session, ctx):
    """En mode FAKE_PROVIDERS, le flow complet doit pouvoir aller jusqu'au rendu final."""
    p = await seed(session)
    await set_running(session, "final")
    await run_step(ctx, p.id, "final")
    step = await get_step(session, p.id, "final")
    assert step.status == "awaiting_validation" and step.result["title"] and step.result["hashtags"]


async def test_db_error_is_rolled_back_and_failure_recorded(session, ctx, monkeypatch):
    from app.services import pipeline

    async def broken(ctx, project, step, scene_id):
        ctx.session.add(Scene(project_id=project.id + 999, position=1))  # FK invalide
        await ctx.session.flush()

    monkeypatch.setitem(pipeline.EXECUTORS, "music", broken)
    pid = (await seed(session)).id  # le rollback expire les objets de la session
    await set_running(session, "music")
    await run_step(ctx, pid, "music")
    step = await get_step(session, pid, "music")
    assert step.status == "failed" and step.error.startswith("IntegrityError")


async def test_clips_run_overrides_win_over_step_params_without_saving_them(session, ctx):
    p = await seed(session)
    session.add(Scene(project_id=p.id, position=1, voice_text="a", visual_prompt="b", duration_s=3))
    await set_running(session, "clips", params={"provider": "fal", "model": "kling"})
    asked = []

    async def video(name):
        asked.append(name)
        return FakeVideo()

    ctx.registry.video = video
    ctx.overrides = {"provider": "comfyui", "model": "wan"}
    await run_step(ctx, p.id, "clips")
    clip = await session.scalar(select(Asset).where(Asset.kind == "clip"))
    step = await get_step(session, p.id, "clips")
    assert asked == ["comfyui"] and clip.meta["model"] == "wan"
    assert step.params == {"provider": "fal", "model": "kling"}


def test_local_comfyui_clips_get_a_longer_timeout_than_cloud_ones():
    from app.providers.comfyui import CLIP_TIMEOUT_S, MAX_POLLS
    from app.services.pipeline import STEP_TIMEOUTS, job_timeout, step_timeout

    assert step_timeout("clips", "comfyui") == CLIP_TIMEOUT_S > STEP_TIMEOUTS["clips"] == step_timeout("clips", "fal")
    assert step_timeout("voice", "comfyui") == step_timeout("voice")  # seule l'étape clips dépend du provider
    assert MAX_POLLS * 2.0 >= CLIP_TIMEOUT_S  # le polling (2 s) ne coupe pas avant le timeout de l'appel
    # Wan 2.2 14B (workflow par défaut), 5 s : 2510 s mesurées sur M4 Max + ~250 s d'upscale ; marge d'au moins x2.
    assert CLIP_TIMEOUT_S >= 2 * (2510 + 250)
    assert job_timeout("clips", 1, "comfyui") > job_timeout("clips", 1) and job_timeout("clips", 1, "comfyui") > CLIP_TIMEOUT_S


def test_local_clips_of_a_long_video_are_not_cut_by_the_job_cap():
    from app.services.pipeline import job_timeout

    # Projet de 17 scènes mesuré : plus de 6 h de clips ComfyUI séquentiels (un GPU, une scène à la fois).
    assert job_timeout("clips", 17, "comfyui") > 12 * 3600


async def test_clips_call_timeout_follows_resolved_provider(session, ctx, monkeypatch):
    from app.providers.comfyui import CLIP_TIMEOUT_S
    from app.services import pipeline

    p = await seed(session)
    session.add(Scene(project_id=p.id, position=1, voice_text="a", visual_prompt="b", duration_s=3))
    await AppSettings(session).set("default_video_provider", "comfyui")
    await set_running(session, "clips")
    timeouts = []
    real = pipeline.tracked_call

    async def spy(*args, **kwargs):
        timeouts.append(kwargs["timeout"])
        return await real(*args, **kwargs)

    monkeypatch.setattr(pipeline, "tracked_call", spy)
    await run_step(ctx, p.id, "clips")
    assert timeouts == [CLIP_TIMEOUT_S]


def test_job_timeout_covers_every_scene_call_with_retries_and_is_bounded():
    from app.services.costs import DEFAULT_ATTEMPTS
    from app.services.pipeline import MAX_JOB_TIMEOUT, STEP_TIMEOUTS, job_timeout

    assert job_timeout("clips", 3) >= 3 * DEFAULT_ATTEMPTS * STEP_TIMEOUTS["clips"]
    assert job_timeout("voice", 4) > job_timeout("voice", 1)
    assert job_timeout("idea", 10) == job_timeout("idea", 1)  # un seul appel, quel que soit le nombre de scènes
    assert job_timeout("clips", 500) == MAX_JOB_TIMEOUT


# --- Script : sortie structurée, parse tolérant, relance ciblée (bug « scène incomplète » avec Gemini) ---

LONG_MARKDOWN_ANGLE = (
    "## Angle : « Le chat qui juge tes plantes »\n\n**Accroche** : un chat inspecte chaque plante...\n\n"
    "### Structure\n1. **Hook (0-3 s)** : gros plan, regard noir\n2. **Développement** :\n   - *plante 1* : trop d'eau\n"
    "   - *plante 2* : pas assez de lumière\n3. **Chute** : il renverse le cactus\n\n> Ton : sarcastique, rythmé\n"
) * 3


@pytest.mark.parametrize("raw", [
    '{"scenes":[{"voice_text":"a","visual_prompt":"b","duration_s":"4s"}]}',
    '{"scenes":[{"voice_text":"a","visual_prompt":"b","duration_s":"4,0 secondes"}]}',
    '{"scenes":[{"voice_text":"a","visual_prompt":"b","duration":4}]}',
    '{"scenes":[{"scene":1,"title":"Hook","voice_text":"a","visual_prompt":"b","duration_s":4,"music":"x"}]}',
    '[{"voice_text":"a","visual_prompt":"b","duration_s":4}]',
    '```json\n{"scenes":[{"voiceover":"a","visual":"b","duration_s":4}]}\n```',
    '{"scenes":[{"voice_text":["a"],"visual_prompt":"b","duration_s":4}]}',
])
def test_parse_scenes_tolerates_plausible_llm_shapes(raw):
    assert parse_scenes(raw) == [{"voice_text": "a", "visual_prompt": "b", "duration_s": 4.0, "reference": ""}]


def test_parse_references_normalizes_ids_and_drops_incomplete_or_duplicate_entries():
    raw = json.dumps({"references": [
        {"id": "Ray Kroc", "prompt": "a man"}, {"id": "ray_kroc", "prompt": "duplicate"}, {"id": "x", "prompt": ""},
        {"id": "", "prompt": "nameless"}, "junk", {"id": "coca-can", "prompt": "a can"}]})
    assert parse_references(raw) == [{"id": "ray_kroc", "prompt": "a man"}, {"id": "coca-can", "prompt": "a can"}]
    assert parse_references('{"scenes": []}') == [] and parse_references("[]") == []
    assert parse_scenes('{"scenes":[{"voice_text":"a","visual_prompt":"b","duration_s":3,"reference":"Ray Kroc"}]}'
                        )[0]["reference"] == "ray_kroc"


def test_parse_scenes_missing_duration_shares_the_remaining_target():
    raw = ('{"scenes":[{"voice_text":"a","visual_prompt":"b","duration_s":6},{"voice_text":"c","visual_prompt":"d"},'
           '{"voice_text":"e","visual_prompt":"f","duration_s":"?"}]}')
    assert [s["duration_s"] for s in parse_scenes(raw, target_duration_s=20)] == [6.0, 7.0, 7.0]
    assert [s["duration_s"] for s in parse_scenes(raw)][1:] == [4.0, 4.0]  # sans cible : durée par défaut


def test_parse_scenes_error_names_the_scene_and_fields():
    raw = ('{"scenes":[{"voice_text":"a","visual_prompt":"b","duration_s":3},'
           '{"voice_text":"  ","visual_prompt":"","duration_s":3}]}')
    with pytest.raises(ProviderError, match=r"scène 2 incomplète.*voice_text.*visual_prompt"):
        parse_scenes(raw)


async def test_script_prompt_follows_target_duration_and_asks_structured_json(session, ctx):
    p = await seed(session)
    p.target_duration_s = 30
    await session.commit()
    llm = use_llm(ctx, '{"scenes":[{"voice_text":"a","visual_prompt":"b","duration_s":30}]}')
    await run_step(ctx, p.id, "script")
    prompt = llm.prompts[0]
    assert "30 secondes" in prompt and "75 mots" in prompt and "2,5 mots par seconde" in prompt
    # style de prompt Wan 2.2 mesuré (Tâche 20A) : long, sujet + action d'abord, mouvement de caméra explicite
    assert VISUAL_PROMPT_GUIDE in prompt and "Motion:" in VISUAL_PROMPT_GUIDE
    assert "dolly" in VISUAL_PROMPT_GUIDE and "tracking shot" in VISUAL_PROMPT_GUIDE
    assert llm.schemas[0]["properties"]["scenes"]["type"] == "ARRAY"


def test_visual_prompt_guide_has_no_contradiction_or_style_of_its_own():
    assert "2 ou 3 gestes enchaînés" in VISUAL_PROMPT_GUIDE and "une seule action continue" not in VISUAL_PROMPT_GUIDE
    assert "photorealistic" not in VISUAL_PROMPT_GUIDE and "cinematic" not in VISUAL_PROMPT_GUIDE  # le style vient du projet
    assert "aucune négation" in VISUAL_PROMPT_GUIDE and "Spencerian" not in VISUAL_PROMPT_GUIDE


@pytest.mark.parametrize("style,look", [("anime", "Japanese anime style"), ("", "cinematic")])
def test_reference_suffix_follows_project_style(style, look):
    assert look in reference_suffix(Project(title="t", theme="t", style=style))


async def test_script_prompt_scene_length_param_sets_scene_count(session, ctx):
    p = await seed(session)
    p.target_duration_s = 30
    await session.commit()
    llm = use_llm(ctx, '{"scenes":[{"voice_text":"a","visual_prompt":"b","duration_s":30}]}')
    await set_running(session, "script", params={"scene_length_s": 5})
    await run_step(ctx, p.id, "script")
    assert "6 scènes d'environ 5 secondes chacune" in llm.prompts[0]
    assert "de 2 à 6 secondes" not in llm.prompts[0]


async def test_script_retries_once_with_validation_error_then_succeeds(session, ctx):
    p = await seed(session)
    bad = f'{{"scenes":[{{"voice_text":"a","visual_prompt":"b","duration_s":15}},{{"voice_text":"{CTA}","duration_s":15}}]}}'
    good = ('{"scenes":[{"voice_text":"a","visual_prompt":"b","duration_s":15},'
            f'{{"voice_text":"{CTA}","visual_prompt":"d","duration_s":15}}]}}')
    llm = use_llm(ctx, bad, good)
    await run_step(ctx, p.id, "script")
    step = await get_step(session, p.id, "script")
    assert step.status == "awaiting_validation" and step.result == {"scene_count": 2}
    assert len(llm.prompts) == 2 and "scène 2 incomplète" in llm.prompts[1] and "visual_prompt" in llm.prompts[1]
    calls = (await session.scalars(select(ProviderCall).where(ProviderCall.step == "script"))).all()
    assert len(calls) == 2 and all(c.project_id == p.id for c in calls)  # la relance est facturée et tracée


async def test_script_fails_after_one_retry_with_precise_error(session, ctx):
    p = await seed(session)
    llm = use_llm(ctx, '{"scenes":[{"voice_text":"a","visual_prompt":"","duration_s":3}]}')
    await run_step(ctx, p.id, "script")
    step = await get_step(session, p.id, "script")
    assert len(llm.prompts) == 2
    assert step.status == "failed" and "scène 1 incomplète" in step.error and "visual_prompt" in step.error


async def test_script_with_long_markdown_angle_and_gemini_shapes(session, ctx):
    """Reproduction : angle markdown long + réponse Gemini plausible (bloc ```json, durée « 4 s », champs en trop)."""
    import json as _json

    import httpx

    from app.providers.gemini import GeminiLLM

    p = await seed(session)
    idea = await get_step(session, p.id, "idea")
    idea.result = {"angle": LONG_MARKDOWN_ANGLE}
    await session.commit()
    sent = []
    answer = ('```json\n{"scenes": [{"scene_number": 1, "title": "**Hook**", "voice_text": "Ton chat te juge.", '
              '"visual_prompt": "close-up of a cat staring", "duration_s": "4 s"}, {"scene_number": 2, '
              '"voice_text": "Et il a raison, like, commente et partage !", "visual_prompt": "cat pushes a cactus", "duration": 3.5}]}\n```')

    def handler(req):
        sent.append(_json.loads(req.content))
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": answer}]},
                                                         "finishReason": "STOP"}],
                                         "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}})

    use_llm(ctx, GeminiLLM("k", httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    await run_step(ctx, p.id, "script")
    step = await get_step(session, p.id, "script")
    assert step.status == "awaiting_validation", step.error
    scenes = (await session.scalars(select(Scene).where(Scene.project_id == p.id).order_by(Scene.position))).all()
    assert [(s.voice_text, s.duration_s) for s in scenes] == [("Ton chat te juge.", 4.0), ("Et il a raison, like, commente et partage !", 3.5)]
    config = sent[0]["generationConfig"]
    assert config["responseMimeType"] == "application/json" and "scenes" in config["responseSchema"]["properties"]
    assert "Le chat qui juge tes plantes" in sent[0]["contents"][0]["parts"][0]["text"]


async def test_final_asks_structured_json(session, ctx):
    p = await seed(session)
    await set_running(session, "final")
    llm = use_llm(ctx, '{"title": "t", "description": "d", "hashtags": ["#a"]}')
    await run_step(ctx, p.id, "final")
    assert set(llm.schemas[0]["properties"]) == {"title", "description", "hashtags"}


def test_parse_scenes_never_yields_tiny_or_absurd_durations():
    raw = ('{"scenes":[{"voice_text":"a","visual_prompt":"b","duration_s":9},{"voice_text":"c","visual_prompt":"d"},'
           '{"voice_text":"e","visual_prompt":"f","duration_s":"00:04"},{"voice_text":"g","visual_prompt":"h",'
           '"duration_s":"4000 ms"},{"voice_text":"i","visual_prompt":"j","duration_s":500}]}')
    durations = [s["duration_s"] for s in parse_scenes(raw, target_duration_s=10)]
    # « 00:04 », « 4000 ms », 500 s rejetées ; le reste de la cible (1 s pour 4 scènes) ne descend pas sous 2 s
    assert durations == [9.0, 2.0, 2.0, 2.0, 2.0]


async def test_llm_without_json_schema_parameter_still_works_for_text_steps(session, ctx):
    class OldLLM:
        name = "old-llm"

        async def complete(self, system, prompt, *, max_tokens=4000):
            return TextResult("Un angle", 0.001, "old")

    p = await seed(session)
    await set_running(session, "idea")
    use_llm(ctx, OldLLM())
    await run_step(ctx, p.id, "idea")
    assert (await get_step(session, p.id, "idea")).result == {"angle": "Un angle"}


def test_script_job_timeout_covers_the_retry_call():
    from app.services.pipeline import job_timeout, step_timeout

    assert job_timeout("script", 0) >= 2 * step_timeout("script") * 3
    assert job_timeout("script", 0) > job_timeout("idea", 0)


class SlowVideo:
    """Fournisseur vidéo qui compte les appels simultanés ; `fail_on` : prompt qui échoue."""
    name = "fal"
    models = ["kling"]

    def __init__(self, fail_on=None, delay=0.05):
        self.running = self.peak = self.started = 0
        self.fail_on, self.delay = fail_on, delay

    def estimate_cost(self, model, duration_s):
        return 0.0

    async def generate(self, prompt, *, model, duration_s, image=None):
        self.running += 1
        self.started += 1
        self.peak = max(self.peak, self.running)
        try:
            await asyncio.sleep(self.delay)
            if prompt == self.fail_on:
                raise ProviderError("fal: génération échouée")
            return GenerationResult(prompt.encode(), "video/mp4", 0.1, "kling")
        finally:
            self.running -= 1

    async def health(self):
        return True


def use_video(ctx, video):
    async def factory(name):
        return video

    ctx.registry.video = factory
    return video


async def seed_scenes(session, count):
    p = await seed(session)
    session.add_all(Scene(project_id=p.id, position=i, voice_text=f"v{i}", visual_prompt=f"p{i}", duration_s=3)
                    for i in range(1, count + 1))
    await session.commit()
    return p


async def test_clips_run_concurrently_up_to_the_provider_limit(session, ctx):
    p = await seed_scenes(session, 7)
    video = use_video(ctx, SlowVideo())
    await set_running(session, "clips", params={"provider": "fal", "model": "kling"})
    await run_step(ctx, p.id, "clips")
    step = await get_step(session, p.id, "clips")
    assert step.status == "awaiting_validation"
    assert video.peak == CLIP_CONCURRENCY["fal"] == 3  # en parallèle, sans dépasser la limite
    scenes = (await session.scalars(select(Scene).where(Scene.project_id == p.id).order_by(Scene.position))).all()
    assets = {a.scene_id: a for a in (await session.scalars(select(Asset).where(Asset.kind == "clip"))).all()}
    # un clip par scène, résultat dans l'ordre des scènes, sélectionné d'office, coût de chaque appel journalisé
    assert step.result["asset_ids"] == [assets[s.id].id for s in scenes]
    assert [s.selected_clip_asset_id for s in scenes] == step.result["asset_ids"]
    assert await session.scalar(select(func.count()).select_from(ProviderCall).where(ProviderCall.status == "ok")) == 7


async def test_local_provider_generates_one_clip_at_a_time(session, ctx):
    p = await seed_scenes(session, 3)
    video = use_video(ctx, SlowVideo())
    await ctx.app_settings.set("default_video_provider", "comfyui")
    await set_running(session, "clips")
    await run_step(ctx, p.id, "clips")
    assert video.peak == 1 and (await get_step(session, p.id, "clips")).status == "awaiting_validation"


async def test_first_failure_stops_the_other_scenes_and_reports_the_original_error(session, ctx):
    p = await seed_scenes(session, 9)
    video = use_video(ctx, SlowVideo(fail_on="p2"))
    await set_running(session, "clips")
    await run_step(ctx, p.id, "clips")
    step = await get_step(session, p.id, "clips")
    assert step.status == "failed" and step.error == "fal: génération échouée"  # pas un « ExceptionGroup »
    assert video.started < 9 and video.running == 0  # scènes suivantes non lancées, appels en cours annulés


async def test_voice_runs_two_at_a_time(session, ctx):
    p = await seed_scenes(session, 5)
    state = {"running": 0, "peak": 0}

    class SlowVoice:
        name = "slow-voice"

        async def synthesize(self, text, *, voice_id):
            state["running"] += 1
            state["peak"] = max(state["peak"], state["running"])
            await asyncio.sleep(0.03)
            state["running"] -= 1
            return GenerationResult(text.encode(), "audio/mpeg", 0.01, "v")

    async def factory():
        return SlowVoice()

    ctx.registry.voice = factory
    await ctx.app_settings.set("default_voice_id", "voix-test")
    await set_running(session, "voice")
    await run_step(ctx, p.id, "voice")
    step = await get_step(session, p.id, "voice")
    assert step.status == "awaiting_validation" and state["peak"] == VOICE_CONCURRENCY == 2
    assert len(step.result["asset_ids"]) == 5


async def montage_ready_project(session, ctx, scenes=3):
    """Projet à `scenes` scènes avec clips et voix factices produits, prêt pour le montage."""
    p = await seed(session)
    session.add_all(Scene(project_id=p.id, position=i, voice_text=f"Scène numéro {i}", visual_prompt="b", duration_s=2)
                    for i in range(1, scenes + 1))
    await session.commit()
    await run_clips_and_voice(session, ctx, p)
    return p


async def run_montage(session, ctx, p):
    await set_running(session, "montage")
    await run_step(ctx, p.id, "montage")
    step = await get_step(session, p.id, "montage")
    assert step.status == "awaiting_validation", step.error
    return step.result


async def test_montage_encodes_each_scene_once_then_reuses_segments(session, ctx):
    p = await montage_ready_project(session, ctx, scenes=3)
    first = await run_montage(session, ctx, p)
    assert (first["segments_rendered"], first["segments_reused"]) == (3, 0)
    assert len([k for k in ctx.storage.files if "/segments/" in k]) == 6  # une vidéo et une voix par scène
    second = await run_montage(session, ctx, p)
    assert (second["segments_rendered"], second["segments_reused"]) == (0, 3)  # rien à ré-encoder
    assert abs(second["duration_s"] - first["duration_s"]) < 0.05  # même vidéo


async def test_montage_after_regenerating_one_scene_encodes_only_that_scene(session, ctx):
    p = await montage_ready_project(session, ctx, scenes=3)
    first = await run_montage(session, ctx, p)
    scenes = (await session.scalars(select(Scene).where(Scene.project_id == p.id).order_by(Scene.position))).all()
    use_video(ctx, FakeVideo())  # nouveau (vrai) clip pour la scène 2 seulement
    await set_running(session, "clips")
    ctx.overrides = {"select_new": True}
    await run_step(ctx, p.id, "clips", scene_id=scenes[1].id)
    ctx.overrides = {}
    second = await run_montage(session, ctx, p)
    assert (second["segments_rendered"], second["segments_reused"]) == (1, 2)
    assert second["asset_id"] != first["asset_id"]  # un nouveau rendu complet est bien produit


async def test_deleting_a_project_removes_its_cached_segments(api, session, ctx):
    pid = await new_project_with_segments(api, session)
    assert any("/segments/" in k for k in api.storage.files)
    assert (await api.delete(f"/api/projects/{pid}")).status_code == 204
    assert not any(k.startswith(f"projects/{pid}/") for k in api.storage.files)


async def new_project_with_segments(api, session):
    from tests.test_api_steps import new_project
    pid = await new_project(api)
    for suffix in ("mp4", "wav"):
        await api.storage.put(f"projects/{pid}/segments/abc-1-2.{suffix}", b"x", "video/mp4")
    await api.storage.put("projects/9999/segments/other.mp4", b"x", "video/mp4")
    return pid


async def test_precision_clip_stores_a_keyframe_asset(session, ctx):
    p = await seed_scenes(session, 1)
    use_video(ctx, FakeVideo(keyframe=b"PNGDATA"))
    await set_running(session, "clips", params={"provider": "comfyui", "model": "precision"})
    await run_step(ctx, p.id, "clips")
    assert (await get_step(session, p.id, "clips")).status == "awaiting_validation"
    clip = await session.scalar(select(Asset).where(Asset.kind == "clip"))
    keyframe = await session.scalar(select(Asset).where(Asset.kind == "keyframe"))
    assert keyframe.scene_id == clip.scene_id and keyframe.meta["clip_asset_id"] == clip.id
    assert keyframe.content_type == "image/png" and ctx.storage.files[keyframe.key] == b"PNGDATA"
    assert keyframe.key.endswith(".png") and keyframe.meta["cost_usd"] == 0


async def test_clip_without_keyframe_stores_no_keyframe_asset(session, ctx):
    p = await seed_scenes(session, 1)
    await set_running(session, "clips")
    await run_step(ctx, p.id, "clips")
    assert await session.scalar(select(func.count()).select_from(Asset).where(Asset.kind == "keyframe")) == 0


def test_visual_guide_contains_composition_rules():
    guide = VISUAL_PROMPT_GUIDE.lower()
    assert "marge" in guide and "remplissant" in guide  # sujet de taille modérée, jamais remplissant le conteneur
    assert "ce qu'on voit" in guide and "dévisser" in guide  # action visible, pas un verbe abstrait
    assert "derrière le verre" in guide and "vue de côté" in guide  # séparation intérieur/extérieur


async def test_script_stores_visual_bible_and_applies_user_instruction(session, ctx):
    p = await seed(session)
    llm = use_llm(ctx, '{"bible":"Anna, 30, red coat. Coca-Cola can: red, white script logo.",'
                       f'"scenes":[{{"voice_text":"{CTA}","visual_prompt":"b","duration_s":30}}]}}')
    ctx.overrides["instruction"] = "plus d'action"
    await run_step(ctx, p.id, "script")
    step = await get_step(session, p.id, "script")
    assert step.result == {"scene_count": 1, "bible": "Anna, 30, red coat. Coca-Cola can: red, white script logo."}
    prompt = llm.prompts[0]
    assert "Consigne de l'utilisateur, à appliquer en priorité : plus d'action" in prompt
    assert "« commente »" in prompt and "logo" in prompt  # dernière scène = engagement ; marques et logos décrits
    assert llm.schemas[0]["properties"]["bible"]["type"] == "STRING"


async def test_reference_prompt_defaults_to_the_visual_bible(session, ctx):
    prompts = []

    class Image:
        name = "fake-image"

        async def generate(self, prompt, *, model):
            prompts.append(prompt)
            return GenerationResult(b"PNG", "image/png", 0.0, model)

    async def image(name):
        return Image()

    ctx.registry.image = image
    p = await seed(session)
    (await get_step(session, p.id, "script")).result = {"bible": "Anna, red coat"}
    await set_running(session, "reference")
    await run_step(ctx, p.id, "reference")
    assert prompts[0].startswith("Anna, red coat")


def scenes_json(*scenes: tuple[str, float]) -> str:
    return json.dumps({"scenes": [{"voice_text": v, "visual_prompt": "p", "duration_s": d} for v, d in scenes]})


async def test_script_last_scene_without_engagement_is_retried_then_completed(session, ctx):
    p = await seed(session)
    llm = use_llm(ctx, scenes_json(("Accroche", 15), ("Chute", 15)), scenes_json(("Accroche", 15), ("Chute", 15)))
    await run_step(ctx, p.id, "script")
    scenes = (await session.scalars(select(Scene).where(Scene.project_id == p.id).order_by(Scene.position))).all()
    assert len(llm.prompts) == 2 and "« commente »" in llm.prompts[1]
    assert scenes[0].voice_text == "Accroche" and scenes[-1].voice_text == f"Chute {ENGAGEMENT_FALLBACK}"  # toujours présent
    assert (await get_step(session, p.id, "script")).status == "awaiting_validation"


async def test_script_quality_problems_are_reported_without_failing(session, ctx):
    p = await seed(session)
    long_voice = " ".join(["mot"] * 60)
    use_llm(ctx, scenes_json((long_voice, 4), (CTA, 4)))
    await run_step(ctx, p.id, "script")
    step = await get_step(session, p.id, "script")
    assert step.status == "awaiting_validation"
    assert any("somme des duration_s" in w for w in step.result["warnings"])
    assert any("scène 1 : 60 mots" in w for w in step.result["warnings"])


async def test_script_keeps_usable_first_answer_when_retry_is_invalid(session, ctx):
    p = await seed(session)
    first = scenes_json(("Accroche", 15), (CTA, 5))
    llm = use_llm(ctx, first, '{"scenes":[]}')
    await run_step(ctx, p.id, "script")
    step = await get_step(session, p.id, "script")
    assert len(llm.prompts) == 2 and step.status == "awaiting_validation" and step.result["scene_count"] == 2


@pytest.mark.parametrize("text,ok", [("Like, commente et partage !", True), ("Aime, commentez, partagez", True),
                                     ("Abonne-toi !", False), ("Commente et partage", False)])
def test_has_engagement_needs_like_comment_and_share(text, ok):
    assert has_engagement(text) is ok


def test_apply_descriptors_prepends_only_when_the_llm_dropped_or_paraphrased_it():
    refs = [{"id": "kroc", "prompt": "p", "descriptor": "Ray Kroc, 52, grey suit, round glasses."}, {"id": "can", "prompt": "p"}]
    scenes = [
        {"reference": "kroc", "visual_prompt": "Ray Kroc, 52, grey suit, round glasses. He opens a door."},
        {"reference": "kroc", "visual_prompt": "A man opens a door."},
        {"reference": "can", "visual_prompt": "A can."},  # pas de descripteur : intact
        {"reference": "", "visual_prompt": "A street."},
    ]
    apply_descriptors(scenes, refs)
    assert [s["visual_prompt"] for s in scenes] == [
        "Ray Kroc, 52, grey suit, round glasses. He opens a door.",  # déjà présent (ponctuation et casse ignorées)
        "Ray Kroc, 52, grey suit, round glasses. A man opens a door.", "A can.", "A street."]


def test_parse_references_keeps_the_descriptor():
    raw = json.dumps({"references": [{"id": "a", "prompt": "p", "descriptor": " tall man "}, {"id": "b", "prompt": "q"}]})
    assert parse_references(raw) == [{"id": "a", "prompt": "p", "descriptor": "tall man"}, {"id": "b", "prompt": "q"}]


async def test_script_enforces_descriptors_in_stored_scene_prompts(session, ctx):
    p = await seed(session)
    use_llm(ctx, json.dumps({"bible": "b", "references": [{"id": "kroc", "prompt": "p", "descriptor": "Ray Kroc, grey suit"}],
                             "scenes": [{"voice_text": CTA, "visual_prompt": "A man opens a door.", "duration_s": 30,
                                         "reference": "kroc"}]}))
    await run_step(ctx, p.id, "script")
    scene = await session.scalar(select(Scene).where(Scene.project_id == p.id))
    assert scene.visual_prompt == "Ray Kroc, grey suit. A man opens a door." and scene.reference == "kroc"


@pytest.mark.parametrize("scene_length", [0.001, 0, -3, "abc", float("nan")])
def test_script_max_tokens_is_bounded_whatever_the_params(scene_length):
    assert script_max_tokens(60, scene_length) in (script_max_tokens(60), 16000) and script_max_tokens(10**6, 1) == 16000


@pytest.mark.parametrize("target,scene_length,expected", [(15, None, 5000), (30, None, 6600), (60, None, 10200), (30, 5, 5400)])
def test_script_max_tokens_grows_with_the_number_of_scenes(target, scene_length, expected):
    assert script_max_tokens(target, scene_length) == expected


async def test_script_asks_for_enough_output_tokens(session, ctx):
    p = await seed(session)

    class Spy(ScriptedLLM):
        async def complete(self, system, prompt, *, max_tokens=4000, json_schema=None):
            self.max_tokens = max_tokens
            return await super().complete(system, prompt, max_tokens=max_tokens, json_schema=json_schema)

    llm = Spy(scenes_json((CTA, 30)))
    use_llm(ctx, llm)
    await run_step(ctx, p.id, "script")
    assert llm.max_tokens == script_max_tokens(30)


# --- Étape story : histoire (beats) puis inventaire des éléments suivis ----------------------------------------------

def beats_answer(voice_last=CTA):
    return json.dumps({"beats": [{"summary": "Elle verse l'eau sur le sac", "voice_text": "Regarde ses mains.", "duration_s": 15},
                                 {"summary": "Chloé découvre le dégât", "voice_text": voice_last, "duration_s": 15}]})


def inventory_answer(second_id="sac"):
    return json.dumps({
        "bible": "Anime, cel shading, cocktail bar.",
        "elements": [{"id": "chloe", "kind": "character", "name": "Chloe", "descriptor": "Chloe, 22, blonde", "prompt": "Chloe alone"},
                     {"id": "sac", "kind": "prop", "name": "Sac", "descriptor": "a beige handbag", "prompt": "A beige handbag"}],
        "beats": [{"elements": [{"id": "chloe", "state": ""}, {"id": "sac", "state": "dry"}]},
                  {"elements": [{"id": "chloe", "state": ""}, {"id": second_id, "state": "wet"}]}]})


async def run_story(session, ctx, *texts):
    p = await seed(session)
    await set_running(session, "story")
    llm = use_llm(ctx, *texts)
    await run_step(ctx, p.id, "story")
    return p, llm, await get_step(session, p.id, "story")


async def test_story_runs_two_passes_and_merges_beats_and_elements(session, ctx):
    p, llm, step = await run_story(session, ctx, beats_answer(), inventory_answer())
    assert step.status == "awaiting_validation", step.error
    assert [e["id"] for e in step.result["elements"]] == ["chloe", "sac"]
    assert step.result["beats"][1]["elements"] == [{"id": "chloe", "state": ""}, {"id": "sac", "state": "wet"}]
    assert step.result["bible"] == "Anime, cel shading, cocktail bar." and "warnings" not in step.result
    assert len(llm.prompts) == 2 and llm.schemas[0] == STORY_SCHEMA and llm.schemas[1] == INVENTORY_SCHEMA
    assert "Elle verse l'eau sur le sac" in llm.prompts[1]  # l'inventaire part des beats


async def test_story_prompts_carry_the_angle_the_engagement_rule_and_the_style(session, ctx):
    p = await seed(session)
    await set_running(session, "story")
    p.style = "anime"
    await session.commit()
    llm = use_llm(ctx, beats_answer(), inventory_answer())
    await run_step(ctx, p.id, "story")
    assert "like" in llm.prompts[0] and "<<<" in llm.prompts[0] and "30 secondes" in llm.prompts[0]
    assert "`continuity`" in llm.prompts[0] and "continue" in llm.prompts[0] and "cut" in llm.prompts[0]
    assert "Style visuel imposé" in llm.prompts[1] and "résolu" in llm.prompts[0]
    assert "personnalité réelle" in llm.prompts[1]  # personnage inventé, jamais le sosie d'une personne connue


async def test_story_retries_the_inventory_once_with_the_problems_then_succeeds(session, ctx):
    p, llm, step = await run_story(session, ctx, beats_answer(), inventory_answer("sac_x"), inventory_answer())
    assert step.status == "awaiting_validation" and "warnings" not in step.result
    assert len(llm.prompts) == 3 and "sac_x" in llm.prompts[2] and llm.schemas[2] == INVENTORY_SCHEMA
    calls = (await session.scalars(select(ProviderCall).where(ProviderCall.step == "story"))).all()
    assert len(calls) == 3  # la relance est facturée et tracée


async def test_story_keeps_the_defects_left_after_the_retry_as_warnings(session, ctx):
    p, llm, step = await run_story(session, ctx, beats_answer(), inventory_answer("sac_x"))
    assert step.status == "awaiting_validation" and len(llm.prompts) == 3
    assert any("sac_x" in w for w in step.result["warnings"])


async def test_story_retries_the_story_pass_when_the_voice_over_misses_the_engagement_call(session, ctx):
    p, llm, step = await run_story(session, ctx, beats_answer("Voilà."), beats_answer(), inventory_answer())
    assert len(llm.prompts) == 3 and "liker, commenter et partager" in llm.prompts[1]
    assert step.result["beats"][1]["voice_text"] == CTA and "warnings" not in step.result


async def test_story_guarantees_the_engagement_call_in_the_last_beat(session, ctx):
    p, llm, step = await run_story(session, ctx, beats_answer("Voilà."), beats_answer("Voilà."), inventory_answer())
    assert step.result["beats"][1]["voice_text"].endswith(ENGAGEMENT_FALLBACK)


async def test_story_without_beats_fails_readably_and_keeps_the_scenes(session, ctx):
    p = await seed(session)
    session.add(Scene(project_id=p.id, position=1, voice_text="old", visual_prompt="old", duration_s=3))
    await session.commit()
    await set_running(session, "story")
    llm = use_llm(ctx, "Désolé, je ne peux pas.")
    await run_step(ctx, p.id, "story")
    step = await get_step(session, p.id, "story")
    assert step.status == "failed" and "story" in step.error and "après une relance automatique" in step.error
    assert len(llm.prompts) == 2 and len((await session.scalars(select(Scene))).all()) == 1


# --- Étape script à partir de la story -------------------------------------------------------------------------------

STORY_ELEMENTS = [
    {"id": "chloe", "kind": "character", "name": "Chloe", "descriptor": "Chloe, 22, long blonde ponytail, emerald dress",
     "prompt": "Chloe alone"},
    {"id": "sac", "kind": "prop", "name": "Sac", "descriptor": "a beige handbag with a gold chain", "prompt": "A beige handbag"},
    {"id": "bar", "kind": "place", "name": "Bar", "descriptor": "a cozy cocktail bar", "prompt": ""}]
STORY = {"elements": STORY_ELEMENTS, "bible": "Anime, cel shading.", "beats": [
    {"summary": "Elle verse l'eau", "voice_text": "Regarde ses mains.", "duration_s": 4,
     "elements": [{"id": "chloe", "state": ""}, {"id": "sac", "state": "dry"}, {"id": "bar", "state": ""}]},
    {"summary": "Le sac est trempé", "voice_text": CTA, "duration_s": 5, "continuity": "continue",
     "elements": [{"id": "sac", "state": "wet, with a visible spill"}, {"id": "bar", "state": ""}]}]}
SCENE_ANSWER = '{"visual_prompt": "A close-up shot.\\n\\nMotion: the glass tilts."}'


async def seed_story(session, story=STORY):
    p = await seed(session)
    await session.execute(Step.__table__.update().where(Step.project_id == p.id, Step.name == "story")
                          .values(status="approved", result=story))
    await session.commit()
    return p


async def run_script(session, ctx, story=STORY, answer=SCENE_ANSWER):
    p = await seed_story(session, story)
    llm = use_llm(ctx, answer)
    await run_step(ctx, p.id, "script")
    scenes = (await session.scalars(select(Scene).where(Scene.project_id == p.id).order_by(Scene.position))).all()
    return p, llm, await get_step(session, p.id, "script"), scenes


async def test_script_from_story_writes_one_scene_per_beat_with_voice_and_duration_copied(session, ctx):
    p, llm, step, scenes = await run_script(session, ctx)
    assert step.status == "awaiting_validation", step.error
    assert [(s.voice_text, s.duration_s) for s in scenes] == [("Regarde ses mains.", 4.0), (CTA, 5.0)]
    assert len(llm.prompts) == 2 and all(schema == SCENE_SCHEMA for schema in llm.schemas)
    assert step.result["scene_count"] == 2 and step.result["bible"].startswith("Anime, cel shading.")


async def test_script_from_story_prompts_carry_descriptors_and_states_of_present_elements(session, ctx):
    p, llm, step, scenes = await run_script(session, ctx)
    second = next(prompt for prompt in llm.prompts if "Le sac est trempé" in prompt)
    assert "a beige handbag with a gold chain" in second and "wet, with a visible spill" in second
    assert "Chloe, 22" not in second and "Elle verse l'eau" in second  # scène précédente rappelée, Chloé absente du beat
    assert scenes[1].visual_prompt.startswith("a beige handbag with a gold chain (wet, with a visible spill). a cozy cocktail bar. ")
    assert scenes[0].visual_prompt.startswith("Chloe, 22, long blonde ponytail, emerald dress. a beige handbag with a gold chain (dry)")


async def test_script_from_story_sets_scene_elements_and_main_reference(session, ctx):
    p, llm, step, scenes = await run_script(session, ctx)
    assert scenes[0].elements == [{"id": "chloe", "state": ""}, {"id": "sac", "state": "dry"}, {"id": "bar", "state": ""}]
    assert [s.reference for s in scenes] == ["chloe", "sac"]  # personnage d'abord, sinon l'accessoire s'il a une image


async def test_script_result_references_come_from_story_elements(session, ctx):
    p, llm, step, scenes = await run_script(session, ctx)
    assert [r["id"] for r in step.result["references"]] == ["chloe", "sac"]  # le lieu n'a pas d'image de référence


async def test_script_from_story_failing_scene_fails_the_step_and_keeps_old_scenes(session, ctx):
    p = await seed_story(session)
    session.add(Scene(project_id=p.id, position=1, voice_text="old", visual_prompt="old", duration_s=3))
    await session.commit()
    use_llm(ctx, "Désolé.")
    await run_step(ctx, p.id, "script")
    step = await get_step(session, p.id, "script")
    assert step.status == "failed" and "beat" in step.error and "visual_prompt" in step.error
    assert [s.voice_text for s in (await session.scalars(select(Scene))).all()] == ["old"]


async def test_script_with_an_empty_approved_story_keeps_the_legacy_path(session, ctx):
    p = await seed_story(session, {})
    llm = use_llm(ctx, '{"scenes":[{"voice_text":"a","visual_prompt":"b","duration_s":15},'
                       f'{{"voice_text":"{CTA}","visual_prompt":"d","duration_s":15}}]}}')
    await run_step(ctx, p.id, "script")
    step = await get_step(session, p.id, "script")
    assert step.status == "awaiting_validation" and llm.schemas == [SCENES_SCHEMA]


async def test_script_from_story_reads_the_llm_settings_one_call_at_a_time(session, ctx):
    """Les appels par beat partagent la session : choisir le LLM (lecture des réglages en base) ne se fait jamais en
    même temps que la lecture d'un autre appel (asyncpg : « another operation is in progress »)."""
    from sqlalchemy import text

    p = await seed_story(session)
    llm = ScriptedLLM(SCENE_ANSWER)

    active = peak = 0

    async def factory():
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await ctx.session.execute(text("select pg_sleep(0.05)"))  # lecture des réglages, comme le registre
        active -= 1
        return llm

    ctx.registry.llm = factory
    await run_step(ctx, p.id, "script")
    step = await get_step(session, p.id, "script")
    assert step.status == "awaiting_validation", step.error
    assert peak == 1


async def test_script_from_story_passes_the_user_instruction_to_every_scene_prompt(session, ctx):
    p = await seed_story(session)
    llm = use_llm(ctx, SCENE_ANSWER)
    ctx.overrides["instruction"] = "ajoute un logo rouge sur le sac"
    await run_step(ctx, p.id, "script")
    assert len(llm.prompts) == 2 and all("ajoute un logo rouge sur le sac" in prompt for prompt in llm.prompts)


async def test_script_from_story_copies_the_continuity_of_each_beat_to_its_scene(session, ctx):
    p, llm, step, scenes = await run_script(session, ctx)
    assert [s.continuity for s in scenes] == ["cut", "continue"]  # le beat sans valeur (story ancienne) vaut « cut »


async def test_script_on_the_legacy_path_leaves_the_scenes_unchained(session, ctx):
    p = await seed(session)
    use_llm(ctx, '{"scenes":[{"voice_text":"a","visual_prompt":"b","duration_s":15},'
                 f'{{"voice_text":"{CTA}","visual_prompt":"d","duration_s":15}}]}}')
    await run_step(ctx, p.id, "script")
    scenes = (await session.scalars(select(Scene).where(Scene.project_id == p.id))).all()
    assert {s.continuity for s in scenes} == {"cut"}


# --- Chaînage : une scène « continue » part de la dernière image du clip précédent ----------------------------------

class ChainVideo(FakeVideo):
    """Clip « CLIP:<prompt> » ; note dans l'ordre l'image reçue par chaque appel."""

    def __init__(self):
        super().__init__()
        self.calls = []

    async def generate(self, prompt, *, model, duration_s, image=None):
        self.calls.append((prompt, image))
        return GenerationResult(b"CLIP:" + prompt.encode(), "video/mp4", 0.0, model)


async def seed_chain(session, ctx, monkeypatch, continuities=("cut", "continue", "continue")):
    from app.services import montage

    async def fake_last_frame(video):
        return b"LAST:" + video

    monkeypatch.setattr(montage, "last_frame", fake_last_frame)
    p = await seed(session)
    await set_running(session, "clips")
    for position, continuity in enumerate(continuities, 1):
        session.add(Scene(project_id=p.id, position=position, voice_text="a", visual_prompt=f"v{position}", duration_s=3,
                          reference="kroc", continuity=continuity))
    ctx.storage.files[f"projects/{p.id}/reference/kroc.png"] = b"KROC"
    session.add(Asset(project_id=p.id, kind="reference", key=f"projects/{p.id}/reference/kroc.png",
                      content_type="image/png", meta={"ref": "kroc"}))
    await session.commit()
    video = ChainVideo()

    async def registry_video(name):
        return video

    ctx.registry.video = registry_video
    return p, video


async def test_chained_scenes_start_from_the_last_frame_of_the_previous_clip_in_order(session, ctx, monkeypatch):
    p, video = await seed_chain(session, ctx, monkeypatch)
    await run_step(ctx, p.id, "clips")
    assert video.calls == [("v1", b"KROC"), ("v2", b"LAST:CLIP:v1"), ("v3", b"LAST:CLIP:v2")]


async def test_a_cut_scene_after_a_chain_starts_again_from_its_reference(session, ctx, monkeypatch):
    p, video = await seed_chain(session, ctx, monkeypatch, ("cut", "continue", "cut"))
    await run_step(ctx, p.id, "clips")
    assert [image for _, image in video.calls] == [b"KROC", b"LAST:CLIP:v1", b"KROC"]


async def test_regenerating_one_chained_scene_uses_the_selected_clip_of_the_previous_scene(session, ctx, monkeypatch):
    p, video = await seed_chain(session, ctx, monkeypatch)
    scenes = (await session.scalars(select(Scene).where(Scene.project_id == p.id).order_by(Scene.position))).all()
    ctx.storage.files["projects/clip1.mp4"] = b"STORED"
    first = Asset(project_id=p.id, scene_id=scenes[0].id, kind="clip", key="projects/clip1.mp4", content_type="video/mp4")
    session.add(first)
    await session.flush()
    scenes[0].selected_clip_asset_id = first.id
    await session.commit()
    await run_step(ctx, p.id, "clips", scenes[1].id)
    assert video.calls == [("v2", b"LAST:STORED")]


async def test_a_chained_scene_without_a_previous_clip_falls_back_to_its_reference(session, ctx, monkeypatch):
    p, video = await seed_chain(session, ctx, monkeypatch)
    scenes = (await session.scalars(select(Scene).where(Scene.project_id == p.id).order_by(Scene.position))).all()
    await run_step(ctx, p.id, "clips", scenes[1].id)  # la scène 1 n'a aucun clip
    assert video.calls == [("v2", b"KROC")]


async def test_a_project_without_chained_scenes_still_generates_in_parallel(session, ctx, monkeypatch):
    p, video = await seed_chain(session, ctx, monkeypatch, ("cut", "cut", "cut"))
    await run_step(ctx, p.id, "clips")
    assert sorted(image for _, image in video.calls) == [b"KROC"] * 3


class MultiVideo(ChainVideo):
    """Comme ChainVideo, mais note aussi les images en plus (`references`, absentes de l'appel quand il n'y en a pas)."""

    async def generate(self, prompt, *, model, duration_s, image=None, **extra):
        self.calls.append((prompt, image, extra.get("references")))
        return GenerationResult(b"CLIP:" + prompt.encode(), "video/mp4", 0.0, model)


async def seed_multi(session, ctx, monkeypatch, scenes):
    """`scenes` : [(continuité, référence principale, ids des éléments visibles)] ; images KROC (personnage), SARAH
    (personnage), BAG, MUG (accessoires), toutes avec une image de référence."""
    p, _ = await seed_chain(session, ctx, monkeypatch, ())
    kinds = {"kroc": "character", "sarah": "character", "bag": "prop", "mug": "prop", "bar": "place"}
    await session.execute(Step.__table__.update().where(Step.project_id == p.id, Step.name == "story").values(
        status="approved", result={"elements": [{"id": i, "kind": k, "name": i, "descriptor": "d", "prompt": "p"}
                                                for i, k in kinds.items()], "beats": []}))
    for position, (continuity, reference, shown) in enumerate(scenes, 1):
        session.add(Scene(project_id=p.id, position=position, voice_text="a", visual_prompt=f"v{position}", duration_s=3,
                          reference=reference, continuity=continuity, elements=[{"id": i, "state": ""} for i in shown]))
    for ref in ("sarah", "bag", "mug"):
        key = f"projects/{p.id}/reference/{ref}.png"
        ctx.storage.files[key] = ref.upper().encode()
        session.add(Asset(project_id=p.id, kind="reference", key=key, content_type="image/png", meta={"ref": ref}))
    await session.commit()
    video = MultiVideo()

    async def registry_video(name):
        return video

    ctx.registry.video = registry_video
    return p, video


async def test_a_scene_sends_the_images_of_its_other_visible_elements_after_its_main_reference(session, ctx, monkeypatch):
    p, video = await seed_multi(session, ctx, monkeypatch, [("cut", "kroc", ["bar", "mug", "kroc", "bag", "sarah"])])
    await run_step(ctx, p.id, "clips")
    # KROC (principal) puis le personnage restant : au plus 2 images, personnages d'abord
    assert video.calls == [("v1", b"KROC", [b"SARAH"])]


async def test_a_chained_scene_sends_the_last_frame_then_the_characters_and_props_it_shows(session, ctx, monkeypatch):
    p, video = await seed_multi(session, ctx, monkeypatch, [("cut", "kroc", ["kroc"]), ("continue", "kroc", ["bag", "kroc", "mug"])])
    await run_step(ctx, p.id, "clips")
    assert video.calls[1] == ("v2", b"LAST:CLIP:v1", [b"KROC"])


async def test_a_chained_scene_sends_its_reference_when_its_subject_was_not_in_the_previous_scene(session, ctx, monkeypatch):
    p, video = await seed_multi(session, ctx, monkeypatch, [("cut", "kroc", ["kroc"]), ("continue", "sarah", ["bag"]),
                                                            ("continue", "sarah", ["mug"])])
    await run_step(ctx, p.id, "clips")
    assert video.calls[1] == ("v2", b"LAST:CLIP:v1", [b"SARAH"])  # Sarah entre dans la scène
    assert video.calls[2] == ("v3", b"LAST:CLIP:v2", [b"MUG"])  # déjà dans la dernière image : pas répétée


async def test_a_scene_without_any_other_image_keeps_the_single_image_call(session, ctx, monkeypatch):
    p, video = await seed_multi(session, ctx, monkeypatch, [("cut", "kroc", ["kroc", "bar"])])
    await run_step(ctx, p.id, "clips")
    assert video.calls == [("v1", b"KROC", None)]


# --- Voix par personnage ---------------------------------------------------------------------------------------------

class RecordingVoice:
    name = "recording-voice"

    def __init__(self):
        self.calls = []

    async def synthesize(self, text, *, voice_id):
        self.calls.append((text, voice_id))
        return GenerationResult(b"VOICE:" + voice_id.encode(), "audio/mpeg", 0.0, "recording-voice")


async def seed_voices(session, ctx, speakers, voices, default="narr"):
    p = await seed(session)
    await set_running(session, "voice")
    await session.execute(Step.__table__.update().where(Step.project_id == p.id, Step.name == "story").values(
        status="approved", result={"beats": [], "elements": [
            {"id": i, "kind": "character", "name": i, "descriptor": "d", "prompt": "p", "voice_id": v} for i, v in voices.items()]}))
    for position, speaker in enumerate(speakers, 1):
        session.add(Scene(project_id=p.id, position=position, voice_text=f"t{position}", visual_prompt="v", duration_s=3,
                          speaker=speaker))
    await session.commit()
    if default:
        await ctx.app_settings.set("default_voice_id", default)
    voice = RecordingVoice()

    async def registry_voice():
        return voice

    ctx.registry.voice = registry_voice
    return p, voice


async def test_each_scene_is_voiced_by_its_speaker_or_by_the_default_voice(session, ctx):
    p, voice = await seed_voices(session, ctx, ["", "chloe", "sarah", "chloe"], {"chloe": "v-chloe", "sarah": ""})
    await run_step(ctx, p.id, "voice")
    assert (await get_step(session, p.id, "voice")).status == "awaiting_validation"
    assert sorted(voice.calls) == [("t1", "narr"), ("t2", "v-chloe"), ("t3", "narr"), ("t4", "v-chloe")]


async def test_a_speaker_voice_wins_over_the_step_voice_param_for_that_scene_only(session, ctx):
    p, voice = await seed_voices(session, ctx, ["", "chloe"], {"chloe": "v-chloe"}, default="")
    await session.execute(Step.__table__.update().where(Step.project_id == p.id, Step.name == "voice").values(params={"voice_id": "step"}))
    await session.commit()
    await run_step(ctx, p.id, "voice")
    assert sorted(voice.calls) == [("t1", "step"), ("t2", "v-chloe")]


async def test_voice_fails_before_any_call_when_a_scene_has_no_voice_at_all(session, ctx, monkeypatch):
    monkeypatch.setattr(settings, "fake_providers", False)
    p, voice = await seed_voices(session, ctx, ["", "chloe"], {"chloe": "v-chloe"}, default="")
    await run_step(ctx, p.id, "voice")
    step = await get_step(session, p.id, "voice")
    assert step.status == "failed" and "aucune voix" in step.error and voice.calls == []


async def test_voice_rejects_an_unsafe_character_voice_before_any_call(session, ctx):
    p, voice = await seed_voices(session, ctx, ["chloe"], {"chloe": "../x"})
    await run_step(ctx, p.id, "voice")
    step = await get_step(session, p.id, "voice")
    assert step.status == "failed" and "identifiant de voix invalide" in step.error and voice.calls == []


async def test_script_from_story_copies_the_speaker_of_each_beat_to_its_scene(session, ctx):
    story = {**STORY, "beats": [{**STORY["beats"][0], "speaker": ""}, {**STORY["beats"][1], "speaker": "chloe"}]}
    p, llm, step, scenes = await run_script(session, ctx, story)
    assert [s.speaker for s in scenes] == ["", "chloe"]


async def test_story_assigns_catalog_voices_to_speaking_characters(session, ctx):
    await ctx.app_settings.set("default_voice_id", "narr")
    await ctx.app_settings.set("voice_catalog", json.dumps([{"id": "narr", "name": "N"}, {"id": "v1", "name": "A"}]))
    inventory = json.loads(inventory_answer())
    inventory["beats"][1]["speaker"] = "chloe"
    p, llm, step = await run_story(session, ctx, beats_answer(), json.dumps(inventory))
    assert step.status == "awaiting_validation", step.error
    assert [e.get("voice_id") for e in step.result["elements"]] == ["v1", ""]
    assert [b["speaker"] for b in step.result["beats"]] == ["", "chloe"]


async def clips_with_references(session, ctx, ref_by_scene, *, composed=b"COMPOSED"):
    """Projet à scènes référencées, Gemini et vidéo enregistreurs : (appels Gemini, appels vidéo)."""
    p = await seed(session)
    await set_running(session, "clips")
    for position, ref in enumerate(ref_by_scene, 1):
        session.add(Scene(project_id=p.id, position=position, voice_text="a", visual_prompt=f"v{position}\nMotion: pan",
                          duration_s=3, reference=ref))
    for ref in {r for r in ref_by_scene if r}:
        key = f"projects/{p.id}/reference/{ref}.png"
        ctx.storage.files[key] = ref.upper().encode()
        session.add(Asset(project_id=p.id, kind="reference", key=key, content_type="image/png", meta={"ref": ref}))
    await session.commit()
    images, videos = [], []

    class RecordingImage:
        name = "fake-image"

        async def generate(self, prompt, *, model, references=()):
            images.append((prompt, list(references)))
            return GenerationResult(composed, "image/png", 0.07, model)

    class RecordingVideo(FakeVideo):
        async def generate(self, prompt, *, model, duration_s, image=None, references=(), start_image=None):
            videos.append({"image": image, "start_image": start_image})
            return await super().generate(prompt, model=model, duration_s=duration_s)

    async def image(name):
        return RecordingImage()

    ctx.registry.image = image
    use_video(ctx, RecordingVideo())
    return p, images, videos


async def test_gemini_composes_the_start_image_which_comfyui_then_animates(session, ctx):
    from app.providers.comfyui import KONTEXT_PREFIX
    ctx.overrides["start_image"] = "gemini"
    p, images, videos = await clips_with_references(session, ctx, ["kroc", ""])
    await ctx.app_settings.set("default_video_provider", "comfyui")
    await run_step(ctx, p.id, "clips")
    assert [(prompt, refs) for prompt, refs in images][0] == (KONTEXT_PREFIX + "v1", [b"KROC"])  # sans « Motion: »
    assert videos[0] == {"image": b"KROC", "start_image": b"COMPOSED"}
    assert len(images) == 1  # la scène sans image de référence n'en demande pas à Gemini
    assert videos[1] == {"image": None, "start_image": None}
    cost = await session.scalar(select(func.sum(ProviderCall.cost_usd)).where(ProviderCall.provider == "fake-image"))
    assert cost == pytest.approx(0.07)


async def test_kontext_stays_the_default_start_image(session, ctx):
    p, images, videos = await clips_with_references(session, ctx, ["kroc"])
    await run_step(ctx, p.id, "clips")
    assert images == [] and videos[0]["start_image"] is None


async def test_the_preference_setting_applies_without_a_launch_choice(session, ctx):
    await ctx.app_settings.set("start_image_provider", "gemini")
    p, images, videos = await clips_with_references(session, ctx, ["kroc"])
    await run_step(ctx, p.id, "clips")
    assert len(images) == 1 and videos[0]["start_image"] == b"COMPOSED"


async def test_a_launch_choice_beats_the_preference(session, ctx):
    await ctx.app_settings.set("start_image_provider", "gemini")
    ctx.overrides["start_image"] = "comfyui"
    p, images, videos = await clips_with_references(session, ctx, ["kroc"])
    await run_step(ctx, p.id, "clips")
    assert images == [] and videos[0]["start_image"] is None


async def test_only_comfyui_has_a_start_image_step(session):
    from app.app_settings import AppSettings
    from app.services.pipeline import start_image_provider
    settings = AppSettings(session)
    assert await start_image_provider({"start_image": "gemini"}, settings, "comfyui") == "gemini"
    assert await start_image_provider({"start_image": "gemini"}, settings, "fal") == "comfyui"
    assert await start_image_provider({}, settings, "comfyui") == "comfyui"
