"""Shared money formatting and the one Russian status map.

The ledger stores integer satoshis. Telegram screens use these labels
instead of order-status enums.
"""

import html
from decimal import Decimal, ROUND_HALF_UP

from app.models import OrderStatus


def esc(value: object) -> str:
    return html.escape(str(value), quote=False)


def format_rub(kopecks: int) -> str:
    sign = "-" if kopecks < 0 else ""
    rubles, frac = divmod(abs(kopecks), 100)
    if frac:
        return f"{sign}{rubles},{frac:02d}"
    return f"{sign}{rubles}"


def format_btc(sats: int) -> str:
    sign = "-" if sats < 0 else ""
    whole, frac = divmod(abs(sats), 100_000_000)
    return f"{sign}{whole}.{frac:08d}"


def html_rub(kopecks: int) -> str:
    return f"<code>{format_rub(kopecks)} ₽</code>"


def html_btc(sats: int) -> str:
    return f"<code>{format_btc(sats)} BTC</code>"


def html_card(title: str, body: str = "") -> str:
    head = f"<b>{esc(title)}</b>"
    text = body.strip("\n")
    if not text:
        return head
    return f"{head}\n\n{text}"


def rub_kop_for_sats(sats: int, rate_rub_per_btc: Decimal) -> int:
    """Convert satoshis to integer kopecks at a rub-per-BTC rate. Half-up."""

    value = Decimal(sats) * Decimal(rate_rub_per_btc) / Decimal(1_000_000)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


STATUS_LABEL: dict[OrderStatus, str] = {
    OrderStatus.CREATED: "создана",
    OrderStatus.QUOTED: "котировка",
    OrderStatus.SEARCHING_EXECUTOR: "ищем трейдера",
    OrderStatus.EXECUTOR_ASSIGNED: "трейдер найден",
    OrderStatus.WAITING_PAYMENT: "ждём оплату",
    OrderStatus.CLIENT_MARKED_PAID: "вы отметили оплату",
    OrderStatus.PAYMENT_CONFIRMED: "оплата подтверждена",
    OrderStatus.RELEASING: "биток отправляется",
    OrderStatus.COMPLETED: "готово",
    OrderStatus.CANCELLED: "отменено",
    OrderStatus.EXPIRED: "истекло",
    OrderStatus.DISPUTED: "спор",
    OrderStatus.FAILED: "ошибка",
}

BTN_ACCEPT = "Принять"
BTN_PAID = "Я оплатил"
BTN_CANCEL = "Отмена"
BTN_CONTINUE = "Продолжить"
BTN_QUOTE_CANCEL = "Отмена"
BTN_CONFIRM = "Подтвердить"
BTN_DISPUTE = "Открыть спор"


def status_label(status: OrderStatus | str, *, for_trader: bool = False) -> str:
    key = status.value if isinstance(status, OrderStatus) else str(status)
    if for_trader and key == OrderStatus.CLIENT_MARKED_PAID.value:
        return "клиент отметил оплату"
    try:
        return STATUS_LABEL[OrderStatus(key)]
    except ValueError:
        return "заявка"
