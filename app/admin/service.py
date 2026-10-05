"""Operator actions that are not the web admin panel."""

import uuid
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import add_audit
from app.ledger.service import (
    LedgerLine,
    TraderBalances,
    balance_of,
    post_group,
    trader_available_code,
    trader_balances,
)
from app.models import AdminUser, Dispute, Order, User
from app.users.service import get_user_by_telegram_id

SATS_PER_BTC = Decimal(100_000_000)


class NotAdmin(Exception):
    pass


class CreditUsage(Exception):
    pass


async def require_admin(session: AsyncSession, user_id: uuid.UUID) -> AdminUser:
    admin = await session.get(AdminUser, user_id)
    if admin is None:
        raise NotAdmin()
    return admin


async def admin_adjust_deposit(
    session: AsyncSession,
    admin_user_id: uuid.UUID,
    trader_user_id: uuid.UUID,
    amount_sats: int,
    *,
    idempotency_key: str | None = None,
) -> TraderBalances:
    """Credit trader_available and debit external_in. Only admin_users may call this."""

    await require_admin(session, admin_user_id)
    trader = await session.get(User, trader_user_id)
    if trader is None:
        raise LookupError("trader user not found")
    if amount_sats <= 0 or amount_sats > 2**63 - 1:
        raise ValueError("amount must be a positive satoshi count")

    key = idempotency_key or f"admin-adjust:{uuid.uuid4()}"
    before = await balance_of(session, trader_available_code(trader_user_id))
    result = await post_group(
        session,
        operation_key=key,
        scope="admin_adjust",
        order_id=None,
        lines=[
            LedgerLine(
                code=trader_available_code(trader_user_id),
                kind="trader_available",
                user_id=trader_user_id,
                amount_sats=amount_sats,
                entry_type="ADMIN_ADJUSTMENT",
                idempotency_key=f"{key}:available",
            ),
            LedgerLine(
                code="external_in",
                kind="external_in",
                user_id=None,
                amount_sats=-amount_sats,
                entry_type="ADMIN_ADJUSTMENT",
                idempotency_key=f"{key}:external_in",
            ),
        ],
    )
    balances = await trader_balances(session, trader_user_id)
    if result.created:
        add_audit(
            session,
            actor_user_id=admin_user_id,
            action="admin_adjust_deposit",
            entity_type="user",
            entity_id=trader_user_id,
            before_state={"available_sats": before},
            after_state={
                "available_sats": balances.available_sats,
                "amount_sats": amount_sats,
                "group_id": str(result.group_id),
            },
        )
    return balances


def parse_amount_token(token: str) -> int:
    """Integer tokens are satoshis. A decimal token is BTC (0.01 BTC = 1_000_000 sats)."""

    normalized = token.replace(",", ".").strip()
    if not normalized:
        raise CreditUsage("Укажите сумму.")
    if any(char in normalized for char in ".eE"):
        value = Decimal(normalized)
        sats = int((value * SATS_PER_BTC).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    else:
        sats = int(normalized)
    if sats <= 0:
        raise CreditUsage("Сумма должна быть положительной.")
    return sats


async def apply_credit_command(session: AsyncSession, *, admin_telegram_id: int, args: str) -> str:
    admin = await get_user_by_telegram_id(session, admin_telegram_id)
    if admin is None:
        raise NotAdmin()
    await require_admin(session, admin.id)
    parts = args.split()
    if len(parts) == 1:
        target = admin
        sats = parse_amount_token(parts[0])
    elif len(parts) == 2:
        try:
            target_telegram_id = int(parts[0])
        except ValueError as exc:
            raise CreditUsage("Формат: /credit telegram_id сумма, или /credit 0.01") from exc
        target = await get_user_by_telegram_id(session, target_telegram_id)
        if target is None:
            raise LookupError("user not found")
        sats = parse_amount_token(parts[1])
    else:
        raise CreditUsage("Формат: /credit telegram_id сумма, или /credit 0.01")
    balances = await admin_adjust_deposit(session, admin.id, target.id, sats)
    return (
        f"Зачислено {sats} сатоши.\n"
        f"Доступно: {balances.available_sats} сатоши.\n"
        "Это виртуальное пополнение для теста, не вход в сети."
    )


async def apply_resolve_command(session: AsyncSession, *, admin_telegram_id: int, args: str) -> str:
    from app.disputes.service import resolve_dispute

    admin = await get_user_by_telegram_id(session, admin_telegram_id)
    if admin is None:
        raise NotAdmin()
    parts = args.split()
    if len(parts) != 2 or parts[1] not in {"release", "unlock"}:
        raise CreditUsage("Формат: /resolve номер release или unlock")
    try:
        public_no = int(parts[0])
    except ValueError as exc:
        raise CreditUsage("Номер заявки должен быть числом.") from exc
    from sqlalchemy import select

    order = await session.scalar(select(Order).where(Order.public_no == public_no))
    if order is None:
        raise LookupError("order not found")
    await resolve_dispute(session, admin.id, order.id, parts[1])
    dispute = await session.scalar(select(Dispute).where(Dispute.order_id == order.id))
    resolution = "" if dispute is None or dispute.resolution is None else str(dispute.resolution)
    return f"Спор по заявке №{public_no}: {resolution}."
