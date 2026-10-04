from aiogram import Dispatcher
from aiogram.fsm.storage.base import BaseStorage
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.client import router as client_router
from app.bot.common.db_middleware import DbSessionMiddleware
from app.bot.common.rate_limit import RateLimitMiddleware


def build_dispatcher(
    storage: BaseStorage,
    sessionmaker: async_sessionmaker | None = None,
    redis: Redis | None = None,
) -> Dispatcher:
    dispatcher = Dispatcher(storage=storage)
    if redis is not None:
        dispatcher.update.middleware(RateLimitMiddleware(redis))
    if sessionmaker is not None:
        dispatcher.update.middleware(DbSessionMiddleware(sessionmaker))
    dispatcher.include_router(client_router)
    return dispatcher
