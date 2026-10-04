"""Wallet failures. Broadcast failure is a money-state signal, not a lost payment."""

import uuid


class WalletError(Exception):
    pass


class WalletConfigError(WalletError):
    pass


class WalletRpcError(WalletError):
    pass


class WalletBroadcastError(WalletError):
    pass


class PayoutBroadcastError(WalletError):
    """The chain send did not return a txid.

    The order is already RELEASING in this database transaction. The escrow
    lock is still locked: trader_locked is not moved to trader_available and
    is not posted to external_out. A failed broadcast therefore neither
    returns the sats nor pays them out. The caller must commit that
    RELEASING row and must not try the send again from the same button.
    """

    def __init__(self, *, order_id: uuid.UUID, public_no: int):
        self.order_id = order_id
        self.public_no = public_no
        super().__init__(
            f"Не удалось отправить выплату по заявке №{public_no} в testnet. "
            "Заявка остаётся в RELEASING, эскроу остаётся locked: "
            "замороженные сатоши не возвращаются на доступный баланс и не списываются повторно."
        )
