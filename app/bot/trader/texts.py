from app.bot.client.texts import STATUS_RU
from app.formatting import format_btc, format_rub
from app.ledger.service import TraderBalances
from app.models import Order, OrderStatus, Trader, TraderPaymentMethod
from app.traders.service import TraderStats

MENU_BALANCE = "Баланс"
MENU_ONLINE = "Принимать заявки"
MENU_ACTIVE = "Активные заявки"
MENU_STATS = "Статистика"
MENU_WITHDRAW = "Вывод"
MENU_TIER = "Мой tier"
MENU_SBP = "Реквизиты СБП"
TRADER_MENU = (MENU_BALANCE, MENU_ONLINE, MENU_ACTIVE, MENU_STATS, MENU_WITHDRAW, MENU_TIER, MENU_SBP)


def format_balance(balances: TraderBalances) -> str:
    return (
        "Баланс\n"
        f"Доступно: {format_btc(balances.available_sats)} BTC\n"
        f"Заморожено: {format_btc(balances.locked_sats)} BTC\n"
        f"Всего: {format_btc(balances.total_sats)} BTC"
    )


def format_stats(stats: TraderStats) -> str:
    return (
        "Статистика\n"
        f"Завершено заявок: {stats.completed_count}\n"
        f"Оборот: {format_rub(stats.turnover_rub_kop)} ₽\n"
        f"Сегодня: {format_rub(stats.used_today_rub_kop)} / {format_rub(stats.daily_limit_rub_kop)} ₽"
    )


def format_tier(trader: Trader) -> str:
    return (
        f"Мой tier: {trader.tier}\n"
        f"Минимум: {format_rub(trader.min_order_rub_kop)} ₽\n"
        f"Максимум: {format_rub(trader.max_order_rub_kop)} ₽\n"
        f"Дневной лимит: {format_rub(trader.daily_limit_rub_kop)} ₽"
    )


def format_sbp(method: TraderPaymentMethod | None) -> str:
    if method is None:
        return "Реквизиты СБП не заданы. Введите телефон, затем банк и имя получателя. Банк бот не определяет."
    return (
        "Реквизиты СБП\n"
        f"Телефон: {method.phone}\n"
        f"Банк: {method.bank_name}\n"
        f"Получатель: {method.holder_name}\n"
        "Чтобы заменить, введите телефон. Банк бот не определяет."
    )


def format_trader_order(order: Order) -> str:
    status = STATUS_RU[OrderStatus(str(order.status))]
    markup = order.payment_rub_kop - order.principal_rub_kop
    return (
        f"№{order.public_no} — {status}\n"
        f"К оплате: {format_rub(order.payment_rub_kop)} ₽\n"
        f"На карту: {format_rub(markup)} ₽"
    )


def format_online(online: bool) -> str:
    if online:
        return "Приём заявок включён."
    return "Приём заявок выключен."
