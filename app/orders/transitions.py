"""Legal order status changes.

After CLIENT_MARKED_PAID the client cannot cancel the order. Trader claim,
escrow, and payout are later stages: this module only names the edges.
"""

from app.models import OrderStatus

ALLOWED: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.CREATED: frozenset(
        {OrderStatus.QUOTED, OrderStatus.CANCELLED, OrderStatus.EXPIRED, OrderStatus.FAILED}
    ),
    OrderStatus.QUOTED: frozenset(
        {
            OrderStatus.SEARCHING_EXECUTOR,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
            OrderStatus.FAILED,
        }
    ),
    OrderStatus.SEARCHING_EXECUTOR: frozenset(
        {
            OrderStatus.EXECUTOR_ASSIGNED,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
            OrderStatus.FAILED,
        }
    ),
    OrderStatus.EXECUTOR_ASSIGNED: frozenset(
        {
            OrderStatus.WAITING_PAYMENT,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
            OrderStatus.FAILED,
        }
    ),
    OrderStatus.WAITING_PAYMENT: frozenset(
        {
            OrderStatus.CLIENT_MARKED_PAID,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
            OrderStatus.DISPUTED,
            OrderStatus.FAILED,
        }
    ),
    OrderStatus.CLIENT_MARKED_PAID: frozenset(
        {OrderStatus.PAYMENT_CONFIRMED, OrderStatus.DISPUTED, OrderStatus.FAILED}
    ),
    OrderStatus.PAYMENT_CONFIRMED: frozenset(
        {OrderStatus.RELEASING, OrderStatus.DISPUTED, OrderStatus.FAILED}
    ),
    OrderStatus.RELEASING: frozenset({OrderStatus.COMPLETED, OrderStatus.DISPUTED, OrderStatus.FAILED}),
    OrderStatus.DISPUTED: frozenset(
        {OrderStatus.RELEASING, OrderStatus.CANCELLED, OrderStatus.FAILED}
    ),
    OrderStatus.COMPLETED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.EXPIRED: frozenset(),
    OrderStatus.FAILED: frozenset(),
}


def can_transition(current: OrderStatus, target: OrderStatus) -> bool:
    return target in ALLOWED[current]
