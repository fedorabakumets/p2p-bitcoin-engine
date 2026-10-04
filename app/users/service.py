import secrets
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


class UserBlocked(Exception):
    pass


def parse_referral_payload(payload: str | None) -> str | None:
    if not payload:
        return None
    text = payload.strip()
    if not text.startswith("ref_") or len(text) <= 4:
        return None
    code = text[4:].strip()
    return code or None


def resolve_referrer_id(
    *,
    referrer_id: uuid.UUID | None,
    referrer_telegram_id: int | None,
    telegram_id: int,
) -> uuid.UUID | None:
    """A user cannot be referred by themselves."""

    if referrer_id is None or referrer_telegram_id is None:
        return None
    if referrer_telegram_id == telegram_id:
        return None
    return referrer_id


def new_referral_code() -> str:
    return secrets.token_hex(4)


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.scalar(select(User).where(User.telegram_id == telegram_id))


async def invited_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    count = await session.scalar(
        select(func.count()).select_from(User).where(User.referred_by_user_id == user_id)
    )
    return int(count or 0)


async def register_from_start(
    session: AsyncSession,
    *,
    telegram_id: int,
    username: str | None,
    display_name: str | None,
    start_payload: str | None,
) -> User:
    """Create the user on /start. A later /start does not change the referrer."""

    existing = await get_user_by_telegram_id(session, telegram_id)
    if existing is not None:
        return existing

    code = parse_referral_payload(start_payload)
    referrer: User | None = None
    if code:
        referrer = await session.scalar(select(User).where(User.referral_code == code))
    referred_by = resolve_referrer_id(
        referrer_id=None if referrer is None else referrer.id,
        referrer_telegram_id=None if referrer is None else referrer.telegram_id,
        telegram_id=telegram_id,
    )

    username = _clean(username, 64)
    display_name = _clean(display_name, 256)

    for _ in range(5):
        user = User(
            telegram_id=telegram_id,
            username=username,
            display_name=display_name,
            referral_code=new_referral_code(),
            referred_by_user_id=referred_by,
            status="active",
        )
        try:
            async with session.begin_nested():
                session.add(user)
                await session.flush()
            return user
        except IntegrityError:
            existing = await get_user_by_telegram_id(session, telegram_id)
            if existing is not None:
                return existing
    raise RuntimeError("could not allocate a unique referral code")


def _clean(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    return text[:limit]
