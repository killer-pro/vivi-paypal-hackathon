import json

import httpx
import pytest

from app.providers.base import ProviderError
from app.providers.comfycloud import KEY_MISSING, NO_PLAN, USD_PER_GPU_S, ComfyCloudImage, ComfyCloudProvider
from app.providers.workflows import CLOUD_UNETS

KEY = "comfyui-test"
SIGNED = "https://storage.example/v.mp4?sig=1"
OUTPUT = {"gifs": [{"filename": "v.mp4", "subfolder": "", "type": "output"}]}


class FakeCloud:
    """Comfy Cloud simulé : statut du job (`statuses`, un par lecture), historique, durée facturée et fichier servi par
    une URL signée ; requêtes enregistrées avec leurs en-têtes."""

    def __init__(self, statuses=("success",), prompt_response=None, history=None):
        self.statuses = list(statuses)
        self.prompt_response = prompt_response or httpx.Response(200, json={"prompt_id": "p"})
        self.history = history or {"status": {"status_str": "success"}, "outputs": {"9": OUTPUT}}
        self.requests: list[httpx.Request] = []

    def __call__(self, req: httpx.Request):
        self.requests.append(req)
        path = req.url.path
        if req.url.host == "storage.example":
            return httpx.Response(200, content=b"VID")
        if path == "/api/prompt":
            return self.prompt_response
        if path == "/api/job/p/status":
            return httpx.Response(200, json={"status": self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]})
        if path == "/api/history_v2/p":
            return httpx.Response(200, json={"p": self.history})
        if path == "/api/jobs/p":
            return httpx.Response(200, json={"execution_start_time": 1_000, "execution_end_time": 31_000})
        if path == "/api/view":
            return httpx.Response(302, headers={"location": SIGNED})
        if path in ("/api/queue", "/api/interrupt"):
            return httpx.Response(200)
        if path == "/api/user":
            return httpx.Response(200, json={"id": "u", "status": "active"})
        return httpx.Response(404)

    def posted_workflow(self) -> dict:
        return json.loads(next(r for r in self.requests if r.url.path == "/api/prompt").content)["prompt"]


def provider(cloud: FakeCloud, key: str = KEY) -> ComfyCloudProvider:
    return ComfyCloudProvider(key, httpx.AsyncClient(transport=httpx.MockTransport(cloud)), poll_interval=0.001)


async def test_clip_runs_the_cloud_graph_and_bills_the_gpu_time():
    cloud = FakeCloud(statuses=("pending", "in_progress", "success"))
    result = await provider(cloud).generate("A fox in the snow", model="fast", duration_s=3)
    assert result.data == b"VID" and result.model == "fast"
    assert result.cost_usd == pytest.approx(30 * USD_PER_GPU_S)  # 30 s de calcul facturées
    workflow = cloud.posted_workflow()
    loaders = [n for n in workflow.values() if n["class_type"] == "UNETLoader"]
    assert loaders and all(n["inputs"]["unet_name"] in CLOUD_UNETS.values() for n in loaders)
    assert not any(n["class_type"] == "UnetLoaderGGUF" for n in workflow.values())


async def test_the_key_goes_to_the_service_but_not_to_the_signed_url():
    cloud = FakeCloud()
    await provider(cloud).generate("A fox", model="fast", duration_s=3)
    for req in cloud.requests:
        assert (req.headers.get("x-api-key") == KEY) == (req.url.host != "storage.example")


@pytest.mark.parametrize("response", [
    httpx.Response(403, json={"error": {"type": "FREE_TIER_NOT_ALLOWED"}}),
    httpx.Response(402, json={"error": {"type": "FREE_TIER_EXHAUSTED"}}),
])
async def test_account_without_a_plan_gets_a_clear_non_retryable_error(response):
    with pytest.raises(ProviderError) as e:
        await provider(FakeCloud(prompt_response=response)).generate("A fox", model="fast", duration_s=3)
    assert str(e.value) == NO_PLAN and not e.value.retryable


async def test_failed_job_reports_the_workflow_error():
    history = {"status": {"status_str": "error", "messages": [
        ["execution_error", {"node_type": "UNETLoader", "exception_message": "model not found"}]]}, "outputs": {}}
    with pytest.raises(ProviderError, match="model not found"):
        await provider(FakeCloud(statuses=("error",), history=history)).generate("A fox", model="fast", duration_s=3)


async def test_missing_key_is_reported_before_any_call():
    cloud = FakeCloud()
    with pytest.raises(ProviderError, match="Comfy Cloud"):
        await provider(cloud, key="").generate("A fox", model="fast", duration_s=3)
    assert not cloud.requests
    assert all(not s.available and s.reason == KEY_MISSING for s in (await provider(cloud, key="").availability()).values())


async def test_reference_image_is_billed_too():
    cloud = FakeCloud()
    image = ComfyCloudImage(provider(cloud))
    result = await image.generate("A red sneaker", model=ComfyCloudImage.MODEL)
    assert result.data == b"VID" and result.cost_usd == pytest.approx(30 * USD_PER_GPU_S)
