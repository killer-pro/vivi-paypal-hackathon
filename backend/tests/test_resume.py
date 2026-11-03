"""Reprise des clips / voix après un échec, et nouveau prompt visuel d'une scène."""
from sqlalchemy import func, select

from app.models import Asset, Project, ProviderCall, Scene, Step
from app.services.pipeline import run_step
from tests.test_api_steps import new_project, set_status
from tests.test_pipeline import SlowVideo, get_step, seed_scenes, set_running, use_video


async def project_with_failed_clips(api, session, scenes=4, done=2):
    """Projet dont l'étape clips a échoué (lancement « r1 ») après avoir produit les `done` premières scènes."""
    pid = await new_project(api)
    session.add_all(Scene(project_id=pid, position=i, voice_text=f"v{i}", visual_prompt=f"p{i}", duration_s=3)
                    for i in range(1, scenes + 1))
    await session.flush()
    first = (await session.scalars(select(Scene).where(Scene.project_id == pid).order_by(Scene.position))).all()
    session.add_all(Asset(project_id=pid, scene_id=s.id, kind="clip", key=f"c{s.position}", content_type="video/mp4",
                          meta={"run": "r1"}) for s in first[:done])
    await session.execute(Step.__table__.update().where(Step.name.in_(["idea", "story", "script", "reference"]))
                          .values(status="approved"))
    await session.execute(Step.__table__.update().where(Step.name == "clips").values(status="failed", run_id="r1",
                                                                                     error="fal: génération échouée"))
    await session.commit()
    return pid, first


async def clips_step(api, pid):
    return next(s for s in (await api.get(f"/api/projects/{pid}")).json()["steps"] if s["name"] == "clips")


# --- Reprise : API ---------------------------------------------------------------------------------------------------

async def test_failed_step_exposes_what_can_be_resumed(api, session):
    pid, _ = await project_with_failed_clips(api, session, scenes=4, done=2)
    assert (await clips_step(api, pid))["resume"] == {"done": 2, "total": 4}
    await set_status(session, ["clips"], "awaiting_validation")
    assert (await clips_step(api, pid))["resume"] is None  # seule une étape en échec se reprend


async def test_nothing_to_resume_when_the_failed_run_produced_nothing(api, session):
    pid, _ = await project_with_failed_clips(api, session, scenes=3, done=0)
    assert (await clips_step(api, pid))["resume"] is None
    r = await api.post(f"/api/projects/{pid}/steps/clips/run", json={"resume": True})
    assert r.status_code == 409 and "Rien à reprendre" in r.json()["detail"]


async def test_resume_launches_a_new_run_that_skips_done_scenes(api, session):
    pid, first = await project_with_failed_clips(api, session)
    r = await api.post(f"/api/projects/{pid}/steps/clips/run", json={"resume": True})
    assert r.status_code == 202
    done = sorted(s.id for s in first[:2])
    assert api.enqueued == [(pid, "clips", None, {"skip_scenes": done})]
    step = await session.scalar(select(Step).where(Step.name == "clips").execution_options(populate_existing=True))
    assert step.status == "running" and step.run_id not in (None, "r1") and len(step.run_id) == 32


async def test_resume_timeout_and_estimate_only_cover_remaining_scenes(api, session):
    pid, _ = await project_with_failed_clips(api, session, scenes=4, done=3)
    await api.post(f"/api/projects/{pid}/steps/clips/run", json={"resume": True})
    other = await new_project(api)
    await session.execute(Step.__table__.update().where(Step.project_id == other, Step.name.in_(
        ["idea", "story", "script", "reference"])).values(status="approved"))
    session.add(Scene(project_id=other, position=1, voice_text="a", visual_prompt="b", duration_s=3))
    await session.commit()
    await api.post(f"/api/projects/{other}/steps/clips/run", json={})  # une scène à générer, sans reprise
    assert api.timeouts[0] == api.timeouts[1]  # 1 scène restante sur 4 = 1 scène : même timeout


async def test_resume_is_refused_unless_the_step_failed_and_is_per_scene(api, session):
    pid, first = await project_with_failed_clips(api, session)
    assert (await api.post(f"/api/projects/{pid}/steps/idea/run", json={"resume": True})).status_code == 422
    assert (await api.post(f"/api/projects/{pid}/steps/clips/run",
                           json={"resume": True, "scene_id": first[0].id})).status_code == 422
    await set_status(session, ["clips"], "awaiting_validation")
    assert (await api.post(f"/api/projects/{pid}/steps/clips/run", json={"resume": True})).status_code == 409


async def test_single_scene_run_is_tagged_with_its_scene(api, session):
    pid, first = await project_with_failed_clips(api, session)
    assert (await api.post(f"/api/projects/{pid}/steps/clips/run", json={"scene_id": first[3].id})).status_code == 202
    step = await session.scalar(select(Step).where(Step.name == "clips").execution_options(populate_existing=True))
    assert step.run_id.startswith(f"scene:{first[3].id}:")  # ni reprise d'un lancement complet, ni identifiant de lancement


async def test_failed_single_scene_run_is_retried_for_that_scene_only(api, session):
    """Après l'échec de la régénération d'UNE scène, « Relancer » ne doit viser que cette scène (jamais toute la vidéo)."""
    pid, first = await project_with_failed_clips(api, session, scenes=4, done=2)
    await api.post(f"/api/projects/{pid}/steps/clips/run", json={"scene_id": first[3].id})
    await session.execute(Step.__table__.update().where(Step.name == "clips").values(status="failed", error="comfyui"))
    await session.commit()
    step = await clips_step(api, pid)
    assert step["target_scene"] == first[3].id and step["resume"] is None  # pas de reprise « complète » proposée
    r = await api.post(f"/api/projects/{pid}/steps/clips/run", json={"resume": True})
    assert r.status_code == 409  # un lancement d'une scène n'est pas un lancement à reprendre
    assert (await api.post(f"/api/projects/{pid}/steps/clips/run", json={"scene_id": first[3].id})).status_code == 202


async def test_target_scene_is_only_reported_for_a_scene_run_of_an_existing_scene(api, session):
    pid, first = await project_with_failed_clips(api, session)
    assert (await clips_step(api, pid))["target_scene"] is None  # échec d'un lancement complet
    await session.execute(Step.__table__.update().where(Step.name == "clips").values(run_id="scene:999999:abcd1234"))
    await session.commit()
    assert (await clips_step(api, pid))["target_scene"] is None  # scène disparue depuis


# --- Reprise : exécuteur ---------------------------------------------------------------------------------------------

async def test_resumed_run_generates_only_missing_scenes_and_keeps_scene_order(session, ctx):
    p = await seed_scenes(session, 5)
    await ctx.app_settings.set("default_video_provider", "comfyui")  # un clip à la fois : l'échec tombe à la scène 4
    first = use_video(ctx, SlowVideo(fail_on="p4", delay=0))
    await set_running(session, "clips", run_id="r1")
    await run_step(ctx, p.id, "clips")
    assert (await get_step(session, p.id, "clips")).status == "failed" and first.started >= 4
    kept = {a.scene_id: a.id for a in (await session.scalars(select(Asset).where(Asset.kind == "clip"))).all()}
    assert len(kept) == 3

    second = use_video(ctx, SlowVideo(delay=0))
    ctx.overrides = {"skip_scenes": list(kept)}
    await set_running(session, "clips", run_id="r2")
    await run_step(ctx, p.id, "clips")
    step = await get_step(session, p.id, "clips")
    assert step.status == "awaiting_validation" and second.started == 2  # scènes 4 et 5 seulement
    scenes = (await session.scalars(select(Scene).where(Scene.project_id == p.id).order_by(Scene.position))).all()
    ids = step.result["asset_ids"]
    assert ids[:3] == [kept[s.id] for s in scenes[:3]] and len(ids) == 5 and len(set(ids)) == 5
    assert await session.scalar(select(func.count()).select_from(Asset).where(Asset.kind == "clip")) == 5  # pas de doublon
    assert await session.scalar(select(func.count()).select_from(ProviderCall).where(ProviderCall.status == "ok")) == 5


async def test_without_resume_every_scene_is_regenerated(session, ctx):
    p = await seed_scenes(session, 3)
    video = use_video(ctx, SlowVideo(delay=0))
    await set_running(session, "clips", run_id="r1")
    await run_step(ctx, p.id, "clips")
    await set_running(session, "clips", run_id="r2")
    await run_step(ctx, p.id, "clips")
    assert video.started == 6  # « Tout régénérer » : aucune scène ignorée


# --- Scènes manquantes ---------------------------------------------------------------------------------------------

async def test_only_missing_skips_every_scene_that_already_has_a_clip(api, session):
    pid, first = await project_with_failed_clips(api, session, scenes=4, done=2)
    await set_status(session, ["clips"], "awaiting_validation")  # quel que soit l'état de l'étape
    r = await api.post(f"/api/projects/{pid}/steps/clips/run", json={"only_missing": True})
    assert r.status_code == 202
    assert api.enqueued == [(pid, "clips", None, {"skip_scenes": sorted(s.id for s in first[:2])})]


async def test_only_missing_counts_any_variant_not_just_the_last_run(api, session):
    pid, first = await project_with_failed_clips(api, session, scenes=3, done=0)
    session.add(Asset(project_id=pid, scene_id=first[2].id, kind="clip", key="old", content_type="video/mp4",
                      meta={"run": "ancien"}))
    await session.commit()
    assert (await api.post(f"/api/projects/{pid}/steps/clips/run", json={"only_missing": True})).status_code == 202
    assert api.enqueued[0][3] == {"skip_scenes": [first[2].id]}


async def test_only_missing_refused_when_nothing_is_missing_or_it_does_not_apply(api, session):
    pid, first = await project_with_failed_clips(api, session, scenes=2, done=2)
    url = f"/api/projects/{pid}/steps/clips/run"
    r = await api.post(url, json={"only_missing": True})
    assert r.status_code == 409 and "Aucune scène manquante" in r.json()["detail"]
    assert (await api.post(url, json={"only_missing": True, "resume": True})).status_code == 422
    assert (await api.post(url, json={"only_missing": True, "scene_id": first[0].id})).status_code == 422
    assert (await api.post(f"/api/projects/{pid}/steps/idea/run", json={"only_missing": True})).status_code == 422
    assert api.enqueued == []


async def test_executor_regenerates_only_scenes_without_clip(session, ctx):
    p = await seed_scenes(session, 4)
    scenes = (await session.scalars(select(Scene).where(Scene.project_id == p.id).order_by(Scene.position))).all()
    old = [Asset(project_id=p.id, scene_id=s.id, kind="clip", key=f"old{s.position}", content_type="video/mp4")
           for s in scenes[:2]]
    session.add_all(old)
    await session.commit()
    video = use_video(ctx, SlowVideo(delay=0))
    ctx.overrides = {"skip_scenes": [s.id for s in scenes[:2]]}
    await set_running(session, "clips")
    await run_step(ctx, p.id, "clips")
    step = await get_step(session, p.id, "clips")
    assert video.started == 2 and step.result["asset_ids"][:2] == [a.id for a in old] and len(step.result["asset_ids"]) == 4


# --- Une seule scène : une seule requête au provider --------------------------------------------------------------

async def test_regenerating_one_scene_calls_the_provider_once(session, ctx):
    """Cinq scènes, une scène visée : UNE génération (ComfyUI : des minutes par clip), jamais la vidéo entière."""
    p = await seed_scenes(session, 5)
    scenes = (await session.scalars(select(Scene).where(Scene.project_id == p.id).order_by(Scene.position))).all()
    video = use_video(ctx, SlowVideo(delay=0))
    await set_running(session, "clips", run_id=f"scene:{scenes[4].id}")
    await run_step(ctx, p.id, "clips", scene_id=scenes[4].id)
    assert video.started == 1
    clips = (await session.scalars(select(Asset).where(Asset.kind == "clip"))).all()
    assert [c.scene_id for c in clips] == [scenes[4].id]


async def test_new_prompt_selects_the_new_clip_but_a_plain_new_variant_does_not(session, ctx):
    p = await seed_scenes(session, 2)
    scene = (await session.scalars(select(Scene).where(Scene.project_id == p.id).order_by(Scene.position))).first()
    use_video(ctx, SlowVideo(delay=0))
    await set_running(session, "clips")
    await run_step(ctx, p.id, "clips", scene_id=scene.id)
    first = scene.selected_clip_asset_id
    assert first is not None  # première variante : choisie d'office
    await set_running(session, "clips")
    await run_step(ctx, p.id, "clips", scene_id=scene.id)  # variante simple : le choix de l'utilisateur est conservé
    assert scene.selected_clip_asset_id == first
    ctx.overrides = {"select_new": True}
    await set_running(session, "clips")
    await run_step(ctx, p.id, "clips", scene_id=scene.id)  # nouveau prompt : le nouveau clip est choisi
    assert scene.selected_clip_asset_id not in (None, first)


# --- Nouveau prompt visuel d'une scène -------------------------------------------------------------------------------

async def scene_prompt(session, scene_id):
    return (await session.scalar(select(Scene.visual_prompt).where(Scene.id == scene_id)
                                 .execution_options(populate_existing=True)))


async def test_new_visual_prompt_is_saved_and_the_scene_regenerated(api, session):
    pid, first = await project_with_failed_clips(api, session)
    detailed = "Close-up of an octopus changing colour, slow dolly in, golden light, photorealistic, shallow depth"
    r = await api.post(f"/api/projects/{pid}/steps/clips/run", json={"scene_id": first[1].id, "visual_prompt": detailed})
    assert r.status_code == 202 and api.enqueued == [(pid, "clips", first[1].id, {"select_new": True})]
    assert await scene_prompt(session, first[1].id) == detailed
    assert await scene_prompt(session, first[0].id) == "p1"  # les autres scènes ne changent pas


async def test_visual_prompt_needs_clips_and_a_scene(api, session):
    pid, first = await project_with_failed_clips(api, session)
    url = f"/api/projects/{pid}/steps/clips/run"
    assert (await api.post(url, json={"visual_prompt": "x"})).status_code == 422  # sans scène
    assert (await api.post(f"/api/projects/{pid}/steps/voice/run",
                           json={"scene_id": first[0].id, "visual_prompt": "x"})).status_code == 422
    assert (await api.post(url, json={"scene_id": first[0].id, "visual_prompt": "   "})).status_code == 422
    assert (await api.post(url, json={"scene_id": first[0].id, "visual_prompt": "x" * 4001})).status_code == 422
    other = await new_project(api)
    assert (await api.post(f"/api/projects/{other}/steps/clips/run",
                           json={"scene_id": first[0].id, "visual_prompt": "x"})).status_code == 404
    assert await scene_prompt(session, first[0].id) == "p1" and api.enqueued == []


async def test_refused_launch_does_not_change_the_prompt(api, session):
    pid, first = await project_with_failed_clips(api, session)
    assert (await api.put("/api/settings", json={"project_budget_usd": "0.0001"})).status_code == 200
    session.add(ProviderCall(project_id=pid, step="clips", provider="fal", model="kling", cost_usd=1.0, status="ok"))
    await session.commit()
    r = await api.post(f"/api/projects/{pid}/steps/clips/run", json={"scene_id": first[0].id, "visual_prompt": "nouveau"})
    assert r.status_code == 409
    assert await scene_prompt(session, first[0].id) == "p1"


# --- Arrêter une génération en cours --------------------------------------------------------------------------------

async def test_cancel_marks_the_running_step_failed_and_keeps_what_was_produced(api, session):
    pid, first = await project_with_failed_clips(api, session, scenes=4, done=2)
    await session.execute(Step.__table__.update().where(Step.name == "clips").values(status="running", error=None))
    await session.execute(Step.__table__.update().where(Step.project_id == pid).values())
    await session.commit()
    project = await session.get(Project, pid)
    project.autopilot = True
    await session.commit()
    r = await api.post(f"/api/projects/{pid}/steps/clips/cancel")
    assert r.status_code == 202
    data = (await api.get(f"/api/projects/{pid}")).json()
    step = next(s for s in data["steps"] if s["name"] == "clips")
    assert step["status"] == "failed" and step["error"] == "Arrêtée par l'utilisateur"
    assert step["resume"] == {"done": 2, "total": 4}  # les scènes déjà produites se reprennent
    assert data["autopilot"] is False


async def test_cancel_refuses_a_step_that_is_not_running(api, session):
    pid, _ = await project_with_failed_clips(api, session)  # clips en échec, rien ne tourne
    r = await api.post(f"/api/projects/{pid}/steps/clips/cancel")
    assert r.status_code == 409 and "pas en cours" in r.json()["detail"]
    assert (await api.post(f"/api/projects/{pid}/steps/inconnue/cancel")).status_code == 404


async def test_running_step_exposes_its_scope_and_progress(api, session):
    """Pendant la génération, l'API dit s'il s'agit d'une scène ou de toutes (avec l'avancement)."""
    pid, first = await project_with_failed_clips(api, session, scenes=4, done=2)
    await session.execute(Step.__table__.update().where(Step.name == "clips").values(status="running"))
    await session.commit()
    step = await clips_step(api, pid)
    assert step["progress"] == {"done": 2, "total": 4} and step["target_scene"] is None  # toutes les scènes
    assert step["running_since"] is not None  # de quoi afficher le temps écoulé
    await session.execute(Step.__table__.update().where(Step.name == "clips").values(run_id=f"scene:{first[3].id}:ab12cd34"))
    await session.commit()
    step = await clips_step(api, pid)
    assert step["target_scene"] == first[3].id and step["progress"] is None  # une seule scène


async def test_running_since_is_only_reported_while_running(api, session):
    pid, _ = await project_with_failed_clips(api, session)
    assert (await clips_step(api, pid))["running_since"] is None  # en échec : rien ne tourne
