"""Greeting logo: upload once, then reuse Telegram's file_id."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, FSInputFile, InputProfilePhotoStatic, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Setting, utcnow

LOGO_FILE_ID_KEY = "brand_logo_file_id"
_LOG = logging.getLogger("app")


def logo_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / "logo.png"


async def load_logo_file_id(session: AsyncSession) -> str | None:
    row = await session.get(Setting, LOGO_FILE_ID_KEY)
    if row is None or not isinstance(row.value, str):
        return None
    file_id = row.value.strip()
    return file_id or None


async def save_logo_file_id(session: AsyncSession, file_id: str) -> None:
    cleaned = file_id.strip()
    if not cleaned:
        raise ValueError("empty logo file_id")
    row = await session.get(Setting, LOGO_FILE_ID_KEY)
    now = utcnow()
    if row is None:
        session.add(Setting(key=LOGO_FILE_ID_KEY, value=cleaned, updated_at=now))
    else:
        row.value = cleaned
        row.updated_at = now
    await session.flush()


def _file_id_from_photo(message: Message) -> str:
    photos = message.photo or []
    if not photos:
        raise RuntimeError("send_photo returned no photo sizes")
    file_id = photos[-1].file_id.strip()
    if not file_id:
        raise RuntimeError("send_photo returned an empty file_id")
    return file_id


async def send_brand_greeting(
    bot: Bot,
    session: AsyncSession,
    chat_id: int,
    caption: str,
    reply_markup: object | None = None,
) -> str:
    """Send the greeting photo. Upload the PNG only when the cache is empty or rejected."""

    cached = await load_logo_file_id(session)
    if cached is not None:
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=cached,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        except TelegramBadRequest:
            cached = None
        else:
            return cached
    message = await bot.send_photo(
        chat_id=chat_id,
        photo=FSInputFile(logo_path()),
        caption=caption,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML,
    )
    file_id = _file_id_from_photo(message)
    await save_logo_file_id(session, file_id)
    return file_id


def logo_jpeg_bytes() -> bytes:
    """Telegram static profile photos are JPEG. The repo asset stays PNG."""

    completed = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(logo_path()),
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    if not completed.stdout:
        raise RuntimeError("ffmpeg produced an empty JPEG")
    return completed.stdout


async def apply_profile_photo(bot: Bot) -> bool:
    setter = getattr(bot, "set_my_profile_photo", None)
    if setter is None:
        _LOG.error("setMyProfilePhoto is not available on this Bot API client")
        return False
    try:
        jpeg = logo_jpeg_bytes()
        await setter(photo=InputProfilePhotoStatic(photo=BufferedInputFile(jpeg, filename="logo.jpg")))
    except Exception as exc:
        detail = str(exc)
        lowered = detail.lower()
        if "token" in lowered or "ghp_" in lowered:
            detail = type(exc).__name__
        _LOG.error("setMyProfilePhoto failed: %s", detail[:300])
        return False
    _LOG.info("profile photo set")
    return True
