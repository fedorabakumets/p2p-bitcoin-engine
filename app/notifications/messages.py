from app.config import bitcoin_network
from app.formatting import esc, format_btc, format_rub, status_label
from app.models import Order, OrderStatus, TraderPaymentMethod


def _network_name() -> str:
    network = bitcoin_network().strip().lower()
    if network == "testnet":
        return "testnet"
    if network == "mainnet":
        return "mainnet"
    return network or "testnet"


def trader_offer_text(order: Order, accept_seconds: int) -> str:
    markup = order.payment_rub_kop - order.principal_rub_kop
    return (
        f"<b>Новая заявка №{order.public_no}</b>\n"
        f"Получит: {format_rub(order.principal_rub_kop)} ₽\n"
        f"К оплате: {format_rub(order.payment_rub_kop)} ₽\n"
        "СБП\n"
        f"На карту: {format_rub(markup)} ₽\n"
        f"Осталось {accept_seconds} секунд"
    )


def client_payment_text(order: Order, method: TraderPaymentMethod) -> str:
    return (
        f"<b>Заявка №{order.public_no}</b>\n"
        f"{status_label(OrderStatus.WAITING_PAYMENT)}\n\n"
        f"К оплате: {format_rub(order.payment_rub_kop)} ₽\n"
        "Оплата трейдеру по СБП, не платформе.\n"
        f"Телефон: <code>{esc(method.phone)}</code>\n"
        f"Банк: {esc(method.bank_name)}\n"
        f"Получатель: {esc(method.holder_name)}"
    )


def trader_paid_text(order: Order) -> str:
    return (
        f"<b>Заявка №{order.public_no}</b>\n"
        f"{status_label(OrderStatus.CLIENT_MARKED_PAID, for_trader=True)}\n\n"
        f"К оплате: {format_rub(order.payment_rub_kop)} ₽\n"
        "Скриншот оплату не подтверждает."
    )


def client_completed_text(order: Order, *, chain_txid: str | None = None) -> str:
    lines = [
        f"<b>Заявка №{order.public_no}</b>",
        status_label(OrderStatus.COMPLETED),
        "",
        f"Ушло: {format_btc(order.client_btc_sats)} BTC",
        f"Адрес: <code>{esc(order.btc_address)}</code>",
    ]
    if chain_txid:
        lines.append(f"Сеть: {esc(_network_name())}")
        lines.append(f"txid: <code>{esc(chain_txid)}</code>")
    else:
        lines.append("В сеть не отправляли.")
    return "\n".join(lines)


def client_cancelled_text(order: Order) -> str:
    return f"<b>Заявка №{order.public_no}</b>\n{status_label(OrderStatus.CANCELLED)}"


def client_expired_text(order: Order) -> str:
    return f"<b>Заявка №{order.public_no}</b>\n{status_label(OrderStatus.EXPIRED)}"
