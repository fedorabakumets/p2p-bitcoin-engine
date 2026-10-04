"""Rate source. The bot is not tied to an exchange.

The only implementation in this prototype is a fixed number, taken from
BTC_RUB_RATE or from the caller. The default is 6_000_000 RUB per BTC.
"""

from decimal import Decimal
from typing import Protocol

from app.config import btc_rub_rate


class RateSource(Protocol):
    async def get_rate_rub_per_btc(self) -> Decimal:
        """Return how many rubles one bitcoin costs."""


class FixedRateSource:
    def __init__(self, rate: Decimal):
        self._rate = rate

    async def get_rate_rub_per_btc(self) -> Decimal:
        return self._rate


class EnvRateSource:
    """Fixed stub. Reads BTC_RUB_RATE once per call so tests can change it."""

    async def get_rate_rub_per_btc(self) -> Decimal:
        return btc_rub_rate()
