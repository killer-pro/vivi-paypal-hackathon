from datetime import UTC, datetime, timedelta

import pytest

from app.app_settings import AppSettings
from app.providers.comfycloud import cloud_clip_usd
from app.services.pricing import load_pricing

FORFAIT = "Réservé au forfait"


async def _models(c):
    cards = (await c.get("/api/providers/models")).json()["video"]
    return {(card["provider"], card["id"]): card for card in cards}


async def test_free_account_sees_locked_profiles_with_their_reason(api_as, make_user):
    cards = await _models(await api_as(await make_user("f@x.fr")))
    locked = {key: card["locked"] for key, card in cards.items() if key[0] == "comfyui"}
    assert locked == {("comfyui", "fast"): False, ("comfyui", "balanced"): False, ("comfyui", "precision"): True,
                      ("comfyui", "max"): True}
    assert cards[("comfyui", "precision")]["locked_reason"] == f"{FORFAIT} Starter : le profil Précision"
    assert cards[("comfyui", "fast")]["locked_reason"] is None
    assert cards[("comfyui", "max")]["available"] is True  # le verrou est distinct de la disponibilité technique


async def test_creator_and_admin_see_nothing_locked(api, api_as, make_user, session):
    user = await make_user("s@x.fr")
    user.subscription_ends_at, user.plan_id = datetime.now(UTC) + timedelta(days=3), "creator"
    await session.commit()
    for client in (await api_as(user), api):
        assert not any(card["locked"] for card in (await _models(client)).values())


async def test_access_api_exposes_perks(api_as, make_user, session):
    user = await make_user("f@x.fr")
    c = await api_as(user)
    body = (await c.get("/api/access")).json()
    assert body["subscribed"] is False and body["subscription_ends_at"] is None and body["tier"] is None
    assert body["perks"] == {"queue_max": 1, "references_max": 2, "profiles": ["balanced", "fast"], "max_duration_s": 30,
                             "parallel_clips": 1, "styles": False}
    assert body["locked"] == {"profiles": ["max", "precision"], "styles": ["anime", "illustration", "realistic"]}
    assert body["reasons"] == {"style": f"{FORFAIT} Starter : les styles visuels"}
    user.subscription_ends_at, user.plan_id = datetime.now(UTC) + timedelta(days=3), "starter"
    await session.commit()
    body = (await c.get("/api/access")).json()
    assert body["subscribed"] is True and body["tier"] == {"id": "starter", "name": "Starter"}
    assert body["perks"]["queue_max"] == 2 and body["locked"] == {"profiles": ["max"], "styles": []}
    assert body["reasons"] == {"style": None}


async def test_access_requires_login(api_as):
    assert (await (await api_as(None)).get("/api/access")).status_code == 401


async def test_client_cards_show_credits_not_dollars(api_as, make_user, session):
    cards = await _models(await api_as(await make_user("f@x.fr")))
    pricing = await load_pricing(AppSettings(session))
    assert all(card["cost_usd_per_clip"] is None and card["minutes_per_clip"] is None for card in cards.values())
    assert cards[("comfycloud", "fast")]["credits_per_clip"] == pricing.clip_credits(cloud_clip_usd("fast", 3))
    assert cards[("comfyui", "fast")]["credits_per_clip"] == pricing.clip_credits(pricing.local_clip_cost_usd("fast", 3))


async def test_admin_cards_keep_dollars(api):
    cards = await _models(api)
    assert cards[("comfyui", "fast")]["minutes_per_clip"] == 5 and cards[("comfycloud", "fast")]["cost_usd_per_clip"] > 0
    assert all(card["credits_per_clip"] is None for card in cards.values())


@pytest.fixture
async def offline(monkeypatch, session):
    """Vrais providers sans clé, ComfyUI local injoignable : des cartes indisponibles, sans appel réseau."""
    from app.config import settings
    monkeypatch.setattr(settings, "fake_providers", False)
    await AppSettings(session).set("comfyui_url", "http://127.0.0.1:9")


async def test_client_sees_neutral_reason(api_as, make_user, offline):
    data = (await (await api_as(await make_user("f@x.fr"))).get("/api/providers/models")).json()
    down = [c for c in data["video"] + data["image"] if not c["available"]]
    assert down and {c["reason"] for c in down} == {"Indisponible pour le moment"}


async def test_admin_sees_technical_reason(api, offline):
    data = (await api.get("/api/providers/models")).json()
    kling = next(c for c in data["video"] if (c["provider"], c["id"]) == ("fal", "kling"))
    assert not kling["available"] and "Clé API fal" in kling["reason"]
