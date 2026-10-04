"""Deposit addresses and the one-time ledger credit for a confirmed output.

Unconfirmed coins are stored on wallet_transactions and do not move the ledger.
The same txid and vout cannot credit trader_available twice.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import wallet_min_confirmations
from app.ledger.service import LedgerLine, post_group, trader_available_code
from app.models import Trader, WalletAddress, WalletTransaction
from app.wallets.adapter import IncomingOutput, WalletAdapter, normalize_txid
from app.wallets.errors import WalletError
from app.wallets.fake import HOT_WALLET_ID, FakeWalletAdapter


class DepositAddressError(WalletError):
    def __init__(self) -> None:
        super().__init__("Адрес пополнения доступен активному трейдеру.")


async def ensure_deposit_address(
    session: AsyncSession,
    trader_id: uuid.UUID,
    adapter: WalletAdapter,
) -> str:
    """Return the trader's one active deposit address, creating it once."""

    trader = await session.scalar(select(Trader).where(Trader.user_id == trader_id).with_for_update())
    if trader is None or str(trader.status) != "active":
        raise DepositAddressError()
    existing = await session.scalar(
        select(WalletAddress).where(
            WalletAddress.trader_id == trader_id,
            WalletAddress.purpose == "deposit",
            WalletAddress.is_active.is_(True),
        )
    )
    if existing is not None:
        return existing.address
    address = (await adapter.create_deposit_address(trader_id)).strip()
    if not address:
        raise WalletError("wallet did not return a deposit address")
    session.add(
        WalletAddress(
            trader_id=trader_id,
            purpose="deposit",
            address=address,
            is_active=True,
        )
    )
    await session.flush()
    return address


async def ensure_hot_address(session: AsyncSession, adapter: WalletAdapter) -> WalletAddress:
    existing = await session.scalar(
        select(WalletAddress)
        .where(WalletAddress.purpose == "hot", WalletAddress.is_active.is_(True))
        .with_for_update()
    )
    if existing is not None:
        return existing
    address = (await adapter.create_deposit_address(HOT_WALLET_ID)).strip()
    if not address:
        raise WalletError("wallet did not return a hot address")
    row = WalletAddress(trader_id=None, purpose="hot", address=address, is_active=True)
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(
            select(WalletAddress).where(WalletAddress.purpose == "hot", WalletAddress.is_active.is_(True))
        )
        if existing is None:
            raise
        return existing
    return row


async def poll_deposits(
    session: AsyncSession,
    adapter: WalletAdapter,
    *,
    min_confirmations: int | None = None,
) -> int:
    """Write each new incoming output once and credit it after the confirmation minimum."""

    minimum = wallet_min_confirmations() if min_confirmations is None else min_confirmations
    if minimum < 1:
        raise WalletError("the confirmation minimum must be at least 1")
    credited = 0
    addresses = list(
        await session.scalars(
            select(WalletAddress).where(
                WalletAddress.purpose == "deposit",
                WalletAddress.is_active.is_(True),
            )
        )
    )
    for address in addresses:
        if address.trader_id is None:
            continue
        for item in await adapter.list_incoming(address.address):
            if await _apply_incoming(session, address, item, minimum):
                credited += 1
    return credited


async def simulate_confirmed_deposit(
    session: AsyncSession,
    trader_id: uuid.UUID,
    amount_sats: int,
    *,
    txid: str,
    vout: int = 0,
    confirmations: int = 1,
    adapter: FakeWalletAdapter,
) -> None:
    """Queue one pretend deposit and run the same poll the Electrum worker uses.

    Tests call this instead of admin_credit when they want a DEPOSIT ledger group.
    The default bot still uses admin_credit while WALLET_BACKEND=fake.
    """

    address = await ensure_deposit_address(session, trader_id, adapter)
    adapter.queue_deposit(
        address,
        txid=txid,
        vout=vout,
        amount_sats=amount_sats,
        confirmations=confirmations,
    )
    await poll_deposits(session, adapter)


async def _apply_incoming(
    session: AsyncSession,
    address: WalletAddress,
    item: IncomingOutput,
    min_confirmations: int,
) -> bool:
    txid = normalize_txid(item.txid)
    if txid is None or item.vout < 0 or item.amount_sats <= 0 or address.trader_id is None:
        return False
    stored = IncomingOutput(txid, item.vout, item.amount_sats, max(0, item.confirmations))
    row = await _lock_incoming(session, address.id, stored)
    if stored.confirmations > row.confirmations:
        row.confirmations = stored.confirmations
    if row.ledger_group_id is None and row.confirmations > 0 and str(row.status) == "seen":
        row.status = "confirmed"
    return await _credit_if_confirmed(session, row, address.trader_id, min_confirmations)


async def _lock_incoming(
    session: AsyncSession,
    address_id: uuid.UUID,
    item: IncomingOutput,
) -> WalletTransaction:
    existing = await _find_incoming(session, item.txid, item.vout)
    if existing is not None:
        return existing
    row = WalletTransaction(
        txid=item.txid,
        vout=item.vout,
        direction="in",
        address_id=address_id,
        amount_sats=item.amount_sats,
        confirmations=item.confirmations,
        status="seen" if item.confirmations < 1 else "confirmed",
        raw={},
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        existing = await _find_incoming(session, item.txid, item.vout)
        if existing is None:
            raise
        return existing
    return row


async def _find_incoming(session: AsyncSession, txid: str, vout: int) -> WalletTransaction | None:
    return await session.scalar(
        select(WalletTransaction)
        .where(
            WalletTransaction.txid == txid,
            WalletTransaction.vout == vout,
            WalletTransaction.direction == "in",
        )
        .with_for_update()
    )


async def _credit_if_confirmed(
    session: AsyncSession,
    row: WalletTransaction,
    trader_id: uuid.UUID,
    min_confirmations: int,
) -> bool:
    if row.ledger_group_id is not None:
        return False
    if row.confirmations < min_confirmations:
        return False
    key = f"deposit:{row.txid}:{row.vout}"
    result = await post_group(
        session,
        operation_key=key,
        scope="deposit",
        order_id=None,
        lines=[
            LedgerLine(
                code=trader_available_code(trader_id),
                kind="trader_available",
                user_id=trader_id,
                amount_sats=row.amount_sats,
                entry_type="DEPOSIT",
                idempotency_key=f"{key}:available",
            ),
            LedgerLine(
                code="external_in",
                kind="external_in",
                user_id=None,
                amount_sats=-row.amount_sats,
                entry_type="DEPOSIT",
                idempotency_key=f"{key}:external_in",
            ),
        ],
    )
    row.ledger_group_id = result.group_id
    row.status = "credited"
    await session.flush()
    return result.created
