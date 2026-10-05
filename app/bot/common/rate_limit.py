import logging

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, Update
from redis.asyncio import Redis

log = logging.getLogger(__name__)

WINDOW_SECONDS = 10
MAX_EVENTS = 30


class RateLimitMiddleware(BaseMiddleware):
    """Redis counter. It never claims or locks an order."""

    def __init__(self, redis: Redis):
        self._redis = redis

    async def __call__(self, handler, event, data):  # type: ignore[no-untyped-def]
        user_id = _user_id(event)
        if user_id is None:
            return await handler(event, data)
        try:
            allowed = await _allow(self._redis, user_id)
        except Exception:
            log.warning("rate limit skipped because Redis failed", exc_info=True)
            return await handler(event, data)
        if allowed:
            return await handler(event, data)
        await _tell_user(event)
        return None


async def _allow(redis: Redis, user_id: int) -> bool:
    key = f"rl:tg:{user_id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, WINDOW_SECONDS)
    return int(count) <= MAX_EVENTS


def _user_id(event: object) -> int | None:
    if isinstance(event, Update):
        incoming = event.message or event.callback_query
        if incoming is not None and incoming.from_user is not None:
            return incoming.from_user.id
        return None
    if isinstance(event, (Message, CallbackQuery)) and event.from_user is not None:
        return event.from_user.id
    return None


async def _tell_user(event: object) -> None:
    text = "<b>Пауза</b>\n\nСлишком много сообщений. Подождите немного."
    alert = "Слишком много сообщений. Подождите немного."
    if isinstance(event, Update):
        if event.message is not None:
            await event.message.answer(text)
        elif event.callback_query is not None:
            await event.callback_query.answer(alert, show_alert=True)
        return
    if isinstance(event, Message):
        await event.answer(text)
    elif isinstance(event, CallbackQuery):
        await event.answer(alert, show_alert=True)
