"""ORM rows for the tables this prototype writes.

The SQL file is the schema. These mappings follow it and do not create tables.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Integer, Numeric, String, Text, cast
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)


class OrderStatus(enum.StrEnum):
    CREATED = "CREATED"
    QUOTED = "QUOTED"
    SEARCHING_EXECUTOR = "SEARCHING_EXECUTOR"
    EXECUTOR_ASSIGNED = "EXECUTOR_ASSIGNED"
    WAITING_PAYMENT = "WAITING_PAYMENT"
    CLIENT_MARKED_PAID = "CLIENT_MARKED_PAID"
    PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED"
    RELEASING = "RELEASING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    DISPUTED = "DISPUTED"
    FAILED = "FAILED"


class PgEnumValue(TypeDecorator[str]):
    """Bind Python strings as PostgreSQL enums and read them back as text."""

    impl = String
    cache_ok = True

    def __init__(self, name: str, values: tuple[str, ...]):
        super().__init__()
        self.enum_name = name
        self.values = values
        self._pg_enum = PgEnum(*values, name=name, create_type=False)

    def bind_expression(self, bindvalue):  # type: ignore[no-untyped-def]
        return cast(bindvalue, self._pg_enum)

    def column_expression(self, column):  # type: ignore[no-untyped-def]
        return cast(column, String)


USER_STATUS = PgEnumValue("user_status", ("active", "blocked"))
ORDER_STATUS = PgEnumValue("order_status", tuple(status.value for status in OrderStatus))
ACTOR_TYPE = PgEnumValue("actor_type", ("client", "trader", "system", "admin"))
EXECUTION_CHANNEL = PgEnumValue("execution_channel", ("trader", "processor"))


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    referral_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    referred_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(USER_STATUS, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class Quote(Base):
    __tablename__ = "quotes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    principal_rub_kop: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payment_rub_kop: Mapped[int] = mapped_column(BigInteger, nullable=False)
    markup_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    platform_fee_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    referral_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    market_rate_rub_per_btc: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    client_btc_sats: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform_fee_sats: Mapped[int] = mapped_column(BigInteger, nullable=False)
    referral_sats: Mapped[int] = mapped_column(BigInteger, nullable=False)
    trader_lock_sats: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    public_no: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    quote_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False)
    trader_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payment_method_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    execution_channel: Mapped[str] = mapped_column(EXECUTION_CHANNEL, nullable=False, default="trader")
    status: Mapped[str] = mapped_column(ORDER_STATUS, nullable=False, default=OrderStatus.CREATED.value)
    btc_address: Mapped[str] = mapped_column(Text, nullable=False)
    principal_rub_kop: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payment_rub_kop: Mapped[int] = mapped_column(BigInteger, nullable=False)
    markup_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    platform_fee_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    market_rate_rub_per_btc: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    client_btc_sats: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform_fee_sats: Mapped[int] = mapped_column(BigInteger, nullable=False)
    referral_sats: Mapped[int] = mapped_column(BigInteger, nullable=False)
    trader_lock_sats: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quote_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accept_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pay_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_marked_paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trader_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    payout_wallet_tx_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class OrderEvent(Base):
    __tablename__ = "order_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    from_status: Mapped[str | None] = mapped_column(ORDER_STATUS)
    to_status: Mapped[str] = mapped_column(ORDER_STATUS, nullable=False)
    actor_type: Mapped[str] = mapped_column(ACTOR_TYPE, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
