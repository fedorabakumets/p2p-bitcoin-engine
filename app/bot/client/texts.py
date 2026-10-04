from app.formatting import format_btc, format_rub
from app.models import Order, OrderStatus
from app.pricing.formula import QuoteSnapshot
from app.wallets.btc_address import classify_btc_mainnet_address

MENU_BUY = "Купить BTC"
MENU_ORDERS = "Мои заявки"
MENU_PARTNER = "Партнёрская программа"
MENU_SUPPORT = "Поддержка"
MENU_TEXTS = (MENU_BUY, MENU_ORDERS, MENU_PARTNER, MENU_SUPPORT)

STATUS_RU = {
    OrderStatus.CREATED: "создана",
    OrderStatus.QUOTED: "котировка сохранена",
    OrderStatus.SEARCHING_EXECUTOR: "ищем трейдера",
    OrderStatus.EXECUTOR_ASSIGNED: "трейдер назначен",
    OrderStatus.WAITING_PAYMENT: "ожидаем оплату",
    OrderStatus.CLIENT_MARKED_PAID: "оплата отмечена",
    OrderStatus.PAYMENT_CONFIRMED: "оплата подтверждена",
    OrderStatus.RELEASING: "отправляем BTC",
    OrderStatus.COMPLETED: "завершена",
    OrderStatus.CANCELLED: "отменена",
    OrderStatus.EXPIRED: "истекла",
    OrderStatus.DISPUTED: "спор",
    OrderStatus.FAILED: "ошибка",
}

SUPPORT_TEXT = (
    "Поддержка\n\n"
    "Напишите оператору номер заявки из раздела «Мои заявки». "
    "Скриншот перевода сам по себе оплату не подтверждает."
)

AMOUNT_PROMPT = "Введите сумму в рублях, на которую хотите получить BTC. Например: 2000"
ADDRESS_PROMPT = "Введите BTC-адрес. Подходят адреса, которые начинаются с bc1, 1 или 3."
AMOUNT_RETRY = "Введите сумму в рублях, например 2000."
ADDRESS_PREFIX_HINT = "Этот адрес не подходит. Нужен Bitcoin-адрес, который начинается с bc1, 1 или 3."
ADDRESS_CHECKSUM_HINT = "Адрес неполный или контрольная сумма не совпадает."
AMOUNT_TOO_SMALL = "Сумма слишком маленькая для текущего курса. Введите больше."
QUOTE_EXPIRED = "Котировка истекла. Нажмите «Купить BTC» и запросите новую."
CANCELLED_TEXT = "Отменено."
MAIN_MENU_TEXT = "Главное меню"
BLOCKED_TEXT = "Аккаунт заблокирован."
EMPTY_ORDERS = "Заявок пока нет."


def address_retry_text(address: str) -> str:
    if classify_btc_mainnet_address(address) == "checksum":
        return ADDRESS_CHECKSUM_HINT
    return ADDRESS_PREFIX_HINT


def format_markup_percent(bps: int) -> str:
    whole, frac = divmod(bps, 100)
    if frac == 0:
        return str(whole)
    return f"{whole}.{frac:02d}".rstrip("0")


def format_quote_ttl(seconds: int) -> str:
    if seconds % 60 == 0:
        return f"{seconds // 60} мин"
    return f"{seconds} сек"


def format_quote(snapshot: QuoteSnapshot) -> str:
    return (
        f"Получите BTC: ≈ {format_rub(snapshot.principal_rub_kop)} ₽\n"
        f"Наценка: {format_markup_percent(snapshot.markup_bps)}%\n"
        f"К оплате: {format_rub(snapshot.payment_rub_kop)} ₽\n"
        f"Курс действует: {format_quote_ttl(snapshot.ttl_seconds)}"
    )


def format_searching(public_no: int) -> str:
    return f"Заявка №{public_no} создана. Ищем трейдера."


def format_orders(orders: list[Order]) -> str:
    if not orders:
        return EMPTY_ORDERS
    blocks = ["Мои заявки"]
    for order in orders:
        status = STATUS_RU[OrderStatus(str(order.status))]
        blocks.append(
            f"№{order.public_no} — {status}\n"
            f"Получите: {format_rub(order.principal_rub_kop)} ₽\n"
            f"К оплате: {format_rub(order.payment_rub_kop)} ₽\n"
            f"Адрес: {order.btc_address}"
        )
    return "\n\n".join(blocks)


def format_partner(
    *,
    code: str,
    bot_username: str | None,
    invited: int,
    completed_invitees: int,
    turnover_rub_kop: int,
    earned_sats: int,
    available_sats: int,
    snapshot_rub_kop: int,
    estimate_rub_kop: int,
) -> str:
    if bot_username:
        link = f"t.me/{bot_username}?start=ref_{code}"
    else:
        link = code
    return (
        "Партнёрская программа\n\n"
        f"Ваша ссылка: {link}\n"
        f"Приглашено: {invited}\n"
        f"С завершённой заявкой: {completed_invitees}\n"
        f"Оборот приглашённых: {format_rub(turnover_rub_kop)} ₽\n"
        f"Заработано: {format_btc(earned_sats)} BTC\n"
        f"Доступно: {format_btc(available_sats)} BTC\n"
        f"По курсу заявок: {format_rub(snapshot_rub_kop)} ₽\n"
        f"Оценка по текущему курсу: ≈ {format_rub(estimate_rub_kop)} ₽"
    )
