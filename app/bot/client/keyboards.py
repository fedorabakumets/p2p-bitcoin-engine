import uuid

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.bot.client.texts import MENU_BUY, MENU_ORDERS, MENU_PARTNER, MENU_SUPPORT
from app.bot.trader.texts import (
    MENU_ACTIVE,
    MENU_BALANCE,
    MENU_ONLINE,
    MENU_SBP,
    MENU_STATS,
    MENU_TIER,
    MENU_WITHDRAW,
)
from app.models import Order, OrderStatus


def main_menu(is_trader: bool = False) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = [
        [KeyboardButton(text=MENU_BUY)],
        [KeyboardButton(text=MENU_ORDERS)],
        [KeyboardButton(text=MENU_PARTNER)],
        [KeyboardButton(text=MENU_SUPPORT)],
    ]
    if is_trader:
        rows.extend(
            [
                [KeyboardButton(text=MENU_BALANCE), KeyboardButton(text=MENU_ONLINE)],
                [KeyboardButton(text=MENU_ACTIVE), KeyboardButton(text=MENU_STATS)],
                [KeyboardButton(text=MENU_WITHDRAW), KeyboardButton(text=MENU_TIER)],
                [KeyboardButton(text=MENU_SBP)],
            ]
        )
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def searching_keyboard(order_id: uuid.UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Отменить", callback_data=f"cancel:{order_id}")]]
    )


def client_order_keyboard(order: Order) -> InlineKeyboardMarkup | None:
    status = str(order.status)
    if status == OrderStatus.WAITING_PAYMENT.value:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Я оплатил", callback_data=f"pay:{order.id}"),
                    InlineKeyboardButton(text="Отменить", callback_data=f"cancel:{order.id}"),
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
            inline_keyboard=[[InlineKeyboardButton(text="Отменить", callback_data=f"cancel:{order.id}")]]
        )
    return None


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Продолжить", callback_data="buy:confirm"),
                InlineKeyboardButton(text="Отмена", callback_data="buy:cancel"),
            ]
        ]
    )
