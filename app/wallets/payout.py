"""Broadcast the client's satoshis and record the outgoing wallet row.

Failure choice: send_btc runs after the order is RELEASING and before the
ledger release. If broadcast raises or returns no txid, this function raises
PayoutBroadcastError and does not insert wallet_transactions. The caller
does not release escrow and does not mark COMPLETED. Locked sats stay on
trader_locked, so they are not lost and a second release cannot spend them.
The trader button will not send again, because confirm only starts from
CLIENT_MARKED_PAID.

If broadcast returns a txid and the database transaction later rolls back,
the chain transaction exists without a local row. This step does not add a
second commit to reserve the txid before broadcast. The tested failure is
the broadcast error, which happens before any ledger movement.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order, WalletTransaction
from app.wallets.adapter import WalletAdapter, normalize_txid
from app.wallets.deposits import ensure_hot_address
from app.wallets.errors import PayoutBroadcastError

log = logging.getLogger("app.wallets.payout")


async def broadcast_client_payout(
    session: AsyncSession,
    order: Order,
    adapter: WalletAdapter,
) -> tuple[WalletTransaction, str]:
    existing = await session.scalar(
        select(WalletTransaction)
        .where(WalletTransaction.order_id == order.id, WalletTransaction.direction == "out")
        .with_for_update()
    )
    if existing is not None:
        return existing, existing.txid

    hot = await ensure_hot_address(session, adapter)
    try:
        txid = await adapter.send_btc(order.btc_address, order.client_btc_sats)
    except PayoutBroadcastError:
        raise
    except Exception as exc:
        log.exception("payout broadcast failed order=%s", order.id)
        raise PayoutBroadcastError(order_id=order.id, public_no=int(order.public_no)) from exc
    normalized = normalize_txid(txid)
    if normalized is None:
        log.error("payout broadcast returned no txid order=%s", order.id)
        raise PayoutBroadcastError(order_id=order.id, public_no=int(order.public_no))

    row = WalletTransaction(
        txid=normalized,
        vout=0,
        direction="out",
        address_id=hot.id,
        amount_sats=order.client_btc_sats,
        confirmations=0,
        status="broadcast",
        order_id=order.id,
        raw={"destination": order.btc_address},
    )
    session.add(row)
    await session.flush()
    return row, normalized


def payout_adapter(explicit: WalletAdapter | None) -> WalletAdapter | None:
    """Fake runtime passes None and does not call the network.

    An explicit adapter, including a fake one that returns a txid, is used
    as given. Electrum is loaded only when the environment asks for it.
    """

    if explicit is not None:
        return explicit
    from app.config import wallet_backend
    from app.wallets.factory import get_wallet_adapter

    if wallet_backend() != "electrum":
        return None
    return get_wallet_adapter()

