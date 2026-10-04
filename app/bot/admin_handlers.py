from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.service import CreditUsage, NotAdmin, apply_credit_command, apply_resolve_command
from app.bot.menus import menu_for

router = Router(name="admin")


@router.message(Command("credit"))
async def cmd_credit(message: Message, command: CommandObject, session: AsyncSession) -> None:
    if message.from_user is None:
        return
    try:
        text = await apply_credit_command(
            session,
            admin_telegram_id=message.from_user.id,
            args=command.args or "",
        )
        await session.commit()
    except NotAdmin:
        await session.rollback()
        await message.answer("Команда доступна только администратору.")
        return
    except CreditUsage as exc:
        await session.rollback()
        await message.answer(str(exc))
        return
    except LookupError:
        await session.rollback()
        await message.answer("Пользователь не найден.")
        return
    await message.answer(text, reply_markup=await menu_for(session, message.from_user.id))


@router.message(Command("resolve"))
async def cmd_resolve(message: Message, command: CommandObject, session: AsyncSession) -> None:
    if message.from_user is None:
        return
    try:
        text = await apply_resolve_command(
            session,
            admin_telegram_id=message.from_user.id,
            args=command.args or "",
        )
        await session.commit()
    except NotAdmin:
        await session.rollback()
        await message.answer("Команда доступна только администратору.")
        return
    except CreditUsage as exc:
        await session.rollback()
        await message.answer(str(exc))
        return
    except LookupError:
        await session.rollback()
        await message.answer("Заявка не найдена.")
        return
    await message.answer(text, reply_markup=await menu_for(session, message.from_user.id))
