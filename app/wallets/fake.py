"""In-memory wallet. No network. The running bot uses this unless Electrum is configured."""

import uuid

from app.wallets.adapter import IncomingOutput, normalize_txid, require_positive_sats
from app.wallets.errors import WalletBroadcastError

# A stand-in id for the hot-wallet bookkeeping address. It is not a trader.
HOT_WALLET_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# Ordinary payout size used only by the fake fee estimate.
_FAKE_FEE_SATS = 1500


class FakeWalletAdapter:
    """Records addresses and a queue of pretend deposits and sends.

    send_btc does not run unless a caller passes this object into the payout
    path. The default runtime keeps WALLET_BACKEND=fake and never calls it,
    so completed orders still have a null payout_wallet_tx_id.
    """

    def __init__(self) -> None:
        self._addresses: dict[uuid.UUID, str] = {}
        self._incoming: dict[str, list[IncomingOutput]] = {}
        self._known: dict[str, IncomingOutput] = {}
        self.sent: list[tuple[str, int, str]] = []
        self.send_attempts = 0
        self.fail_send = False
        self.next_txid: str | None = None
        self.balance_sats = 0

    async def create_deposit_address(self, trader_id: uuid.UUID) -> str:
        existing = self._addresses.get(trader_id)
        if existing is not None:
            return existing
        address = "tb1q" + trader_id.hex + "fakedep"
        self._addresses[trader_id] = address
        return address

    def queue_deposit(
        self,
        address: str,
        *,
        txid: str,
        vout: int = 0,
        amount_sats: int,
        confirmations: int,
    ) -> None:
        require_positive_sats(amount_sats)
        normalized = normalize_txid(txid)
        if normalized is None:
            raise WalletBroadcastError("deposit txid must be 64 hex characters")
        if vout < 0:
            raise WalletBroadcastError("vout must be >= 0")
        if confirmations < 0:
            raise WalletBroadcastError("confirmations must be >= 0")
        item = IncomingOutput(
            txid=normalized,
            vout=vout,
            amount_sats=amount_sats,
            confirmations=confirmations,
        )
        bucket = [
            current
            for current in self._incoming.get(address, [])
            if not (current.txid == item.txid and current.vout == item.vout)
        ]
        bucket.append(item)
        self._incoming[address] = bucket
        self._known[normalized] = item

    async def list_incoming(self, address: str) -> list[IncomingOutput]:
        return list(self._incoming.get(address, []))

    async def get_transaction(self, txid: str) -> dict[str, object] | None:
        normalized = normalize_txid(txid)
        if normalized is None:
            return None
        item = self._known.get(normalized)
        if item is None:
            for _destination, amount_sats, sent_txid in self.sent:
                if sent_txid == normalized:
                    return {"txid": sent_txid, "confirmations": 0, "amount_sats": amount_sats}
            return None
        return {
            "txid": item.txid,
            "vout": item.vout,
            "amount_sats": item.amount_sats,
            "confirmations": item.confirmations,
        }

    async def get_confirmations(self, txid: str) -> int:
        found = await self.get_transaction(txid)
        if found is None:
            return 0
        return int(found.get("confirmations") or 0)

    async def estimate_fee(self) -> int:
        return _FAKE_FEE_SATS

    async def send_btc(self, destination: str, amount_sats: int) -> str:
        require_positive_sats(amount_sats)
        if not destination.strip():
            raise WalletBroadcastError("destination is empty")
        self.send_attempts += 1
        if self.fail_send:
            raise WalletBroadcastError("broadcast failed")
        txid = self.next_txid or (uuid.uuid4().hex + uuid.uuid4().hex)
        normalized = normalize_txid(txid)
        if normalized is None:
            raise WalletBroadcastError("broadcast did not return a txid")
        self.sent.append((destination, amount_sats, normalized))
        self.balance_sats -= amount_sats
        return normalized

    async def get_wallet_balance(self) -> int:
        return self.balance_sats
