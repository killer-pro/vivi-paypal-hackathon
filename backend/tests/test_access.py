import json
from datetime import UTC, datetime, timedelta

import pytest

from app.app_settings import AppSettings
from app.services import access
from app.services.access import SubscriptionRequired


def _in(days: int) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)


async def _settings(session) -> AppSettings:
    return AppSettings(session)


async def test_subscribed_expired_and_admin(session, make_user, admin):
    plain = await make_user("p@x.fr")
    active = await make_user("a@x.fr")
    expired = await make_user("e@x.fr")
    active.subscription_ends_at, expired.subscription_ends_at = _in(10), _in(-1)
    assert [u.is_subscribed for u in (plain, active, expired, admin)] == [False, True, False, True]


async def test_default_locked_features(session):
    locked = await access.load_locked(AppSettings(session))
    assert locked.profiles == {"precision", "max"} and locked.reference is True
    assert locked.styles == {"realistic", "anime", "illustration"}


async def test_require_refuses_locked_feature_with_readable_reason(session, make_user):
    user, app_settings = await make_user("p@x.fr"), AppSettings(session)
    with pytest.raises(SubscriptionRequired) as err:
        await access.require(app_settings, user, "profile", "precision")
    assert err.value.status_code == 403 and "Réservé à l'abonnement" in err.value.detail and "Précision" in err.value.detail
    for feature, value in (("reference", ""), ("style", "anime")):
        with pytest.raises(SubscriptionRequired, match="Réservé à l'abonnement"):
            await access.require(app_settings, user, feature, value)


async def test_require_lets_free_features_through(session, make_user):
    user, app_settings = await make_user("p@x.fr"), AppSettings(session)
    await access.require(app_settings, user, "profile", "fast")
    await access.require(app_settings, user, "profile", "balanced")
    await access.require(app_settings, user, "style", "")  # pas de style : rien de réservé


async def test_subscriber_and_admin_use_everything(session, make_user, admin):
    user = await make_user("a@x.fr")
    user.subscription_ends_at = _in(5)
    app_settings = AppSettings(session)
    for who in (user, admin):
        await access.require(app_settings, who, "profile", "max")
        await access.require(app_settings, who, "reference")
        await access.require(app_settings, who, "style", "anime")


async def test_legacy_workflow_name_is_the_max_profile(session, make_user):
    with pytest.raises(SubscriptionRequired):
        await access.require(AppSettings(session), await make_user("p@x.fr"), "profile", "workflow")


async def test_locked_list_is_configuration(session, make_user):
    app_settings = AppSettings(session)
    await app_settings.set("subscription_locked", json.dumps({"profiles": ["balanced"], "reference": False, "styles": []}))
    user = await make_user("p@x.fr")
    await access.require(app_settings, user, "profile", "precision")
    await access.require(app_settings, user, "reference")
    with pytest.raises(SubscriptionRequired):
        await access.require(app_settings, user, "profile", "balanced")


@pytest.mark.parametrize("raw", [
    "pas du json", "[]", '{"profiles": "max"}', '{"profiles": ["turbo"]}', '{"styles": ["cubiste"]}',
    '{"reference": "oui"}', '{"autre": 1}',
])
async def test_subscription_locked_setting_rejects_invalid_values(session, raw):
    with pytest.raises(ValueError, match="subscription_locked"):
        await AppSettings(session).set("subscription_locked", raw)


async def test_locked_for_account_is_empty_for_subscribers(session, make_user):
    free, paid = await make_user("f@x.fr"), await make_user("p@x.fr")
    paid.subscription_ends_at = _in(3)
    app_settings = AppSettings(session)
    assert (await access.locked_for(app_settings, free)).profiles == {"precision", "max"}
    assert await access.locked_for(app_settings, paid) == access.Locked(frozenset(), False, frozenset())


async def test_me_exposes_subscription(api_as, make_user, session):
    user = await make_user("a@x.fr")
    assert (await (await api_as(user)).get("/api/auth/me")).json()["subscribed"] is False
    user.subscription_ends_at = _in(30)
    await session.commit()
    body = (await (await api_as(user)).get("/api/auth/me")).json()
    assert body["subscribed"] is True and body["subscription_ends_at"] is not None
