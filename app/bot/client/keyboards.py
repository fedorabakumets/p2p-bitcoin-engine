import uuid

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.bot.client.texts import MENU_BUY, MENU_ORDERS, MENU_PARTNER, MENU_SUPPORT
from app.bot.trader.texts import (
    MENU_ACTIVE,
    MENU_BALANCE,
    MENU_OFFLINE,
    MENU_ONLINE,
    MENU_SBP,
    MENU_STATS,
    MENU_WITHDRAW,
)
from app.formatting import BTN_CANCEL, BTN_CONTINUE, BTN_PAID, BTN_QUOTE_CANCEL
from app.models import Order, OrderStatus


def main_menu(is_trader: bool = False, *, online: bool = False) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = [
        [KeyboardButton(text=MENU_BUY), KeyboardButton(text=MENU_ORDERS)],
        [KeyboardButton(text=MENU_PARTNER), KeyboardButton(text=MENU_SUPPORT)],
    ]
    if is_trader:
        line = MENU_ONLINE if online else MENU_OFFLINE
        rows.extend(
            [
                [KeyboardButton(text=line)],
                [KeyboardButton(text=MENU_BALANCE), KeyboardButton(text=MENU_ACTIVE)],
                [KeyboardButton(text=MENU_SBP), KeyboardButton(text=MENU_WITHDRAW)],
                [KeyboardButton(text=MENU_STATS)],
            ]
        )
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def searching_keyboard(order_id: uuid.UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=BTN_CANCEL, callback_data=f"cancel:{order_id}")]]
    )


def client_orders_keyboard(orders: list[Order]) -> InlineKeyboardMarkup | None:
    if not orders:
        return None
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for order in orders:
        row.append(InlineKeyboardButton(text=f"№{order.public_no}", callback_data=f"ord:{order.id}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def client_order_keyboard(order: Order) -> InlineKeyboardMarkup | None:
    status = str(order.status)
    if status == OrderStatus.WAITING_PAYMENT.value:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text=BTN_PAID, callback_data=f"pay:{order.id}"),
                    InlineKeyboardButton(text=BTN_CANCEL, callback_data=f"cancel:{order.id}"),
                ]
            ]
        )
    if status in {
        OrderStatus.CREATED.value,
        OrderStatus.QUOTED.value,
        OrderStatus.SEARCHING_EXECUTOR.value,
        OrderStatus.EXECUTOR_ASSIGNED.value,
    }:
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=BTN_CANCEL, callback_data=f"cancel:{order.id}")]]
        )
    return None


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=BTN_CONTINUE, callback_data="buy:confirm"),
                InlineKeyboardButton(text=BTN_QUOTE_CANCEL, callback_data="buy:cancel"),
            ]
        ]
    )
