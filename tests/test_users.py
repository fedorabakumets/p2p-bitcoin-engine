import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.users.service import invited_count, register_from_start, resolve_referrer_id


def test_self_referral_is_rejected() -> None:
    referrer_id = uuid.uuid4()
    assert (
        resolve_referrer_id(referrer_id=referrer_id, referrer_telegram_id=7, telegram_id=7)
        is None
    )
    assert resolve_referrer_id(referrer_id=referrer_id, referrer_telegram_id=7, telegram_id=8) == referrer_id
    assert resolve_referrer_id(referrer_id=None, referrer_telegram_id=None, telegram_id=8) is None


async def test_start_creates_user_and_binds_referral_once(session: AsyncSession) -> None:
    first = await register_from_start(
        session,
        telegram_id=1001,
        username="ann",
        display_name="Ann",
        start_payload=None,
    )
    repeated = await register_from_start(
        session,
        telegram_id=1001,
        username="ann",
        display_name="Ann",
        start_payload=f"ref_{first.referral_code}",
    )
    assert repeated.id == first.id
    assert repeated.referred_by_user_id is None

    invited = await register_from_start(
        session,
        telegram_id=1002,
        username="bob",
        display_name="Bob",
        start_payload=f"ref_{first.referral_code}",
    )
    assert invited.referred_by_user_id == first.id
    assert await invited_count(session, first.id) == 1

    stranger = await register_from_start(
        session,
        telegram_id=1003,
        username=None,
        display_name=None,
        start_payload="ref_missing",
    )
    assert stranger.referred_by_user_id is None

    other = await register_from_start(
        session,
        telegram_id=1004,
        username="cay",
        display_name="Cay",
        start_payload=None,
    )
    again = await register_from_start(
        session,
        telegram_id=1002,
        username="bob",
        display_name="Bob",
        start_payload=f"ref_{other.referral_code}",
    )
    assert again.referred_by_user_id == first.id
    assert await invited_count(session, first.id) == 1
