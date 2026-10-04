"""Client payment, cancel, and trader confirmation. Handlers only call these."""

import uuid
from datetime import timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.escrow.service import get_escrow, release_escrow, unlock_escrow
from app.models import Order, OrderStatus, utcnow
from app.notifications.messages import client_cancelled_text, client_completed_text, trader_paid_text
from app.notifications.service import enqueue
from app.orders.service import IllegalOrderTransition, transition
from app.traders.service import add_daily_volume
from app.wallets.adapter import WalletAdapter
from app.wallets.payout import broadcast_client_payout, payout_adapter


class CancelNotAllowed(Exception):
    def __init__(self) -> None:
        super().__init__("После отметки об оплате отменить заявку нельзя.")


class NotOrderClient(Exception):
    def __init__(self) -> None:
        super().__init__("Это не ваша заявка.")


class NotOrderTrader(Exception):
    def __init__(self) -> None:
        super().__init__("Это не ваша заявка.")


class ConfirmTooEarly(Exception):
    def __init__(self) -> None:
        super().__init__("Сначала клиент отмечает оплату.")


_CLIENT_CAN_CANCEL = {
    OrderStatus.CREATED.value,
    OrderStatus.QUOTED.value,
    OrderStatus.SEARCHING_EXECUTOR.value,
    OrderStatus.EXECUTOR_ASSIGNED.value,
    OrderStatus.WAITING_PAYMENT.value,
}


async def mark_client_paid(session: AsyncSession, *, order_id: uuid.UUID, client_id: uuid.UUID) -> Order:
    order = await _lock_order(session, order_id)
    if order.client_id != client_id:
        raise NotOrderClient()
    status = str(order.status)
    if status == OrderStatus.CLIENT_MARKED_PAID.value:
        return order
    if status != OrderStatus.WAITING_PAYMENT.value:
        raise IllegalOrderTransition(status, OrderStatus.CLIENT_MARKED_PAID.value)
    order.client_marked_paid_at = utcnow()
    await transition(
        session,
        order,
        OrderStatus.CLIENT_MARKED_PAID,
        actor_type="client",
        actor_user_id=client_id,
        idempotency_key=f"order:{order.id}:status:CLIENT_MARKED_PAID",
    )
    if order.trader_id is not None:
        await enqueue(
            session,
            user_id=order.trader_id,
            order_id=order.id,
            kind="trader_client_paid",
            text=trader_paid_text(order),
            buttons=[
                {"text": "Подтвердить получение", "callback_data": f"confirm:{order.id}"},
                {"text": "Открыть спор", "callback_data": f"dispute:{order.id}"},
            ],
        )
    await session.refresh(order)
    return order


async def cancel_by_client(session: AsyncSession, *, order_id: uuid.UUID, client_id: uuid.UUID) -> Order:
    order = await _lock_order(session, order_id)
    if order.client_id != client_id:
        raise NotOrderClient()
    status = str(order.status)
    if status == OrderStatus.CANCELLED.value:
        return order
    if status not in _CLIENT_CAN_CANCEL:
        raise CancelNotAllowed()
    await return_lock_to_trader(session, order)
    order.cancel_reason = "client"
    await transition(
        session,
        order,
        OrderStatus.CANCELLED,
        actor_type="client",
        actor_user_id=client_id,
        idempotency_key=f"order:{order.id}:status:CANCELLED",
        payload={"reason": "client"},
    )
    await enqueue(
        session,
        user_id=order.client_id,
        order_id=order.id,
        kind="client_cancelled",
        text=client_cancelled_text(order),
    )
    await session.refresh(order)
    return order


async def confirm_receipt(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    trader_id: uuid.UUID,
    wallet: WalletAdapter | None = None,
) -> Order:
    order = await _lock_order(session, order_id)
    if order.trader_id != trader_id:
        raise NotOrderTrader()
    status = str(order.status)
    if status == OrderStatus.COMPLETED.value:
        return order
    if status != OrderStatus.CLIENT_MARKED_PAID.value:
        if status == OrderStatus.WAITING_PAYMENT.value:
            raise ConfirmTooEarly()
        raise IllegalOrderTransition(status, OrderStatus.PAYMENT_CONFIRMED.value)
    order.trader_confirmed_at = utcnow()
    await transition(
        session,
        order,
        OrderStatus.PAYMENT_CONFIRMED,
        actor_type="trader",
        actor_user_id=trader_id,
        idempotency_key=f"order:{order.id}:status:PAYMENT_CONFIRMED",
    )
    return await release_and_complete(
        session,
        order,
        actor_type="trader",
        actor_user_id=trader_id,
        wallet=wallet,
    )


async def return_lock_to_trader(session: AsyncSession, order: Order) -> None:
    escrow = await get_escrow(session, order.id)
    if escrow is None or str(escrow.status) != "locked":
        return
    day = escrow.created_at.astimezone(timezone.utc).date() if escrow.created_at.tzinfo else escrow.created_at.date()
    await unlock_escrow(session, order)
    if order.trader_id is not None:
        await add_daily_volume(session, order.trader_id, day, -order.principal_rub_kop)


async def release_and_complete(
    session: AsyncSession,
    order: Order,
    *,
    actor_type: str,
    actor_user_id: uuid.UUID | None,
    idempotency_suffix: str = "",
    wallet: WalletAdapter | None = None,
) -> Order:
    """Release escrow and complete the order in this same database transaction.

    WALLET_BACKEND=fake does not call the network. payout_wallet_tx_id stays
    null and the order still becomes COMPLETED.

    An Electrum backend, or an adapter passed by a test, broadcasts
    client_btc_sats first. COMPLETED is set only after that call returns a
    txid, and the ledger release is in this same transaction. If broadcast
    fails, PayoutBroadcastError is raised while the order is already
    RELEASING and the escrow is still locked. The caller commits that state.
    Locked sats are not unlocked and not released, so they cannot be lost or
    paid twice by a second click.
    """

    suffix = idempotency_suffix
    await transition(
        session,
        order,
        OrderStatus.RELEASING,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        idempotency_key=f"order:{order.id}:status:RELEASING{suffix}",
    )
    adapter = payout_adapter(wallet)
    wallet_row = None
    chain_txid = None
    if adapter is not None:
        wallet_row, chain_txid = await broadcast_client_payout(session, order, adapter)
    escrow = await release_escrow(session, order)
    if wallet_row is not None:
        wallet_row.ledger_group_id = escrow.release_group_id
    await transition(
        session,
        order,
        OrderStatus.COMPLETED,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        idempotency_key=f"order:{order.id}:status:COMPLETED{suffix}",
    )
    order.completed_at = utcnow()
    order.payout_wallet_tx_id = None if wallet_row is None else wallet_row.id
    await enqueue(
        session,
        user_id=order.client_id,
        order_id=order.id,
        kind="client_completed",
        text=client_completed_text(order, chain_txid=chain_txid),
    )
    await session.flush()
    await session.refresh(order)
    return order


async def _lock_order(session: AsyncSession, order_id: uuid.UUID) -> Order:
    order = await session.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        raise LookupError("order not found")
    return order
