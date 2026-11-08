"""Contrôle du modèle vidéo au lancement des clips (`services/video_models.py`), partagé par l'API et l'autopilot."""
from app.providers.base import Availability
from tests.test_api_steps import new_project, set_status

# ComfyUI occupé : carte lançable, avec un avertissement (même état pour la carte et le contrôle au lancement)
BUSY = Availability(True, "ComfyUI ne répond pas (occupé ?)")


async def comfy_availability(monkeypatch, state):
    from app.config import settings
    from app.providers.comfyui import ComfyUIProvider

    monkeypatch.setattr(settings, "fake_providers", False)

    async def availability(self):
        return dict.fromkeys(ComfyUIProvider.models, state)

    monkeypatch.setattr(ComfyUIProvider, "availability", availability)


async def test_busy_comfyui_does_not_block_the_launch(api, session, monkeypatch):
    """ComfyUI qui ne répond pas dans le délai (occupé par une longue génération, swap saturé) : le job est enfilé et
    attend son tour, comme avant le contrôle au lancement."""
    await comfy_availability(monkeypatch, BUSY)
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script"], "approved")
    r = await api.post(f"/api/projects/{pid}/steps/clips/run", json={"provider": "comfyui", "model": "fast"})
    assert r.status_code == 202 and api.enqueued == [(pid, "clips", None, {"provider": "comfyui", "model": "fast"})]


async def test_unreachable_comfyui_blocks_the_launch(api, session, monkeypatch):
    await comfy_availability(monkeypatch, Availability(False, "ComfyUI injoignable"))
    pid = await new_project(api)
    await set_status(session, ["idea", "story", "script"], "approved")
    r = await api.post(f"/api/projects/{pid}/steps/clips/run", json={"provider": "comfyui", "model": "fast"})
    assert r.status_code == 409 and r.json()["detail"] == "ComfyUI injoignable" and api.enqueued == []


async def test_busy_comfyui_card_stays_available_with_its_warning(api, monkeypatch):
    await comfy_availability(monkeypatch, BUSY)
    local = [c for c in (await api.get("/api/providers/models")).json()["video"] if c["provider"] == "comfyui"]
    assert {(c["available"], c["reason"]) for c in local} == {(True, "ComfyUI ne répond pas (occupé ?)")}


async def test_comfy_cloud_cards_are_the_profiles_priced_in_dollars(api, monkeypatch):
    """Comfy Cloud exécute les mêmes profils que ComfyUI, facturés au temps de calcul : coût par clip au lieu d'une
    durée, jamais recommandé (le choix par défaut reste gratuit)."""
    from app.config import settings
    from app.providers.comfycloud import ComfyCloudProvider

    monkeypatch.setattr(settings, "fake_providers", False)
    monkeypatch.setattr(settings, "comfy_cloud_api_key", "comfyui-key")
    await comfy_availability(monkeypatch, Availability(True))
    cards = {c["id"]: c for c in (await api.get("/api/providers/models")).json()["video"] if c["provider"] == "comfycloud"}
    assert list(cards) == ComfyCloudProvider.models
    fast = cards["fast"]
    assert fast["available"] and fast["minutes_per_clip"] is None and not fast["recommended"] and not fast["locked"]
    assert fast["cost_usd_per_clip"] == ComfyCloudProvider("k", None).estimate_cost("fast", 3) > 0  # type: ignore[arg-type]
