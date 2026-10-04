"""Offer a searching order to eligible traders and accept it in one transaction.

The claim is a single UPDATE ... WHERE status = SEARCHING_EXECUTOR. Redis is not the lock.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ledger.service import InsufficientBalance, available_for_update
from app.models import Order, OrderStatus, Trader, TraderPaymentMethod, User, utcnow
from app.notifications.messages import client_payment_text, trader_offer_text
from app.notifications.service import enqueue
from app.orders.service import add_order_event, transition
from app.pricing.service import load_pricing_settings
from app.traders.service import active_sbp, add_daily_volume, used_volume_for_update, utc_today

ALREADY_TAKEN_TEXT = "Заявка уже принята другим трейдером"


class OrderAlreadyTaken(Exception):
    def __init__(self) -> None:
        super().__init__(ALREADY_TAKEN_TEXT)


class AcceptExpired(Exception):
    def __init__(self) -> None:
        super().__init__("Время на принятие заявки истекло")


class NotEligible(Exception):
    def __init__(self) -> None:
        super().__init__("Заявка вам недоступна.")


async def offer_order(session: AsyncSession, order: Order) -> list[uuid.UUID]:
    if str(order.status) != OrderStatus.SEARCHING_EXECUTOR.value:
        return []
    settings = await load_pricing_settings(session)
    notified: list[uuid.UUID] = []
    for trader_id, _method_id in await eligible_traders(session, order):
        await enqueue(
            session,
            user_id=trader_id,
            order_id=order.id,
            kind="trader_offer",
            text=trader_offer_text(order, settings.accept_ttl_seconds),
            buttons=[{"text": "ПРИНЯТЬ", "callback_data": f"accept:{order.id}"}],
        )
        notified.append(trader_id)
    return notified


async def eligible_traders(session: AsyncSession, order: Order) -> list[tuple[uuid.UUID, uuid.UUID]]:
    rows = (
        await session.execute(
            text(
                """
                SELECT t.user_id, m.id
                FROM traders t
                JOIN users u ON u.id = t.user_id
                JOIN trader_payment_methods m
                  ON m.trader_id = t.user_id
                 AND m.is_active
                 AND m.kind = 'sbp'
                LEFT JOIN trader_daily_volume v
                  ON v.trader_id = t.user_id
                 AND v.day = :day
                LEFT JOIN ledger_accounts a
                  ON a.code = 'trader_available:' || t.user_id::text
                LEFT JOIN ledger_balances b
                  ON b.account_id = a.id
                WHERE t.status = 'active'
                  AND u.status = 'active'
                  AND t.is_online
                  AND COALESCE(b.balance_sats, 0) >= :lock_sats
                  AND :principal >= t.min_order_rub_kop
                  AND :principal <= t.max_order_rub_kop
                  AND COALESCE(v.used_rub_kop, 0) + :principal <= t.daily_limit_rub_kop
                """
            ),
            {
                "day": utc_today(),
                "lock_sats": order.trader_lock_sats,
                "principal": order.principal_rub_kop,
            },
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


async def accept_order(session: AsyncSession, *, order_id: uuid.UUID, trader_user_id: uuid.UUID) -> Order:
    trader = await session.get(Trader, trader_user_id, with_for_update=True)
    user = await session.get(User, trader_user_id)
    if trader is None or user is None:
        raise NotEligible()
    order = await session.get(Order, order_id)
    if order is None:
        raise LookupError("order not found")
    if str(order.status) != OrderStatus.SEARCHING_EXECUTOR.value:
        raise OrderAlreadyTaken()
    if order.accept_expires_at is not None and order.accept_expires_at <= datetime.now(timezone.utc):
        raise AcceptExpired()

    method = await active_sbp(session, trader_user_id)
    await _require_eligible(session, trader, user, method, order)

    claimed = await session.execute(
        text(
            """
            UPDATE orders
            SET status = 'EXECUTOR_ASSIGNED',
                trader_id = :trader_id,
                updated_at = NOW()
            WHERE id = :order_id
              AND status = 'SEARCHING_EXECUTOR'
              AND (accept_expires_at IS NULL OR accept_expires_at > NOW())
            RETURNING id
            """
        ),
        {"trader_id": trader_user_id, "order_id": order_id},
    )
    if claimed.first() is None:
        fresh = await session.get(Order, order_id, populate_existing=True)
        if fresh is not None and str(fresh.status) == OrderStatus.SEARCHING_EXECUTOR.value:
            raise AcceptExpired()
        raise OrderAlreadyTaken()

    await session.refresh(order)
    if method is None:
        raise NotEligible()
    order.payment_method_id = method.id
    settings = await load_pricing_settings(session)
    order.pay_expires_at = utcnow() + timedelta(seconds=settings.pay_ttl_seconds)
    add_order_event(
        session,
        order,
        from_status=OrderStatus.SEARCHING_EXECUTOR,
        to_status=OrderStatus.EXECUTOR_ASSIGNED,
        actor_type="trader",
        actor_user_id=trader_user_id,
        idempotency_key=f"order:{order.id}:status:EXECUTOR_ASSIGNED",
        payload={"trader_id": str(trader_user_id)},
    )
    from app.escrow.service import lock_escrow

    try:
        await lock_escrow(session, order)
    except InsufficientBalance as exc:
        raise NotEligible() from exc
    await add_daily_volume(session, trader_user_id, utc_today(), order.principal_rub_kop)
    await transition(
        session,
        order,
        OrderStatus.WAITING_PAYMENT,
        actor_type="trader",
        actor_user_id=trader_user_id,
        idempotency_key=f"order:{order.id}:status:WAITING_PAYMENT",
        payload={"payment_method_id": str(method.id)},
    )
    await enqueue(
        session,
        user_id=order.client_id,
        order_id=order.id,
        kind="client_payment_details",
        text=client_payment_text(order, method),
        buttons=[
            {"text": "Я оплатил", "callback_data": f"pay:{order.id}"},
            {"text": "Отменить", "callback_data": f"cancel:{order.id}"},
        ],
    )
    await session.flush()
    await session.refresh(order)
    return order


async def _require_eligible(
    session: AsyncSession,
    trader: Trader,
    user: User,
    method: TraderPaymentMethod | None,
    order: Order,
) -> None:
    if str(trader.status) != "active" or str(user.status) != "active" or not trader.is_online:
        raise NotEligible()
    if method is None:
        raise NotEligible()
    principal = order.principal_rub_kop
    if principal < trader.min_order_rub_kop or principal > trader.max_order_rub_kop:
        raise NotEligible()
    available = await available_for_update(session, trader.user_id)
    if available < order.trader_lock_sats:
        raise NotEligible()
    used = await used_volume_for_update(session, trader.user_id, utc_today())
    if used + principal > trader.daily_limit_rub_kop:
        raise NotEligible()
