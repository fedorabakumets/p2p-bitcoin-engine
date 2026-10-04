from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.bot.client.texts import MENU_BUY, MENU_ORDERS, MENU_PARTNER, MENU_SUPPORT


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MENU_BUY)],
            [KeyboardButton(text=MENU_ORDERS)],
            [KeyboardButton(text=MENU_PARTNER)],
            [KeyboardButton(text=MENU_SUPPORT)],
        ],
        resize_keyboard=True,
    )


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Продолжить", callback_data="buy:confirm"),
                InlineKeyboardButton(text="Отмена", callback_data="buy:cancel"),
            ]
        ]
    )
