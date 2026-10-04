"""Run migrations separately, then this module. A missing token exits without a traceback."""

import asyncio
import logging
import sys

from app.config import btc_rub_rate, health_host, health_port, redis_url

MISSING_TOKEN = (
    "BOT_TOKEN is not set. "
    "The Telegram token comes from BotFather and is not stored in the repo. "
    "Export BOT_TOKEN and start the bot again."
)


def require_bot_token() -> str:
    import os

    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        print(MISSING_TOKEN, file=sys.stderr)
        raise SystemExit(1)
    return token


def dry_run() -> int:
    """Load the bot and print one quote. No token, no Telegram, no database."""

    from aiogram.fsm.storage.memory import MemoryStorage

    from app.bot.client.texts import format_quote
    from app.bot.factory import build_dispatcher
    from app.pricing.formula import build_quote
    from app.wallets.btc_address import is_btc_mainnet_address

    rate = btc_rub_rate()
    snapshot = build_quote(
        principal_rub_kop=200_000,
        markup_bps=1800,
        platform_fee_bps=0,
        referral_bps=0,
        rate_rub_per_btc=rate,
        ttl_seconds=120,
    )
    if not is_btc_mainnet_address("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"):
        print("dry-run failed: sample bc1 address was rejected", file=sys.stderr)
        return 1
    if is_btc_mainnet_address("not-an-address"):
        print("dry-run failed: junk address was accepted", file=sys.stderr)
        return 1
    build_dispatcher(MemoryStorage())
    print(format_quote(snapshot))
    print("dry-run ok")
    return 0


async def run_bot(token: str) -> None:
    import uvicorn
    from aiogram import Bot
    from aiogram.exceptions import TelegramUnauthorizedError
    from aiogram.fsm.storage.redis import RedisStorage
    from aiogram.utils.token import TokenValidationError
    from redis.asyncio import Redis
    from sqlalchemy import text

    from app.bot.factory import build_dispatcher
    from app.bot.runtime import set_bot_username
    from app.db import get_sessionmaker
    from app.health import create_health_app

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log = logging.getLogger("app")

    bot: Bot | None = None
    redis: Redis | None = None
    storage: RedisStorage | None = None
    health: uvicorn.Server | None = None
    health_task: asyncio.Task[None] | None = None
    maintenance_task: asyncio.Task[None] | None = None
    try:
        try:
            bot = Bot(token=token)
        except TokenValidationError:
            print("BOT_TOKEN is set but is not a valid Telegram bot token.", file=sys.stderr)
            raise SystemExit(1) from None

        sessionmaker = get_sessionmaker()
        try:
            async with sessionmaker() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            print(
                "DATABASE_URL is not reachable. PostgreSQL must be up before the bot starts.",
                file=sys.stderr,
            )
            raise SystemExit(1) from None

        redis = Redis.from_url(redis_url(), decode_responses=True)
        try:
            await redis.ping()
        except Exception:
            print(
                "REDIS_URL is not reachable. Redis is used for timers and rate limits.",
                file=sys.stderr,
            )
            raise SystemExit(1) from None

        try:
            me = await bot.get_me()
        except TelegramUnauthorizedError:
            print("BOT_TOKEN was rejected by Telegram.", file=sys.stderr)
            raise SystemExit(1) from None
        set_bot_username(me.username)
        storage = RedisStorage(redis=redis)
        redis = None
        dispatcher = build_dispatcher(storage, sessionmaker, storage.redis)
        health = uvicorn.Server(
            uvicorn.Config(
                create_health_app(),
                host=health_host(),
                port=health_port(),
                log_level="info",
                access_log=False,
            )
        )
        # _serve does not install signal handlers, so polling keeps SIGINT/SIGTERM.
        health_task = asyncio.create_task(health._serve())
        from app.maintenance import maintenance_loop

        maintenance_task = asyncio.create_task(maintenance_loop(sessionmaker, bot))
        log.info("bot started as @%s", me.username)
        await dispatcher.start_polling(bot)
    finally:
        if maintenance_task is not None:
            maintenance_task.cancel()
            try:
                await maintenance_task
            except asyncio.CancelledError:
                pass
        if health is not None and health_task is not None:
            health.should_exit = True
            await health_task
        if bot is not None:
            await bot.session.close()
        if storage is not None:
            await storage.close()
        elif redis is not None:
            await redis.aclose()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--dry-run" in args:
        try:
            return dry_run()
        except SystemExit as exc:
            return int(exc.code or 1)
    try:
        token = require_bot_token()
    except SystemExit as exc:
        return int(exc.code or 1)
    try:
        asyncio.run(run_bot(token))
    except SystemExit as exc:
        return int(exc.code or 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
