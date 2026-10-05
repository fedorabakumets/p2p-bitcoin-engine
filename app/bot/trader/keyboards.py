import uuid

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.formatting import BTN_CONFIRM, BTN_DISPUTE
from app.models import Order, OrderStatus


def trader_orders_keyboard(orders: list[Order]) -> InlineKeyboardMarkup | None:
    if not orders:
        return None
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for order in orders:
        row.append(InlineKeyboardButton(text=f"№{order.public_no}", callback_data=f"tord:{order.id}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def trader_order_keyboard(order: Order) -> InlineKeyboardMarkup | None:
    status = str(order.status)
    if status not in {OrderStatus.WAITING_PAYMENT.value, OrderStatus.CLIENT_MARKED_PAID.value}:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=BTN_CONFIRM, callback_data=f"confirm:{order.id}"),
                InlineKeyboardButton(text=BTN_DISPUTE, callback_data=f"dispute:{order.id}"),
            ]
        ]
    )


def dispute_skip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Без вложения", callback_data="dispute:skip")]]
    )


def order_id_from_callback(data: str, prefix: str) -> uuid.UUID:
    return uuid.UUID(data.removeprefix(prefix))
