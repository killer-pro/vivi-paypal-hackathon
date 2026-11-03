"""Provider sans clé API : erreur claire et non relançable avant toute requête (au lieu d'un en-tête invalide
« Key  » refusé par httpx, ou d'une requête refusée par le service), carte grisée, lancement de l'image de référence
refusé d'emblée."""
import httpx
import pytest

from app.models import Step
from app.providers.base import Availability, ProviderError
from app.providers.claude import ClaudeLLM
from app.providers.elevenlabs import ElevenLabsVoice
from app.providers.fal import FAL_KEY_MISSING, FalProvider
from app.providers.gemini import DEFAULT_IMAGE_MODEL, GeminiImage, GeminiLLM, image_models
from app.providers.gemini import KEY_MISSING as GEMINI_KEY_MISSING


def no_request(req):
    raise AssertionError(f"aucune requête attendue sans clé : {req.url}")


def client():
    return httpx.AsyncClient(transport=httpx.MockTransport(no_request))


CALLS = {
    "fal image": (lambda key: FalProvider(key, client()).generate("p", model="flux"),
                  "Clé API fal manquante, à saisir dans Réglages → fal.ai"),
    "fal vidéo": (lambda key: FalProvider(key, client()).generate("p", model="kling", duration_s=5),
                  "Clé API fal manquante, à saisir dans Réglages → fal.ai"),
    "elevenlabs": (lambda key: ElevenLabsVoice(key, client()).synthesize("t", voice_id="v"),
                   "Clé API elevenlabs manquante, à saisir dans Réglages → ElevenLabs"),
    "gemini": (lambda key: GeminiLLM(key, client()).complete("s", "p"),
               "Clé API gemini manquante, à saisir dans Réglages → Gemini"),
    "gemini image": (lambda key: GeminiImage(key, client()).generate("p", model=DEFAULT_IMAGE_MODEL),
                     "Clé API gemini manquante, à saisir dans Réglages → Gemini"),
    "claude": (lambda key: ClaudeLLM(key).complete("s", "p"),
               "Clé API claude manquante, à saisir dans Réglages → Claude"),
}


@pytest.mark.parametrize("name", list(CALLS))
async def test_call_without_key_is_a_clear_non_retryable_error(name):
    call, message = CALLS[name]
    with pytest.raises(ProviderError) as e:
        await call("")
    assert str(e.value) == message and e.value.retryable is False


async def test_health_without_key_is_false_without_request():
    assert await FalProvider("", client()).health() is False
    assert await ElevenLabsVoice("", client()).health() is False
    assert await GeminiLLM("", client()).health() is False
    assert await ClaudeLLM("").health() is False


async def test_fal_availability_without_key_gives_where_to_set_it():
    fal = FalProvider("", client())
    assert set((await fal.availability()).values()) == {Availability(False, FAL_KEY_MISSING)}
    assert await fal.image_availability() == {"flux": Availability(False, FAL_KEY_MISSING)}
    assert await FalProvider("k", client()).image_availability() == {"flux": Availability(True)}


async def test_secret_settings_are_read_without_surrounding_spaces(api, session, monkeypatch):
    """Clé collée avec un espace ou un retour à la ligne (en-tête invalide pour httpx), ou faite d'espaces seulement
    (= clé absente), en base comme dans l'environnement."""
    from app.app_settings import AppSettings
    from app.config import settings as env

    monkeypatch.setattr(env, "gemini_api_key", " g-key\n")
    assert (await api.put("/api/settings", json={"fal_key": "  abc123\n", "elevenlabs_api_key": " "})).status_code == 200
    settings = AppSettings(session)
    assert await settings.get("fal_key") == "abc123" and await settings.get("elevenlabs_api_key") == ""
    assert await settings.get("gemini_api_key") == "g-key"


@pytest.fixture
def real_providers(monkeypatch):
    """Vrais providers, sans aucune clé (ni en base ni dans `backend/.env`)."""
    from app.config import settings

    monkeypatch.setattr(settings, "fake_providers", False)
    for key in ("gemini_api_key", "fal_key"):
        monkeypatch.setattr(settings, key, "")


async def project_ready_for_reference(api, session, params=None):
    pid = (await api.post("/api/projects", json={"title": "t", "theme": "chats"})).json()["id"]
    await session.execute(Step.__table__.update().where(Step.project_id == pid, Step.name.in_(["idea", "story", "script"]))
                          .values(status="approved"))
    if params is not None:
        await session.execute(Step.__table__.update().where(Step.project_id == pid, Step.name == "reference")
                              .values(params=params))
    await session.commit()
    return pid


async def reference_status(api, pid):
    steps = (await api.get(f"/api/projects/{pid}")).json()["steps"]
    return next(s["status"] for s in steps if s["name"] == "reference")


async def run_reference(api, pid):
    return await api.post(f"/api/projects/{pid}/steps/reference/run", json={})


async def test_reference_run_without_gemini_key_is_refused_upfront(api, session, real_providers):
    """Défaut : Gemini (`image_provider`). Sans sa clé, refus d'emblée avec la raison, rien réclamé ni enfilé."""
    pid = await project_ready_for_reference(api, session)
    r = await run_reference(api, pid)
    assert r.status_code == 409 and r.json()["detail"] == GEMINI_KEY_MISSING
    assert await reference_status(api, pid) == "pending" and api.enqueued == []


async def test_reference_run_with_gemini_key_is_launched(api, session, real_providers):
    assert (await api.put("/api/settings", json={"gemini_api_key": "g"})).status_code == 200
    pid = await project_ready_for_reference(api, session)
    assert (await run_reference(api, pid)).status_code == 202
    assert api.enqueued == [(pid, "reference", None)]


async def test_reference_run_on_fal_needs_the_fal_key(api, session, real_providers):
    """Choix fal (paramètres de l'étape, ou ancien paramètre `model: flux` sans provider)."""
    assert (await api.put("/api/settings", json={"gemini_api_key": "g"})).status_code == 200
    for params in ({"provider": "fal", "model": "flux"}, {"model": "flux"}):
        pid = await project_ready_for_reference(api, session, params)
        r = await run_reference(api, pid)
        assert r.status_code == 409 and r.json()["detail"] == FAL_KEY_MISSING
    assert (await api.put("/api/settings", json={"fal_key": "k"})).status_code == 200
    assert (await run_reference(api, pid)).status_code == 202


@pytest.mark.parametrize(("params", "detail"), [
    ({"provider": "gemini", "model": "dalle"}, "Modèle d'image inconnu pour gemini : dalle"),
    ({"provider": "openai", "model": "dalle"}, "Provider d'image inconnu : openai"),
])
async def test_reference_run_with_unknown_image_model_is_400(api, session, params, detail):
    pid = await project_ready_for_reference(api, session, params)
    r = await run_reference(api, pid)
    assert r.status_code == 400 and r.json()["detail"] == detail
    assert api.enqueued == []


async def test_reference_uses_the_image_provider_setting(api, session, real_providers):
    assert (await api.put("/api/settings", json={"image_provider": "fal", "gemini_api_key": "g"})).status_code == 200
    pid = await project_ready_for_reference(api, session)
    assert (await run_reference(api, pid)).json()["detail"] == FAL_KEY_MISSING
    assert (await api.put("/api/settings", json={"image_provider": "dalle"})).status_code == 400


async def test_models_endpoint_exposes_image_availability_per_provider(api, real_providers):
    image = (await api.get("/api/providers/models")).json()["image"]
    assert [(c["provider"], c["id"]) for c in image] == [("gemini", m) for m in image_models(DEFAULT_IMAGE_MODEL)] + [
        ("fal", "flux")]
    assert image[0] == {"provider": "gemini", "id": DEFAULT_IMAGE_MODEL, "name": DEFAULT_IMAGE_MODEL,
                        "available": False, "reason": GEMINI_KEY_MISSING}
    assert image[-1]["reason"] == FAL_KEY_MISSING
    assert (await api.put("/api/settings", json={"gemini_api_key": "g", "gemini_image_model": "gemini-9-image"})
            ).status_code == 200
    image = (await api.get("/api/providers/models")).json()["image"]
    assert image[0]["id"] == "gemini-9-image"
    assert [c["available"] for c in image if c["provider"] == "gemini"] == [True] * (len(image) - 1)
