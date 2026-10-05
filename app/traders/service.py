"""Trader profile, SBP method, daily volume, and withdrawal requests.

A withdrawal request notifies an operator. It does not move the ledger.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import add_audit
from app.ledger.service import trader_balances
from app.models import (
    AdminUser,
    Order,
    OrderStatus,
    Trader,
    TraderPaymentMethod,
    User,
)
from app.notifications.service import enqueue

TERMINAL = {
    OrderStatus.COMPLETED.value,
    OrderStatus.CANCELLED.value,
    OrderStatus.EXPIRED.value,
    OrderStatus.FAILED.value,
}


class NeedSbp(Exception):
    def __init__(self) -> None:
        super().__init__("Сначала укажите реквизиты СБП: телефон, банк и имя получателя.")


class TraderNotActive(Exception):
    def __init__(self) -> None:
        super().__init__("Приём заявок доступен активному трейдеру.")


class InvalidPaymentMethod(Exception):
    pass


class WithdrawalRejected(Exception):
    pass


@dataclass(frozen=True)
class TraderStats:
    completed_count: int
    turnover_rub_kop: int
    used_today_rub_kop: int
    daily_limit_rub_kop: int


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def normalize_phone(raw: str) -> str:
    text_value = raw.strip().replace(" ", "").replace("-", "")
    digits = text_value[1:] if text_value.startswith("+") else text_value
    if not digits.isdigit() or not 10 <= len(digits) <= 15:
        raise InvalidPaymentMethod("Введите телефон: от 10 до 15 цифр.")
    return text_value


def _clean_label(raw: str, label: str) -> str:
    text_value = " ".join(raw.split())
    if not text_value or len(text_value) > 100:
        raise InvalidPaymentMethod(f"Введите {label}.")
    return text_value


async def get_trader(session: AsyncSession, user_id: uuid.UUID) -> Trader | None:
    return await session.get(Trader, user_id)


async def active_sbp(session: AsyncSession, trader_id: uuid.UUID) -> TraderPaymentMethod | None:
    return await session.scalar(
        select(TraderPaymentMethod).where(
            TraderPaymentMethod.trader_id == trader_id,
            TraderPaymentMethod.is_active.is_(True),
            TraderPaymentMethod.kind == "sbp",
        )
    )


async def save_sbp(
    session: AsyncSession,
    trader_id: uuid.UUID,
    *,
    phone: str,
    bank_name: str,
    holder_name: str,
) -> TraderPaymentMethod:
    trader = await session.get(Trader, trader_id)
    if trader is None:
        raise LookupError("trader not found")
    normalized = normalize_phone(phone)
    bank = _clean_label(bank_name, "название банка")
    holder = _clean_label(holder_name, "имя получателя")
    await session.execute(
        text(
            """
            UPDATE trader_payment_methods
            SET is_active = false
            WHERE trader_id = :trader_id AND is_active
            """
        ),
        {"trader_id": trader_id},
    )
    method = TraderPaymentMethod(
        trader_id=trader_id,
        kind="sbp",
        phone=normalized,
        bank_name=bank,
        holder_name=holder,
        is_active=True,
    )
    session.add(method)
    await session.flush()
    return method


async def set_online(session: AsyncSession, trader_id: uuid.UUID, online: bool) -> Trader:
    trader = await session.get(Trader, trader_id, with_for_update=True)
    if trader is None:
        raise LookupError("trader not found")
    if online:
        if str(trader.status) != "active":
            raise TraderNotActive()
        method = await active_sbp(session, trader_id)
        if method is None:
            raise NeedSbp()
    trader.is_online = online
    await session.flush()
    return trader


async def used_volume_for_update(session: AsyncSession, trader_id: uuid.UUID, day: date) -> int:
    value = await session.scalar(
        text(
            """
            SELECT used_rub_kop
            FROM trader_daily_volume
            WHERE trader_id = :trader_id AND day = :day
            FOR UPDATE
            """
        ),
        {"trader_id": trader_id, "day": day},
    )
    return int(value or 0)


async def add_daily_volume(session: AsyncSession, trader_id: uuid.UUID, day: date, delta: int) -> int:
    if delta >= 0:
        value = await session.scalar(
            text(
                """
                INSERT INTO trader_daily_volume (trader_id, day, used_rub_kop)
                VALUES (:trader_id, :day, :delta)
                ON CONFLICT (trader_id, day)
                DO UPDATE SET used_rub_kop = trader_daily_volume.used_rub_kop + :delta
                RETURNING used_rub_kop
                """
            ),
            {"trader_id": trader_id, "day": day, "delta": delta},
        )
        return int(value or 0)
    value = await session.scalar(
        text(
            """
            UPDATE trader_daily_volume
            SET used_rub_kop = GREATEST(used_rub_kop + :delta, 0)
            WHERE trader_id = :trader_id AND day = :day
            RETURNING used_rub_kop
            """
        ),
        {"trader_id": trader_id, "day": day, "delta": delta},
    )
    return int(value or 0)


async def list_active_orders(session: AsyncSession, trader_id: uuid.UUID) -> list[Order]:
    rows = await session.scalars(
        select(Order)
        .where(Order.trader_id == trader_id, Order.status.not_in(tuple(TERMINAL)))
        .order_by(Order.created_at.desc())
    )
    return list(rows)


async def trader_stats(session: AsyncSession, trader_id: uuid.UUID) -> TraderStats:
    trader = await session.get(Trader, trader_id)
    if trader is None:
        raise LookupError("trader not found")
    completed = await session.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.trader_id == trader_id, Order.status == OrderStatus.COMPLETED.value)
    )
    turnover = await session.scalar(
        select(func.coalesce(func.sum(Order.principal_rub_kop), 0)).where(
            Order.trader_id == trader_id,
            Order.status == OrderStatus.COMPLETED.value,
        )
    )
    used = await session.scalar(
        text(
            """
            SELECT COALESCE(used_rub_kop, 0)
            FROM trader_daily_volume
            WHERE trader_id = :trader_id AND day = :day
            """
        ),
        {"trader_id": trader_id, "day": utc_today()},
    )
    return TraderStats(
        completed_count=int(completed or 0),
        turnover_rub_kop=int(turnover or 0),
        used_today_rub_kop=int(used or 0),
        daily_limit_rub_kop=trader.daily_limit_rub_kop,
    )


async def request_withdrawal(session: AsyncSession, trader_id: uuid.UUID, amount_sats: int) -> None:
    """Record an operator request. Available balance is not debited."""

    if amount_sats <= 0:
        raise WithdrawalRejected("Сумма вывода должна быть положительной.")
    trader = await session.get(Trader, trader_id)
    user = await session.get(User, trader_id)
    if trader is None or user is None:
        raise LookupError("trader not found")
    balances = await trader_balances(session, trader_id)
    if amount_sats > balances.available_sats:
        raise WithdrawalRejected("Недостаточно доступного баланса. Автовыплаты нет.")
    before = balances.available_sats
    add_audit(
        session,
        actor_user_id=trader_id,
        action="withdrawal_request",
        entity_type="trader",
        entity_id=trader_id,
        before_state={"available_sats": before},
        after_state={"available_sats": before, "requested_sats": amount_sats, "autopayout": False},
    )
    from app.formatting import html_btc, html_card

    text_value = html_card(
        "Вывод",
        f"Трейдер: <code>{user.telegram_id}</code>\n"
        f"Сумма: {html_btc(amount_sats)}\n"
        "Автовыплаты нет. Это заявка оператору.",
    )
    admins = list(await session.scalars(select(AdminUser.user_id)))
    for admin_id in admins:
        await enqueue(
            session,
            user_id=admin_id,
            order_id=None,
            kind="withdrawal_request",
            text=text_value,
        )
    after = await trader_balances(session, trader_id)
    if after.available_sats != before or after.locked_sats != balances.locked_sats:
        raise WithdrawalRejected("Вывод не должен менять баланс.")
