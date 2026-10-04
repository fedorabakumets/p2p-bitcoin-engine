from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order, OrderEvent, OrderStatus, Quote
from app.orders.service import (
    IllegalOrderTransition,
    InvalidBtcAddress,
    QuoteExpired,
    open_searching_order,
    persist_created_order,
    transition,
)
from app.pricing.formula import build_quote
from app.users.service import register_from_start

ADDRESS = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"


def _snapshot(**overrides):
    params = dict(
        principal_rub_kop=200_000,
        markup_bps=1800,
        platform_fee_bps=0,
        referral_bps=0,
        rate_rub_per_btc=Decimal("6000000"),
        ttl_seconds=120,
        now=datetime.now(timezone.utc),
    )
    params.update(overrides)
    return build_quote(**params)


async def _user(session: AsyncSession, telegram_id: int = 501):
    return await register_from_start(
        session,
        telegram_id=telegram_id,
        username="client",
        display_name="Client",
        start_payload=None,
    )


async def test_illegal_transition_is_rejected(session: AsyncSession) -> None:
    user = await _user(session)
    order = await persist_created_order(
        session,
        user_id=user.id,
        snapshot=_snapshot(),
        btc_address=ADDRESS,
    )
    with pytest.raises(IllegalOrderTransition) as caught:
        await transition(
            session,
            order,
            OrderStatus.COMPLETED,
            actor_type="client",
            actor_user_id=user.id,
            idempotency_key="jump",
        )
    assert caught.value.from_status == "CREATED"
    assert caught.value.to_status == "COMPLETED"
    stored = await session.get(Order, order.id)
    assert stored is not None
    assert OrderStatus(str(stored.status)) == OrderStatus.CREATED


async def test_legal_transition_and_no_cancel_after_client_marked_paid(session: AsyncSession) -> None:
    user = await _user(session, 502)
    order = await persist_created_order(
        session,
        user_id=user.id,
        snapshot=_snapshot(),
        btc_address=ADDRESS,
    )
    steps = [
        OrderStatus.QUOTED,
        OrderStatus.SEARCHING_EXECUTOR,
        OrderStatus.EXECUTOR_ASSIGNED,
        OrderStatus.WAITING_PAYMENT,
        OrderStatus.CLIENT_MARKED_PAID,
    ]
    for step in steps:
        order = await transition(
            session,
            order,
            step,
            actor_type="system",
            actor_user_id=None,
            idempotency_key=f"order:{order.id}:status:{step.value}",
        )
    with pytest.raises(IllegalOrderTransition):
        await transition(
            session,
            order,
            OrderStatus.CANCELLED,
            actor_type="client",
            actor_user_id=user.id,
            idempotency_key=f"order:{order.id}:status:CANCELLED",
        )
    assert OrderStatus(str(order.status)) == OrderStatus.CLIENT_MARKED_PAID
    assert order.trader_id is None


async def test_confirm_copies_snapshot_and_searches_without_a_trader(session: AsyncSession) -> None:
    user = await _user(session, 503)
    snapshot = _snapshot(platform_fee_bps=100, referral_bps=2500)
    order = await open_searching_order(
        session,
        user_id=user.id,
        snapshot=snapshot,
        btc_address=ADDRESS.upper(),
    )
    assert OrderStatus(str(order.status)) == OrderStatus.SEARCHING_EXECUTOR
    assert order.trader_id is None
    assert order.public_no >= 1
    assert order.btc_address == ADDRESS
    assert order.principal_rub_kop == snapshot.principal_rub_kop
    assert order.payment_rub_kop == snapshot.payment_rub_kop
    assert order.markup_bps == snapshot.markup_bps
    assert order.client_btc_sats == snapshot.client_btc_sats
    assert order.platform_fee_sats == snapshot.platform_fee_sats
    assert order.referral_sats == snapshot.referral_sats
    assert order.trader_lock_sats == snapshot.client_btc_sats + snapshot.platform_fee_sats
    assert order.market_rate_rub_per_btc == snapshot.market_rate_rub_per_btc

    quote = await session.get(Quote, order.quote_id)
    assert quote is not None
    assert quote.order_id == order.id
    assert quote.client_btc_sats == order.client_btc_sats
    assert quote.referral_sats == order.referral_sats
    assert quote.referral_bps == snapshot.referral_bps

    events = list(
        await session.scalars(
            select(OrderEvent).where(OrderEvent.order_id == order.id).order_by(OrderEvent.id)
        )
    )
    assert [event.to_status for event in events] == ["CREATED", "QUOTED", "SEARCHING_EXECUTOR"]
    assert events[0].from_status is None
    assert events[0].actor_type == "client"

    later = build_quote(
        principal_rub_kop=200_000,
        markup_bps=0,
        platform_fee_bps=0,
        referral_bps=0,
        rate_rub_per_btc=Decimal("1000000"),
        ttl_seconds=120,
    )
    reloaded = await session.get(Order, order.id)
    assert reloaded is not None
    assert reloaded.client_btc_sats == snapshot.client_btc_sats
    assert reloaded.client_btc_sats != later.client_btc_sats
    assert reloaded.markup_bps == 1800


async def test_expired_and_inconsistent_snapshots_are_not_stored(session: AsyncSession) -> None:
    user = await _user(session, 504)
    expired = build_quote(
        principal_rub_kop=200_000,
        markup_bps=1800,
        platform_fee_bps=0,
        referral_bps=0,
        rate_rub_per_btc=Decimal("6000000"),
        ttl_seconds=120,
        now=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    with pytest.raises(QuoteExpired):
        await persist_created_order(session, user_id=user.id, snapshot=expired, btc_address=ADDRESS)

    fresh = _snapshot()
    tampered = replace(fresh, client_btc_sats=fresh.client_btc_sats + 5)
    with pytest.raises(ValueError):
        await persist_created_order(session, user_id=user.id, snapshot=tampered, btc_address=ADDRESS)

    with pytest.raises(InvalidBtcAddress):
        await persist_created_order(session, user_id=user.id, snapshot=fresh, btc_address="hello")
