import json
import re
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app.providers.base import Availability, ProviderError, plain_prompt, split_prompt
from app.providers.claude import PRICE_IN_PER_M, PRICE_OUT_PER_M, ClaudeLLM
from app.providers.comfyui import AVAILABILITY_TIMEOUT_S, MISSING_POLLS, ComfyUIProvider, frames_for
from app.providers.elevenlabs import ElevenLabsVoice
from app.providers.fal import FAL_KEY_MISSING, FalProvider
from app.providers.profiles import PROFILES, required_files


def client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fal_video_polls_then_downloads():
    calls = []

    def handler(req: httpx.Request):
        calls.append(req.url.path)
        if req.method == "POST":
            return httpx.Response(200, json={"request_id": "r1", "status_url": "https://q/s", "response_url": "https://q/r"})
        if str(req.url) == "https://q/s":
            status = "COMPLETED" if calls.count("/s") > 1 else "IN_PROGRESS"
            return httpx.Response(200, json={"status": status})
        if str(req.url) == "https://q/r":
            return httpx.Response(200, json={"video": {"url": "https://cdn/v.mp4"}})
        return httpx.Response(200, content=b"MP4DATA")

    p = FalProvider("k", client(handler), poll_interval=0)
    r = await p.generate("un chat", model="kling", duration_s=5)
    assert r.data == b"MP4DATA" and r.cost_usd == p.estimate_cost("kling", 5)


async def test_fal_image_flux():
    def handler(req: httpx.Request):
        if req.method == "POST":
            return httpx.Response(200, json={"status_url": "https://q/s", "response_url": "https://q/r"})
        if str(req.url) == "https://q/s":
            return httpx.Response(200, json={"status": "COMPLETED"})
        if str(req.url) == "https://q/r":
            return httpx.Response(200, json={"images": [{"url": "https://cdn/i.png"}]})
        return httpx.Response(200, content=b"PNG")

    r = await FalProvider("k", client(handler), poll_interval=0).generate("x", model="flux")
    assert r.data == b"PNG" and r.content_type == "image/png"


async def test_fal_empty_download_is_provider_error():
    def handler(req):
        if req.method == "POST":
            return httpx.Response(200, json={"status_url": "https://q/s", "response_url": "https://q/r"})
        if str(req.url) == "https://q/s":
            return httpx.Response(200, json={"status": "COMPLETED"})
        if str(req.url) == "https://q/r":
            return httpx.Response(200, json={"video": {"url": "https://cdn/v.mp4"}})
        return httpx.Response(200, content=b"")

    with pytest.raises(ProviderError, match="vide"):
        await FalProvider("k", client(handler), poll_interval=0).generate("x", model="kling", duration_s=5)


async def test_fal_5xx_is_retryable_4xx_is_not():
    with pytest.raises(ProviderError) as e5:
        await FalProvider("k", client(lambda r: httpx.Response(503)), poll_interval=0).generate("x", model="kling", duration_s=5)
    assert e5.value.retryable
    with pytest.raises(ProviderError) as e4:
        await FalProvider("k", client(lambda r: httpx.Response(402, text="quota")), poll_interval=0).generate("x", model="kling", duration_s=5)
    assert not e4.value.retryable


def unreachable(req):
    raise httpx.ConnectError("down")


async def test_comfyui_unreachable_is_non_retryable_and_health_false():
    p = ComfyUIProvider("http://c", client(unreachable))
    assert await p.health() is False
    with pytest.raises(ProviderError, match="injoignable") as e:
        await p.generate("x", model="fast", duration_s=5)
    assert not e.value.retryable


def object_info(files):
    """Réponses `GET /object_info/<classe>` listant `files` (ModelFile) dans leur nœud chargeur."""
    info: dict = {}
    for f in files:
        inputs = info.setdefault(f.node, {f.node: {"input": {"required": {}}}})[f.node]["input"]["required"]
        inputs.setdefault(f.field, [[], {}])[0].append(f.filename)
    return info


ALL_FILES = [f for profile in PROFILES for f in required_files(profile)]


def prompt_id(n: int) -> str:
    """Identifiant du n-ième prompt soumis à FakeComfy : `p`, puis `p2`, `p3`…"""
    return "p" if n == 1 else f"p{n}"


def done(*outputs):
    """Historique de prompts terminés dans l'ordre de soumission, une sortie chacun."""
    return {prompt_id(n): {"status": {"status_str": "success"}, "outputs": {"9": out}}
            for n, out in enumerate(outputs, 1)}


VIDEO_OUT = {"gifs": [{"filename": "v.mp4", "subfolder": "", "type": "output"}]}
KEYFRAME_OUT = {"images": [{"filename": "k.png", "subfolder": "video_virale", "type": "output"}]}
VIEWS = {"v.mp4": b"VID", "k.png": b"PNGDATA"}


class FakeComfy:
    """Serveur ComfyUI simulé : historique, file d'attente et modèles installés pilotés par le test, requêtes
    enregistrées."""

    def __init__(self, history=None, running=(), pending=(), info=None, uploaded_name="vv_keyframe.png"):
        self.history, self.running, self.pending = history or {}, list(running), list(pending)
        self.info = object_info(ALL_FILES) if info is None else info
        self.uploaded_name = uploaded_name
        self.requests: list[tuple[str, str, dict | bytes | None]] = []

    def __call__(self, req: httpx.Request):
        is_json = req.headers.get("content-type") == "application/json"
        body = json.loads(req.content) if is_json and req.content else (req.content or None)
        self.requests.append((req.method, req.url.path, body))
        path = req.url.path
        if path == "/prompt":
            return httpx.Response(200, json={"prompt_id": prompt_id(len(self.posted("/prompt")))})
        if path.startswith("/history/"):
            return httpx.Response(200, json=self.history)
        if path == "/queue" and req.method == "GET":
            item = lambda pid: [0, pid, {}, {}, []]  # noqa: E731
            return httpx.Response(200, json={"queue_running": [item(i) for i in self.running],
                                             "queue_pending": [item(i) for i in self.pending]})
        if path in ("/queue", "/interrupt"):
            return httpx.Response(200)
        if path == "/view" and req.url.params["filename"] in VIEWS:
            return httpx.Response(200, content=VIEWS[req.url.params["filename"]])
        if path == "/upload/image":
            return httpx.Response(200, json={"name": self.uploaded_name, "subfolder": "", "type": "input"})
        if path == "/system_stats":
            return httpx.Response(200, json={"system": {}})
        if path.startswith("/object_info/") and (node := path.removeprefix("/object_info/")) in self.info:
            return httpx.Response(200, json=self.info[node])
        return httpx.Response(404)

    def posted(self, path):
        return [b for m, p, b in self.requests if m == "POST" and p == path]

    def workflows(self):
        return [b["prompt"] for b in self.posted("/prompt")]


def node(workflow, class_type):
    return next(n["inputs"] for n in workflow.values() if n["class_type"] == class_type)


@pytest.mark.parametrize("running, pending, path, body", [
    (["p"], [], "/interrupt", {"prompt_id": "p"}),
    (["autre"], ["p"], "/queue", {"delete": ["p"]}),
])
async def test_comfyui_timeout_cancels_its_prompt(running, pending, path, body):
    import asyncio

    comfy = FakeComfy(running=running, pending=pending)
    p = ComfyUIProvider("http://c", client(comfy), poll_interval=0.01)
    with pytest.raises(TimeoutError):  # comme tracked_call : asyncio.wait_for annule generate()
        await asyncio.wait_for(p.generate("x", model="fast", duration_s=2), 0.1)
    assert comfy.posted(path) == [body]
    assert comfy.posted("/interrupt" if path == "/queue" else "/queue") == []  # jamais le prompt d'un autre


async def test_comfyui_keyframe_stage_is_cancelled_too():
    import asyncio

    comfy = FakeComfy(running=["p"])  # l'image Flux tourne encore quand l'appel est abandonné
    p = ComfyUIProvider("http://c", client(comfy), poll_interval=0.01)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(p.generate("x", model="precision", duration_s=2), 0.1)
    assert comfy.posted("/interrupt") == [{"prompt_id": "p"}] and len(comfy.workflows()) == 1


async def test_comfyui_workflow_error_is_reported_with_comfy_message():
    status = {"status_str": "error", "completed": False, "messages": [
        ["execution_start", {"prompt_id": "p"}],
        ["execution_error", {"node_type": "KSampler", "exception_message": "MPS backend out of memory"}]]}
    comfy = FakeComfy(history={"p": {"status": status, "outputs": {}}})
    with pytest.raises(ProviderError, match="KSampler.*MPS backend out of memory") as e:
        await ComfyUIProvider("http://c", client(comfy), poll_interval=0).generate("x", model="fast", duration_s=2)
    assert not e.value.retryable


async def test_comfyui_prompt_vanished_from_queue_fails_fast():
    comfy = FakeComfy()  # ni dans l'historique ni dans la file : ComfyUI a redémarré
    with pytest.raises(ProviderError, match="introuvable") as e:
        await ComfyUIProvider("http://c", client(comfy), poll_interval=0).generate("x", model="fast", duration_s=2)
    assert not e.value.retryable
    assert sum(1 for m, path, _ in comfy.requests if path == "/history/p") == MISSING_POLLS


async def test_comfyui_prompt_still_queued_keeps_polling():
    comfy = FakeComfy(pending=["p"])

    def handler(req):
        if req.url.path == "/history/p" and sum(1 for r in comfy.requests if r[1] == "/history/p") >= MISSING_POLLS + 2:
            comfy.history = done(VIDEO_OUT)
        return comfy(req)

    r = await ComfyUIProvider("http://c", client(handler), poll_interval=0).generate("x", model="fast", duration_s=2)
    assert r.data == b"VID"


async def test_fast_profile_posts_one_320x576_workflow():
    comfy = FakeComfy(history=done(VIDEO_OUT, VIDEO_OUT))
    p = ComfyUIProvider("http://c", client(comfy), poll_interval=0)
    r = await p.generate('un "chat"', model="fast", duration_s=3)
    await p.generate('un "chat"', model="fast", duration_s=3)
    first, second = comfy.workflows()
    latent = node(first, "EmptyHunyuanLatentVideo")
    assert (latent["width"], latent["height"], latent["length"]) == (320, 576, 49)  # 3 s à 16 fps, 4n+1
    assert 'un "chat"' in [n["inputs"].get("text") for n in first.values()]
    assert node(first, "KSamplerAdvanced")["noise_seed"] != node(second, "KSamplerAdvanced")["noise_seed"]
    assert comfy.posted("/upload/image") == []
    assert (r.data, r.content_type, r.cost_usd, r.model, r.keyframe) == (b"VID", "video/mp4", 0.0, "fast", None)


async def test_precision_chains_keyframe_then_i2v():
    comfy = FakeComfy(history=done(KEYFRAME_OUT, VIDEO_OUT))
    r = await ComfyUIProvider("http://c", client(comfy), poll_interval=0).generate("renard", model="precision",
                                                                                     duration_s=3)
    keyframe, i2v = comfy.workflows()
    assert node(keyframe, "EmptySD3LatentImage")["width"] == 576 and "LoadImage" not in str(keyframe)
    (upload,) = comfy.posted("/upload/image")
    # un seul fichier dans input/ de ComfyUI, réécrit à chaque run (LoadImage hache son contenu : pas de cache périmé)
    assert re.search(rb'name="image"; filename="vv_keyframe\.png"', upload) and b"PNGDATA" in upload
    assert re.search(rb'name="overwrite"\r\n\r\ntrue', upload)
    assert node(i2v, "LoadImage")["image"] == "vv_keyframe.png"  # nom renvoyé par ComfyUI
    assert node(i2v, "WanImageToVideo")["width"] == 384
    order = [path for m, path, _ in comfy.requests if path in ("/view", "/upload/image", "/prompt")]
    assert order == ["/prompt", "/view", "/upload/image", "/prompt", "/view"]
    assert (r.data, r.keyframe, r.model) == (b"VID", b"PNGDATA", "precision")


async def test_concurrent_precision_runs_never_overwrite_a_keyframe_still_in_use():
    """Deux jobs à la fois (worker `max_jobs = 2`) : l'image de départ partagée n'est réécrite qu'une fois l'animation
    qui la lit terminée."""
    import asyncio

    submitted: dict[str, dict] = {}
    polls: dict[str, int] = {}
    order: list[str] = []

    class Comfy(FakeComfy):
        def __call__(self, req):
            path = req.url.path
            resp = super().__call__(req)
            if path == "/prompt":
                submitted[resp.json()["prompt_id"]] = json.loads(req.content)["prompt"]
            elif path == "/upload/image":
                order.append("upload")
            elif path.startswith("/history/"):
                pid = path.removeprefix("/history/")
                is_i2v = "LoadImage" in str(submitted[pid])
                polls[pid] = polls.get(pid, 0) + 1
                if is_i2v and polls[pid] < 3:  # animation en cours : l'autre run avance pendant ce temps
                    self.pending = [pid]
                    return httpx.Response(200, json={})
                if is_i2v:
                    order.append("i2v fini")
                out = VIDEO_OUT if is_i2v else KEYFRAME_OUT
                return httpx.Response(200, json={pid: {"status": {"status_str": "success"}, "outputs": {"9": out}}})
            return resp

    comfy = Comfy()
    await asyncio.gather(*(ComfyUIProvider("http://c", client(comfy), poll_interval=0).generate(
        prompt, model="precision", duration_s=3) for prompt in ("a", "b")))
    assert order == ["upload", "i2v fini", "upload", "i2v fini"]


async def test_retry_after_an_i2v_failure_reuses_the_keyframe():
    """Nouvelle tentative de `tracked_call` (même provider, même prompt) après un échec relançable de l'animation :
    l'image Flux déjà produite (≈ 2 min) est réutilisée."""
    comfy = FakeComfy(history=done(KEYFRAME_OUT, VIDEO_OUT, KEYFRAME_OUT, VIDEO_OUT))
    failures = [503]

    def handler(req):
        if req.url.path == "/prompt" and "LoadImage" in req.content.decode() and failures:
            return httpx.Response(failures.pop())
        return comfy(req)

    p = ComfyUIProvider("http://c", client(handler), poll_interval=0)
    with pytest.raises(ProviderError) as e:
        await p.generate("renard", model="precision", duration_s=3)
    assert e.value.retryable
    r = await p.generate("renard", model="precision", duration_s=3)
    flux = [w for w in comfy.workflows() if "LoadImage" not in str(w)]
    assert len(flux) == 1 and len(comfy.posted("/upload/image")) == 2 and r.keyframe == b"PNGDATA"
    await p.generate("renard", model="precision", duration_s=3)  # réussite : l'image n'est plus gardée
    assert len([w for w in comfy.workflows() if "LoadImage" not in str(w)]) == 2


async def test_same_prompt_twice_at_once_on_one_provider_does_not_crash():
    """Hors du cas normal (une instance par job, un clip ComfyUI à la fois) : un second appel au même prompt pendant
    l'animation du premier reprend l'image gardée, et l'oubli de cette image ne fait pas échouer l'un des deux."""
    import asyncio

    comfy = FakeComfy(history=done(KEYFRAME_OUT, VIDEO_OUT, VIDEO_OUT))
    animating = asyncio.Event()

    async def handler(req):
        if req.url.path == "/history/p2" and not animating.is_set():  # première animation en cours
            animating.set()
            await asyncio.sleep(0.05)
        return comfy(req)

    p = ComfyUIProvider("http://c", client(handler), poll_interval=0)
    first = asyncio.create_task(p.generate("renard", model="precision", duration_s=3))
    await animating.wait()
    second = await p.generate("renard", model="precision", duration_s=3)  # attend le verrou, sans refaire Flux
    assert (await first).data == second.data == b"VID" and len(comfy.workflows()) == 3


async def test_legacy_workflow_model_runs_as_max():
    comfy = FakeComfy(history=done(VIDEO_OUT))
    r = await ComfyUIProvider("http://c", client(comfy), poll_interval=0).generate("x", model="workflow", duration_s=3)
    (workflow,) = comfy.workflows()
    assert node(workflow, "EmptyHunyuanLatentVideo")["width"] == 480 and "ImageUpscaleWithModel" in str(workflow)
    assert r.model == "max"


async def test_unknown_profile_is_a_clear_error():
    comfy = FakeComfy()
    with pytest.raises(ProviderError, match="comfyui: profil inconnu : turbo") as e:
        await ComfyUIProvider("http://c", client(comfy)).generate("x", model="turbo", duration_s=3)
    assert not e.value.retryable and comfy.requests == []


def test_comfyui_models_are_the_profiles_and_frames_are_4n_plus_1_at_16fps():
    assert ComfyUIProvider.models == ["fast", "balanced", "precision", "max"]
    assert [frames_for(d) for d in (2, 3, 5, 30)] == [33, 49, 81, 81]  # Wan 2.2 14B : 16 fps, 5 s max
    assert all((frames_for(d) - 1) % 4 == 0 for d in (0.1, 1.7, 2.5, 4.2)) and frames_for(0.01) == 1


async def test_availability_reports_unreachable_and_missing_file():
    down = await ComfyUIProvider("http://c", client(unreachable)).availability()  # connexion refusée : pas « occupé »
    assert down == {m: Availability(False, "ComfyUI injoignable") for m in ComfyUIProvider.models}

    lora = "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors"
    comfy = FakeComfy(info=object_info([f for f in ALL_FILES if f.filename != lora]))
    report = await ComfyUIProvider("http://c", client(comfy)).availability()
    assert report["precision"] == Availability(False, f"Modèle manquant : {lora}")
    assert report["fast"] == report["balanced"] == report["max"] == Availability(True)
    assert {path for _, path, _ in comfy.requests} == {"/system_stats"} | {f"/object_info/{f.node}" for f in ALL_FILES}


async def test_availability_without_a_loader_node_names_the_missing_file():
    info = object_info(ALL_FILES)
    del info["UpscaleModelLoader"]  # nœud absent : ComfyUI répond 404
    report = await ComfyUIProvider("http://c", client(FakeComfy(info=info))).availability()
    assert report["max"] == Availability(False, "Modèle manquant : ESRGAN/4x-UltraSharp.pth")
    assert report["fast"].available


async def test_availability_reads_the_combo_input_format():
    info = {node: {node: {"input": {"required": {field: ["COMBO", {"options": files}]
                                                 for field, (files, _) in spec[node]["input"]["required"].items()}}}}
            for node, spec in object_info(ALL_FILES).items()}  # format récent de ComfyUI
    report = await ComfyUIProvider("http://c", client(FakeComfy(info=info))).availability()
    assert all(a.available for a in report.values())


@pytest.mark.parametrize("body", [
    [],  # liste au lieu d'un objet
    {"UnetLoaderGGUF": {"input": "?"}},  # `input` qui n'est pas un objet
    {"UnetLoaderGGUF": {"input": {"required": {"unet_name": ["COMBO"]}}}},  # COMBO sans options
    {"UnetLoaderGGUF": {"input": {"required": {"unet_name": ["COMBO", "x"]}}}},  # options qui ne sont pas un objet
    {"UnetLoaderGGUF": {"input": {"required": {"unet_name": [None]}}}},  # pas de liste de fichiers
    {"UnetLoaderGGUF": {"input": {"required": {"unet_name": "Wan2.2-T2V-A14B-HighNoise-Q4_K_M.gguf"}}}},
])
async def test_availability_degrades_on_malformed_object_info(body):
    info = {**object_info(ALL_FILES), "UnetLoaderGGUF": body}
    report = await ComfyUIProvider("http://c", client(FakeComfy(info=info))).availability()
    missing = Availability(False, "Modèle manquant : Wan2.2-T2V-A14B-HighNoise-Q4_K_M.gguf")
    assert report["fast"] == report["balanced"] == report["max"] == missing and not report["precision"].available


async def test_availability_uses_a_short_timeout_per_request():
    """`GET /providers/models` et chaque lancement des clips attendent la disponibilité : jamais le timeout de 120 s du
    client, et un ComfyUI qui ne répond pas dans ce délai est signalé occupé (pas injoignable)."""
    comfy = FakeComfy()
    timeouts = []

    def handler(req):
        timeouts.append(req.extensions["timeout"])
        return comfy(req)

    report = await ComfyUIProvider("http://c", client(handler)).availability()
    assert all(state.available for state in report.values())
    short = {"connect": AVAILABILITY_TIMEOUT_S, "read": AVAILABILITY_TIMEOUT_S, "write": AVAILABILITY_TIMEOUT_S,
             "pool": AVAILABILITY_TIMEOUT_S}
    assert len(timeouts) > 1 and all(t == short for t in timeouts) and AVAILABILITY_TIMEOUT_S <= 5

    def hangs(req):
        raise httpx.ReadTimeout("silence")

    report = await ComfyUIProvider("http://c", client(hangs)).availability()
    assert set(report.values()) == {Availability(True, "ComfyUI ne répond pas (occupé ?)")}


def slow_comfy(delay_s: float):
    """ComfyUI qui répond à chaque `GET /object_info/<nœud>` après `delay_s` secondes."""
    import asyncio

    comfy = FakeComfy()

    async def handler(req):
        if req.url.path.startswith("/object_info/"):
            await asyncio.sleep(delay_s)
        return comfy(req)

    return client(handler)


async def test_availability_queries_the_loader_nodes_together(monkeypatch):
    """Les nœuds chargeurs sont interrogés ensemble : 7 réponses de 0,2 s tiennent dans un délai total de 0,5 s."""
    from app.providers import comfyui

    monkeypatch.setattr(comfyui, "AVAILABILITY_TIMEOUT_S", 0.5)
    report = await ComfyUIProvider("http://c", slow_comfy(0.2)).availability()
    assert all(state.available for state in report.values())


async def test_availability_is_bounded_as_a_whole(monkeypatch):
    """Le délai borne tout l'appel (il tient le verrou du projet au lancement des clips), pas chaque requête."""
    import time

    from app.providers import comfyui

    monkeypatch.setattr(comfyui, "AVAILABILITY_TIMEOUT_S", 0.3)
    start = time.monotonic()
    report = await ComfyUIProvider("http://c", slow_comfy(1)).availability()  # 1 s par requête, 0,3 s au total
    assert time.monotonic() - start < 0.6
    assert set(report.values()) == {Availability(True, "ComfyUI ne répond pas (occupé ?)")}


async def test_invalid_comfyui_url_is_unreachable_not_a_crash():
    p = ComfyUIProvider("http://c:port", client(FakeComfy()))  # httpx.InvalidURL, hors TransportError
    assert set((await p.availability()).values()) == {Availability(False, "ComfyUI injoignable")}
    assert await p.health() is False
    with pytest.raises(ProviderError, match="ComfyUI injoignable") as e:
        await p.generate("x", model="fast", duration_s=3)
    assert not e.value.retryable


async def test_upload_without_name_is_a_clear_error():
    comfy = FakeComfy(history=done(KEYFRAME_OUT, VIDEO_OUT))

    def handler(req):
        if req.url.path == "/upload/image":
            return httpx.Response(200, json={"subfolder": "", "type": "input"})
        return comfy(req)

    with pytest.raises(ProviderError, match="comfyui: envoi de l'image de départ sans nom de fichier en retour"):
        await ComfyUIProvider("http://c", client(handler), poll_interval=0).generate("x", model="precision", duration_s=3)


async def test_fal_availability_requires_a_key():
    assert await FalProvider("", client(unreachable)).availability() == {
        m: Availability(False, FAL_KEY_MISSING) for m in FalProvider.models}
    assert await FalProvider("k", client(unreachable)).availability() == {m: Availability(True) for m in FalProvider.models}


async def test_elevenlabs_returns_audio_and_cost():
    def handler(req):
        assert req.headers["xi-api-key"] == "k" and "/text-to-speech/v1" in req.url.path
        return httpx.Response(200, content=b"MP3")

    r = await ElevenLabsVoice("k", client(handler)).synthesize("bonjour", voice_id="v1")
    assert r.data == b"MP3" and r.cost_usd > 0


async def test_elevenlabs_429_is_retryable():
    with pytest.raises(ProviderError) as e:
        await ElevenLabsVoice("k", client(lambda r: httpx.Response(429))).synthesize("x", voice_id="v")
    assert e.value.retryable


async def test_claude_complete_computes_cost():
    async def create(**kwargs):
        assert kwargs["system"] == "sys"
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="salut")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )

    fake = SimpleNamespace(messages=SimpleNamespace(create=create))
    r = await ClaudeLLM("key", client=fake).complete("sys", "hello")
    assert r.text == "salut"
    assert r.cost_usd == pytest.approx((10 * PRICE_IN_PER_M + 5 * PRICE_OUT_PER_M) / 1_000_000)


async def test_claude_empty_reply_is_error():
    async def create(**kwargs):
        return SimpleNamespace(content=[], usage=SimpleNamespace(input_tokens=1, output_tokens=0))

    fake = SimpleNamespace(messages=SimpleNamespace(create=create))
    with pytest.raises(ProviderError, match="vide"):
        await ClaudeLLM("key", client=fake).complete("s", "p")


def fal_handler(calls, *, status_errors=(), download_status=200):
    """Faux fal : `status_errors` = codes HTTP renvoyés successivement par le polling avant de réussir."""
    errors = list(status_errors)

    def handler(req: httpx.Request):
        calls.append((req.method, str(req.url)))
        if req.method == "POST":
            calls[-1] += (json.loads(req.content),)
            return httpx.Response(200, json={"status_url": "https://q/s", "response_url": "https://q/r"})
        if str(req.url) == "https://q/s":
            return httpx.Response(errors.pop(0)) if errors else httpx.Response(200, json={"status": "COMPLETED"})
        if str(req.url) == "https://q/r":
            return httpx.Response(200, json={"video": {"url": "https://cdn/v.mp4"}})
        return httpx.Response(download_status, content=b"MP4")

    return handler


def posts(calls):
    return [c for c in calls if c[0] == "POST"]


async def test_fal_polling_5xx_is_retried_in_place_without_resubmitting(session):
    from app.services.costs import tracked_call

    calls = []
    p = FalProvider("k", client(fal_handler(calls, status_errors=[502])), poll_interval=0)
    r = await tracked_call(session, project_id=None, step="clips", provider="fal", model="kling", base_delay=0,
                           fn=lambda: p.generate("x", model="kling", duration_s=5))
    assert r.data == b"MP4" and len(posts(calls)) == 1  # soumission payante envoyée une seule fois


async def test_fal_error_after_submit_is_not_retryable(session):
    from app.services.costs import tracked_call

    calls = []
    p = FalProvider("k", client(fal_handler(calls, status_errors=[503] * 50)), poll_interval=0)
    with pytest.raises(ProviderError) as e:
        await tracked_call(session, project_id=None, step="clips", provider="fal", model="kling", base_delay=0,
                           fn=lambda: p.generate("x", model="kling", duration_s=5))
    assert not e.value.retryable and len(posts(calls)) == 1
    calls.clear()
    p = FalProvider("k", client(fal_handler(calls, download_status=500)), poll_interval=0)
    with pytest.raises(ProviderError) as e:
        await p.generate("x", model="kling", duration_s=5)
    assert not e.value.retryable and len(posts(calls)) == 1


@pytest.mark.parametrize(("scene_s", "billed_s"), [(3, 5), (5, 5), (5.5, 10), (8, 10), (14, 10)])
async def test_fal_kling_duration_rounded_to_allowed_value(scene_s, billed_s):
    calls = []
    p = FalProvider("k", client(fal_handler(calls)), poll_interval=0)
    r = await p.generate("x", model="kling", duration_s=scene_s)
    assert posts(calls)[0][2]["duration"] == str(billed_s)
    assert r.cost_usd == p.estimate_cost("kling", scene_s) == p.estimate_cost("kling", billed_s)


@pytest.mark.parametrize("model", ["wan", "ltx"])
async def test_fal_models_without_duration_param_bill_their_fixed_length(model):
    calls = []
    p = FalProvider("k", client(fal_handler(calls)), poll_interval=0)
    r = await p.generate("x", model=model, duration_s=3)
    assert "duration" not in posts(calls)[0][2]
    assert r.cost_usd == p.estimate_cost(model, 3) == p.estimate_cost(model, 8)


def test_claude_sdk_does_not_retry_itself():
    assert ClaudeLLM("key")._c.max_retries == 0  # tracked_call gère les retries (et les journalise)


async def test_elevenlabs_health_checks_the_key():
    def handler(request):
        return httpx.Response(200 if request.headers.get("xi-api-key") == "bonne" else 401)

    assert await ElevenLabsVoice("bonne", client(handler)).health() is True
    assert await ElevenLabsVoice("mauvaise", client(handler)).health() is False
    assert await ElevenLabsVoice("", client(handler)).health() is False  # sans clé : aucun appel


async def test_claude_health_is_false_without_key_and_when_the_key_is_refused():
    assert await ClaudeLLM("").health() is False

    async def refused(**kwargs):
        raise anthropic.APIConnectionError(request=httpx.Request("GET", "https://api.anthropic.com/v1/models"))

    async def listed(**kwargs):
        return SimpleNamespace(data=[])

    assert await ClaudeLLM("k", client=SimpleNamespace(models=SimpleNamespace(list=refused))).health() is False
    assert await ClaudeLLM("k", client=SimpleNamespace(models=SimpleNamespace(list=listed))).health() is True


async def test_a_reference_image_makes_every_profile_place_it_with_kontext_then_animate_it():
    comfy = FakeComfy(history=done(KEYFRAME_OUT, VIDEO_OUT))
    r = await ComfyUIProvider("http://c", client(comfy), poll_interval=0).generate(
        "renard qui court", model="fast", duration_s=3, image=b"REFPNG")
    kontext, i2v = comfy.workflows()
    uploads = comfy.posted("/upload/image")
    assert re.search(rb'filename="vv_reference\.png"', uploads[0]) and b"REFPNG" in uploads[0]
    assert "ReferenceLatent" in str(kontext) and "flux1-kontext-dev-Q4_K_S.gguf" in str(kontext)
    assert "same character" in node(kontext, "CLIPTextEncode")["text"] and "renard qui court" in str(kontext)
    assert re.search(rb'filename="vv_keyframe\.png"', uploads[1])
    assert node(i2v, "WanImageToVideo")["width"] == 320 and "Wan2.2-I2V" in str(i2v)  # résolution du profil Rapide
    assert (r.data, r.keyframe, r.model) == (b"VID", b"PNGDATA", "fast")


async def test_extra_reference_images_are_all_sent_to_kontext_in_order():
    comfy = FakeComfy(history=done(KEYFRAME_OUT, VIDEO_OUT))
    await ComfyUIProvider("http://c", client(comfy), poll_interval=0).generate(
        "renard", model="fast", duration_s=3, image=b"LASTFRAME", references=[b"HEROPNG", b"BAGPNG"])
    kontext, _i2v = comfy.workflows()
    uploads = comfy.posted("/upload/image")
    assert [bool(re.search(rb'filename="vv_reference(_\d)?\.png"', u)) for u in uploads[:3]] == [True, True, True]
    assert b"LASTFRAME" in uploads[0] and b"HEROPNG" in uploads[1] and b"BAGPNG" in uploads[2]
    assert len([n for n in kontext.values() if n["class_type"] == "ReferenceLatent"]) == 3


async def test_precision_with_a_reference_uses_kontext_not_flux_dev():
    comfy = FakeComfy(history=done(KEYFRAME_OUT, VIDEO_OUT))
    await ComfyUIProvider("http://c", client(comfy), poll_interval=0).generate(
        "x", model="precision", duration_s=3, image=b"REFPNG")
    first, _ = comfy.workflows()
    assert "flux1-kontext-dev-Q4_K_S.gguf" in str(first) and "flux1-dev-Q4_K_S.gguf" not in str(first)


async def test_reference_availability_also_requires_wan_i2v_and_kontext():
    kontext = "flux1-kontext-dev-Q4_K_S.gguf"
    files = [f for f in ALL_FILES if f.filename != kontext]
    p = ComfyUIProvider("http://c", client(FakeComfy(info=object_info(files))))
    assert (await p.availability())["fast"] == Availability(True)  # sans référence, Kontext n'est pas nécessaire
    assert await p.reference_availability("fast") == Availability(False, f"Modèle manquant : {kontext}")


SPLIT_PROMPT = "A red fox stands in snow, golden light.\n\nMotion: the fox runs toward the camera. Slow dolly in."


async def test_each_model_gets_its_part_of_a_two_paragraph_prompt():
    """Kontext dessine l'image fixe, Wan I2V n'anime qu'avec le mouvement, Wan T2V lit tout sans l'étiquette."""
    comfy = FakeComfy(history=done(KEYFRAME_OUT, VIDEO_OUT))
    await ComfyUIProvider("http://c", client(comfy), poll_interval=0).generate(
        SPLIT_PROMPT, model="fast", duration_s=3, image=b"REFPNG")
    kontext, i2v = comfy.workflows()
    assert "A red fox stands" in node(kontext, "CLIPTextEncode")["text"] and "dolly" not in str(kontext)
    assert node(i2v, "CLIPTextEncode")["text"] == "the fox runs toward the camera. Slow dolly in."

    comfy = FakeComfy(history=done(VIDEO_OUT))
    await ComfyUIProvider("http://c", client(comfy), poll_interval=0).generate(SPLIT_PROMPT, model="fast", duration_s=3)
    (t2v,) = comfy.workflows()
    assert node(t2v, "CLIPTextEncode")["text"] == (
        "A red fox stands in snow, golden light. the fox runs toward the camera. Slow dolly in.")


async def test_a_prompt_without_motion_paragraph_is_used_everywhere_as_before():
    comfy = FakeComfy(history=done(KEYFRAME_OUT, VIDEO_OUT))
    await ComfyUIProvider("http://c", client(comfy), poll_interval=0).generate(
        "renard qui court", model="fast", duration_s=3, image=b"REFPNG")
    _, i2v = comfy.workflows()
    assert node(i2v, "CLIPTextEncode")["text"] == "renard qui court"


def test_split_and_plain_prompt():
    assert split_prompt(SPLIT_PROMPT) == ("A red fox stands in snow, golden light.",
                                          "the fox runs toward the camera. Slow dolly in.")
    assert split_prompt("seul") == ("seul", "") and plain_prompt("seul") == "seul"
    assert plain_prompt("a\n\nmotion :  b") == "a b"


async def test_a_composed_start_image_replaces_kontext_and_is_animated_as_is():
    comfy = FakeComfy(history=done(VIDEO_OUT))
    r = await ComfyUIProvider("http://c", client(comfy), poll_interval=0).generate(
        "renard qui court", model="fast", duration_s=3, image=b"REFPNG", start_image=b"GEMINIPNG")
    (i2v,) = comfy.workflows()  # aucun graphe Kontext
    uploads = comfy.posted("/upload/image")
    assert len(uploads) == 1 and b"GEMINIPNG" in uploads[0] and b"REFPNG" not in uploads[0]
    assert "Wan2.2-I2V" in str(i2v) and "ReferenceLatent" not in str(i2v)
    assert (r.data, r.keyframe) == (b"VID", b"GEMINIPNG")
