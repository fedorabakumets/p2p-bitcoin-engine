"""ORM rows for the tables this prototype writes.

The SQL file is the schema. These mappings follow it and do not create tables.
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Identity, Integer, Numeric, String, Text, cast
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
ADMIN_ROLE = PgEnumValue("admin_role", ("owner", "operator"))
TRADER_STATUS = PgEnumValue("trader_status", ("pending", "active", "suspended"))
PAYMENT_KIND = PgEnumValue("payment_kind", ("sbp",))
LEDGER_ACCOUNT_KIND = PgEnumValue(
    "ledger_account_kind",
    (
        "trader_available",
        "trader_locked",
        "platform_revenue",
        "referral_payable",
        "external_in",
        "external_out",
    ),
)
LEDGER_ENTRY_TYPE = PgEnumValue(
    "ledger_entry_type",
    (
        "DEPOSIT",
        "WITHDRAWAL",
        "ESCROW_LOCK",
        "ESCROW_UNLOCK",
        "ESCROW_RELEASE",
        "PLATFORM_REVENUE",
        "REFERRAL_REWARD",
        "ADMIN_ADJUSTMENT",
    ),
)
ESCROW_STATUS = PgEnumValue("escrow_status", ("locked", "released", "unlocked"))
REFERRAL_REWARD_STATUS = PgEnumValue("referral_reward_status", ("accrued", "paid"))
DISPUTE_STATUS = PgEnumValue("dispute_status", ("open", "resolved"))
DISPUTE_RESOLUTION = PgEnumValue("dispute_resolution", ("release", "unlock"))
EVIDENCE_KIND = PgEnumValue("evidence_kind", ("screenshot", "text"))
NOTIFICATION_STATUS = PgEnumValue("notification_status", ("pending", "sent", "failed"))


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


class AdminUser(Base):
    __tablename__ = "admin_users"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(ADMIN_ROLE, nullable=False)


class Trader(Base):
    __tablename__ = "traders"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    status: Mapped[str] = mapped_column(TRADER_STATUS, nullable=False, default="pending")
    is_online: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tier: Mapped[str] = mapped_column(Text, nullable=False, default="basic")
    min_order_rub_kop: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    max_order_rub_kop: Mapped[int] = mapped_column(BigInteger, nullable=False, default=10_000_000_000)
    daily_limit_rub_kop: Mapped[int] = mapped_column(BigInteger, nullable=False, default=10_000_000_000)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class TraderPaymentMethod(Base):
    __tablename__ = "trader_payment_methods"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trader_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("traders.user_id"), nullable=False)
    kind: Mapped[str] = mapped_column(PAYMENT_KIND, nullable=False, default="sbp")
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    bank_name: Mapped[str] = mapped_column(Text, nullable=False)
    holder_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class TraderDailyVolume(Base):
    __tablename__ = "trader_daily_volume"

    trader_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("traders.user_id"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    used_rub_kop: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class LedgerAccount(Base):
    __tablename__ = "ledger_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(LEDGER_ACCOUNT_KIND, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    asset: Mapped[str] = mapped_column(Text, nullable=False, default="btc")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ledger_accounts.id"), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"))
    amount_sats: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entry_type: Mapped[str] = mapped_column(LEDGER_ENTRY_TYPE, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class LedgerBalance(Base):
    __tablename__ = "ledger_balances"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ledger_accounts.id"), primary_key=True
    )
    balance_sats: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class EscrowLock(Base):
    __tablename__ = "escrow_locks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), unique=True, nullable=False)
    trader_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("traders.user_id"), nullable=False)
    amount_sats: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(ESCROW_STATUS, nullable=False, default="locked")
    lock_group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    release_group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReferralReward(Base):
    __tablename__ = "referral_rewards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), unique=True, nullable=False)
    referrer_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    referred_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    amount_sats: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ledger_group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(REFERRAL_REWARD_STATUS, nullable=False, default="accrued")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class Dispute(Base):
    __tablename__ = "disputes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), unique=True, nullable=False)
    opened_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(DISPUTE_STATUS, nullable=False, default="open")
    resolution: Mapped[str | None] = mapped_column(DISPUTE_RESOLUTION)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DisputeEvidence(Base):
    __tablename__ = "dispute_evidence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dispute_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("disputes.id"), nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    telegram_file_id: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(EVIDENCE_KIND, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(NOTIFICATION_STATUS, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
