from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Setting
from app.pricing.formula import QuoteSnapshot, build_quote
from app.pricing.rates import RateSource

DEFAULTS = {
    "quote_ttl_seconds": 120,
    "accept_ttl_seconds": 20,
    "pay_ttl_seconds": 900,
    "default_markup_bps": 1800,
    "platform_fee_bps": 0,
    "referral_bps": 0,
}


@dataclass(frozen=True)
class PricingSettings:
    quote_ttl_seconds: int
    accept_ttl_seconds: int
    pay_ttl_seconds: int
    default_markup_bps: int
    platform_fee_bps: int
    referral_bps: int


class PricingService:
    def __init__(self, rates: RateSource):
        self._rates = rates

    async def quote(
        self,
        session: AsyncSession,
        principal_rub_kop: int,
        *,
        now: datetime | None = None,
    ) -> QuoteSnapshot:
        settings = await load_pricing_settings(session)
        rate = await self._rates.get_rate_rub_per_btc()
        return build_quote(
            principal_rub_kop=principal_rub_kop,
            markup_bps=settings.default_markup_bps,
            platform_fee_bps=settings.platform_fee_bps,
            referral_bps=settings.referral_bps,
            rate_rub_per_btc=rate,
            ttl_seconds=settings.quote_ttl_seconds,
            now=now,
        )


async def load_pricing_settings(session: AsyncSession) -> PricingSettings:
    rows = (await session.scalars(select(Setting))).all()
    values = dict(DEFAULTS)
    for row in rows:
        if row.key not in values:
            continue
        values[row.key] = _as_int(row.value)
    return PricingSettings(
        quote_ttl_seconds=values["quote_ttl_seconds"],
        accept_ttl_seconds=values["accept_ttl_seconds"],
        pay_ttl_seconds=values["pay_ttl_seconds"],
        default_markup_bps=values["default_markup_bps"],
        platform_fee_bps=values["platform_fee_bps"],
        referral_bps=values["referral_bps"],
    )


def _as_int(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        raise TypeError(f"setting value {value!r} is not an integer")
    return int(value)
