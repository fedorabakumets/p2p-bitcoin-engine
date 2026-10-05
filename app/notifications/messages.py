from app.config import bitcoin_network
from app.formatting import esc, html_btc, html_card, html_rub, status_label
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
    return html_card(
        f"Новая заявка №{order.public_no}",
        "\n".join(
            [
                f"Получит: {html_rub(order.principal_rub_kop)}",
                f"К оплате: {html_rub(order.payment_rub_kop)}",
                "СБП",
                f"На карту: {html_rub(markup)}",
                f"Осталось {accept_seconds} секунд",
            ]
        ),
    )


def client_payment_text(order: Order, method: TraderPaymentMethod) -> str:
    return html_card(
        "Оплата",
        "\n".join(
            [
                f"Заявка №{order.public_no}",
                status_label(OrderStatus.WAITING_PAYMENT),
                f"К оплате: {html_rub(order.payment_rub_kop)}",
                "Оплата трейдеру по СБП, не платформе.",
                f"Телефон: <code>{esc(method.phone)}</code>",
                f"Банк: {esc(method.bank_name)}",
                f"Получатель: {esc(method.holder_name)}",
            ]
        ),
    )


def trader_paid_text(order: Order) -> str:
    return html_card(
        f"Заявка №{order.public_no}",
        "\n".join(
            [
                status_label(OrderStatus.CLIENT_MARKED_PAID, for_trader=True),
                f"К оплате: {html_rub(order.payment_rub_kop)}",
                "Скриншот оплату не подтверждает.",
            ]
        ),
    )


def client_completed_text(order: Order, *, chain_txid: str | None = None) -> str:
    lines = [
        status_label(OrderStatus.COMPLETED),
        f"Ушло: {html_btc(order.client_btc_sats)}",
        f"Адрес: <code>{esc(order.btc_address)}</code>",
    ]
    if chain_txid:
        lines.append(f"Сеть: {esc(_network_name())}")
        lines.append(f"txid: <code>{esc(chain_txid)}</code>")
    else:
        lines.append("В сеть не отправляли.")
    return html_card(f"Заявка №{order.public_no}", "\n".join(lines))


def client_cancelled_text(order: Order) -> str:
    return html_card(f"Заявка №{order.public_no}", status_label(OrderStatus.CANCELLED))


def client_expired_text(order: Order) -> str:
    return html_card(f"Заявка №{order.public_no}", status_label(OrderStatus.EXPIRED))
