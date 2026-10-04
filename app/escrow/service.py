"""Lock, unlock, and release trader satoshis for one order.

Release pays the client through external_out, keeps the platform fee, and moves
the referral slice from platform_revenue to referral_payable. The ruble markup
is not credited.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ledger.service import (
    LedgerLine,
    post_group,
    referral_payable_code,
    trader_available_code,
    trader_locked_code,
)
from app.models import EscrowLock, Order, ReferralReward, User, utcnow


class EscrowStateError(Exception):
    pass


async def get_escrow(session: AsyncSession, order_id: uuid.UUID) -> EscrowLock | None:
    return await session.scalar(select(EscrowLock).where(EscrowLock.order_id == order_id))


async def lock_escrow(session: AsyncSession, order: Order) -> EscrowLock:
    existing = await session.scalar(
        select(EscrowLock).where(EscrowLock.order_id == order.id).with_for_update()
    )
    if existing is not None:
        if str(existing.status) == "locked" and existing.amount_sats == order.trader_lock_sats:
            return existing
        raise EscrowStateError(f"escrow is {existing.status}")
    if order.trader_id is None:
        raise EscrowStateError("order has no trader")
    amount = order.trader_lock_sats
    result = await post_group(
        session,
        operation_key=f"escrow-lock:{order.id}",
        scope="escrow_lock",
        order_id=order.id,
        lines=[
            LedgerLine(
                code=trader_available_code(order.trader_id),
                kind="trader_available",
                user_id=order.trader_id,
                amount_sats=-amount,
                entry_type="ESCROW_LOCK",
                idempotency_key=f"escrow-lock:{order.id}:available",
            ),
            LedgerLine(
                code=trader_locked_code(order.trader_id),
                kind="trader_locked",
                user_id=order.trader_id,
                amount_sats=amount,
                entry_type="ESCROW_LOCK",
                idempotency_key=f"escrow-lock:{order.id}:locked",
            ),
        ],
    )
    if existing is None:
        existing = EscrowLock(
            order_id=order.id,
            trader_id=order.trader_id,
            amount_sats=amount,
            status="locked",
            lock_group_id=result.group_id,
        )
        session.add(existing)
        await session.flush()
    return existing


async def unlock_escrow(session: AsyncSession, order: Order) -> EscrowLock:
    escrow = await session.scalar(select(EscrowLock).where(EscrowLock.order_id == order.id).with_for_update())
    if escrow is None:
        raise EscrowStateError("escrow is missing")
    if str(escrow.status) == "unlocked":
        return escrow
    if str(escrow.status) != "locked":
        raise EscrowStateError(f"escrow is {escrow.status}")
    result = await post_group(
        session,
        operation_key=f"escrow-unlock:{order.id}",
        scope="escrow_unlock",
        order_id=order.id,
        lines=[
            LedgerLine(
                code=trader_locked_code(escrow.trader_id),
                kind="trader_locked",
                user_id=escrow.trader_id,
                amount_sats=-escrow.amount_sats,
                entry_type="ESCROW_UNLOCK",
                idempotency_key=f"escrow-unlock:{order.id}:locked",
            ),
            LedgerLine(
                code=trader_available_code(escrow.trader_id),
                kind="trader_available",
                user_id=escrow.trader_id,
                amount_sats=escrow.amount_sats,
                entry_type="ESCROW_UNLOCK",
                idempotency_key=f"escrow-unlock:{order.id}:available",
            ),
        ],
    )
    escrow.status = "unlocked"
    escrow.release_group_id = result.group_id
    escrow.closed_at = utcnow()
    await session.flush()
    return escrow


async def release_escrow(session: AsyncSession, order: Order) -> EscrowLock:
    """Move trader_lock_sats off trader_locked. payout_wallet_tx_id stays untouched."""

    escrow = await session.scalar(select(EscrowLock).where(EscrowLock.order_id == order.id).with_for_update())
    if escrow is None:
        raise EscrowStateError("escrow is missing")
    if str(escrow.status) == "released":
        return escrow
    if str(escrow.status) != "locked":
        raise EscrowStateError(f"escrow is {escrow.status}")
    if escrow.amount_sats != order.trader_lock_sats:
        raise EscrowStateError("escrow amount does not match the order snapshot")

    client_sats = order.client_btc_sats
    fee_sats = order.platform_fee_sats
    lines = [
        LedgerLine(
            code=trader_locked_code(escrow.trader_id),
            kind="trader_locked",
            user_id=escrow.trader_id,
            amount_sats=-order.trader_lock_sats,
            entry_type="ESCROW_RELEASE",
            idempotency_key=f"escrow-release:{order.id}:locked",
        ),
        LedgerLine(
            code="external_out",
            kind="external_out",
            user_id=None,
            amount_sats=client_sats,
            entry_type="ESCROW_RELEASE",
            idempotency_key=f"escrow-release:{order.id}:external_out",
        ),
    ]
    if fee_sats > 0:
        lines.append(
            LedgerLine(
                code="platform_revenue",
                kind="platform_revenue",
                user_id=None,
                amount_sats=fee_sats,
                entry_type="PLATFORM_REVENUE",
                idempotency_key=f"escrow-release:{order.id}:platform",
            )
        )
    result = await post_group(
        session,
        operation_key=f"escrow-release:{order.id}",
        scope="escrow_release",
        order_id=order.id,
        lines=lines,
    )
    await _accrue_referral(session, order)
    escrow.status = "released"
    escrow.release_group_id = result.group_id
    escrow.closed_at = utcnow()
    await session.flush()
    return escrow


async def _accrue_referral(session: AsyncSession, order: Order) -> None:
    if order.referral_sats <= 0:
        return
    client = await session.get(User, order.client_id)
    if client is None or client.referred_by_user_id is None:
        return
    existing = await session.scalar(select(ReferralReward.id).where(ReferralReward.order_id == order.id))
    if existing is not None:
        return
    referrer_id = client.referred_by_user_id
    result = await post_group(
        session,
        operation_key=f"referral:{order.id}",
        scope="referral_reward",
        order_id=order.id,
        lines=[
            LedgerLine(
                code="platform_revenue",
                kind="platform_revenue",
                user_id=None,
                amount_sats=-order.referral_sats,
                entry_type="REFERRAL_REWARD",
                idempotency_key=f"referral:{order.id}:platform",
            ),
            LedgerLine(
                code=referral_payable_code(referrer_id),
                kind="referral_payable",
                user_id=referrer_id,
                amount_sats=order.referral_sats,
                entry_type="REFERRAL_REWARD",
                idempotency_key=f"referral:{order.id}:payable",
            ),
        ],
    )
    if not result.created:
        existing = await session.scalar(select(ReferralReward.id).where(ReferralReward.order_id == order.id))
        if existing is not None:
            return
    session.add(
        ReferralReward(
            order_id=order.id,
            referrer_user_id=referrer_id,
            referred_user_id=order.client_id,
            amount_sats=order.referral_sats,
            ledger_group_id=result.group_id,
            status="accrued",
        )
    )
    await session.flush()
