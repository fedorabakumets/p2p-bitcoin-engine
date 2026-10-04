"""Electrum testnet wallet: fake deposits, mocked RPC, and payout txids."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.disputes.service import open_dispute, resolve_dispute
from app.ledger.service import balance_of, trader_balances
from app.models import (
    AdminUser,
    Dispute,
    EscrowLock,
    Order,
    OrderStatus,
    Trader,
    TraderPaymentMethod,
    User,
    WalletTransaction,
)
from app.orders.payment import confirm_receipt, mark_client_paid
from app.orders.service import IllegalOrderTransition, open_searching_order
from app.pricing.formula import build_quote
from app.routing.service import accept_order
from app.users.service import register_from_start
from app.wallets.adapter import IncomingOutput
from app.wallets.deposits import ensure_deposit_address, poll_deposits, simulate_confirmed_deposit
from app.wallets.electrum import ElectrumAdapter
from app.wallets.errors import PayoutBroadcastError, WalletBroadcastError, WalletConfigError
from app.wallets.factory import require_wallet_backend
from app.wallets.fake import FakeWalletAdapter

ADDRESS = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"

CHAIN_TXID = "ab" * 32
DEPOSIT_TXID = "cd" * 32


class ScriptedRpc:
    def __init__(self, replies: dict[str, object]):
        self.replies = replies
        self.calls: list[tuple[str, object]] = []

    async def call(self, method: str, params: object = None) -> object:
        self.calls.append((method, params))
        reply = self.replies[method]
        if callable(reply):
            return reply(params)
        return reply


async def test_fake_deposit_credits_once(session: AsyncSession) -> None:
    admin = await _admin(session, 1100)
    trader = await _trader(session, admin, 1101, balance=0)
    adapter = FakeWalletAdapter()
    await simulate_confirmed_deposit(
        session,
        trader.id,
        50_000,
        txid=DEPOSIT_TXID,
        adapter=adapter,
    )
    assert (await trader_balances(session, trader.id)).available_sats == 50_000
    assert await balance_of(session, "external_in") == -50_000
    rows = list(await session.scalars(select(WalletTransaction)))
    assert len(rows) == 1
    assert rows[0].txid == DEPOSIT_TXID
    assert str(rows[0].direction) == "in"
    assert str(rows[0].status) == "credited"
    assert rows[0].ledger_group_id is not None
    deposit_lines = await session.scalar(
        text("SELECT count(*) FROM ledger_entries WHERE entry_type = 'DEPOSIT'")
    )
    assert int(deposit_lines or 0) == 2

    assert await poll_deposits(session, adapter) == 0
    assert (await trader_balances(session, trader.id)).available_sats == 50_000
    assert await balance_of(session, "external_in") == -50_000
    again = await session.scalar(select(func.count()).select_from(WalletTransaction))
    assert int(again or 0) == 1
    deposit_lines = await session.scalar(
        text("SELECT count(*) FROM ledger_entries WHERE entry_type = 'DEPOSIT'")
    )
    assert int(deposit_lines or 0) == 2
    groups = (
        await session.execute(text("SELECT COALESCE(SUM(amount_sats), 0) FROM ledger_entries GROUP BY group_id"))
    ).scalars()
    assert all(int(total) == 0 for total in groups)


async def test_unconfirmed_deposit_is_not_credited_until_the_minimum(session: AsyncSession) -> None:
    admin = await _admin(session, 1110)
    trader = await _trader(session, admin, 1111, balance=0)
    adapter = FakeWalletAdapter()
    address = await ensure_deposit_address(session, trader.id, adapter)
    adapter.queue_deposit(address, txid=DEPOSIT_TXID, amount_sats=40_000, confirmations=0)
    assert await poll_deposits(session, adapter) == 0
    assert (await trader_balances(session, trader.id)).available_sats == 0
    seen = await session.scalar(select(WalletTransaction))
    assert seen is not None
    assert str(seen.status) == "seen"
    assert seen.ledger_group_id is None

    adapter.queue_deposit(address, txid=DEPOSIT_TXID, amount_sats=40_000, confirmations=1)
    assert await poll_deposits(session, adapter) == 1
    assert await poll_deposits(session, adapter) == 0
    assert (await trader_balances(session, trader.id)).available_sats == 40_000


async def test_fake_backend_payout_completes_without_txid(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WALLET_BACKEND", "fake")
    _admin_user, _trader_user, _client, order = await _paid_order(session, 1120)
    completed = await confirm_receipt(session, order_id=order.id, trader_id=order.trader_id)
    assert OrderStatus(str(completed.status)) == OrderStatus.COMPLETED
    assert completed.payout_wallet_tx_id is None
    assert await session.scalar(select(func.count()).select_from(WalletTransaction)) == 0
    assert await balance_of(session, "external_out") == order.client_btc_sats


async def test_payout_adapter_stores_txid(session: AsyncSession) -> None:
    _admin_user, _trader_user, _client, order = await _paid_order(session, 1130, platform_fee_bps=100)
    assert order.client_btc_sats < order.trader_lock_sats
    adapter = FakeWalletAdapter()
    adapter.next_txid = CHAIN_TXID
    completed = await confirm_receipt(
        session,
        order_id=order.id,
        trader_id=order.trader_id,
        wallet=adapter,
    )
    assert OrderStatus(str(completed.status)) == OrderStatus.COMPLETED
    assert completed.payout_wallet_tx_id is not None
    stored = await session.get(WalletTransaction, completed.payout_wallet_tx_id)
    assert stored is not None
    assert stored.txid == CHAIN_TXID
    assert stored.amount_sats == order.client_btc_sats
    assert str(stored.direction) == "out"
    assert str(stored.status) == "broadcast"
    assert stored.ledger_group_id is not None
    assert adapter.sent == [(order.btc_address, order.client_btc_sats, CHAIN_TXID)]
    assert adapter.send_attempts == 1
    again = await confirm_receipt(session, order_id=order.id, trader_id=order.trader_id, wallet=adapter)
    assert again.payout_wallet_tx_id == completed.payout_wallet_tx_id
    assert adapter.send_attempts == 1
    assert await balance_of(session, "external_out") == order.client_btc_sats
    assert (await trader_balances(session, order.trader_id)).locked_sats == 0


async def test_dispute_release_stores_txid(session: AsyncSession) -> None:
    admin, _trader_user, client, order = await _paid_order(session, 1140)
    await open_dispute(session, order_id=order.id, trader_user_id=order.trader_id, reason="спор")
    adapter = FakeWalletAdapter()
    adapter.next_txid = CHAIN_TXID
    released = await resolve_dispute(session, admin.id, order.id, "release", wallet=adapter)
    assert OrderStatus(str(released.status)) == OrderStatus.COMPLETED
    stored = await session.get(WalletTransaction, released.payout_wallet_tx_id)
    assert stored is not None
    assert stored.txid == CHAIN_TXID
    assert stored.amount_sats == order.client_btc_sats
    assert adapter.send_attempts == 1
    assert client.id == order.client_id


async def test_broadcast_failure_keeps_escrow_locked(session: AsyncSession) -> None:
    admin, trader, _client, order = await _paid_order(session, 1150)
    locked = order.trader_lock_sats
    available_before = (await trader_balances(session, trader.id)).available_sats
    adapter = FakeWalletAdapter()
    adapter.fail_send = True
    with pytest.raises(PayoutBroadcastError):
        await confirm_receipt(session, order_id=order.id, trader_id=trader.id, wallet=adapter)
    failed = await session.get(Order, order.id)
    assert failed is not None
    assert OrderStatus(str(failed.status)) == OrderStatus.RELEASING
    assert failed.payout_wallet_tx_id is None
    escrow = await session.scalar(select(EscrowLock).where(EscrowLock.order_id == order.id))
    assert escrow is not None
    assert str(escrow.status) == "locked"
    balances = await trader_balances(session, trader.id)
    assert balances.locked_sats == locked
    assert balances.available_sats == available_before
    assert await balance_of(session, "external_out") == 0
    assert await session.scalar(select(func.count()).select_from(WalletTransaction)) == 0
    release_rows = await session.scalar(
        text("SELECT count(*) FROM ledger_entries WHERE entry_type = 'ESCROW_RELEASE'")
    )
    assert int(release_rows or 0) == 0

    with pytest.raises(IllegalOrderTransition):
        await confirm_receipt(session, order_id=order.id, trader_id=trader.id, wallet=adapter)
    assert adapter.send_attempts == 1
    assert (await trader_balances(session, trader.id)).locked_sats == locked
    assert admin.id is not None


async def test_dispute_release_broadcast_failure_keeps_escrow_and_dispute_open(session: AsyncSession) -> None:
    admin, trader, _client, order = await _paid_order(session, 1160)
    await open_dispute(session, order_id=order.id, trader_user_id=trader.id, reason="не ушло")
    failing = FakeWalletAdapter()
    failing.fail_send = True
    locked = order.trader_lock_sats
    with pytest.raises(PayoutBroadcastError):
        await resolve_dispute(session, admin.id, order.id, "release", wallet=failing)
    assert OrderStatus(str(order.status)) == OrderStatus.RELEASING
    dispute = await session.scalar(select(Dispute).where(Dispute.order_id == order.id))
    assert dispute is not None
    assert str(dispute.status) == "open"
    assert dispute.resolution is None
    escrow = await session.scalar(select(EscrowLock).where(EscrowLock.order_id == order.id))
    assert escrow is not None
    assert str(escrow.status) == "locked"
    assert (await trader_balances(session, trader.id)).locked_sats == locked
    with pytest.raises(IllegalOrderTransition):
        await resolve_dispute(session, admin.id, order.id, "release", wallet=failing)
    assert failing.send_attempts == 1


def test_mainnet_setting_is_rejected(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("WALLET_BACKEND", "electrum")
    monkeypatch.setenv("BITCOIN_NETWORK", "mainnet")
    monkeypatch.setenv("ELECTRUM_RPC_HOST", "127.0.0.1")
    monkeypatch.setenv("ELECTRUM_RPC_PORT", "7777")
    monkeypatch.setenv("ELECTRUM_RPC_USER", "rpcuser")
    monkeypatch.setenv("ELECTRUM_RPC_PASSWORD", "x")
    with pytest.raises(SystemExit) as caught:
        require_wallet_backend()
    assert caught.value.code == 1
    assert "mainnet" in capsys.readouterr().err.lower()
    with pytest.raises(WalletConfigError):
        ElectrumAdapter(ScriptedRpc({}), network="mainnet")


async def test_electrum_adapter_createnewaddress_balance_and_broadcast() -> None:
    trader_id = uuid.uuid4()
    created = ScriptedRpc({"createnewaddress": "tb1qtestdepositaddress"})
    adapter = ElectrumAdapter(created)
    assert await adapter.create_deposit_address(trader_id) == "tb1qtestdepositaddress"
    assert created.calls == [("createnewaddress", [])]

    mainnet = ScriptedRpc({"createnewaddress": "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"})
    with pytest.raises(WalletConfigError):
        await ElectrumAdapter(mainnet).create_deposit_address(trader_id)

    balance = ScriptedRpc(
        {"getbalance": {"confirmed": "0.01000000", "unconfirmed": "0.00000002", "lightning": "3"}}
    )
    assert await ElectrumAdapter(balance).get_wallet_balance() == 1_000_002

    hex_tx = "aa" * 16
    destination = "tb1qclientpayoutaddress"
    amount_sats = 15_000

    def payto(params: object) -> str:
        assert params == [destination, "0.00015000"]
        return hex_tx

    def broadcast(params: object) -> str:
        assert params == [hex_tx]
        return CHAIN_TXID

    sender = ScriptedRpc({"payto": payto, "broadcast": broadcast})
    assert await ElectrumAdapter(sender).send_btc(destination, amount_sats) == CHAIN_TXID
    assert [name for name, _params in sender.calls] == ["payto", "broadcast"]

    legacy = ScriptedRpc(
        {
            "payto": {"hex": hex_tx, "complete": True},
            "broadcast": CHAIN_TXID,
        }
    )
    assert await ElectrumAdapter(legacy).send_btc(destination, amount_sats) == CHAIN_TXID

    incomplete = ScriptedRpc({"payto": {"hex": hex_tx, "complete": False}})
    with pytest.raises(WalletBroadcastError):
        await ElectrumAdapter(incomplete).send_btc(destination, amount_sats)

    fee = ScriptedRpc({"getfeerate": {"sat/kvB": 2500, "policy": "eta:2"}})
    assert await ElectrumAdapter(fee).estimate_fee() == 500

    txid = "ef" * 32
    status = ScriptedRpc({"get_tx_status": {"confirmations": 4}})
    assert await ElectrumAdapter(status).get_confirmations(txid) == 4

    height = 100
    incoming = ScriptedRpc(
        {
            "getaddresshistory": [{"tx_hash": txid, "height": height}],
            "getaddressunspent": [{"tx_hash": txid, "tx_pos": 1, "height": height, "value": 50_000}],
            "getinfo": {"blockchain_height": 103, "network": "testnet"},
        }
    )
    outputs = await ElectrumAdapter(incoming).list_incoming("tb1qtestdepositaddress")
    assert outputs == [IncomingOutput(txid=txid, vout=1, amount_sats=50_000, confirmations=4)]


async def _user(session: AsyncSession, telegram_id: int) -> User:
    return await register_from_start(
        session,
        telegram_id=telegram_id,
        username=f"u{telegram_id}",
        display_name="User",
        start_payload=None,
    )


async def _admin(session: AsyncSession, telegram_id: int) -> User:
    user = await _user(session, telegram_id)
    session.add(AdminUser(user_id=user.id, role="operator"))
    await session.flush()
    return user


async def _trader(session: AsyncSession, admin: User, telegram_id: int, *, balance: int) -> User:
    from app.admin.service import admin_adjust_deposit

    user = await _user(session, telegram_id)
    session.add(
        Trader(
            user_id=user.id,
            status="active",
            is_online=True,
            tier="basic",
            min_order_rub_kop=0,
            max_order_rub_kop=10_000_000_000,
            daily_limit_rub_kop=10_000_000_000,
        )
    )
    await session.flush()
    session.add(
        TraderPaymentMethod(
            trader_id=user.id,
            kind="sbp",
            phone=f"7900{telegram_id:07d}",
            bank_name="Сбер",
            holder_name="Иван Иванов",
            is_active=True,
        )
    )
    await session.flush()
    if balance:
        await admin_adjust_deposit(session, admin.id, user.id, balance)
    return user


async def _paid_order(
    session: AsyncSession,
    telegram_base: int,
    **snapshot_overrides: int,
) -> tuple[User, User, User, Order]:
    admin = await _admin(session, telegram_base)
    trader = await _trader(session, admin, telegram_base + 1, balance=5_000_000)
    client = await _user(session, telegram_base + 2)
    snapshot = build_quote(
        principal_rub_kop=200_000,
        markup_bps=1800,
        platform_fee_bps=snapshot_overrides.get("platform_fee_bps", 0),
        referral_bps=0,
        rate_rub_per_btc=Decimal("6000000"),
        ttl_seconds=120,
        now=datetime.now(timezone.utc),
    )
    order = await open_searching_order(
        session,
        user_id=client.id,
        snapshot=snapshot,
        btc_address=ADDRESS,
    )
    await accept_order(session, order_id=order.id, trader_user_id=trader.id)
    await mark_client_paid(session, order_id=order.id, client_id=client.id)
    return admin, trader, client, order
