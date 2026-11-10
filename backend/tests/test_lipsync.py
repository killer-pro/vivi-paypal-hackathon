"""Avatar parlant (`Project.lipsync`) : scènes concernées, graphes Comfy Cloud, clips, montage, coût et API."""
import json

import pytest
from sqlalchemy import select

from app.models import Asset, Project, Scene, Step
from app.providers.comfycloud import cloud_talk_usd
from app.providers.fakes import _ffmpeg
from app.providers.profiles import TALK_MODELS
from app.providers.registry import ProviderRegistry
from app.providers.workflows import talk_frames, talk_workflow
from app.services import montage
from app.services.budget import TALK_VOICE_USD, clip_scene_costs_usd
from app.services.lipsync import talks
from app.services.pipeline import run_step
from app.services.prompts import scene_prompt
from tests.test_api_steps import set_status
from tests.test_pipeline import get_step, seed, set_running
from tests.test_styles import create


def scene(speaker="awa", reference="", elements=()):
    return Scene(speaker=speaker, reference=reference, elements=[{"id": e, "state": ""} for e in elements])


@pytest.mark.parametrize("lipsync,s,expected", [
    (True, scene(reference="awa"), True),
    (True, scene(elements=["awa"]), True),
    (True, scene(elements=["sac"]), False),  # le personnage parle hors champ
    (True, scene(speaker="", reference="awa"), False),  # narrateur
    (False, scene(reference="awa"), False),
    (True, Scene(speaker="awa", reference="awa", elements=[], lipsync=False), False),  # sortie du lip-sync
])
def test_a_scene_talks_when_its_visible_speaker_says_the_voice_over_in_lipsync_mode(lipsync, s, expected):
    assert talks(Project(lipsync=lipsync), s) is expected


@pytest.mark.parametrize("model", list(TALK_MODELS))
def test_talk_workflow_fills_every_marker(model):
    graph = talk_workflow(model, 'elle dit "bonjour"', 42, 5.1, "vv_talk.png", "vv_talk.mp3")
    raw = json.dumps(graph, ensure_ascii=False)
    assert "{{" not in raw and "vv_talk.png" in raw and "vv_talk.mp3" in raw and 'elle dit \\"bonjour\\"' in raw


def test_talk_frames_cover_the_voice_at_the_model_rate_in_4n_plus_1_images():
    assert talk_frames("s2v", 5.0) == 81 and talk_frames("infinitetalk", 4.84) == 121
    assert all((talk_frames(m, 3.3) - 1) % 4 == 0 for m in TALK_MODELS)


def test_talk_cost_grows_with_the_voice_and_the_model():
    assert cloud_talk_usd("s2v", 8) > cloud_talk_usd("s2v", 4) > 0
    assert cloud_talk_usd("infinitetalk", 4) > cloud_talk_usd("s2v", 4)


def test_scene_prompt_frames_the_speaker_face_to_camera_in_lipsync_mode():
    beat = {"duration_s": 4, "summary": "Awa salue", "voice_text": "Salut", "speaker": "awa"}
    present = [{"id": "awa", "name": "Awa", "descriptor": "d", "state": ""}]
    assert "face caméra" in scene_prompt(Project(lipsync=True), "", beat, present, "", 1, 3)
    assert "face caméra" not in scene_prompt(Project(lipsync=False), "", beat, present, "", 1, 3)


async def seed_talking(session, ctx):
    """Projet en mode avatar parlant : scène 1 dite par Awa à l'écran, scène 2 par le narrateur."""
    p = await seed(session)
    p.lipsync = True
    await session.execute(Step.__table__.update().where(Step.project_id == p.id, Step.name == "story").values(
        status="approved", result={"beats": [], "elements": [
            {"id": "awa", "kind": "character", "name": "Awa", "descriptor": "d", "prompt": "p", "voice_id": "v-awa"}]}))
    session.add_all([Scene(project_id=p.id, position=1, voice_text="Je suis née dans Vivi", visual_prompt="a",
                           duration_s=3, speaker="awa", reference="awa"),
                     Scene(project_id=p.id, position=2, voice_text="Et voilà", visual_prompt="b", duration_s=3)])
    await session.commit()
    await ctx.app_settings.set("default_voice_id", "narr")
    return p


async def clips_of(session, p):
    return (await session.scalars(select(Asset).where(Asset.project_id == p.id, Asset.kind == "clip")
                                  .order_by(Asset.scene_id))).all()


async def test_talking_scene_is_generated_on_its_own_voice_and_others_stay_ordinary_clips(session, ctx):
    p = await seed_talking(session, ctx)
    await set_running(session, "clips")
    await run_step(ctx, p.id, "clips")
    assert (await get_step(session, p.id, "clips")).status == "awaiting_validation"
    talking, ordinary = await clips_of(session, p)
    voice = await session.get(Asset, talking.meta["voice_asset_id"])
    assert talking.meta["lipsync"] == "s2v" and voice.kind == "voice" and voice.scene_id == talking.scene_id
    assert voice.meta["text"] == "Je suis née dans Vivi" and voice.meta["voice_id"] == "v-awa"
    assert "voice_asset_id" not in ordinary.meta


async def test_talking_clip_reuses_the_voice_already_made_for_the_same_text(session, ctx):
    p = await seed_talking(session, ctx)
    await set_running(session, "voice")
    await run_step(ctx, p.id, "voice")
    await set_running(session, "clips")
    await run_step(ctx, p.id, "clips")
    voices = (await session.scalars(select(Asset).where(Asset.kind == "voice"))).all()
    assert len(voices) == 2  # aucune voix en plus
    talking, _ = await clips_of(session, p)
    assert talking.meta["voice_asset_id"] in {v.id for v in voices}


async def test_imported_voices_are_kept_by_the_voice_step_and_spoken_by_the_avatar(session, ctx):
    """Voix enregistrées (wolof…) : ni synthèse ni voix configurée ; la scène choisie seule est resynthétisée."""
    p = await seed_talking(session, ctx)
    await ctx.app_settings.set("default_voice_id", "")
    await session.execute(Step.__table__.update().where(Step.project_id == p.id, Step.name == "story").values(
        result={"beats": [], "elements": [{"id": "awa", "kind": "character", "name": "Awa", "descriptor": "d",
                                           "prompt": "p"}]}))
    recorded = {}
    for sc in (await session.scalars(select(Scene).where(Scene.project_id == p.id))).all():
        key = f"projects/{p.id}/voice/rec{sc.position}.mp3"
        ctx.storage.files[key] = _ffmpeg("-f", "lavfi", "-i", "sine=duration=1", suffix=".mp3")
        asset = Asset(project_id=p.id, scene_id=sc.id, kind="voice", key=key, content_type="audio/mpeg",
                      meta={"model": "upload", "cost_usd": 0.0, "imported": True, "text": sc.voice_text})
        session.add(asset)
        await session.flush()
        recorded[sc.id] = asset.id
    await session.commit()
    for name in ("voice", "clips"):
        await set_running(session, name)
        await run_step(ctx, p.id, name)
        step = await get_step(session, p.id, name)
        assert step.status == "awaiting_validation", step.error
    assert (await get_step(session, p.id, "voice")).result["asset_ids"] == list(recorded.values())
    assert len((await session.scalars(select(Asset).where(Asset.kind == "voice"))).all()) == 2  # aucune synthèse
    talking, _ = await clips_of(session, p)
    assert talking.meta["voice_asset_id"] == recorded[talking.scene_id]


async def test_reuse_start_image_restarts_each_scene_from_the_kept_image_of_its_chosen_clip(session, ctx, monkeypatch):
    """Changer de modèle lip-sync sans repayer l'image de départ : celle du clip choisi part telle quelle."""
    from app.providers.fakes import FakeVideo

    p = await seed_talking(session, ctx)
    await set_running(session, "clips")
    await run_step(ctx, p.id, "clips")
    talking, ordinary = await clips_of(session, p)
    ctx.storage.files["projects/kf.png"] = b"image validee"
    session.add(Asset(project_id=p.id, scene_id=talking.scene_id, kind="keyframe", key="projects/kf.png",
                      content_type="image/png", meta={"clip_asset_id": talking.id}))
    await session.commit()
    sent = {}
    talk, generate = FakeVideo.talk, FakeVideo.generate

    async def spy_talk(self, prompt, **kw):
        sent["talk"] = kw.get("start_image")
        return await talk(self, prompt, **kw)

    async def spy_generate(self, prompt, **kw):
        sent["generate"] = kw.get("start_image")
        return await generate(self, prompt, **kw)

    monkeypatch.setattr(FakeVideo, "talk", spy_talk)
    monkeypatch.setattr(FakeVideo, "generate", spy_generate)
    ctx.overrides = {"reuse_start_image": True}
    await set_running(session, "clips")
    await run_step(ctx, p.id, "clips")
    assert (await get_step(session, p.id, "clips")).status == "awaiting_validation"
    assert sent == {"talk": b"image validee", "generate": None}  # sans image gardée : composition habituelle


async def test_montage_keeps_the_voice_the_lips_follow_even_after_a_new_voice(session, ctx):
    p = await seed_talking(session, ctx)
    for name in ("clips", "voice"):  # la voix est refaite après le clip parlant
        await set_running(session, name)
        await run_step(ctx, p.id, name)
    await set_running(session, "montage")
    await run_step(ctx, p.id, "montage")
    step = await get_step(session, p.id, "montage")
    assert step.status == "awaiting_validation", step.error
    talking, _ = await clips_of(session, p)
    synced = montage.segment_key(p.id, talking.id, talking.meta["voice_asset_id"])
    assert f"{synced}.wav" in ctx.storage.files


async def test_synced_segment_keeps_voice_and_clip_speed(tmp_path):
    voice = tmp_path / "v.mp3"
    voice.write_bytes(_ffmpeg("-f", "lavfi", "-i", "sine=frequency=220:duration=2", suffix=".mp3"))
    clip = tmp_path / "c.mp4"
    clip.write_bytes(_ffmpeg("-f", "lavfi", "-i", "color=c=green:s=320x568:d=3.5:r=16", "-pix_fmt", "yuv420p",
                             suffix=".mp4"))
    segment = await montage.render_segment(montage.SceneInput(clip, voice, "t", synced=True), tmp_path, "s")
    assert segment.duration == pytest.approx(await montage.probe_duration(voice) + montage.PAD_S, abs=0.01)


async def test_talking_scenes_are_priced_at_the_lipsync_model(session, ctx):
    p = await seed_talking(session, ctx)
    async with ProviderRegistry(ctx.app_settings) as registry:
        costs = await clip_scene_costs_usd(session, registry, p.id, "comfycloud", "fast", talk_model="infinitetalk")
    talking, ordinary = (await session.scalars(select(Scene).where(Scene.project_id == p.id).order_by(Scene.position))).all()
    assert costs[talking.id] == pytest.approx(cloud_talk_usd("infinitetalk", 3) + TALK_VOICE_USD)
    assert costs[ordinary.id] < costs[talking.id]


async def test_lipsync_is_set_at_creation_and_switching_it_makes_clips_stale(api, session):
    r = await create(api, lipsync=True)
    assert r.status_code == 201 and r.json()["lipsync"] is True
    pid = r.json()["id"]
    await set_status(session, ["script", "clips", "montage"], "awaiting_validation")
    assert (await api.patch(f"/api/projects/{pid}", json={"lipsync": False})).status_code == 200
    steps = {s["name"]: s["status"] for s in (await api.get(f"/api/projects/{pid}")).json()["steps"]}
    assert steps["script"] == "awaiting_validation" and steps["clips"] == steps["montage"] == "stale"


async def test_a_scene_can_leave_lipsync_and_the_project_says_where_the_speaker_is_on_screen(api, session):
    pid = (await create(api, lipsync=True)).json()["id"]
    talking = Scene(project_id=pid, position=1, voice_text="v", visual_prompt="p", speaker="awa", reference="awa")
    session.add(talking)
    await session.commit()
    r = await api.put(f"/api/projects/{pid}/scenes/{talking.id}/lipsync", json={"lipsync": False})
    assert r.status_code == 200 and r.json()["lipsync"] is False
    [out] = (await api.get(f"/api/projects/{pid}")).json()["scenes"]
    assert out["on_screen"] is True and out["lipsync"] is False
    assert (await api.put(f"/api/projects/{pid}/scenes/999999/lipsync", json={"lipsync": True})).status_code == 404


async def test_a_retouched_lipsync_clip_keeps_the_voice_its_lips_follow(api, session):
    pid = (await create(api, lipsync=True)).json()["id"]
    talking = Scene(project_id=pid, position=1, voice_text="v", visual_prompt="p", speaker="awa", reference="awa")
    session.add(talking)
    await session.flush()
    plain = Asset(project_id=pid, scene_id=talking.id, kind="clip", key="c0", content_type="video/mp4", variant=1)
    lipsynced = Asset(project_id=pid, scene_id=talking.id, kind="clip", key="c1", content_type="video/mp4", variant=2,
                      meta={"voice_asset_id": 7, "lipsync": "s2v"})
    session.add_all([plain, lipsynced])
    await session.commit()
    video = {"file": ("retouche.mp4", b"\x00\x00\x00\x1cftypisom\x00\x00\x02\x00isomiso2mp41", "video/mp4")}
    url = f"/api/projects/{pid}/scenes/{talking.id}/upload-clip"
    r = await api.post(url, files=video, data={"retouches": str(lipsynced.id)})
    assert r.status_code == 201
    expected = {"retouches": lipsynced.id, "voice_asset_id": 7, "lipsync": "s2v", "model": "upload"}
    assert expected.items() <= r.json()["meta"].items()
    assert (await api.post(url, files=video, data={"retouches": str(plain.id)})).status_code == 422
