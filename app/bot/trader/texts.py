from app.formatting import esc, format_btc, format_rub, status_label
from app.ledger.service import TraderBalances
from app.models import Order, Trader, TraderPaymentMethod
from app.traders.service import TraderStats

MENU_BALANCE = "Баланс"
MENU_ONLINE = "На линии"
MENU_OFFLINE = "Не на линии"
MENU_ONLINE_LEGACY = "Принимать заявки"
MENU_ACTIVE = "Заявки"
MENU_ACTIVE_LEGACY = "Активные заявки"
MENU_STATS = "Статистика"
MENU_WITHDRAW = "Вывод"
MENU_TIER = "Мой tier"
MENU_SBP = "Реквизиты"
MENU_SBP_LEGACY = "Реквизиты СБП"
TRADER_MENU = (
    MENU_BALANCE,
    MENU_ONLINE,
    MENU_OFFLINE,
    MENU_ACTIVE,
    MENU_STATS,
    MENU_SBP,
    MENU_WITHDRAW,
)
TRADER_ORDERS_PAGE = 10


def format_balance(balances: TraderBalances, deposit_address: str | None = None) -> str:
    lines = [
        "<b>Баланс</b>",
        f"Доступно: {format_btc(balances.available_sats)} BTC",
        f"Заморожено: {format_btc(balances.locked_sats)} BTC",
        f"Всего: {format_btc(balances.total_sats)} BTC",
    ]
    if deposit_address:
        lines.append(f"Пополнение: <code>{esc(deposit_address)}</code>")
    return "\n".join(lines)


def format_stats(stats: TraderStats) -> str:
    return (
        "<b>Статистика</b>\n"
        f"Завершено: {stats.completed_count}\n"
        f"Оборот: {format_rub(stats.turnover_rub_kop)} ₽\n"
        f"Сегодня: {format_rub(stats.used_today_rub_kop)} / {format_rub(stats.daily_limit_rub_kop)} ₽"
    )


def format_tier(trader: Trader) -> str:
    return (
        f"<b>Лимиты</b>\n"
        f"Уровень: {esc(trader.tier)}\n"
        f"Минимум: {format_rub(trader.min_order_rub_kop)} ₽\n"
        f"Максимум: {format_rub(trader.max_order_rub_kop)} ₽\n"
        f"Дневной лимит: {format_rub(trader.daily_limit_rub_kop)} ₽"
    )


def format_sbp(method: TraderPaymentMethod | None) -> str:
    if method is None:
        return "<b>Реквизиты</b>\n\nНе заданы. Введите телефон, банк и имя. Банк бот не определяет."
    return (
        "<b>Реквизиты</b>\n"
        f"Телефон: <code>{esc(method.phone)}</code>\n"
        f"Банк: {esc(method.bank_name)}\n"
        f"Получатель: {esc(method.holder_name)}\n\n"
        "Чтобы заменить, введите телефон. Банк бот не определяет."
    )


def format_trader_orders(orders: list[Order]) -> str:
    lines = ["<b>Заявки</b>"]
    for order in orders:
        markup = order.payment_rub_kop - order.principal_rub_kop
        lines.append(
            f"№{order.public_no} — {status_label(order.status, for_trader=True)}\n"
            f"К оплате: {format_rub(order.payment_rub_kop)} ₽ · На карту: {format_rub(markup)} ₽"
        )
    return "\n\n".join(lines)


def format_trader_order(order: Order) -> str:
    markup = order.payment_rub_kop - order.principal_rub_kop
    return (
        f"<b>Заявка №{order.public_no}</b>\n"
        f"{status_label(order.status, for_trader=True)}\n\n"
        f"К оплате: {format_rub(order.payment_rub_kop)} ₽\n"
        f"На карту: {format_rub(markup)} ₽"
    )


def format_online(online: bool) -> str:
    if online:
        return "На линии."
    return "Не на линии."
