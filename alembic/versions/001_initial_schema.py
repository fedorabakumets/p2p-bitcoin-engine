"""Apply schema v1 from migrations/001_initial.sql.

Revision ID: 001_initial
Revises:
Create Date: 2026-10-04

"""

from pathlib import Path

from alembic import op

from app.schema_sql import exec_sql_script, prepare_schema_sql

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None

SQL_PATH = Path(__file__).resolve().parents[2] / "migrations" / "001_initial.sql"

DOWNGRADE_SQL = """
DROP TABLE IF EXISTS
    idempotency_keys,
    audit_log,
    notifications,
    dispute_evidence,
    disputes,
    wallet_transactions,
    wallet_addresses,
    referral_rewards,
    escrow_locks,
    ledger_balances,
    ledger_entries,
    ledger_accounts,
    order_events,
    orders,
    quotes,
    settings,
    trader_daily_volume,
    trader_payment_methods,
    traders,
    admin_users,
    users
CASCADE;
DROP FUNCTION IF EXISTS ledger_balances_non_negative();
DROP TYPE IF EXISTS
    notification_status,
    evidence_kind,
    dispute_resolution,
    dispute_status,
    chain_tx_status,
    chain_direction,
    address_purpose,
    referral_reward_status,
    escrow_status,
    ledger_entry_type,
    ledger_account_kind,
    actor_type,
    order_status,
    execution_channel,
    payment_kind,
    trader_status,
    admin_role,
    user_status;
"""


def upgrade() -> None:
    sql = prepare_schema_sql(SQL_PATH.read_text(encoding="utf-8"))
    exec_sql_script(op.get_bind(), sql)


def downgrade() -> None:
    exec_sql_script(op.get_bind(), DOWNGRADE_SQL)
