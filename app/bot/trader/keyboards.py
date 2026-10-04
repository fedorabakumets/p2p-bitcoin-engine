import uuid

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import Order, OrderStatus


def trader_order_keyboard(order: Order) -> InlineKeyboardMarkup | None:
    status = str(order.status)
    if status not in {OrderStatus.WAITING_PAYMENT.value, OrderStatus.CLIENT_MARKED_PAID.value}:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Подтвердить получение", callback_data=f"confirm:{order.id}"),
                InlineKeyboardButton(text="Открыть спор", callback_data=f"dispute:{order.id}"),
            ]
        ]
    )


def dispute_skip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Без вложения", callback_data="dispute:skip")]]
    )


def order_id_from_callback(data: str, prefix: str) -> uuid.UUID:
    return uuid.UUID(data.removeprefix(prefix))
