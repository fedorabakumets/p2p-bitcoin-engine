import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["DATABASE_URL"] = "postgresql+asyncpg://p2p:p2p@127.0.0.1:5432/p2p_test"
os.environ["BTC_RUB_RATE"] = "6000000"
os.environ["WALLET_BACKEND"] = "fake"
# Order fixtures pay to mainnet addresses. Runtime default stays testnet.
os.environ["BITCOIN_NETWORK"] = "mainnet"
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture(scope="session", autouse=True)
def apply_migrations() -> None:
    if "sqlite" in os.environ["DATABASE_URL"]:
        raise RuntimeError("tests must use PostgreSQL")
    admin = psycopg.connect("postgresql://p2p:p2p@127.0.0.1:5432/postgres", autocommit=True)
    admin.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = 'p2p_test' AND pid <> pg_backend_pid()"
    )
    admin.execute("DROP DATABASE IF EXISTS p2p_test")
    admin.execute("CREATE DATABASE p2p_test OWNER p2p")
    admin.close()
    alembic = Path(sys.executable).with_name("alembic")
    subprocess.check_call([str(alembic), "upgrade", "head"], cwd=ROOT, env=os.environ.copy())


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    from app.db import get_sessionmaker

    maker = get_sessionmaker()
    async with maker() as db:
        try:
            yield db
        finally:
            await db.rollback()
            await db.execute(
                text(
                    """
                    TRUNCATE TABLE
                        idempotency_keys,
                        dispute_evidence,
                        disputes,
                        notifications,
                        audit_log,
                        referral_rewards,
                        escrow_locks,
                        ledger_entries,
                        ledger_balances,
                        ledger_accounts,
                        order_events,
                        wallet_transactions,
                        wallet_addresses,
                        trader_daily_volume,
                        trader_payment_methods,
                        orders,
                        quotes,
                        traders,
                        admin_users,
                        users
                    RESTART IDENTITY CASCADE
                    """
                )
            )
            await db.execute(
                text(
                    """
                    INSERT INTO settings (key, value) VALUES
                        ('quote_ttl_seconds', '120'),
                        ('accept_ttl_seconds', '20'),
                        ('pay_ttl_seconds', '900'),
                        ('default_markup_bps', '1800'),
                        ('platform_fee_bps', '0'),
                        ('referral_bps', '0')
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                    """
                )
            )
            await db.commit()
