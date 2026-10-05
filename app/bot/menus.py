from aiogram.types import ReplyKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Trader
from app.users.service import get_user_by_telegram_id


async def menu_for(session: AsyncSession, telegram_id: int | None) -> ReplyKeyboardMarkup:
    from app.bot.client.keyboards import main_menu

    if telegram_id is None:
        return main_menu(False)
    user = await get_user_by_telegram_id(session, telegram_id)
    if user is None:
        return main_menu(False)
    trader = await session.get(Trader, user.id)
    if trader is None:
        return main_menu(False)
    return main_menu(True, online=bool(trader.is_online))
