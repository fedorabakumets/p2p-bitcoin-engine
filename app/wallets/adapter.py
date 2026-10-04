"""Wallet port. Tests and the default runtime use the fake adapter.

Electrum is a second implementation of the same methods. Deposit polling
uses list_incoming so a new output is discovered without a live daemon in tests.
"""

import uuid
from dataclasses import dataclass
from typing import Protocol

from app.wallets.errors import WalletError


@dataclass(frozen=True)
class IncomingOutput:
    txid: str
    vout: int
    amount_sats: int
    confirmations: int


class WalletAdapter(Protocol):
    async def create_deposit_address(self, trader_id: uuid.UUID) -> str:
        """Return a new deposit address for this trader."""

    async def get_transaction(self, txid: str) -> dict[str, object] | None:
        """Return a transaction description, or None when the node does not know it."""

    async def get_confirmations(self, txid: str) -> int:
        """Return how many blocks sit on top of this transaction. Unconfirmed is 0."""

    async def estimate_fee(self) -> int:
        """Return a fee estimate in satoshis for one ordinary payout."""

    async def send_btc(self, destination: str, amount_sats: int) -> str:
        """Broadcast amount_sats to destination and return the chain txid."""

    async def get_wallet_balance(self) -> int:
        """Return the on-chain wallet balance in satoshis."""

    async def list_incoming(self, address: str) -> list[IncomingOutput]:
        """Return incoming outputs still visible for this deposit address."""


def normalize_txid(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    txid = value.strip().lower()
    if len(txid) != 64:
        return None
    if any(char not in "0123456789abcdef" for char in txid):
        return None
    return txid


def require_positive_sats(amount_sats: int) -> None:
    if isinstance(amount_sats, bool) or not isinstance(amount_sats, int):
        raise WalletError("amount must be a positive satoshi count")
    if amount_sats <= 0 or amount_sats > 2**63 - 1:
        raise WalletError("amount must be a positive satoshi count")
