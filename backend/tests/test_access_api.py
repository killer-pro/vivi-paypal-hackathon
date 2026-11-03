from datetime import UTC, datetime, timedelta

from app.services.access import REASON_PREFIX


async def _models(c):
    cards = (await c.get("/api/providers/models")).json()["video"]
    return {(card["provider"], card["id"]): card for card in cards}


async def test_free_account_sees_locked_profiles_with_their_reason(api_as, make_user):
    cards = await _models(await api_as(await make_user("f@x.fr")))
    locked = {key: card["locked"] for key, card in cards.items() if key[0] == "comfyui"}
    assert locked == {("comfyui", "fast"): False, ("comfyui", "balanced"): False, ("comfyui", "precision"): True,
                      ("comfyui", "max"): True}
    reason = cards[("comfyui", "precision")]["locked_reason"]
    assert reason.startswith(REASON_PREFIX) and "Précision" in reason
    assert cards[("comfyui", "fast")]["locked_reason"] is None
    assert cards[("comfyui", "max")]["available"] is True  # le verrou est distinct de la disponibilité technique


async def test_subscriber_and_admin_see_nothing_locked(api, api_as, make_user, session):
    user = await make_user("s@x.fr")
    user.subscription_ends_at = datetime.now(UTC) + timedelta(days=3)
    await session.commit()
    for client in (await api_as(user), api):
        assert not any(card["locked"] for card in (await _models(client)).values())


async def test_access_endpoint_lists_what_is_locked_for_the_account(api_as, make_user, session):
    user = await make_user("f@x.fr")
    c = await api_as(user)
    body = (await c.get("/api/access")).json()
    assert body["subscribed"] is False and body["subscription_ends_at"] is None
    assert sorted(body["locked"]["profiles"]) == ["max", "precision"] and body["locked"]["reference"] is True
    assert sorted(body["locked"]["styles"]) == ["anime", "illustration", "realistic"]
    assert body["reasons"]["reference"].startswith(REASON_PREFIX) and body["reasons"]["style"].startswith(REASON_PREFIX)
    user.subscription_ends_at = datetime.now(UTC) + timedelta(days=3)
    await session.commit()
    body = (await c.get("/api/access")).json()
    assert body["subscribed"] is True and body["locked"] == {"profiles": [], "reference": False, "styles": []}
    assert body["reasons"] == {"reference": None, "style": None}


async def test_access_requires_login(api_as):
    assert (await (await api_as(None)).get("/api/access")).status_code == 401
