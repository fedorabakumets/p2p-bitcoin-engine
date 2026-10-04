"""Expire searches and unpaid orders. Tests call these functions directly."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order, OrderStatus
from app.notifications.messages import client_expired_text
from app.notifications.service import enqueue
from app.orders.payment import return_lock_to_trader
from app.orders.service import transition


async def expire_search(session: AsyncSession) -> list[Order]:
    return await _expire(
        session,
        status=OrderStatus.SEARCHING_EXECUTOR.value,
        column="accept_expires_at",
        reason="accept_window",
        unlock=False,
    )


async def expire_waiting_payments(session: AsyncSession) -> list[Order]:
    """WAITING_PAYMENT past pay_expires_at becomes EXPIRED. CLIENT_MARKED_PAID stays."""

    return await _expire(
        session,
        status=OrderStatus.WAITING_PAYMENT.value,
        column="pay_expires_at",
        reason="pay_window",
        unlock=True,
    )


async def expire_due(session: AsyncSession) -> list[Order]:
    expired = await expire_search(session)
    expired.extend(await expire_waiting_payments(session))
    return expired


async def _expire(
    session: AsyncSession,
    *,
    status: str,
    column: str,
    reason: str,
    unlock: bool,
) -> list[Order]:
    if column not in {"accept_expires_at", "pay_expires_at"}:
        raise ValueError("unsupported expiry column")
    rows = await session.execute(
        text(
            f"""
            SELECT id
            FROM orders
            WHERE status = CAST(:status AS order_status)
              AND {column} IS NOT NULL
              AND {column} <= NOW()
            FOR UPDATE SKIP LOCKED
            """
        ),
        {"status": status},
    )
    expired: list[Order] = []
    for (order_id,) in rows:
        order = await session.get(Order, order_id, populate_existing=True)
        if order is None or str(order.status) != status:
            continue
        if unlock:
            await return_lock_to_trader(session, order)
        order.cancel_reason = reason
        await transition(
            session,
            order,
            OrderStatus.EXPIRED,
            actor_type="system",
            actor_user_id=None,
            idempotency_key=f"order:{order.id}:status:EXPIRED",
            payload={"reason": reason},
        )
        await enqueue(
            session,
            user_id=order.client_id,
            order_id=order.id,
            kind="client_expired",
            text=client_expired_text(order),
        )
        expired.append(order)
    return expired
