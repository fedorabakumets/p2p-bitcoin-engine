"""Satoshi ledger. Every group sums to zero. Balances move only in this module.

Ruble markup never becomes a ledger credit. There is no TRADER_REWARD entry.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

MAX_SATS = 2**63 - 1


class LedgerError(Exception):
    pass


class InsufficientBalance(LedgerError):
    pass


@dataclass(frozen=True)
class LedgerLine:
    code: str
    kind: str
    user_id: uuid.UUID | None
    amount_sats: int
    entry_type: str
    idempotency_key: str


@dataclass(frozen=True)
class PostResult:
    group_id: uuid.UUID
    created: bool


@dataclass(frozen=True)
class TraderBalances:
    available_sats: int
    locked_sats: int
    total_sats: int


def trader_available_code(user_id: uuid.UUID) -> str:
    return f"trader_available:{user_id}"


def trader_locked_code(user_id: uuid.UUID) -> str:
    return f"trader_locked:{user_id}"


def referral_payable_code(user_id: uuid.UUID) -> str:
    return f"referral_payable:{user_id}"


async def balance_of(session: AsyncSession, code: str) -> int:
    value = await session.scalar(
        text(
            """
            SELECT COALESCE(b.balance_sats, 0)
            FROM ledger_accounts a
            LEFT JOIN ledger_balances b ON b.account_id = a.id
            WHERE a.code = :code
            """
        ),
        {"code": code},
    )
    return int(value or 0)


async def trader_balances(session: AsyncSession, user_id: uuid.UUID) -> TraderBalances:
    available = await balance_of(session, trader_available_code(user_id))
    locked = await balance_of(session, trader_locked_code(user_id))
    return TraderBalances(available, locked, available + locked)


async def available_for_update(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Lock the available row when it exists. Missing account reads as zero."""

    value = await session.scalar(
        text(
            """
            SELECT b.balance_sats
            FROM ledger_accounts a
            JOIN ledger_balances b ON b.account_id = a.id
            WHERE a.code = :code
            FOR UPDATE OF b
            """
        ),
        {"code": trader_available_code(user_id)},
    )
    return int(value or 0)


async def post_group(
    session: AsyncSession,
    *,
    operation_key: str,
    scope: str,
    lines: list[LedgerLine],
    order_id: uuid.UUID | None,
) -> PostResult:
    if not lines:
        raise LedgerError("ledger group is empty")
    if sum(line.amount_sats for line in lines) != 0:
        raise LedgerError("ledger group does not sum to zero")
    if any(line.amount_sats == 0 for line in lines):
        raise LedgerError("ledger line must be non-zero")
    keys = [line.idempotency_key for line in lines]
    if len(set(keys)) != len(keys):
        raise LedgerError("duplicate ledger idempotency key")

    existing = await _group_for_lines(session, keys)
    if existing is not None:
        return PostResult(existing, created=False)

    group_id = uuid.uuid4()
    try:
        async with session.begin_nested():
            claimed = await _claim(session, operation_key, scope)
            if not claimed:
                replay = await _group_for_lines(session, keys)
                if replay is None:
                    raise LedgerError("idempotency key reused without a ledger group")
                return PostResult(replay, created=False)
            accounts: list[tuple[uuid.UUID, LedgerLine]] = []
            for line in lines:
                account_id = await _ensure_account(session, line)
                accounts.append((account_id, line))
            for account_id, line in sorted(accounts, key=lambda item: str(item[0])):
                await _apply(session, account_id, line.amount_sats)
                await session.execute(
                    text(
                        """
                        INSERT INTO ledger_entries (
                            group_id, account_id, order_id, amount_sats, entry_type, idempotency_key
                        )
                        VALUES (
                            :group_id,
                            :account_id,
                            :order_id,
                            :amount_sats,
                            CAST(:entry_type AS ledger_entry_type),
                            :idempotency_key
                        )
                        """
                    ),
                    {
                        "group_id": group_id,
                        "account_id": account_id,
                        "order_id": order_id,
                        "amount_sats": line.amount_sats,
                        "entry_type": line.entry_type,
                        "idempotency_key": line.idempotency_key,
                    },
                )
    except DBAPIError as exc:
        if "negative balance" in str(exc):
            raise InsufficientBalance(str(exc)) from exc
        raise
    return PostResult(group_id, created=True)


async def _group_for_lines(session: AsyncSession, keys: list[str]) -> uuid.UUID | None:
    groups: set[uuid.UUID] = set()
    found = 0
    for key in keys:
        group_id = await session.scalar(
            text("SELECT group_id FROM ledger_entries WHERE idempotency_key = :key"),
            {"key": key},
        )
        if group_id is None:
            continue
        found += 1
        groups.add(group_id)
    if found == 0:
        return None
    if found != len(keys) or len(groups) != 1:
        raise LedgerError("ledger idempotency keys are incomplete")
    return groups.pop()


async def _claim(session: AsyncSession, key: str, scope: str) -> bool:
    row = await session.execute(
        text(
            """
            INSERT INTO idempotency_keys (key, scope)
            VALUES (:key, :scope)
            ON CONFLICT (key) DO NOTHING
            RETURNING key
            """
        ),
        {"key": key, "scope": scope},
    )
    return row.first() is not None


async def _ensure_account(session: AsyncSession, line: LedgerLine) -> uuid.UUID:
    await session.execute(
        text(
            """
            INSERT INTO ledger_accounts (code, kind, user_id)
            VALUES (:code, CAST(:kind AS ledger_account_kind), :user_id)
            ON CONFLICT (code) DO NOTHING
            """
        ),
        {"code": line.code, "kind": line.kind, "user_id": line.user_id},
    )
    account_id = await session.scalar(
        text("SELECT id FROM ledger_accounts WHERE code = :code"),
        {"code": line.code},
    )
    if account_id is None:
        raise LedgerError(f"ledger account {line.code} was not created")
    await session.execute(
        text(
            """
            INSERT INTO ledger_balances (account_id, balance_sats)
            VALUES (:account_id, 0)
            ON CONFLICT (account_id) DO NOTHING
            """
        ),
        {"account_id": account_id},
    )
    return account_id


async def _apply(session: AsyncSession, account_id: uuid.UUID, delta: int) -> None:
    if delta == 0 or abs(delta) > MAX_SATS:
        raise LedgerError("ledger delta is out of range")
    await session.execute(
        text(
            """
            UPDATE ledger_balances
            SET balance_sats = balance_sats + :delta, updated_at = NOW()
            WHERE account_id = :account_id
            """
        ),
        {"delta": delta, "account_id": account_id},
    )
