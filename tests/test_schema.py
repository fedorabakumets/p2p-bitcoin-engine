from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schema_sql import prepare_schema_sql

ROOT = Path(__file__).resolve().parents[1]

ORDER_STATUSES = [
    "CREATED",
    "QUOTED",
    "SEARCHING_EXECUTOR",
    "EXECUTOR_ASSIGNED",
    "WAITING_PAYMENT",
    "CLIENT_MARKED_PAID",
    "PAYMENT_CONFIRMED",
    "RELEASING",
    "COMPLETED",
    "CANCELLED",
    "EXPIRED",
    "DISPUTED",
    "FAILED",
]


def test_schema_script_keeps_the_trigger_function() -> None:
    raw = (ROOT / "migrations" / "001_initial.sql").read_text(encoding="utf-8")
    sql = prepare_schema_sql(raw)
    assert "BEGIN;" not in sql
    assert "COMMIT;" not in sql
    assert "CREATE FUNCTION ledger_balances_non_negative" in sql
    assert "\nBEGIN\n" in sql
    assert "negative balance" in sql


async def test_applied_schema_matches_v1(session: AsyncSession) -> None:
    labels = list(
        await session.scalars(
            text(
                """
                SELECT e.enumlabel
                FROM pg_enum e
                JOIN pg_type t ON t.oid = e.enumtypid
                WHERE t.typname = 'order_status'
                ORDER BY e.enumsortorder
                """
            )
        )
    )
    assert labels == ORDER_STATUSES

    checks = " ".join(
        await session.scalars(
            text(
                """
                SELECT pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conrelid = 'orders'::regclass AND contype = 'c'
                """
            )
        )
    )
    assert "client_btc_sats + platform_fee_sats" in checks

    columns = set(
        await session.scalars(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'ledger_balances'
                """
            )
        )
    )
    assert "balance_sats" in columns
    assert "balance_rub" not in columns
    assert "balance_rub_kop" not in columns
