from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendPhoto
from aiogram.types import FSInputFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.brand import LOGO_FILE_ID_KEY, load_logo_file_id, logo_path, save_logo_file_id, send_brand_greeting
from app.db import get_sessionmaker


class _Photo:
    def __init__(self, file_id: str) -> None:
        self.file_id = file_id


class _Sent:
    def __init__(self, file_id: str) -> None:
        self.photo = [_Photo(file_id)]


class FakeBot:
    def __init__(self, *, uploaded_id: str = "AgAC_uploaded", reject: set[str] | None = None) -> None:
        self.uploaded_id = uploaded_id
        self.reject = reject or set()
        self.photos: list[object] = []

    async def send_photo(self, chat_id: int, photo: object, **kwargs: object) -> _Sent:
        self.photos.append(photo)
        if isinstance(photo, str) and photo in self.reject:
            raise TelegramBadRequest(
                method=SendPhoto(chat_id=chat_id, photo=photo),
                message="wrong file identifier",
            )
        if isinstance(photo, str):
            return _Sent(photo)
        return _Sent(self.uploaded_id)


async def _cleanup(session: AsyncSession) -> None:
    await session.rollback()
    await session.execute(text("DELETE FROM settings WHERE key = :key"), {"key": LOGO_FILE_ID_KEY})
    await session.commit()


async def test_greeting_uploads_and_stores_file_id_when_missing(session: AsyncSession) -> None:
    try:
        bot = FakeBot(uploaded_id="AgAC_uploaded")
        used = await send_brand_greeting(bot, session, 42, "<b>Кедр</b>")
        await session.commit()
        assert used == "AgAC_uploaded"
        assert len(bot.photos) == 1
        assert isinstance(bot.photos[0], FSInputFile)
        async with get_sessionmaker()() as other:
            assert await load_logo_file_id(other) == "AgAC_uploaded"
    finally:
        await _cleanup(session)


async def test_greeting_reuses_stored_file_id_without_upload(session: AsyncSession) -> None:
    try:
        await save_logo_file_id(session, "AgAC_stored")
        await session.commit()
        session.expire_all()
        bot = FakeBot()
        used = await send_brand_greeting(bot, session, 42, "<b>Кедр</b>", reply_markup=object())
        assert used == "AgAC_stored"
        assert bot.photos == ["AgAC_stored"]
        assert await load_logo_file_id(session) == "AgAC_stored"
    finally:
        await _cleanup(session)


async def test_greeting_replaces_rejected_file_id(session: AsyncSession) -> None:
    try:
        await save_logo_file_id(session, "AgAC_old")
        await session.commit()
        session.expire_all()
        bot = FakeBot(uploaded_id="AgAC_new", reject={"AgAC_old"})
        used = await send_brand_greeting(bot, session, 7, "<b>Кедр</b>")
        await session.commit()
        assert used == "AgAC_new"
        assert isinstance(bot.photos[0], str)
        assert isinstance(bot.photos[1], FSInputFile)
        async with get_sessionmaker()() as other:
            assert await load_logo_file_id(other) == "AgAC_new"
    finally:
        await _cleanup(session)


def test_logo_png_is_in_the_repo() -> None:
    data = logo_path().read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
