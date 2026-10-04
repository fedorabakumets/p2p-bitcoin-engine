import os
import sys
from decimal import Decimal, InvalidOperation


DEFAULT_DATABASE_URL = "postgresql+asyncpg://p2p:p2p@127.0.0.1:5432/p2p"
DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
DEFAULT_BTC_RUB_RATE = Decimal("6000000")


def database_url() -> str:
    return to_asyncpg(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))


def sync_database_url() -> str:
    return to_psycopg(database_url())


def libpq_url() -> str:
    return sync_database_url().replace("postgresql+psycopg://", "postgresql://", 1)


def redis_url() -> str:
    return os.environ.get("REDIS_URL", DEFAULT_REDIS_URL)


def btc_rub_rate() -> Decimal:
    raw = os.environ.get("BTC_RUB_RATE", str(DEFAULT_BTC_RUB_RATE)).strip()
    try:
        rate = Decimal(raw)
    except (InvalidOperation, ValueError):
        _die("BTC_RUB_RATE must be a positive number of RUB per BTC.")
    if rate <= 0:
        _die("BTC_RUB_RATE must be a positive number of RUB per BTC.")
    return rate


def health_host() -> str:
    return os.environ.get("HEALTH_HOST", "0.0.0.0")


def health_port() -> int:
    raw = os.environ.get("HEALTH_PORT", "8000")
    try:
        port = int(raw)
    except ValueError:
        _die("HEALTH_PORT must be an integer.")
    if not 1 <= port <= 65535:
        _die("HEALTH_PORT must be between 1 and 65535.")
    return port


def _die(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def to_asyncpg(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql+psycopg://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql+psycopg://")
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgres://")
    return url


def to_psycopg(url: str) -> str:
    return to_asyncpg(url).replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
