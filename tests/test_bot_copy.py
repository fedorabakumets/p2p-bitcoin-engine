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
    assert text.startswith("<b>Котировка</b>\n\n")
    assert "Получите: <code>2000 ₽</code>" in text
    assert "Наценка: <b>18%</b>" in text
    assert "К оплате: <code>2360 ₽</code>" in text
    assert "Уйдёт: <code>0.00033333 BTC</code>" in text
    assert "Курс действует ещё 2 мин" in text


def test_payment_card_pays_the_trader_and_escapes() -> None:
    method = SimpleNamespace(phone="+7900<script>", bank_name="А & Б", holder_name="Иван <Петров>")
    text = client_payment_text(_order(payment_rub_kop=236_000), method)
    assert text.startswith("<b>Оплата</b>\n\n")
    assert "ждём оплату" in text
    assert "К оплате: <code>2360 ₽</code>" in text
    assert "Оплата трейдеру по СБП, не платформе." in text
    assert "<code>+7900&lt;script&gt;</code>" in text
    assert "А &amp; Б" in text
    assert "Иван &lt;Петров&gt;" in text
    assert "<script>" not in text


def test_balance_address_is_copyable_only_when_passed() -> None:
    balances = SimpleNamespace(available_sats=1_000_000, locked_sats=33_333, total_sats=1_033_333)
    plain = format_balance(balances)
    assert plain.startswith("<b>Баланс</b>\n\n")
    assert "Доступно: <code>0.01000000 BTC</code>" in plain
    assert "Заморожено: <code>0.00033333 BTC</code>" in plain
    assert "Всего: <code>0.01033333 BTC</code>" in plain
    assert "Пополнение" not in plain
    shown = format_balance(balances, "tb1q<script>")
    assert "Пополнение: <code>tb1q&lt;script&gt;</code>" in shown


def test_new_order_push_is_scannable() -> None:
    text = trader_offer_text(_order(), 20)
    assert text.startswith("<b>Новая заявка №12</b>\n\n")
    assert "Получит: <code>2000 ₽</code>" in text
    assert "К оплате: <code>2360 ₽</code>" in text
    assert "\nСБП\n" in text
    assert "На карту: <code>360 ₽</code>" in text
    assert "Осталось 20 секунд" in text


def test_completed_network_matches_bitcoin_network(monkeypatch) -> None:
    order = _order()
    monkeypatch.setenv("BITCOIN_NETWORK", "testnet")
    testnet = client_completed_text(order, chain_txid="aa<bb>")
    assert "готово" in testnet
    assert testnet.startswith("<b>Заявка №12</b>\n\n")
    assert "Ушло: <code>0.00033333 BTC</code>" in testnet
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
    assert "Оборот: <code>2000 ₽</code>" in text
    assert "Заработано: <code>0.00000250 BTC</code>" in text
    assert "t.me/bot?start=ref_ab&lt;cd" in text
    assert "Оценка по курсу заявок: <code>15 ₽</code>" in text
    assert "Оценка по текущему курсу: ≈ <code>16 ₽</code>" in text
    assert "<script>" not in text


def test_status_card_uses_label_not_enum() -> None:
    text = format_status_card(_order(status=OrderStatus.SEARCHING_EXECUTOR.value))
    assert text.startswith("<b>Заявка №12</b>\n\n")
    assert "ищем трейдера" in text
    assert "SEARCHING_EXECUTOR" not in text
    assert "<code>bc1qexample</code>" in text


def test_start_greeting_and_support() -> None:
    from app.bot.client.texts import SUPPORT_TEXT, start_text
    from app.bot.profile import BOT_DESCRIPTION, BOT_NAME, BOT_SHORT_DESCRIPTION

    greeting = start_text(is_trader=False)
    assert greeting == (
        "<b>Обмен BTC</b>\n"
        "\n"
        "Здравствуйте.\n"
        "Здесь покупают биткоин за рубли. Деньги уходят трейдеру по СБП, биток приходит на ваш адрес."
    )
    trader = start_text(is_trader=True)
    assert trader.startswith(greeting + "\n")
    assert "Панель трейдера — на этой же клавиатуре." in trader
    sentences = [part for part in SUPPORT_TEXT.split(".") if part.strip()]
    assert 3 <= len(sentences) <= 4
    assert "позже" not in SUPPORT_TEXT.lower()
    assert SUPPORT_TEXT.startswith("<b>Поддержка</b>")
    assert BOT_NAME == "Обмен BTC"
    assert BOT_SHORT_DESCRIPTION == "Биткоин за рубли. Оплата трейдеру по СБП."
    description_lines = [line for line in BOT_DESCRIPTION.splitlines() if line.strip()]
    assert 3 <= len(description_lines) <= 4
    assert "СБП" in BOT_DESCRIPTION
    assert "не принимает" in BOT_DESCRIPTION


def test_reply_keyboard_and_inline_labels() -> None:
    from app.bot.client.keyboards import confirm_keyboard, main_menu
    from app.bot.client.texts import MENU_BUY, MENU_ORDERS, MENU_PARTNER, MENU_SUPPORT
    from app.bot.trader.texts import (
        MENU_ACTIVE,
        MENU_BALANCE,
        MENU_OFFLINE,
        MENU_ONLINE,
        MENU_SBP,
        MENU_STATS,
        MENU_WITHDRAW,
    )
    from app.formatting import BTN_ACCEPT, BTN_CANCEL, BTN_CONFIRM, BTN_CONTINUE, BTN_DISPUTE, BTN_PAID
    import app.bot.trader.texts as trader_texts

    client = main_menu(False)
    assert client.resize_keyboard is True
    assert client.is_persistent is True
    assert [[button.text for button in row] for row in client.keyboard] == [
        [MENU_BUY, MENU_ORDERS],
        [MENU_PARTNER, MENU_SUPPORT],
    ]
    assert (MENU_BUY, MENU_ORDERS, MENU_PARTNER, MENU_SUPPORT) == (
        "💰 Купить BTC",
        "📋 Мои заявки",
        "👥 Партнёрам",
        "💬 Поддержка",
    )
    online = main_menu(True, online=True)
    offline = main_menu(True, online=False)
    assert online.is_persistent is True
    assert [[button.text for button in row] for row in online.keyboard] == [
        [MENU_BUY, MENU_ORDERS],
        [MENU_PARTNER, MENU_SUPPORT],
        [MENU_ONLINE],
        [MENU_BALANCE, MENU_ACTIVE],
        [MENU_SBP, MENU_WITHDRAW],
        [MENU_STATS],
    ]
    assert offline.keyboard[2][0].text == MENU_OFFLINE
    assert (MENU_ONLINE, MENU_OFFLINE, MENU_BALANCE, MENU_ACTIVE, MENU_SBP, MENU_WITHDRAW, MENU_STATS) == (
        "🟢 На линии",
        "🔴 Не на линии",
        "💼 Баланс",
        "📥 Заявки",
        "🏦 Реквизиты",
        "💸 Вывод",
        "📊 Статистика",
    )
    assert not hasattr(trader_texts, "MENU_TIER")
    assert not hasattr(trader_texts, "MENU_ONLINE_LEGACY")
    assert not hasattr(trader_texts, "MENU_ACTIVE_LEGACY")
    assert not hasattr(trader_texts, "MENU_SBP_LEGACY")
    quote_row = confirm_keyboard().inline_keyboard
    assert len(quote_row) == 1
    assert [button.text for button in quote_row[0]] == [BTN_CONTINUE, BTN_CANCEL]
    assert (BTN_CONTINUE, BTN_CANCEL, BTN_PAID, BTN_ACCEPT, BTN_CONFIRM, BTN_DISPUTE) == (
        "Продолжить",
        "Отмена",
        "Я оплатил",
        "Принять",
        "Подтвердить",
        "Открыть спор",
    )
