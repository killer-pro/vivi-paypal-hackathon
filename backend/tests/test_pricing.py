import json
from decimal import Decimal

import pytest

from app.app_settings import AppSettings
from app.providers.comfycloud import cloud_clip_usd
from app.services.pricing import ACTIONS, DEFAULT_PRICING, Pricing, credits_for, load_pricing, video_credits

USD = Decimal("0.05")


def _pricing(**overrides) -> Pricing:
    data = json.loads(DEFAULT_PRICING)
    data.update(overrides)
    return Pricing.from_json(data, usd_per_credit=USD, margin=Decimal("2.5"))


def test_credits_for_rounds_up():
    assert credits_for(1.2, Decimal("2.5"), USD) == 60
    assert credits_for(0.01, Decimal("2.5"), USD) == 1
    assert credits_for(0, Decimal("2.5"), USD) == 0
    assert credits_for(-1, Decimal("2.5"), USD) == 0


def test_no_float_error():
    assert credits_for(0.1 + 0.2, Decimal(1), USD) == credits_for(0.3, Decimal(1), USD) == 6


def test_margin_override_per_action():
    pricing = _pricing(margin_overrides={"story": 5})
    assert pricing.action_credits("story") == 1  # 0,006 $ × 5 ÷ 0,05 = 0,6 → 1
    assert pricing.action_credits("reference") == 2  # 0,04 $ × 2,5 ÷ 0,05 = 2 (marge globale)
    assert _pricing(margin_overrides={"reference": 5}).action_credits("reference") == 4


def test_local_clip_cost_scales_with_duration():
    pricing = _pricing()
    assert pricing.local_clip_cost_usd("balanced", 6) == pytest.approx(2 * pricing.local_clip_cost_usd("balanced", 3))
    assert pricing.local_clip_cost_usd("balanced", 3) == pytest.approx(0.08)


def test_balanced_30s_default_is_about_60_credits():
    pricing = _pricing()
    clip = pricing.clip_credits(pricing.local_clip_cost_usd("balanced", 3))
    total = 10 * clip + 10 * pricing.action_credits("voice")
    total += sum(pricing.action_credits(a) for a in ("idea", "story", "script", "reference", "final"))
    assert 55 <= total <= 70


def test_every_action_has_a_default_price():
    pricing = _pricing()
    assert all(pricing.action_credits(a) >= 1 for a in ACTIONS)


@pytest.mark.parametrize("raw", [
    "pas du json", "[]", '{"flat_usd": {"idea": -1}}', '{"flat_usd": {"inconnue": 1}}', '{"flat_usd": {"idea": "x"}}',
    '{"local_clip_usd": {"turbo": 1}}', '{"margin_overrides": {"story": 0}}', '{"flat_usd": {"idea": 1e999}}',
    '{"flat_usd": []}',
])
async def test_pricing_setting_rejects_invalid_json_or_negative(session, raw):
    with pytest.raises(ValueError, match="credits_pricing"):
        await AppSettings(session).set("credits_pricing", raw)


@pytest.mark.parametrize("key,value", [
    ("credits_usd_per_credit", "0"), ("credits_margin", "abc"), ("credits_signup_grant", "-1"),
    ("credits_reservation_timeout_min", "0"), ("credits_signup_grant", "1.5"),
])
async def test_numeric_credit_settings_are_validated(session, key, value):
    with pytest.raises(ValueError, match=key):
        await AppSettings(session).set(key, value)


async def test_load_pricing_reads_settings(session):
    app_settings = AppSettings(session)
    default = await load_pricing(app_settings)
    assert default.usd_per_credit == Decimal("0.01") and default.margin == Decimal("3")
    await app_settings.set("credits_margin", "5")
    await app_settings.set("credits_pricing", json.dumps({"flat_usd": {"idea": 0.1}}))
    pricing = await load_pricing(app_settings)
    assert pricing.action_credits("idea") == 50  # 0,1 × 5 ÷ 0,01
    assert pricing.action_credits("story") == 3  # les autres prix gardent leur défaut (0,006 × 5 ÷ 0,01)


async def test_30s_video_fits_signup_grant(session):
    app_settings = AppSettings(session)
    pricing = await load_pricing(app_settings)
    assert (pricing.usd_per_credit, pricing.margin) == (Decimal("0.01"), Decimal("3"))
    cost = video_credits(pricing)
    assert 100 <= cost <= int(await app_settings.get("credits_signup_grant")) == 200


def test_cloud_clip_usd_follows_the_measured_gpu_time():
    assert cloud_clip_usd("fast", 3) == pytest.approx(0.0213, abs=0.0001)
    assert cloud_clip_usd("fast", 6) == pytest.approx(2 * cloud_clip_usd("fast", 3), abs=0.0001)
    assert cloud_clip_usd("balanced", 3) < cloud_clip_usd("precision", 3) < cloud_clip_usd("max", 3)
