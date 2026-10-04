import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order, OrderEvent, OrderStatus, Quote, User, utcnow
from app.orders.transitions import can_transition
from app.pricing.formula import QuoteSnapshot, snapshot_matches_formula
from app.users.service import UserBlocked
from app.wallets.btc_address import is_btc_mainnet_address, normalize_btc_mainnet_address


class IllegalOrderTransition(Exception):
    def __init__(self, from_status: str, to_status: str):
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"illegal order transition {from_status} -> {to_status}")


class QuoteExpired(Exception):
    pass


class InvalidBtcAddress(Exception):
    pass


async def persist_created_order(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    snapshot: QuoteSnapshot,
    btc_address: str,
) -> Order:
    """Store the shown snapshot. A later rate does not change this row."""

    if not snapshot_matches_formula(snapshot):
        raise ValueError("quote snapshot does not match the pricing formula")
    if snapshot.expires_at <= datetime.now(timezone.utc):
        raise QuoteExpired()
    if not is_btc_mainnet_address(btc_address):
        raise InvalidBtcAddress()

    user = await session.get(User, user_id)
    if user is None:
        raise LookupError("user not found")
    if str(user.status) != "active":
        raise UserBlocked()

    address = normalize_btc_mainnet_address(btc_address)
    quote = Quote(
        user_id=user.id,
        principal_rub_kop=snapshot.principal_rub_kop,
        payment_rub_kop=snapshot.payment_rub_kop,
        markup_bps=snapshot.markup_bps,
        platform_fee_bps=snapshot.platform_fee_bps,
        referral_bps=snapshot.referral_bps,
        market_rate_rub_per_btc=snapshot.market_rate_rub_per_btc,
        client_btc_sats=snapshot.client_btc_sats,
        platform_fee_sats=snapshot.platform_fee_sats,
        referral_sats=snapshot.referral_sats,
        trader_lock_sats=snapshot.trader_lock_sats,
        expires_at=snapshot.expires_at,
    )
    session.add(quote)
    await session.flush()

    order = Order(
        client_id=user.id,
        quote_id=quote.id,
        execution_channel="trader",
        status=OrderStatus.CREATED.value,
        btc_address=address,
        principal_rub_kop=snapshot.principal_rub_kop,
        payment_rub_kop=snapshot.payment_rub_kop,
        markup_bps=snapshot.markup_bps,
        platform_fee_bps=snapshot.platform_fee_bps,
        market_rate_rub_per_btc=snapshot.market_rate_rub_per_btc,
        client_btc_sats=snapshot.client_btc_sats,
        platform_fee_sats=snapshot.platform_fee_sats,
        referral_sats=snapshot.referral_sats,
        trader_lock_sats=snapshot.trader_lock_sats,
        quote_expires_at=snapshot.expires_at,
    )
    session.add(order)
    await session.flush()

    quote.order_id = order.id
    _add_event(
        session,
        order,
        from_status=None,
        to_status=OrderStatus.CREATED,
        actor_type="client",
        actor_user_id=user.id,
        idempotency_key=f"order:{order.id}:status:CREATED",
        payload={"reason": "quote_confirmed"},
    )
    await session.flush()
    await session.refresh(order)
    return order


async def open_searching_order(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    snapshot: QuoteSnapshot,
    btc_address: str,
) -> Order:
    """Persist the quote and leave the order waiting for a trader.

    Nobody is assigned here. Claim, escrow, and payout are later stages.
    """

    order = await persist_created_order(
        session,
        user_id=user_id,
        snapshot=snapshot,
        btc_address=btc_address,
    )
    await transition(
        session,
        order,
        OrderStatus.QUOTED,
        actor_type="client",
        actor_user_id=user_id,
        idempotency_key=f"order:{order.id}:status:QUOTED",
    )
    await transition(
        session,
        order,
        OrderStatus.SEARCHING_EXECUTOR,
        actor_type="client",
        actor_user_id=user_id,
        idempotency_key=f"order:{order.id}:status:SEARCHING_EXECUTOR",
        payload={"reason": "awaiting_trader"},
    )
    await session.refresh(order)
    return order


async def transition(
    session: AsyncSession,
    order: Order,
    to_status: OrderStatus,
    *,
    actor_type: str,
    actor_user_id: uuid.UUID | None,
    idempotency_key: str,
    payload: dict[str, object] | None = None,
) -> Order:
    locked = await session.scalar(select(Order).where(Order.id == order.id).with_for_update())
    if locked is None:
        raise LookupError("order not found")
    current = OrderStatus(str(locked.status))
    target = OrderStatus(to_status)
    if not can_transition(current, target):
        raise IllegalOrderTransition(current.value, target.value)
    locked.status = target.value
    locked.updated_at = utcnow()
    _add_event(
        session,
        locked,
        from_status=current,
        to_status=target,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        idempotency_key=idempotency_key,
        payload=payload or {},
    )
    await session.flush()
    return locked


async def list_client_orders(session: AsyncSession, client_id: uuid.UUID, *, limit: int = 20) -> list[Order]:
    rows = await session.scalars(
        select(Order).where(Order.client_id == client_id).order_by(Order.created_at.desc()).limit(limit)
    )
    return list(rows)


def _add_event(
    session: AsyncSession,
    order: Order,
    *,
    from_status: OrderStatus | None,
    to_status: OrderStatus,
    actor_type: str,
    actor_user_id: uuid.UUID | None,
    idempotency_key: str,
    payload: dict[str, object],
) -> None:
    session.add(
        OrderEvent(
            order_id=order.id,
            from_status=None if from_status is None else from_status.value,
            to_status=to_status.value,
            actor_type=actor_type,
            actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
            payload=payload,
        )
    )
