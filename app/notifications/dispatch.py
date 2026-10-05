"""Send pending notification rows when a bot token exists. Tests do not call this."""

import uuid

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Notification, User, utcnow


async def deliver_pending(bot: Bot, sessionmaker: async_sessionmaker, ids: list[uuid.UUID]) -> None:
    for notification_id in ids:
        async with sessionmaker() as session:
            note = await session.get(Notification, notification_id)
            if note is None or str(note.status) != "pending":
                continue
            user = await session.get(User, note.user_id)
            if user is None:
                note.status = "failed"
                await session.commit()
                continue
            payload = note.payload or {}
            buttons = payload.get("buttons") or []
            markup = None
            if buttons:
                markup = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text=button["text"], callback_data=button["callback_data"])
                            for button in buttons
                        ]
                    ]
                )
            try:
                await bot.send_message(
                    user.telegram_id,
                    str(payload.get("text") or ""),
                    reply_markup=markup,
                    parse_mode=ParseMode.HTML,
                )
            except TelegramAPIError:
                note.status = "failed"
            else:
                note.status = "sent"
                note.sent_at = utcnow()
            await session.commit()
