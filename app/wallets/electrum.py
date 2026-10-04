"""JSON-RPC client for an Electrum daemon on testnet.

The daemon is not started by this process. payto and broadcast run only when
WALLET_BACKEND=electrum and BITCOIN_NETWORK=testnet.
"""

import asyncio
import base64
import json
import urllib.error
import urllib.request
import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Protocol

from app.wallets.adapter import IncomingOutput, normalize_txid, require_positive_sats
from app.wallets.errors import WalletBroadcastError, WalletConfigError, WalletError, WalletRpcError

# One ordinary 1-input 2-output transaction. getfeerate is sat/kvB.
_PAYOUT_VBYTES = 200
_SATS = Decimal(100_000_000)


class RpcTransport(Protocol):
    async def call(self, method: str, params: list[object] | dict[str, object] | None = None) -> object:
        """Perform one JSON-RPC call and return the result field."""


class HttpRpcTransport:
    """Electrum's CommandsServer is HTTP JSON-RPC with HTTP basic auth."""

    def __init__(self, host: str, port: int, user: str, password: str, *, timeout: float = 20.0):
        self._url = f"http://{host}:{port}/"
        self._user = user
        self._password = password
        self._timeout = timeout

    async def call(self, method: str, params: list[object] | dict[str, object] | None = None) -> object:
        return await asyncio.to_thread(self._call, method, [] if params is None else params)

    def _call(self, method: str, params: list[object] | dict[str, object]) -> object:
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params}
        ).encode()
        request = urllib.request.Request(self._url, data=payload, method="POST")
        token = base64.b64encode(f"{self._user}:{self._password}".encode()).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
        request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            raise WalletRpcError(f"electrum rpc http {exc.code}") from None
        except urllib.error.URLError:
            raise WalletRpcError("electrum rpc is unreachable") from None
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise WalletRpcError("electrum rpc returned invalid json") from exc
        error = data.get("error")
        if error:
            if isinstance(error, dict):
                message = str(error.get("message") or "electrum rpc error")
            else:
                message = str(error)
            raise WalletRpcError(message)
        return data.get("result")


class ElectrumAdapter:
    def __init__(self, transport: RpcTransport, *, network: str = "testnet"):
        if network != "testnet":
            raise WalletConfigError(
                "Electrum backend refuses to start unless BITCOIN_NETWORK=testnet. Mainnet is not enabled."
            )
        self._rpc = transport
        self.network = network

    async def create_deposit_address(self, trader_id: uuid.UUID) -> str:
        del trader_id  # Electrum does not derive from the trader id. The row stores the result.
        result = await self._rpc.call("createnewaddress", [])
        if not isinstance(result, str) or not result.strip():
            raise WalletError("createnewaddress did not return an address")
        address = result.strip()
        if _looks_like_mainnet(address):
            raise WalletConfigError(
                "Electrum returned a mainnet address. This step refuses to store it."
            )
        return address

    async def get_transaction(self, txid: str) -> dict[str, object] | None:
        normalized = normalize_txid(txid)
        if normalized is None:
            return None
        try:
            raw = await self._rpc.call("gettransaction", [normalized])
        except WalletRpcError as exc:
            if _unknown_tx(str(exc)):
                return None
            raise
        confirmations = await self.get_confirmations(normalized)
        if isinstance(raw, dict):
            found = dict(raw)
            found.setdefault("txid", normalized)
            found["confirmations"] = confirmations
            return found
        if isinstance(raw, str):
            return {"txid": normalized, "hex": raw, "confirmations": confirmations}
        return {"txid": normalized, "confirmations": confirmations}

    async def get_confirmations(self, txid: str) -> int:
        normalized = normalize_txid(txid)
        if normalized is None:
            return 0
        try:
            result = await self._rpc.call("get_tx_status", [normalized])
        except WalletRpcError:
            return 0
        if isinstance(result, dict):
            return max(0, int(result.get("confirmations") or 0))
        return 0

    async def estimate_fee(self) -> int:
        result = await self._rpc.call("getfeerate", [])
        rate = _fee_rate_sat_per_kvb(result)
        return max(1, (rate * _PAYOUT_VBYTES + 999) // 1000)

    async def send_btc(self, destination: str, amount_sats: int) -> str:
        require_positive_sats(amount_sats)
        target = destination.strip()
        if not target:
            raise WalletBroadcastError("destination is empty")
        amount_btc = f"{Decimal(amount_sats) / _SATS:.8f}"
        try:
            paid = await self._rpc.call("payto", [target, amount_btc])
            raw_tx = _signed_tx_hex(paid)
            broadcast = await self._rpc.call("broadcast", [raw_tx])
        except WalletRpcError as exc:
            raise WalletBroadcastError("broadcast failed") from exc
        txid = _broadcast_txid(broadcast)
        if txid is None:
            raise WalletBroadcastError("broadcast did not return a txid")
        return txid

    async def get_wallet_balance(self) -> int:
        result = await self._rpc.call("getbalance", [])
        if not isinstance(result, dict):
            raise WalletError("getbalance did not return an object")
        confirmed = _btc_to_sats(result.get("confirmed") or "0")
        unconfirmed = _btc_to_sats(result.get("unconfirmed") or "0")
        return confirmed + unconfirmed

    async def list_incoming(self, address: str) -> list[IncomingOutput]:
        history = await self._rpc.call("getaddresshistory", [address])
        unspent = await self._rpc.call("getaddressunspent", [address])
        info = await self._rpc.call("getinfo", [])
        tip = 0
        if isinstance(info, dict):
            tip = int(info.get("blockchain_height") or 0)
        heights: dict[str, int] = {}
        if isinstance(history, list):
            for item in history:
                if not isinstance(item, dict):
                    continue
                txid = normalize_txid(str(item.get("tx_hash") or item.get("txid") or ""))
                if txid is None:
                    continue
                heights[txid] = int(item.get("height") or 0)
        outputs: list[IncomingOutput] = []
        if not isinstance(unspent, list):
            return outputs
        for coin in unspent:
            if not isinstance(coin, dict):
                continue
            txid = normalize_txid(str(coin.get("tx_hash") or coin.get("txid") or ""))
            if txid is None:
                continue
            vout = int(coin.get("tx_pos") if coin.get("tx_pos") is not None else coin.get("vout") or 0)
            amount = _output_value_to_sats(coin.get("value"))
            if amount <= 0 or vout < 0:
                continue
            height = int(coin.get("height") or heights.get(txid) or 0)
            outputs.append(
                IncomingOutput(
                    txid=txid,
                    vout=vout,
                    amount_sats=amount,
                    confirmations=_confirmations(height, tip),
                )
            )
        return outputs

    async def get_network_info(self) -> dict[str, object]:
        result = await self._rpc.call("getinfo", [])
        if not isinstance(result, dict):
            raise WalletError("getinfo did not return an object")
        return result


def _looks_like_mainnet(address: str) -> bool:
    value = address.strip()
    if value.lower().startswith("bc1"):
        return True
    return value[:1] in {"1", "3"}


def _unknown_tx(message: str) -> bool:
    lowered = message.lower()
    return "unknown" in lowered or "not in wallet" in lowered or "no such" in lowered


def _btc_to_sats(value: object) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    decimal = Decimal(str(value))
    if decimal <= 0:
        return 0
    return int((decimal * _SATS).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _output_value_to_sats(value: object) -> int:
    # Electrum's server listunspent reports satoshis as an int. Wallet balances are BTC strings.
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str) and "." not in value and "e" not in value.lower():
        return int(value)
    return _btc_to_sats(value)


def _confirmations(height: int, tip: int) -> int:
    if height <= 0 or tip <= 0:
        return 0
    return max(0, tip - height + 1)


def _fee_rate_sat_per_kvb(result: object) -> int:
    if isinstance(result, dict):
        raw = result.get("sat/kvB")
        if raw is None:
            raw = result.get("sat_per_kvb")
        if raw is None:
            raise WalletError("getfeerate did not include sat/kvB")
        return max(0, int(raw))
    if isinstance(result, bool) or result is None:
        raise WalletError("getfeerate did not return a rate")
    return max(0, int(result))


def _signed_tx_hex(paid: object) -> str:
    if isinstance(paid, str) and paid.strip():
        return paid.strip()
    if isinstance(paid, dict):
        if paid.get("complete") is False:
            raise WalletBroadcastError("payto returned an incomplete transaction")
        raw = paid.get("hex") or paid.get("tx")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    raise WalletBroadcastError("payto did not return a transaction")


def _broadcast_txid(result: object) -> str | None:
    if isinstance(result, list) and result:
        return normalize_txid(result[0])
    return normalize_txid(result)
