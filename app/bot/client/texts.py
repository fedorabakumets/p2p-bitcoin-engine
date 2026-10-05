from app.formatting import esc, html_btc, html_card, html_rub, status_label
from app.models import Order
from app.pricing.formula import QuoteSnapshot
from app.wallets.btc_address import classify_btc_address

MENU_BUY = "💰 Купить BTC"
MENU_ORDERS = "📋 Мои заявки"
MENU_PARTNER = "👥 Партнёрам"
MENU_SUPPORT = "💬 Поддержка"
MENU_TEXTS = (MENU_BUY, MENU_ORDERS, MENU_PARTNER, MENU_SUPPORT)

ORDERS_PAGE = 5

SUPPORT_TEXT = html_card(
    "Поддержка",
    "Напишите номер заявки из «Мои заявки» и коротко, что случилось.\n"
    "Деньги уходят трейдеру по СБП, бот эти рубли не получает.\n"
    "Скриншот перевода оплату не подтверждает.",
)

AMOUNT_PROMPT = html_card("Сумма", "Сколько рублей меняем. Например, <code>2000</code>.")
ADDRESS_PROMPT = html_card(
    "Адрес",
    "Введите BTC-адрес. Подходят адреса, которые начинаются с bc1, 1 или 3.",
)
ADDRESS_PROMPT_TESTNET = html_card(
    "Адрес",
    "Введите BTC-адрес testnet. Подходят адреса, которые начинаются с tb1, m, n или 2.",
)
AMOUNT_RETRY = html_card("Сумма", "Нужны рубли. Например, <code>2000</code>.")
ADDRESS_PREFIX_HINT = html_card(
    "Адрес",
    "Этот адрес не подходит. Нужен Bitcoin-адрес, который начинается с bc1, 1 или 3.",
)
ADDRESS_PREFIX_HINT_TESTNET = html_card(
    "Адрес",
    "Этот адрес не подходит. Нужен testnet-адрес, который начинается с tb1, m, n или 2.",
)
ADDRESS_CHECKSUM_HINT = html_card("Адрес", "Адрес неполный или контрольная сумма не совпадает.")
AMOUNT_TOO_SMALL = html_card("Сумма", "Для текущего курса это мало. Введите больше.")
QUOTE_EXPIRED = html_card("Котировка", f"Срок вышел. Нажмите «{MENU_BUY}» и запросите новую.")
CANCELLED_TEXT = html_card("Отмена", "Ничего не создано.")
BLOCKED_TEXT = html_card("Доступ закрыт", "Аккаунт заблокирован.")
EMPTY_ORDERS = html_card("Мои заявки", "Пока пусто.")
CONFIRM_HINT = html_card("Котировка", "Нажмите «Продолжить» или «Отмена».")
FALLBACK_TEXT = html_card("Меню", "Выберите кнопку на клавиатуре.")


def start_text(*, is_trader: bool) -> str:
    lines = [
        "<b>Обмен BTC</b>",
        "",
        "Здравствуйте.",
        "Здесь покупают биткоин за рубли. Деньги уходят трейдеру по СБП, биток приходит на ваш адрес.",
    ]
    if is_trader:
        lines.append("Панель трейдера — на этой же клавиатуре.")
    return "\n".join(lines)


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
    return html_card(
        "Котировка",
        "\n".join(
            [
                f"Получите: {html_rub(snapshot.principal_rub_kop)}",
                f"Наценка: <b>{format_markup_percent(snapshot.markup_bps)}%</b>",
                f"К оплате: {html_rub(snapshot.payment_rub_kop)}",
                f"Уйдёт: {html_btc(snapshot.client_btc_sats)}",
                f"Курс действует ещё {format_quote_ttl(snapshot.ttl_seconds)}",
            ]
        ),
    )


def format_status_card(order: Order) -> str:
    return html_card(
        f"Заявка №{order.public_no}",
        "\n".join(
            [
                status_label(order.status),
                f"Получите: {html_rub(order.principal_rub_kop)}",
                f"К оплате: {html_rub(order.payment_rub_kop)}",
                f"Уйдёт: {html_btc(order.client_btc_sats)}",
                f"Адрес: <code>{esc(order.btc_address)}</code>",
            ]
        ),
    )


def format_orders(orders: list[Order]) -> str:
    if not orders:
        return EMPTY_ORDERS
    blocks = [
        f"№{order.public_no} — {status_label(order.status)}\n"
        f"{html_rub(order.principal_rub_kop)} · {html_btc(order.client_btc_sats)}"
        for order in orders
    ]
    return html_card("Мои заявки", "\n\n".join(blocks))


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
    return html_card(
        "Партнёрам",
        "\n".join(
            [
                f"Приглашено: {invited}",
                f"Активные: {completed_invitees}",
                f"Оборот: {html_rub(turnover_rub_kop)}",
                f"Заработано: {html_btc(earned_sats)}",
                f"Доступно: {html_btc(available_sats)}",
                f"Оценка по курсу заявок: {html_rub(snapshot_rub_kop)}",
                f"Оценка по текущему курсу: ≈ {html_rub(estimate_rub_kop)}",
                "",
                f"Ссылка: <code>{esc(link)}</code>",
            ]
        ),
    )
