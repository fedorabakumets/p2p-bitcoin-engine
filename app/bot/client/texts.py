from app.formatting import esc, format_btc, format_rub, status_label
from app.models import Order, OrderStatus
from app.pricing.formula import QuoteSnapshot
from app.wallets.btc_address import classify_btc_address

MENU_BUY = "Купить BTC"
MENU_ORDERS = "Мои заявки"
MENU_PARTNER = "Партнёрская программа"
MENU_SUPPORT = "Поддержка"
MENU_TEXTS = (MENU_BUY, MENU_ORDERS, MENU_PARTNER, MENU_SUPPORT)

ORDERS_PAGE = 5

SUPPORT_TEXT = (
    "<b>Поддержка</b>\n\n"
    "Напишите номер заявки из «Мои заявки». Скриншот перевод не подтверждает."
)

AMOUNT_PROMPT = "Сумма в рублях. Например, 2000."
ADDRESS_PROMPT = "Введите BTC-адрес. Подходят адреса, которые начинаются с bc1, 1 или 3."
ADDRESS_PROMPT_TESTNET = (
    "Введите BTC-адрес testnet. Подходят адреса, которые начинаются с tb1, m, n или 2."
)
AMOUNT_RETRY = "Нужна сумма в рублях. Например, 2000."
ADDRESS_PREFIX_HINT = "Этот адрес не подходит. Нужен Bitcoin-адрес, который начинается с bc1, 1 или 3."
ADDRESS_PREFIX_HINT_TESTNET = (
    "Этот адрес не подходит. Нужен testnet-адрес, который начинается с tb1, m, n или 2."
)
ADDRESS_CHECKSUM_HINT = "Адрес неполный или контрольная сумма не совпадает."
AMOUNT_TOO_SMALL = "Сумма слишком маленькая для текущего курса. Введите больше."
QUOTE_EXPIRED = "Котировка истекла. Нажмите «Купить BTC» и запросите новую."
CANCELLED_TEXT = "Отменено."
MAIN_MENU_TEXT = "<b>Покупка BTC</b>"
BLOCKED_TEXT = "Аккаунт заблокирован."
EMPTY_ORDERS = "Заявок пока нет."
CONFIRM_HINT = "Нажмите «Продолжить» или «Отмена»."


def address_prompt(network: str = "mainnet") -> str:
    if network.strip().lower() == "testnet":
        return ADDRESS_PROMPT_TESTNET
    return ADDRESS_PROMPT


def address_retry_text(address: str, network: str = "mainnet") -> str:
    if classify_btc_address(address, network) == "checksum":
        return ADDRESS_CHECKSUM_HINT
    if network.strip().lower() == "testnet":
        return ADDRESS_PREFIX_HINT_TESTNET
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
        "<b>Котировка</b>\n"
        f"Получите: {format_rub(snapshot.principal_rub_kop)} ₽\n"
        f"Наценка: {format_markup_percent(snapshot.markup_bps)}%\n"
        f"К оплате: {format_rub(snapshot.payment_rub_kop)} ₽\n"
        f"Уйдёт: {format_btc(snapshot.client_btc_sats)} BTC\n"
        f"Курс действует ещё {format_quote_ttl(snapshot.ttl_seconds)}"
    )


def format_status_card(order: Order) -> str:
    return (
        f"<b>Заявка №{order.public_no}</b>\n"
        f"{status_label(order.status)}\n\n"
        f"Получите: {format_rub(order.principal_rub_kop)} ₽\n"
        f"К оплате: {format_rub(order.payment_rub_kop)} ₽\n"
        f"Уйдёт: {format_btc(order.client_btc_sats)} BTC\n"
        f"Адрес: <code>{esc(order.btc_address)}</code>"
    )


def format_orders(orders: list[Order]) -> str:
    if not orders:
        return EMPTY_ORDERS
    blocks = ["<b>Мои заявки</b>"]
    for order in orders:
        blocks.append(
            f"№{order.public_no} — {status_label(order.status)}\n"
            f"{format_rub(order.principal_rub_kop)} ₽ · {format_btc(order.client_btc_sats)} BTC"
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
        "<b>Партнёрская программа</b>\n\n"
        f"Приглашено: {invited}\n"
        f"Активные: {completed_invitees}\n"
        f"Оборот: {format_rub(turnover_rub_kop)} ₽\n"
        f"Заработано: {format_btc(earned_sats)} BTC\n"
        f"Доступно: {format_btc(available_sats)} BTC\n"
        f"Оценка по курсу заявок: {format_rub(snapshot_rub_kop)} ₽\n"
        f"Оценка по текущему курсу: ≈ {format_rub(estimate_rub_kop)} ₽\n\n"
        f"Ссылка: <code>{esc(link)}</code>"
    )
