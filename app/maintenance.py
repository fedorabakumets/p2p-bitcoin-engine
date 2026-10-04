"""Timer for expiry and notification delivery. Correctness does not depend on Redis."""

import asyncio
import logging

from aiogram import Bot
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.notifications.dispatch import deliver_pending
from app.notifications.service import pending_ids
from app.orders.expiry import expire_due

log = logging.getLogger("app.maintenance")


async def maintenance_loop(sessionmaker: async_sessionmaker, bot: Bot, interval: float = 5.0) -> None:
    while True:
        try:
            async with sessionmaker() as session:
                await expire_due(session)
                ids = await pending_ids(session)
                await session.commit()
            if ids:
                await deliver_pending(bot, sessionmaker, ids)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("maintenance pass failed")
        await asyncio.sleep(interval)
