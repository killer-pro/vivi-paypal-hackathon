import json
from datetime import UTC, datetime, timedelta

import pytest

from app.app_settings import AppSettings
from app.models import Setting
from app.services import access
from app.services.access import SubscriptionRequired
from app.services.billing import DEFAULT_BILLING, UNLIMITED, Perks, load_billing, parse_billing


def _in(days: int) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)


async def _subscriber(make_user, email="a@x.fr", plan_id=None):
    user = await make_user(email)
    user.subscription_ends_at, user.plan_id = _in(10), plan_id
    return user


async def test_subscribed_expired_and_admin(session, make_user, admin):
    plain = await make_user("p@x.fr")
    active = await make_user("a@x.fr")
    expired = await make_user("e@x.fr")
    active.subscription_ends_at, expired.subscription_ends_at = _in(10), _in(-1)
    assert [u.is_subscribed for u in (plain, active, expired, admin)] == [False, True, False, True]


def test_default_tiers_match_spec():
    config = parse_billing(DEFAULT_BILLING)
    assert config is not None
    assert [(t.id, t.name, t.credits, t.paypal_amount) for t in config.tiers] == [
        ("starter", "Starter", 1200, "9.00"), ("creator", "Créateur", 3000, "19.00"), ("pro", "Pro", 9000, "49.00")]
    assert config.free == Perks(1, 2, frozenset({"fast", "balanced"}), 30, 1, False)
    starter, creator, pro = (t.perks for t in config.tiers)
    assert starter == Perks(2, 4, frozenset({"fast", "balanced", "precision"}), 60, 1, True)
    assert creator == Perks(4, 8, frozenset({"fast", "balanced", "precision", "max"}), 90, 2, True)
    assert pro == Perks(8, 16, frozenset({"fast", "balanced", "precision", "max"}), 180, 3, True)
    assert config.tier("creator") is config.tiers[1] and config.tier("inconnu") is None


async def test_old_subscription_format_falls_back_to_defaults(session):
    old = json.dumps({"subscription": {"price_id": "", "credits": 400, "label": "19 $ par mois"}, "packs": []})
    assert parse_billing(old) is None
    session.add(Setting(key="billing_config", value=old))
    await session.commit()
    assert [t.id for t in (await load_billing(AppSettings(session))).tiers] == ["starter", "creator", "pro"]


async def test_subscriber_without_plan_gets_first_tier(session, make_user):
    app_settings = AppSettings(session)
    config = await load_billing(app_settings)
    for plan_id in (None, "disparu"):
        user = await _subscriber(make_user, f"{plan_id}@x.fr", plan_id)
        assert await access.perks_for(app_settings, user) == config.tiers[0].perks
        assert (await access.current_tier(app_settings, user)).id == "starter"
    creator = await _subscriber(make_user, "c@x.fr", "creator")
    assert await access.perks_for(app_settings, creator) == config.tiers[1].perks


async def test_free_account_gets_free_perks(session, make_user):
    app_settings = AppSettings(session)
    user = await make_user("f@x.fr")
    user.subscription_ends_at, user.plan_id = _in(-1), "pro"  # abonnement terminé : plus d'avantages
    assert await access.perks_for(app_settings, user) == (await load_billing(app_settings)).free
    assert await access.current_tier(app_settings, user) is None


async def test_admin_is_unlimited(session, admin):
    app_settings = AppSettings(session)
    assert await access.perks_for(app_settings, admin) == UNLIMITED
    await access.require(app_settings, admin, "profile", "max")
    await access.require(app_settings, admin, "style", "anime")
    assert await access.limit_reason(app_settings, admin, "max_duration_s", 180) is None


async def test_profile_reason_names_first_unlocking_tier(session, make_user):
    app_settings, user = AppSettings(session), await make_user("f@x.fr")
    assert await access.reason(app_settings, user, "profile", "max") == "Réservé au forfait Créateur : le profil Maximum"
    assert await access.reason(app_settings, user, "profile", "precision") == "Réservé au forfait Starter : le profil Précision"
    assert await access.reason(app_settings, user, "profile", "workflow") is not None  # ancien nom du profil Maximum
    assert await access.reason(app_settings, user, "profile", "fast") is None
    assert await access.reason(app_settings, user, "style", "") is None  # « Aucun » reste libre
    assert await access.reason(app_settings, user, "style", "anime") == "Réservé au forfait Starter : les styles visuels"
    starter = await _subscriber(make_user, "s@x.fr", "starter")
    assert await access.reason(app_settings, starter, "profile", "precision") is None
    with pytest.raises(SubscriptionRequired) as err:
        await access.require(app_settings, starter, "profile", "max")
    assert err.value.status_code == 403 and err.value.detail == "Réservé au forfait Créateur : le profil Maximum"


async def test_reason_when_no_tier_unlocks(session, make_user):
    app_settings = AppSettings(session)
    config = json.loads(DEFAULT_BILLING)
    for tier in config["tiers"]:
        tier["perks"]["profiles"] = ["fast"]
    await app_settings.set("billing_config", json.dumps(config))
    assert await access.reason(app_settings, await make_user("f@x.fr"), "profile", "max") == "Indisponible : le profil Maximum"


async def test_limit_reason(session, make_user):
    app_settings, user = AppSettings(session), await make_user("f@x.fr")
    assert await access.limit_reason(app_settings, user, "max_duration_s", 30) is None
    assert (await access.limit_reason(app_settings, user, "max_duration_s", 60)
            == "Limite de votre forfait : 30 s (forfait Starter : 60 s)")
    assert (await access.limit_reason(app_settings, user, "references_max", 5)
            == "Limite de votre forfait : 2 images de référence (forfait Créateur : 8 images de référence)")
    assert (await access.limit_reason(app_settings, user, "queue_max", 2)
            == "Limite de votre forfait : 1 demande en file (forfait Starter : 2 demandes en file)")
    assert await access.limit_reason(app_settings, user, "max_duration_s", 600) == "Limite de votre forfait : 30 s"
    with pytest.raises(SubscriptionRequired, match="30 s"):
        await access.require_limit(app_settings, user, "max_duration_s", 60)


@pytest.mark.parametrize("change", [
    lambda c: c["tiers"][0]["perks"].update(profiles=["turbo"]),
    lambda c: c["tiers"][0]["perks"].update(queue_max=0),
    lambda c: c["tiers"][0]["perks"].pop("styles"),
    lambda c: c["free"].update(styles="oui"),
    lambda c: c["tiers"].append(dict(c["tiers"][0])),  # identifiant en double
    lambda c: c.update(tiers=[]),
    lambda c: c["tiers"][0].update(id="un-identifiant-bien-trop-long"),  # plus de 20 caractères : users.plan_id
    lambda c: c["tiers"][0].update(id="Starter Plus"),
])
async def test_billing_config_rejects_invalid_tiers(session, change):
    config = json.loads(DEFAULT_BILLING)
    change(config)
    with pytest.raises(ValueError, match="billing_config"):
        await AppSettings(session).set("billing_config", json.dumps(config))


async def test_me_exposes_subscription(api_as, make_user, session):
    user = await make_user("a@x.fr")
    assert (await (await api_as(user)).get("/api/auth/me")).json()["subscribed"] is False
    user.subscription_ends_at = _in(30)
    await session.commit()
    body = (await (await api_as(user)).get("/api/auth/me")).json()
    assert body["subscribed"] is True and body["subscription_ends_at"] is not None
