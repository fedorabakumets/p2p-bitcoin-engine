"""Choose the wallet backend from the environment. The default is fake."""

import sys

from app.config import (
    bitcoin_network,
    electrum_rpc_host,
    electrum_rpc_password,
    electrum_rpc_port,
    electrum_rpc_user,
    wallet_backend,
)
from app.wallets.adapter import WalletAdapter
from app.wallets.electrum import ElectrumAdapter, HttpRpcTransport
from app.wallets.errors import WalletConfigError, WalletError, WalletRpcError
from app.wallets.fake import FakeWalletAdapter

_fake: FakeWalletAdapter | None = None


def require_wallet_backend() -> str:
    """Return fake or electrum. Electrum starts only on testnet."""

    backend = wallet_backend()
    if backend == "fake":
        return backend
    network = bitcoin_network()
    if network != "testnet":
        _refuse(
            "BITCOIN_NETWORK must be testnet. "
            "This step refuses to start the Electrum backend on mainnet."
        )
    _require_rpc_settings()
    return backend


def get_wallet_adapter() -> WalletAdapter:
    backend = require_wallet_backend()
    if backend == "fake":
        global _fake
        if _fake is None:
            _fake = FakeWalletAdapter()
        return _fake
    return build_electrum_adapter()


def build_electrum_adapter() -> ElectrumAdapter:
    require_wallet_backend()
    if wallet_backend() != "electrum":
        raise WalletConfigError("Electrum adapter requested while WALLET_BACKEND is not electrum")
    _require_rpc_settings()
    transport = HttpRpcTransport(
        electrum_rpc_host(),
        electrum_rpc_port(),
        electrum_rpc_user(),
        electrum_rpc_password(),
    )
    return ElectrumAdapter(transport, network=bitcoin_network())


async def assert_electrum_ready() -> None:
    """When the backend is electrum, refuse mainnet and a daemon that is not testnet.

    Fake mode returns without a network call so the current bot keeps polling.
    """

    if require_wallet_backend() != "electrum":
        return
    adapter = build_electrum_adapter()
    try:
        info = await adapter.get_network_info()
    except (WalletRpcError, WalletConfigError, WalletError) as exc:
        _refuse(
            "Electrum testnet daemon is not reachable. "
            "Leave WALLET_BACKEND=fake or start electrum --testnet daemon yourself. "
            f"({exc})"
        )
    network = str(info.get("network") or "").strip().lower()
    if network != "testnet":
        _refuse(
            f"Electrum daemon reports network {network or 'unknown'}. "
            "This step refuses to start unless the daemon is testnet."
        )


def _require_rpc_settings() -> None:
    if not electrum_rpc_host():
        _refuse("ELECTRUM_RPC_HOST is required when WALLET_BACKEND=electrum.")
    electrum_rpc_port()
    if not electrum_rpc_user():
        _refuse("ELECTRUM_RPC_USER is required when WALLET_BACKEND=electrum.")
    if not electrum_rpc_password():
        _refuse("ELECTRUM_RPC_PASSWORD is required when WALLET_BACKEND=electrum.")


def _refuse(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)
