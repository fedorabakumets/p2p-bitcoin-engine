import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.client.texts import format_quote
from app.pricing.formula import PricingError, build_quote
from app.pricing.rates import FixedRateSource
from app.pricing.service import PricingService, load_pricing_settings


def test_default_quote_for_2000_rub() -> None:
    snapshot = build_quote(
        principal_rub_kop=200_000,
        markup_bps=1800,
        platform_fee_bps=0,
        referral_bps=0,
        rate_rub_per_btc=Decimal("6000000"),
        ttl_seconds=120,
        now=datetime(2026, 10, 4, tzinfo=timezone.utc),
    )
    assert snapshot.payment_rub_kop == 236_000
    assert snapshot.client_btc_sats == 33_333
    assert snapshot.platform_fee_sats == 0
    assert snapshot.referral_sats == 0
    assert snapshot.trader_lock_sats == snapshot.client_btc_sats + snapshot.platform_fee_sats
    assert snapshot.expires_at == datetime(2026, 10, 4, tzinfo=timezone.utc) + timedelta(seconds=120)
    restored = snapshot.__class__.from_dict(json.loads(json.dumps(snapshot.to_dict())))
    assert restored == snapshot
    assert format_quote(snapshot) == (
        "<b>Котировка</b>\n"
        "Получите: 2000 ₽\n"
        "Наценка: 18%\n"
        "К оплате: 2360 ₽\n"
        "Уйдёт: 0.00033333 BTC\n"
        "Курс действует ещё 2 мин"
    )


def test_exact_btc_and_fee_slice() -> None:
    snapshot = build_quote(
        principal_rub_kop=600_000,
        markup_bps=1800,
        platform_fee_bps=100,
        referral_bps=2500,
        rate_rub_per_btc=Decimal("6000000"),
        ttl_seconds=120,
    )
    assert snapshot.client_btc_sats == 100_000
    assert snapshot.payment_rub_kop == 708_000
    assert snapshot.platform_fee_sats == 1_000
    assert snapshot.referral_sats == 250
    assert snapshot.trader_lock_sats == 101_000
    assert snapshot.referral_sats <= snapshot.platform_fee_sats


def test_referral_is_capped_by_platform_fee() -> None:
    snapshot = build_quote(
        principal_rub_kop=600_000,
        markup_bps=0,
        platform_fee_bps=100,
        referral_bps=25_000,
        rate_rub_per_btc=Decimal("6000000"),
        ttl_seconds=60,
    )
    assert snapshot.platform_fee_sats == 1_000
    assert snapshot.referral_sats == snapshot.platform_fee_sats
    assert snapshot.referral_bps == 25_000


def test_half_up_satoshi_and_too_small_principal() -> None:
    one = build_quote(
        principal_rub_kop=1,
        markup_bps=0,
        platform_fee_bps=0,
        referral_bps=0,
        rate_rub_per_btc=Decimal("2000000"),
        ttl_seconds=120,
    )
    assert one.client_btc_sats == 1
    try:
        build_quote(
            principal_rub_kop=1,
            markup_bps=0,
            platform_fee_bps=0,
            referral_bps=0,
            rate_rub_per_btc=Decimal("2500000"),
            ttl_seconds=120,
        )
    except PricingError:
        pass
    else:
        raise AssertionError("expected a principal that rounds to zero sats to fail")


def test_fee_rounding_half_up() -> None:
    snapshot = build_quote(
        principal_rub_kop=200_000,
        markup_bps=1800,
        platform_fee_bps=100,
        referral_bps=2500,
        rate_rub_per_btc=Decimal("6000000"),
        ttl_seconds=120,
    )
    assert snapshot.client_btc_sats == 33_333
    assert snapshot.platform_fee_sats == 333
    assert snapshot.referral_sats == 83
    assert snapshot.trader_lock_sats == 33_666


async def test_settings_defaults_and_service_reads_them(session: AsyncSession) -> None:
    settings = await load_pricing_settings(session)
    assert settings.quote_ttl_seconds == 120
    assert settings.accept_ttl_seconds == 20
    assert settings.pay_ttl_seconds == 900
    assert settings.default_markup_bps == 1800
    assert settings.platform_fee_bps == 0
    assert settings.referral_bps == 0

    await session.execute(text("UPDATE settings SET value = '1000'::jsonb WHERE key = 'default_markup_bps'"))
    await session.execute(text("UPDATE settings SET value = '100'::jsonb WHERE key = 'platform_fee_bps'"))
    await session.execute(text("UPDATE settings SET value = '2500'::jsonb WHERE key = 'referral_bps'"))
    snapshot = await PricingService(FixedRateSource(Decimal("6000000"))).quote(session, 200_000)
    assert snapshot.markup_bps == 1000
    assert snapshot.payment_rub_kop == 220_000
    assert snapshot.platform_fee_bps == 100
    assert snapshot.referral_bps == 2500
    assert snapshot.platform_fee_sats == 333
    assert snapshot.referral_sats == 83
