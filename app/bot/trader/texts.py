from app.formatting import esc, html_btc, html_card, html_rub, status_label
from app.ledger.service import TraderBalances
from app.models import Order, TraderPaymentMethod
from app.traders.service import TraderStats

MENU_BALANCE = "💼 Баланс"
MENU_ONLINE = "🟢 На линии"
MENU_OFFLINE = "🔴 Не на линии"
MENU_ACTIVE = "📥 Заявки"
MENU_STATS = "📊 Статистика"
MENU_WITHDRAW = "💸 Вывод"
MENU_SBP = "🏦 Реквизиты"
TRADER_MENU = (
    MENU_BALANCE,
    MENU_ONLINE,
    MENU_OFFLINE,
    MENU_ACTIVE,
    MENU_STATS,
    MENU_SBP,
    MENU_WITHDRAW,
)
TRADER_ONLY = html_card("Трейдер", "Этот раздел только для трейдера.")
TRADER_ORDERS_PAGE = 10
EMPTY_TRADER_ORDERS = html_card("Заявки", "Активных нет.")


def format_balance(balances: TraderBalances, deposit_address: str | None = None) -> str:
    lines = [
        f"Доступно: {html_btc(balances.available_sats)}",
        f"Заморожено: {html_btc(balances.locked_sats)}",
        f"Всего: {html_btc(balances.total_sats)}",
    ]
    if deposit_address:
        lines.append(f"Пополнение: <code>{esc(deposit_address)}</code>")
    return html_card("Баланс", "\n".join(lines))


def format_stats(stats: TraderStats) -> str:
    return html_card(
        "Статистика",
        "\n".join(
            [
                f"Завершено: {stats.completed_count}",
                f"Оборот: {html_rub(stats.turnover_rub_kop)}",
                f"Сегодня: {html_rub(stats.used_today_rub_kop)} / {html_rub(stats.daily_limit_rub_kop)}",
            ]
        ),
    )


def format_sbp(method: TraderPaymentMethod | None) -> str:
    if method is None:
        return html_card(
            "Реквизиты",
            "Не заданы. Введите телефон, банк и имя.\nБанк бот не определяет.",
        )
    return html_card(
        "Реквизиты",
        "\n".join(
            [
                f"Телефон: <code>{esc(method.phone)}</code>",
                f"Банк: {esc(method.bank_name)}",
                f"Получатель: {esc(method.holder_name)}",
                "",
                "Чтобы заменить, введите телефон. Банк бот не определяет.",
            ]
        ),
    )


def format_trader_orders(orders: list[Order]) -> str:
    blocks = []
    for order in orders:
        markup = order.payment_rub_kop - order.principal_rub_kop
        blocks.append(
            f"№{order.public_no} — {status_label(order.status, for_trader=True)}\n"
            f"К оплате: {html_rub(order.payment_rub_kop)} · На карту: {html_rub(markup)}"
        )
    return html_card("Заявки", "\n\n".join(blocks))


def format_trader_order(order: Order) -> str:
    markup = order.payment_rub_kop - order.principal_rub_kop
    return html_card(
        f"Заявка №{order.public_no}",
        "\n".join(
            [
                status_label(order.status, for_trader=True),
                f"К оплате: {html_rub(order.payment_rub_kop)}",
                f"На карту: {html_rub(markup)}",
            ]
        ),
    )


def format_online(online: bool) -> str:
    if online:
        return html_card("Линия", "Вы на линии. Новые заявки приходят сюда.")
    return html_card("Линия", "Вы не на линии. Заявки не приходят.")


def withdraw_prompt(available_sats: int) -> str:
    return html_card(
        "Вывод",
        "\n".join(
            [
                "Сумма в BTC. Например, <code>0.01</code>.",
                f"Доступно: {html_btc(available_sats)}",
                "Это заявка оператору. Автовыплаты нет.",
            ]
        ),
    )


SBP_BANK_PROMPT = html_card("Банк", "Введите название. Бот его не определяет.")
SBP_HOLDER_PROMPT = html_card("Получатель", "Введите имя.")
WITHDRAW_BAD_AMOUNT = html_card("Вывод", "Нужна сумма в BTC. Например, <code>0.01</code>.")
WITHDRAW_SENT = html_card("Вывод", "Заявка ушла оператору. Автовыплаты нет.")
DISPUTE_OPEN = html_card(
    "Спор",
    "Эскроу заморожен.\n"
    "Пришлите текст или скриншот, либо нажмите «Без вложения».\n"
    "Скриншот оплату не подтверждает.",
)
DISPUTE_SAVED = html_card("Спор", "Вложение сохранено. Оплата не подтверждена.")
DISPUTE_NOTE = html_card("Спор", "Комментарий сохранён. Оплата не подтверждена.")
