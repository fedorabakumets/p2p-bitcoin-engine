"""Disputes keep escrow locked until an admin releases or unlocks.

A screenshot is stored as a Telegram file id and never confirms payment.
Unlock cancels the order and returns trader_locked to trader_available.
Release uses the same satoshi split as trader confirmation. On the fake
wallet that completes with payout_wallet_tx_id null. On Electrum, or when a
wallet adapter is passed in, the client payout is broadcast first and the
order becomes COMPLETED only after a txid. A failed broadcast leaves the
order RELEASING, the dispute open, and the escrow locked. Rubles are settled
off the platform.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.service import require_admin
from app.audit.service import add_audit
from app.escrow.service import get_escrow
from app.models import Dispute, DisputeEvidence, Order, OrderStatus, utcnow
from app.orders.payment import NotOrderTrader, release_and_complete, return_lock_to_trader
from app.orders.service import IllegalOrderTransition, transition
from app.wallets.adapter import WalletAdapter

_OPENABLE = {
    OrderStatus.WAITING_PAYMENT.value,
    OrderStatus.CLIENT_MARKED_PAID.value,
    OrderStatus.PAYMENT_CONFIRMED.value,
    OrderStatus.RELEASING.value,
}


class DisputeClosed(Exception):
    pass


@dataclass(frozen=True)
class EvidenceInput:
    telegram_file_id: str
    kind: str


def _check_evidence(item: EvidenceInput) -> None:
    if item.kind not in {"screenshot", "text"}:
        raise ValueError("evidence kind must be screenshot or text")
    file_id = item.telegram_file_id.strip()
    if not file_id or len(file_id) > 256 or any(char in file_id for char in "\n\r"):
        raise ValueError("telegram file id is required")


async def open_dispute(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    trader_user_id: uuid.UUID,
    reason: str,
    evidence: list[EvidenceInput] | None = None,
) -> Dispute:
    order = await _lock_order(session, order_id)
    if order.trader_id != trader_user_id:
        raise NotOrderTrader()
    existing = await session.scalar(select(Dispute).where(Dispute.order_id == order.id).with_for_update())
    if existing is not None:
        return existing
    status = str(order.status)
    if status not in _OPENABLE:
        raise IllegalOrderTransition(status, OrderStatus.DISPUTED.value)
    for item in evidence or []:
        _check_evidence(item)
    await transition(
        session,
        order,
        OrderStatus.DISPUTED,
        actor_type="trader",
        actor_user_id=trader_user_id,
        idempotency_key=f"order:{order.id}:status:DISPUTED",
        payload={"reason": "dispute"},
    )
    text = reason.strip()[:2000] or "спор"
    dispute = Dispute(
        order_id=order.id,
        opened_by=trader_user_id,
        reason=text,
        status="open",
    )
    session.add(dispute)
    await session.flush()
    for item in evidence or []:
        session.add(
            DisputeEvidence(
                dispute_id=dispute.id,
                uploaded_by=trader_user_id,
                telegram_file_id=item.telegram_file_id.strip(),
                kind=item.kind,
            )
        )
    await session.flush()
    return dispute


async def add_dispute_evidence(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    user_id: uuid.UUID,
    evidence: EvidenceInput,
    reason: str | None = None,
) -> DisputeEvidence:
    """Store a file id or a text marker. This does not confirm payment."""

    _check_evidence(evidence)
    dispute = await session.scalar(select(Dispute).where(Dispute.order_id == order_id).with_for_update())
    if dispute is None:
        raise LookupError("dispute not found")
    if str(dispute.status) != "open":
        raise DisputeClosed()
    if reason and reason.strip():
        dispute.reason = reason.strip()[:2000]
    row = DisputeEvidence(
        dispute_id=dispute.id,
        uploaded_by=user_id,
        telegram_file_id=evidence.telegram_file_id.strip(),
        kind=evidence.kind,
    )
    session.add(row)
    await session.flush()
    return row


async def resolve_dispute(
    session: AsyncSession,
    admin_user_id: uuid.UUID,
    order_id: uuid.UUID,
    action: str,
    note: str | None = None,
    wallet: WalletAdapter | None = None,
) -> Order:
    if action not in {"release", "unlock"}:
        raise ValueError("resolution must be release or unlock")
    await require_admin(session, admin_user_id)
    order = await _lock_order(session, order_id)
    dispute = await session.scalar(select(Dispute).where(Dispute.order_id == order.id).with_for_update())
    if dispute is None:
        raise LookupError("dispute not found")
    if str(dispute.status) == "resolved":
        return order
    escrow = await get_escrow(session, order.id)
    before_status = str(order.status)
    before_escrow = None if escrow is None else str(escrow.status)
    if action == "release":
        if str(order.status) != OrderStatus.DISPUTED.value:
            raise IllegalOrderTransition(str(order.status), OrderStatus.RELEASING.value)
        await release_and_complete(
            session,
            order,
            actor_type="admin",
            actor_user_id=admin_user_id,
            wallet=wallet,
        )
    else:
        if str(order.status) != OrderStatus.DISPUTED.value:
            raise IllegalOrderTransition(str(order.status), OrderStatus.CANCELLED.value)
        await return_lock_to_trader(session, order)
        order.cancel_reason = "dispute_unlock"
        await transition(
            session,
            order,
            OrderStatus.CANCELLED,
            actor_type="admin",
            actor_user_id=admin_user_id,
            idempotency_key=f"order:{order.id}:status:CANCELLED",
            payload={"reason": "dispute_unlock"},
        )
    dispute.status = "resolved"
    dispute.resolution = action
    dispute.resolved_by = admin_user_id
    dispute.resolved_at = utcnow()
    dispute.resolution_note = None if note is None else note.strip()[:2000] or None
    add_audit(
        session,
        actor_user_id=admin_user_id,
        action=f"dispute_{action}",
        entity_type="order",
        entity_id=order.id,
        before_state={"status": before_status, "escrow": before_escrow},
        after_state={"status": str(order.status), "resolution": action},
    )
    await session.flush()
    await session.refresh(order)
    return order


async def _lock_order(session: AsyncSession, order_id: uuid.UUID) -> Order:
    order = await session.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        raise LookupError("order not found")
    return order
