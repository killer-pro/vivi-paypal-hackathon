import asyncio
import os
import random

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import CreditBalance, CreditEntry, CreditReservation
from app.services import credits
from app.services.credits import InsufficientCredits


async def _fund(session, user, *, subscription=0, topup=0):
    if subscription:
        await credits.grant(session, user.id, subscription, bucket="subscription", kind="adjust", reason="test")
    if topup:
        await credits.grant(session, user.id, topup, bucket="topup", kind="adjust", reason="test")
    await session.commit()


async def _reserve(session, user, amount, **kw):
    r = await credits.reserve(session, user.id, amount, project_id=None, step="clips", reason="test", **kw)
    await session.commit()
    return r


async def _ledger_sums(session, user_id) -> dict[str, int]:
    rows = (await session.execute(select(CreditEntry.bucket, func.sum(CreditEntry.amount))
                                  .where(CreditEntry.user_id == user_id).group_by(CreditEntry.bucket))).all()
    return {bucket: int(total) for bucket, total in rows}


async def test_reserve_consumes_subscription_before_topup(session, make_user):
    user = await make_user("a@x.fr")
    await _fund(session, user, subscription=60, topup=50)
    r = await _reserve(session, user, 80)
    assert r.parts == {"subscription": 60, "topup": 20} and r.status == "open" and r.amount == 80
    assert await credits.balance(session, user.id) == credits.Balance(0, 30)


async def test_reserve_refuses_when_insufficient_with_clear_message(session, make_user):
    user = await make_user("a@x.fr")
    uid = user.id  # un rollback expire les objets de la session
    await _fund(session, user, topup=40)
    before = (await session.execute(select(func.count()).select_from(CreditEntry))).scalar_one()
    with pytest.raises(InsufficientCredits) as err:
        await credits.reserve(session, user.id, 60, project_id=None, step="clips", reason="test")
    await session.rollback()
    assert err.value.status_code == 409 and (err.value.needed, err.value.available) == (60, 40)
    assert "60" in err.value.detail and "40" in err.value.detail
    assert await credits.balance(session, uid) == credits.Balance(0, 40)
    assert (await session.execute(select(func.count()).select_from(CreditEntry))).scalar_one() == before


async def test_concurrent_reservations_one_wins(session, make_user):
    user = await make_user("a@x.fr")
    await _fund(session, user, topup=100)
    engine = create_async_engine(os.environ["DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def attempt():
        async with maker() as s:
            try:
                await credits.reserve(s, user.id, 60, project_id=None, step="clips", reason="test")
                await s.commit()
                return "ok"
            except InsufficientCredits:
                await s.rollback()
                return "refused"

    try:
        results = await asyncio.gather(attempt(), attempt())
    finally:
        await engine.dispose()
    assert sorted(results) == ["ok", "refused"]
    assert (await credits.balance(session, user.id)).total == 40


async def test_close_refunds_to_original_buckets(session, make_user):
    user = await make_user("a@x.fr")
    await _fund(session, user, subscription=60, topup=50)
    r = await _reserve(session, user, 80)  # 60 abonnement + 20 recharge
    refunded = await credits.close(session, r, used=70)  # 60 abonnement + 10 recharge consommés
    await session.commit()
    assert refunded == 10 and r.status == "closed" and r.used == 70
    assert await credits.balance(session, user.id) == credits.Balance(0, 40)
    r2 = await _reserve(session, user, 40)  # 0 abonnement + 40 recharge
    await credits.close(session, r2, used=0)
    await session.commit()
    assert await credits.balance(session, user.id) == credits.Balance(0, 40)


async def test_close_refunds_subscription_part_first(session, make_user):
    user = await make_user("a@x.fr")
    await _fund(session, user, subscription=30, topup=50)
    r = await _reserve(session, user, 50)  # 30 + 20
    await credits.close(session, r, used=10)  # 10 d'abonnement consommés : 20 abonnement + 20 recharge rendus
    await session.commit()
    assert await credits.balance(session, user.id) == credits.Balance(20, 50)


async def test_close_is_idempotent(session, make_user):
    user = await make_user("a@x.fr")
    await _fund(session, user, topup=100)
    r = await _reserve(session, user, 60)
    assert await credits.close(session, r, used=20) == 40
    await session.commit()
    entries = (await session.execute(select(func.count()).select_from(CreditEntry))).scalar_one()
    assert await credits.close(session, r, used=0) == 0
    assert await credits.refund_all(session, r) == 0
    await session.commit()
    assert await credits.balance(session, user.id) == credits.Balance(0, 80)
    assert (await session.execute(select(func.count()).select_from(CreditEntry))).scalar_one() == entries


async def test_ledger_sums_to_balance(session, make_user):
    rng = random.Random(7)
    user = await make_user("a@x.fr")
    uid = user.id
    open_reservations: list[CreditReservation] = []
    for _ in range(60):
        action = rng.choice(["grant", "reserve", "close", "refund"])
        if action == "grant":
            await credits.grant(session, uid, rng.randint(1, 50), bucket=rng.choice(["subscription", "topup"]),
                                kind="adjust", reason="test")
        elif action == "reserve":
            try:
                open_reservations.append(await credits.reserve(session, uid, rng.randint(0, 40), project_id=None,
                                                               step="clips", reason="test"))
            except InsufficientCredits:
                await session.rollback()
        elif open_reservations:
            r = open_reservations.pop(rng.randrange(len(open_reservations)))
            if action == "close":
                await credits.close(session, r, used=rng.randint(0, r.amount))
            else:
                await credits.refund_all(session, r)
        await session.commit()
    balance = await credits.balance(session, uid)
    sums = await _ledger_sums(session, uid)
    assert (sums.get("subscription", 0), sums.get("topup", 0)) == (balance.subscription, balance.topup)


async def test_zero_amount_reservation_moves_nothing(session, make_user):
    user = await make_user("a@x.fr")
    r = await _reserve(session, user, 0)
    assert r.parts == {"subscription": 0, "topup": 0}
    assert await credits.close(session, r, used=0) == 0
    await session.commit()
    assert (await session.execute(select(func.count()).select_from(CreditEntry))).scalar_one() == 0
    assert await credits.balance(session, user.id) == credits.Balance(0, 0)


@pytest.mark.parametrize("amount", [0, -5])
async def test_negative_or_zero_grant_rejected(session, make_user, amount):
    user = await make_user("a@x.fr")
    with pytest.raises(ValueError):
        await credits.grant(session, user.id, amount, bucket="topup", kind="adjust", reason="test")
    assert (await session.execute(select(func.count()).select_from(CreditBalance))).scalar_one() == 0


async def test_adjust_negative_debits_one_bucket(session, make_user):
    user = await make_user("a@x.fr")
    await _fund(session, user, subscription=30, topup=50)
    await credits.adjust(session, user.id, -20, bucket="topup", reason="Geste commercial repris")
    await session.commit()
    assert await credits.balance(session, user.id) == credits.Balance(30, 30)
    assert (await _ledger_sums(session, user.id)) == {"subscription": 30, "topup": 30}


async def test_adjust_refuses_to_go_below_zero_and_writes_nothing(session, make_user):
    user = await make_user("a@x.fr")
    uid = user.id
    await _fund(session, user, topup=10)
    before = (await session.execute(select(func.count()).select_from(CreditEntry))).scalar_one()
    with pytest.raises(credits.CreditsRefused) as err:
        await credits.adjust(session, uid, -11, bucket="topup", reason="trop")
    await session.rollback()
    assert err.value.status_code == 409 and "10" in err.value.detail
    assert (await session.execute(select(func.count()).select_from(CreditEntry))).scalar_one() == before


async def test_adjust_positive_credits_bucket_and_zero_rejected(session, make_user):
    user = await make_user("a@x.fr")
    await credits.adjust(session, user.id, 40, bucket="subscription", reason="Compensation")
    await session.commit()
    assert await credits.balance(session, user.id) == credits.Balance(40, 0)
    with pytest.raises(ValueError):
        await credits.adjust(session, user.id, 0, bucket="topup", reason="rien")
