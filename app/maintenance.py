"""Timer for expiry and notification delivery. Correctness does not depend on Redis."""

import asyncio
import logging

from aiogram import Bot
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import wallet_backend
from app.notifications.dispatch import deliver_pending
from app.notifications.service import pending_ids
from app.orders.expiry import expire_due
from app.wallets.deposits import poll_deposits
from app.wallets.factory import get_wallet_adapter

log = logging.getLogger("app.maintenance")


async def maintenance_loop(sessionmaker: async_sessionmaker, bot: Bot, interval: float = 5.0) -> None:
    while True:
        try:
            async with sessionmaker() as session:
                await expire_due(session)
                ids = await pending_ids(session)
                await session.commit()
            if wallet_backend() == "electrum":
                try:
                    async with sessionmaker() as session:
                        await poll_deposits(session, get_wallet_adapter())
                        await session.commit()
                except Exception:
                    log.exception("deposit poll failed")
            if ids:
                await deliver_pending(bot, sessionmaker, ids)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("maintenance pass failed")
        await asyncio.sleep(interval)
