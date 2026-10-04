import asyncio
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.service import NotAdmin, admin_adjust_deposit, apply_credit_command
from app.bot.client.texts import format_partner
from app.disputes.service import EvidenceInput, open_dispute, resolve_dispute
from app.ledger.service import balance_of, trader_available_code, trader_balances, trader_locked_code
from app.models import (
    AdminUser,
    DisputeEvidence,
    EscrowLock,
    Notification,
    Order,
    OrderStatus,
    ReferralReward,
    Trader,
    TraderPaymentMethod,
)
from app.orders.expiry import expire_due, expire_search
from app.orders.payment import CancelNotAllowed, cancel_by_client, confirm_receipt, mark_client_paid
from app.orders.service import open_searching_order
from app.pricing.formula import build_quote
from app.pricing.rates import EnvRateSource
from app.pricing.service import PricingService
from app.referrals.service import partner_summary
from app.routing.service import OrderAlreadyTaken, accept_order, eligible_traders
from app.traders.service import list_active_orders, request_withdrawal
from app.users.service import register_from_start

ROOT = Path(__file__).resolve().parents[1]
ADDRESS = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"


def _snapshot(**overrides):
    params = dict(
        principal_rub_kop=200_000,
        markup_bps=1800,
        platform_fee_bps=0,
        referral_bps=0,
        rate_rub_per_btc=Decimal("6000000"),
        ttl_seconds=120,
        now=datetime.now(timezone.utc),
    )
    params.update(overrides)
    return build_quote(**params)


async def _user(session: AsyncSession, telegram_id: int, **kwargs):
    return await register_from_start(
        session,
        telegram_id=telegram_id,
        username=kwargs.get("username", f"u{telegram_id}"),
        display_name="User",
        start_payload=kwargs.get("start_payload"),
    )


async def _admin(session: AsyncSession, telegram_id: int = 900):
    user = await _user(session, telegram_id, username=f"admin{telegram_id}")
    session.add(AdminUser(user_id=user.id, role="operator"))
    await session.flush()
    return user


async def _trader(
    session: AsyncSession,
    admin,
    telegram_id: int,
    *,
    balance: int = 1_000_000,
    online: bool = True,
    status: str = "active",
    sbp: bool = True,
    daily: int = 10_000_000_000,
    max_kop: int = 10_000_000_000,
):
    user = await _user(session, telegram_id, username=f"tr{telegram_id}")
    session.add(
        Trader(
            user_id=user.id,
            status=status,
            is_online=online,
            tier="basic",
            min_order_rub_kop=0,
            max_order_rub_kop=max_kop,
            daily_limit_rub_kop=daily,
        )
    )
    await session.flush()
    if sbp:
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


async def _order(session: AsyncSession, client, **snapshot_overrides):
    return await open_searching_order(
        session,
        user_id=client.id,
        snapshot=_snapshot(**snapshot_overrides),
        btc_address=ADDRESS,
    )


async def _sums(session: AsyncSession) -> list[int]:
    rows = (
        await session.execute(text("SELECT COALESCE(SUM(amount_sats), 0) FROM ledger_entries GROUP BY group_id"))
    ).scalars()
    return [int(value) for value in rows]


async def _entry_types(session: AsyncSession) -> set[str]:
    rows = await session.scalars(text("SELECT DISTINCT entry_type::text FROM ledger_entries"))
    return set(rows)


async def test_two_traders_race_and_only_one_locks(session: AsyncSession) -> None:
    admin = await _admin(session, 910)
    first = await _trader(session, admin, 911)
    second = await _trader(session, admin, 912)
    first_id = first.id
    second_id = second.id
    client = await _user(session, 913)
    order = await _order(session, client)
    order_id = order.id
    lock = order.trader_lock_sats
    principal = order.principal_rub_kop
    await session.commit()

    from app.db import get_sessionmaker

    maker = get_sessionmaker()

    async def attempt(trader_id):
        async with maker() as db:
            accepted = await accept_order(db, order_id=order_id, trader_user_id=trader_id)
            await db.commit()
            return accepted.trader_id

    results = await asyncio.gather(attempt(first_id), attempt(second_id), return_exceptions=True)
    winners = [item for item in results if isinstance(item, type(first_id))]
    taken = [item for item in results if isinstance(item, OrderAlreadyTaken)]
    other = [item for item in results if item not in winners and item not in taken]
    assert other == [], other
    assert len(winners) == 1
    assert len(taken) == 1
    assert str(taken[0]) == "Заявка уже принята другим трейдером"

    session.expire_all()
    stored = await session.get(Order, order_id)
    assert stored is not None
    assert stored.trader_id == winners[0]
    assert OrderStatus(str(stored.status)) == OrderStatus.WAITING_PAYMENT
    escrow_count = await session.scalar(
        select(func.count()).select_from(EscrowLock).where(EscrowLock.order_id == order_id)
    )
    assert int(escrow_count or 0) == 1
    lock_entries = await session.scalar(
        text(
            """
            SELECT count(*) FROM ledger_entries
            WHERE order_id = :order_id AND entry_type = 'ESCROW_LOCK'
            """
        ),
        {"order_id": order_id},
    )
    assert int(lock_entries or 0) == 2
    winner_balance = await trader_balances(session, winners[0])
    assert winner_balance.locked_sats == lock
    assert winner_balance.available_sats == 1_000_000 - lock
    loser_id = second_id if winners[0] == first_id else first_id
    loser_balance = await trader_balances(session, loser_id)
    assert loser_balance.available_sats == 1_000_000
    assert loser_balance.locked_sats == 0
    volume_rows = (
        await session.execute(
            text("SELECT trader_id, used_rub_kop FROM trader_daily_volume WHERE used_rub_kop > 0")
        )
    ).all()
    assert len(volume_rows) == 1
    assert volume_rows[0][0] == winners[0]
    assert int(volume_rows[0][1]) == principal
    active = await list_active_orders(session, winners[0])
    assert [item.id for item in active] == [order_id]
    assert all(total == 0 for total in await _sums(session))


async def test_ineligible_traders_are_not_offered(session: AsyncSession) -> None:
    admin = await _admin(session, 920)
    good = await _trader(session, admin, 921)
    await _trader(session, admin, 922, balance=1)
    await _trader(session, admin, 923, online=False)
    await _trader(session, admin, 924, daily=1)
    await _trader(session, admin, 925, status="suspended")
    client = await _user(session, 926)
    order = await _order(session, client)
    offered = await eligible_traders(session, order)
    assert [trader_id for trader_id, _method in offered] == [good.id]
    notes = list(
        await session.scalars(select(Notification).where(Notification.kind == "trader_offer"))
    )
    assert len(notes) == 1
    assert notes[0].user_id == good.id
    text_value = notes[0].payload["text"]
    assert "Новая заявка" in text_value
    assert "Сумма: 2000 ₽" in text_value
    assert "К оплате: 2360 ₽" in text_value
    assert "Способ: СБП" in text_value
    assert "На карту: 360 ₽" in text_value
    assert "20 секунд" in text_value
    assert notes[0].payload["buttons"][0]["text"] == "ПРИНЯТЬ"
    assert "118" not in text_value


async def test_double_accept_does_not_lock_twice(session: AsyncSession) -> None:
    admin = await _admin(session, 930)
    trader = await _trader(session, admin, 931)
    client = await _user(session, 932)
    order = await _order(session, client)
    await accept_order(session, order_id=order.id, trader_user_id=trader.id)
    with pytest.raises(OrderAlreadyTaken):
        await accept_order(session, order_id=order.id, trader_user_id=trader.id)
    balances = await trader_balances(session, trader.id)
    assert balances.locked_sats == order.trader_lock_sats
    assert balances.available_sats == 1_000_000 - order.trader_lock_sats
    locks = await session.scalar(select(func.count()).select_from(EscrowLock).where(EscrowLock.order_id == order.id))
    assert int(locks or 0) == 1


async def test_cancel_before_paid_unlocks_and_after_paid_is_rejected(session: AsyncSession) -> None:
    admin = await _admin(session, 940)
    trader = await _trader(session, admin, 941)
    client = await _user(session, 942)
    unlocked = await _order(session, client)
    await accept_order(session, order_id=unlocked.id, trader_user_id=trader.id)
    await cancel_by_client(session, order_id=unlocked.id, client_id=client.id)
    assert OrderStatus(str(unlocked.status)) == OrderStatus.CANCELLED
    restored = await trader_balances(session, trader.id)
    assert restored.available_sats == 1_000_000
    assert restored.locked_sats == 0
    escrow = await session.scalar(select(EscrowLock).where(EscrowLock.order_id == unlocked.id))
    assert escrow is not None
    assert str(escrow.status) == "unlocked"

    held = await _order(session, client)
    await accept_order(session, order_id=held.id, trader_user_id=trader.id)
    await mark_client_paid(session, order_id=held.id, client_id=client.id)
    await mark_client_paid(session, order_id=held.id, client_id=client.id)
    with pytest.raises(CancelNotAllowed):
        await cancel_by_client(session, order_id=held.id, client_id=client.id)
    assert OrderStatus(str(held.status)) == OrderStatus.CLIENT_MARKED_PAID
    still_locked = await trader_balances(session, trader.id)
    assert still_locked.locked_sats == held.trader_lock_sats
    assert await balance_of(session, "external_out") == 0


async def test_confirm_splits_snapshot_and_referral_is_unique(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    admin = await _admin(session, 950)
    trader = await _trader(session, admin, 951, balance=5_000_000)
    referrer = await _user(session, 952, username="partner")
    client = await _user(session, 953, start_payload=f"ref_{referrer.referral_code}")
    assert client.referred_by_user_id == referrer.id
    order = await _order(session, client, platform_fee_bps=100, referral_bps=2500)
    assert order.referral_sats > 0
    assert order.platform_fee_sats > order.referral_sats
    assert order.trader_lock_sats == order.client_btc_sats + order.platform_fee_sats
    original = (
        order.client_btc_sats,
        order.platform_fee_sats,
        order.referral_sats,
        order.trader_lock_sats,
        order.payment_rub_kop,
        order.principal_rub_kop,
    )
    await accept_order(session, order_id=order.id, trader_user_id=trader.id)
    await mark_client_paid(session, order_id=order.id, client_id=client.id)
    monkeypatch.setenv("BTC_RUB_RATE", "1000000")
    await session.execute(text("UPDATE settings SET value = '0' WHERE key = 'default_markup_bps'"))
    completed = await confirm_receipt(session, order_id=order.id, trader_id=trader.id)
    again = await confirm_receipt(session, order_id=order.id, trader_id=trader.id)
    assert again.id == completed.id
    assert OrderStatus(str(completed.status)) == OrderStatus.COMPLETED
    assert completed.payout_wallet_tx_id is None
    assert (
        completed.client_btc_sats,
        completed.platform_fee_sats,
        completed.referral_sats,
        completed.trader_lock_sats,
        completed.payment_rub_kop,
        completed.principal_rub_kop,
    ) == original

    external = await balance_of(session, "external_out")
    platform = await balance_of(session, "platform_revenue")
    referral = await balance_of(session, f"referral_payable:{referrer.id}")
    assert external == original[0]
    assert platform == original[1] - original[2]
    assert referral == original[2]
    assert external + platform + referral == original[3]
    rewards = list(await session.scalars(select(ReferralReward).where(ReferralReward.order_id == order.id)))
    assert len(rewards) == 1
    assert rewards[0].amount_sats == original[2]
    assert rewards[0].referrer_user_id == referrer.id
    types = await _entry_types(session)
    assert "REFERRAL_REWARD" in types
    assert "TRADER_REWARD" not in types
    assert all(total == 0 for total in await _sums(session))
    trader_after = await trader_balances(session, trader.id)
    assert trader_after.locked_sats == 0
    assert trader_after.available_sats == 5_000_000 - original[3]

    summary = await partner_summary(session, referrer.id)
    assert summary.invited == 1
    assert summary.completed_invitees == 1
    assert summary.turnover_rub_kop == original[5]
    assert summary.earned_sats == original[2]
    assert summary.available_sats == original[2]
    text_value = format_partner(
        code=referrer.referral_code,
        bot_username="exchangerbot",
        invited=summary.invited,
        completed_invitees=summary.completed_invitees,
        turnover_rub_kop=summary.turnover_rub_kop,
        earned_sats=summary.earned_sats,
        available_sats=summary.available_sats,
        snapshot_rub_kop=summary.snapshot_rub_kop,
        estimate_rub_kop=summary.estimate_rub_kop,
    )
    assert f"t.me/exchangerbot?start=ref_{referrer.referral_code}" in text_value
    assert "Оценка по текущему курсу" in text_value
    later = await partner_summary(session, referrer.id)
    assert later.snapshot_rub_kop == summary.snapshot_rub_kop
    fresh = await PricingService(EnvRateSource()).quote(session, 200_000)
    assert fresh.client_btc_sats != original[0]


async def test_dispute_stays_locked_until_admin_unlock_or_release(session: AsyncSession) -> None:
    admin = await _admin(session, 960)
    stranger = await _user(session, 961)
    trader = await _trader(session, admin, 962, balance=5_000_000)
    client = await _user(session, 963)
    unlock_order = await _order(session, client, platform_fee_bps=100, referral_bps=2500)
    await accept_order(session, order_id=unlock_order.id, trader_user_id=trader.id)
    await mark_client_paid(session, order_id=unlock_order.id, client_id=client.id)
    dispute = await open_dispute(
        session,
        order_id=unlock_order.id,
        trader_user_id=trader.id,
        reason="деньги не пришли",
        evidence=[EvidenceInput(telegram_file_id="AgAC_test_screenshot", kind="screenshot")],
    )
    assert OrderStatus(str(unlock_order.status)) == OrderStatus.DISPUTED
    evidence = await session.scalar(select(DisputeEvidence).where(DisputeEvidence.dispute_id == dispute.id))
    assert evidence is not None
    assert evidence.telegram_file_id == "AgAC_test_screenshot"
    assert str(evidence.kind) == "screenshot"
    assert await balance_of(session, "external_out") == 0
    locked = await trader_balances(session, trader.id)
    assert locked.locked_sats == unlock_order.trader_lock_sats
    with pytest.raises(NotAdmin):
        await resolve_dispute(session, stranger.id, unlock_order.id, "unlock")
    await resolve_dispute(session, admin.id, unlock_order.id, "unlock", note="рубли вернут вне платформы")
    await resolve_dispute(session, admin.id, unlock_order.id, "unlock")
    assert OrderStatus(str(unlock_order.status)) == OrderStatus.CANCELLED
    returned = await trader_balances(session, trader.id)
    assert returned.available_sats == 5_000_000
    assert returned.locked_sats == 0
    escrow = await session.scalar(select(EscrowLock).where(EscrowLock.order_id == unlock_order.id))
    assert escrow is not None
    assert str(escrow.status) == "unlocked"
    audits = await session.scalar(
        text("SELECT count(*) FROM audit_log WHERE action = 'dispute_unlock' AND entity_id = :id"),
        {"id": unlock_order.id},
    )
    assert int(audits or 0) == 1

    release_order = await _order(session, client, platform_fee_bps=100, referral_bps=2500)
    await accept_order(session, order_id=release_order.id, trader_user_id=trader.id)
    await mark_client_paid(session, order_id=release_order.id, client_id=client.id)
    await open_dispute(session, order_id=release_order.id, trader_user_id=trader.id, reason="спор")
    assert await trader_balances(session, trader.id) == type(returned)(
        returned.available_sats - release_order.trader_lock_sats,
        release_order.trader_lock_sats,
        returned.available_sats,
    )
    await resolve_dispute(session, admin.id, release_order.id, "release")
    await resolve_dispute(session, admin.id, release_order.id, "release")
    assert OrderStatus(str(release_order.status)) == OrderStatus.COMPLETED
    assert release_order.payout_wallet_tx_id is None
    assert await balance_of(session, "external_out") == release_order.client_btc_sats
    assert await trader_balances(session, trader.id) == type(returned)(
        5_000_000 - release_order.trader_lock_sats,
        0,
        5_000_000 - release_order.trader_lock_sats,
    )
    assert all(total == 0 for total in await _sums(session))


async def test_admin_credit_and_cli_refusal(session: AsyncSession) -> None:
    admin = await _admin(session, 970)
    admin_id = admin.id
    trader = await _trader(session, admin, 971, balance=0)
    trader_id = trader.id
    outsider = await _user(session, 972)
    with pytest.raises(NotAdmin):
        await admin_adjust_deposit(session, outsider.id, trader.id, 100_000)
    assert await balance_of(session, trader_available_code(trader.id)) == 0
    first = await admin_adjust_deposit(
        session,
        admin.id,
        trader.id,
        1_000_000,
        idempotency_key="credit-once",
    )
    second = await admin_adjust_deposit(
        session,
        admin.id,
        trader.id,
        1_000_000,
        idempotency_key="credit-once",
    )
    assert first.available_sats == 1_000_000
    assert second.available_sats == 1_000_000
    assert await balance_of(session, "external_in") == -1_000_000
    audits = await session.scalar(
        text("SELECT count(*) FROM audit_log WHERE action = 'admin_adjust_deposit'")
    )
    assert int(audits or 0) == 1
    assert all(total == 0 for total in await _sums(session))
    message = await apply_credit_command(session, admin_telegram_id=970, args=f"{971} 0.01")
    assert "1000000" in message
    assert await trader_balances(session, trader.id) == type(first)(2_000_000, 0, 2_000_000)
    with pytest.raises(NotAdmin):
        await apply_credit_command(session, admin_telegram_id=972, args="1000")

    await request_withdrawal(session, trader.id, 50_000)
    assert (await trader_balances(session, trader.id)).available_sats == 2_000_000

    await session.commit()
    denied = subprocess.run(
        [sys.executable, "-m", "app.admin_credit", "--telegram-id", "972", "--sats", "1000"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        check=False,
    )
    assert denied.returncode == 1
    assert "admin_users" in denied.stderr
    assert "Traceback" not in denied.stderr
    allowed = subprocess.run(
        [sys.executable, "-m", "app.admin_credit", "--telegram-id", "970", "--sats", "250000"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        check=False,
    )
    assert allowed.returncode == 0, allowed.stderr
    assert "available_sats=" in allowed.stdout
    session.expire_all()
    assert await balance_of(session, trader_available_code(admin_id)) == 250_000
    assert await balance_of(session, trader_available_code(trader_id)) == 2_000_000


async def test_quote_snapshot_survives_a_later_rate(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    admin = await _admin(session, 980)
    trader = await _trader(session, admin, 981)
    client = await _user(session, 982)
    order = await _order(session, client)
    original = (order.client_btc_sats, order.payment_rub_kop, order.markup_bps, order.trader_lock_sats)
    monkeypatch.setenv("BTC_RUB_RATE", "1000000")
    await session.execute(text("UPDATE settings SET value = '0' WHERE key = 'default_markup_bps'"))
    fresh = await PricingService(EnvRateSource()).quote(session, 200_000)
    assert fresh.client_btc_sats != original[0]
    assert fresh.markup_bps == 0
    reloaded = await session.get(Order, order.id)
    assert reloaded is not None
    assert (reloaded.client_btc_sats, reloaded.payment_rub_kop, reloaded.markup_bps, reloaded.trader_lock_sats) == original
    await accept_order(session, order_id=order.id, trader_user_id=trader.id)
    await mark_client_paid(session, order_id=order.id, client_id=client.id)
    await confirm_receipt(session, order_id=order.id, trader_id=trader.id)
    done = await session.get(Order, order.id, populate_existing=True)
    assert done is not None
    assert (done.client_btc_sats, done.payment_rub_kop, done.markup_bps, done.trader_lock_sats) == original
    assert await balance_of(session, "external_out") == original[0]


async def test_search_and_pay_windows_expire_without_touching_marked_paid(session: AsyncSession) -> None:
    admin = await _admin(session, 990)
    trader = await _trader(session, admin, 991)
    client = await _user(session, 992)
    searching = await _order(session, client)
    searching.accept_expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    await session.flush()
    expired = await expire_search(session)
    assert [item.id for item in expired] == [searching.id]
    assert OrderStatus(str(searching.status)) == OrderStatus.EXPIRED

    waiting = await _order(session, client)
    await accept_order(session, order_id=waiting.id, trader_user_id=trader.id)
    waiting.pay_expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    marked = await _order(session, client)
    await accept_order(session, order_id=marked.id, trader_user_id=trader.id)
    await mark_client_paid(session, order_id=marked.id, client_id=client.id)
    marked.pay_expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    await session.flush()
    await expire_due(session)
    assert OrderStatus(str(waiting.status)) == OrderStatus.EXPIRED
    assert OrderStatus(str(marked.status)) == OrderStatus.CLIENT_MARKED_PAID
    balances = await trader_balances(session, trader.id)
    assert balances.locked_sats == marked.trader_lock_sats
    assert balances.available_sats == 1_000_000 - marked.trader_lock_sats
