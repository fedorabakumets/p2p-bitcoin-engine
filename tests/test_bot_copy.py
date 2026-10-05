from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.bot.client.texts import format_partner, format_quote, format_status_card
from app.bot.trader.texts import format_balance
from app.formatting import STATUS_LABEL, status_label
from app.models import OrderStatus
from app.notifications.messages import client_completed_text, client_payment_text, trader_offer_text
from app.pricing.formula import build_quote


def _order(**overrides: object) -> SimpleNamespace:
    data: dict[str, object] = {
        "public_no": 12,
        "status": OrderStatus.COMPLETED.value,
        "principal_rub_kop": 200_000,
        "payment_rub_kop": 236_000,
        "client_btc_sats": 33_333,
        "btc_address": "bc1qexample",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_status_labels_are_human() -> None:
    for status in OrderStatus:
        label = status_label(status)
        assert label == STATUS_LABEL[status]
        assert label != status.value
        assert status.value not in label
    assert status_label(OrderStatus.SEARCHING_EXECUTOR) == "ищем трейдера"
    assert status_label(OrderStatus.WAITING_PAYMENT) == "ждём оплату"
    assert status_label(OrderStatus.CLIENT_MARKED_PAID) == "вы отметили оплату"
    assert status_label(OrderStatus.CLIENT_MARKED_PAID, for_trader=True) == "клиент отметил оплату"
    assert status_label(OrderStatus.RELEASING) == "биток отправляется"
    assert status_label(OrderStatus.COMPLETED) == "готово"
    assert status_label(OrderStatus.CANCELLED) == "отменено"
    assert status_label(OrderStatus.DISPUTED) == "спор"


def test_quote_card_includes_btc_and_minutes() -> None:
    snapshot = build_quote(
        principal_rub_kop=200_000,
        markup_bps=1800,
        platform_fee_bps=0,
        referral_bps=0,
        rate_rub_per_btc=Decimal("6000000"),
        ttl_seconds=120,
        now=datetime(2026, 10, 4, tzinfo=timezone.utc),
    )
    text = format_quote(snapshot)
    assert "Получите: 2000 ₽" in text
    assert "Наценка: 18%" in text
    assert "К оплате: 2360 ₽" in text
    assert "Уйдёт: 0.00033333 BTC" in text
    assert "Курс действует ещё 2 мин" in text


def test_payment_card_pays_the_trader_and_escapes() -> None:
    method = SimpleNamespace(phone="+7900<script>", bank_name="А & Б", holder_name="Иван <Петров>")
    text = client_payment_text(_order(payment_rub_kop=236_000), method)
    assert "ждём оплату" in text
    assert "К оплате: 2360 ₽" in text
    assert "Оплата трейдеру по СБП, не платформе." in text
    assert "<code>+7900&lt;script&gt;</code>" in text
    assert "А &amp; Б" in text
    assert "Иван &lt;Петров&gt;" in text
    assert "<script>" not in text


def test_balance_address_is_copyable_only_when_passed() -> None:
    balances = SimpleNamespace(available_sats=1_000_000, locked_sats=33_333, total_sats=1_033_333)
    plain = format_balance(balances)
    assert "Доступно: 0.01000000 BTC" in plain
    assert "Заморожено: 0.00033333 BTC" in plain
    assert "Всего: 0.01033333 BTC" in plain
    assert "Пополнение" not in plain
    shown = format_balance(balances, "tb1q<script>")
    assert "Пополнение: <code>tb1q&lt;script&gt;</code>" in shown


def test_new_order_push_is_scannable() -> None:
    text = trader_offer_text(_order(), 20)
    assert "Получит: 2000 ₽" in text
    assert "К оплате: 2360 ₽" in text
    assert "\nСБП\n" in text
    assert "На карту: 360 ₽" in text
    assert "Осталось 20 секунд" in text


def test_completed_network_matches_bitcoin_network(monkeypatch) -> None:
    order = _order()
    monkeypatch.setenv("BITCOIN_NETWORK", "testnet")
    testnet = client_completed_text(order, chain_txid="aa<bb>")
    assert "готово" in testnet
    assert "Ушло: 0.00033333 BTC" in testnet
    assert "Сеть: testnet" in testnet
    assert "mainnet" not in testnet
    assert "<code>aa&lt;bb&gt;</code>" in testnet
    assert "COMPLETED" not in testnet

    monkeypatch.setenv("BITCOIN_NETWORK", "mainnet")
    mainnet = client_completed_text(order, chain_txid="deadbeef")
    assert "Сеть: mainnet" in mainnet
    assert "testnet" not in mainnet

    ledger_only = client_completed_text(order)
    assert "готово" in ledger_only
    assert "В сеть не отправляли." in ledger_only
    assert "Сеть:" not in ledger_only


def test_partner_marks_ruble_conversions_as_estimates() -> None:
    text = format_partner(
        code="ab<cd",
        bot_username="bot",
        invited=2,
        completed_invitees=1,
        turnover_rub_kop=200_000,
        earned_sats=250,
        available_sats=250,
        snapshot_rub_kop=15_00,
        estimate_rub_kop=16_00,
    )
    assert "Приглашено: 2" in text
    assert "Активные: 1" in text
    assert "Оборот: 2000 ₽" in text
    assert "Заработано: 0.00000250 BTC" in text
    assert "t.me/bot?start=ref_ab&lt;cd" in text
    assert "Оценка по курсу заявок: 15 ₽" in text
    assert "Оценка по текущему курсу: ≈ 16 ₽" in text
    assert "<script>" not in text


def test_status_card_uses_label_not_enum() -> None:
    text = format_status_card(_order(status=OrderStatus.SEARCHING_EXECUTOR.value))
    assert "ищем трейдера" in text
    assert "SEARCHING_EXECUTOR" not in text
    assert "<code>bc1qexample</code>" in text
