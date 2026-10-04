from app.formatting import format_btc, format_rub
from app.models import Order, TraderPaymentMethod


def trader_offer_text(order: Order, accept_seconds: int) -> str:
    markup = order.payment_rub_kop - order.principal_rub_kop
    return (
        f"Новая заявка №{order.public_no}\n"
        f"Сумма: {format_rub(order.principal_rub_kop)} ₽\n"
        f"К оплате: {format_rub(order.payment_rub_kop)} ₽\n"
        f"Способ: СБП\n"
        f"На карту: {format_rub(markup)} ₽\n"
        f"У вас {accept_seconds} секунд"
    )


def client_payment_text(order: Order, method: TraderPaymentMethod) -> str:
    return (
        f"Заявка №{order.public_no}\n"
        f"Переведите {format_rub(order.payment_rub_kop)} ₽ по СБП.\n"
        f"Телефон: {method.phone}\n"
        f"Банк: {method.bank_name}\n"
        f"Получатель: {method.holder_name}\n"
        "После перевода нажмите «Я оплатил»."
    )


def trader_paid_text(order: Order) -> str:
    return (
        f"Клиент отметил оплату по заявке №{order.public_no}.\n"
        f"К оплате: {format_rub(order.payment_rub_kop)} ₽.\n"
        "Скриншот сам по себе оплату не подтверждает."
    )


def client_completed_text(order: Order) -> str:
    return (
        f"Заявка №{order.public_no} завершена.\n"
        f"Выплата {format_btc(order.client_btc_sats)} BTC зафиксирована в учёте.\n"
        "Отправка в сеть в этой версии не выполняется."
    )


def client_cancelled_text(order: Order) -> str:
    return f"Заявка №{order.public_no} отменена."


def client_expired_text(order: Order) -> str:
    return f"Заявка №{order.public_no} истекла."
