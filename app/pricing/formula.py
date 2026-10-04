"""Ruble markup stays on the trader card. The ledger only sees satoshis.

client_btc_sats is the bitcoin for the principal at the locked rate.
platform_fee_sats stays with the platform.
referral_sats is a slice of that platform fee, not an amount added on top.
trader_lock_sats = client_btc_sats + platform_fee_sats.

Rubles are integer kopecks. Basis points are integer hundredths of a percent
(1800 bps = 18%). Satoshis and kopecks use half-up rounding.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

SATS_PER_BTC = Decimal(100_000_000)
KOPECKS_PER_RUBLE = Decimal(100)
BPS_DENOMINATOR = Decimal(10_000)
MAX_SATS = 2**63 - 1
RATE_QUANTUM = Decimal("0.00000001")


class PricingError(Exception):
    pass


@dataclass(frozen=True)
class QuoteSnapshot:
    principal_rub_kop: int
    payment_rub_kop: int
    markup_bps: int
    platform_fee_bps: int
    referral_bps: int
    market_rate_rub_per_btc: Decimal
    client_btc_sats: int
    platform_fee_sats: int
    referral_sats: int
    trader_lock_sats: int
    expires_at: datetime
    ttl_seconds: int

    def to_dict(self) -> dict[str, object]:
        return {
            "principal_rub_kop": self.principal_rub_kop,
            "payment_rub_kop": self.payment_rub_kop,
            "markup_bps": self.markup_bps,
            "platform_fee_bps": self.platform_fee_bps,
            "referral_bps": self.referral_bps,
            "market_rate_rub_per_btc": format(self.market_rate_rub_per_btc, "f"),
            "client_btc_sats": self.client_btc_sats,
            "platform_fee_sats": self.platform_fee_sats,
            "referral_sats": self.referral_sats,
            "trader_lock_sats": self.trader_lock_sats,
            "expires_at": self.expires_at.isoformat(),
            "ttl_seconds": self.ttl_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "QuoteSnapshot":
        expires_raw = str(data["expires_at"])
        expires_at = datetime.fromisoformat(expires_raw)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return cls(
            principal_rub_kop=int(data["principal_rub_kop"]),  # type: ignore[arg-type]
            payment_rub_kop=int(data["payment_rub_kop"]),  # type: ignore[arg-type]
            markup_bps=int(data["markup_bps"]),  # type: ignore[arg-type]
            platform_fee_bps=int(data["platform_fee_bps"]),  # type: ignore[arg-type]
            referral_bps=int(data["referral_bps"]),  # type: ignore[arg-type]
            market_rate_rub_per_btc=Decimal(str(data["market_rate_rub_per_btc"])),
            client_btc_sats=int(data["client_btc_sats"]),  # type: ignore[arg-type]
            platform_fee_sats=int(data["platform_fee_sats"]),  # type: ignore[arg-type]
            referral_sats=int(data["referral_sats"]),  # type: ignore[arg-type]
            trader_lock_sats=int(data["trader_lock_sats"]),  # type: ignore[arg-type]
            expires_at=expires_at,
            ttl_seconds=int(data["ttl_seconds"]),  # type: ignore[arg-type]
        )


def build_quote(
    *,
    principal_rub_kop: int,
    markup_bps: int,
    platform_fee_bps: int,
    referral_bps: int,
    rate_rub_per_btc: Decimal,
    ttl_seconds: int,
    now: datetime | None = None,
) -> QuoteSnapshot:
    if principal_rub_kop <= 0:
        raise PricingError("principal must be positive")
    if markup_bps < 0 or platform_fee_bps < 0 or referral_bps < 0:
        raise PricingError("basis points must be non-negative")
    if ttl_seconds <= 0:
        raise PricingError("quote ttl must be positive")

    rate = _positive_rate(rate_rub_per_btc)
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise PricingError("quote timestamp must be timezone-aware")

    payment_rub_kop = _round_half_up(Decimal(principal_rub_kop) * Decimal(10_000 + markup_bps) / BPS_DENOMINATOR)
    if payment_rub_kop < principal_rub_kop:
        payment_rub_kop = principal_rub_kop

    # principal_rub_kop / 100 RUB * 1e8 sats / rate = principal_rub_kop * 1_000_000 / rate
    client_btc_sats = _round_half_up(Decimal(principal_rub_kop) * Decimal(1_000_000) / rate)
    if client_btc_sats <= 0:
        raise PricingError("principal is too small for the current rate")
    if client_btc_sats > MAX_SATS:
        raise PricingError("principal is too large for the current rate")

    platform_fee_sats = _round_half_up(Decimal(client_btc_sats) * Decimal(platform_fee_bps) / BPS_DENOMINATOR)
    share_bps = min(referral_bps, 10_000)
    referral_sats = _round_half_up(Decimal(platform_fee_sats) * Decimal(share_bps) / BPS_DENOMINATOR)
    if referral_sats > platform_fee_sats:
        referral_sats = platform_fee_sats

    trader_lock_sats = client_btc_sats + platform_fee_sats
    if trader_lock_sats > MAX_SATS:
        raise PricingError("locked amount does not fit in the ledger")

    return QuoteSnapshot(
        principal_rub_kop=principal_rub_kop,
        payment_rub_kop=payment_rub_kop,
        markup_bps=markup_bps,
        platform_fee_bps=platform_fee_bps,
        referral_bps=referral_bps,
        market_rate_rub_per_btc=rate,
        client_btc_sats=client_btc_sats,
        platform_fee_sats=platform_fee_sats,
        referral_sats=referral_sats,
        trader_lock_sats=trader_lock_sats,
        expires_at=moment + timedelta(seconds=ttl_seconds),
        ttl_seconds=ttl_seconds,
    )


def money_signature(snapshot: QuoteSnapshot) -> tuple[object, ...]:
    return (
        snapshot.principal_rub_kop,
        snapshot.payment_rub_kop,
        snapshot.markup_bps,
        snapshot.platform_fee_bps,
        snapshot.referral_bps,
        snapshot.market_rate_rub_per_btc,
        snapshot.client_btc_sats,
        snapshot.platform_fee_sats,
        snapshot.referral_sats,
        snapshot.trader_lock_sats,
    )


def snapshot_matches_formula(snapshot: QuoteSnapshot) -> bool:
    rebuilt = build_quote(
        principal_rub_kop=snapshot.principal_rub_kop,
        markup_bps=snapshot.markup_bps,
        platform_fee_bps=snapshot.platform_fee_bps,
        referral_bps=snapshot.referral_bps,
        rate_rub_per_btc=snapshot.market_rate_rub_per_btc,
        ttl_seconds=snapshot.ttl_seconds,
        now=snapshot.expires_at - timedelta(seconds=snapshot.ttl_seconds),
    )
    return money_signature(rebuilt) == money_signature(snapshot)


def _positive_rate(rate: Decimal) -> Decimal:
    if not isinstance(rate, Decimal):
        rate = Decimal(str(rate))
    if rate <= 0:
        raise PricingError("rate must be positive")
    quantized = rate.quantize(RATE_QUANTUM, rounding=ROUND_HALF_UP)
    if quantized <= 0:
        raise PricingError("rate must be positive")
    return quantized


def _round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
