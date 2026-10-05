from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message


def clear_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[])


def inline_with_back(
    keyboard: InlineKeyboardMarkup | None,
    callback_data: str,
    label: str = "К списку",
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if keyboard is not None:
        rows.extend(list(row) for row in keyboard.inline_keyboard)
    rows.append([InlineKeyboardButton(text=label, callback_data=callback_data)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def edit_or_send(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Edit the message under the tap. Send a new one only if Telegram will not edit."""

    message = callback.message
    if isinstance(message, Message):
        try:
            await message.edit_text(text, reply_markup=reply_markup)
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
    if callback.from_user is not None:
        await callback.bot.send_message(callback.from_user.id, text, reply_markup=reply_markup)
