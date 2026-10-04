"""Shared money formatting. The ledger itself stores integer satoshis."""

from decimal import Decimal, ROUND_HALF_UP


def format_rub(kopecks: int) -> str:
    sign = "-" if kopecks < 0 else ""
    rubles, frac = divmod(abs(kopecks), 100)
    if frac:
        return f"{sign}{rubles},{frac:02d}"
    return f"{sign}{rubles}"


def format_btc(sats: int) -> str:
    sign = "-" if sats < 0 else ""
    whole, frac = divmod(abs(sats), 100_000_000)
    return f"{sign}{whole}.{frac:08d}"


def rub_kop_for_sats(sats: int, rate_rub_per_btc: Decimal) -> int:
    """Convert satoshis to integer kopecks at a rub-per-BTC rate. Half-up."""

    value = Decimal(sats) * Decimal(rate_rub_per_btc) / Decimal(1_000_000)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
