from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.client.keyboards import client_order_keyboard
from app.bot.menus import menu_for
from app.bot.trader.keyboards import order_id_from_callback
from app.orders.payment import CancelNotAllowed, NotOrderClient, cancel_by_client, mark_client_paid
from app.orders.service import IllegalOrderTransition
from app.users.service import get_user_by_telegram_id

router = Router(name="client-payments")


@router.callback_query(F.data.startswith("pay:"))
async def on_paid(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        await callback.answer()
        return
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user is None:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return
    try:
        order_id = order_id_from_callback(callback.data, "pay:")
        order = await mark_client_paid(session, order_id=order_id, client_id=user.id)
        await session.commit()
    except NotOrderClient as exc:
        await session.rollback()
        await callback.answer(str(exc), show_alert=True)
        return
    except (IllegalOrderTransition, LookupError, ValueError):
        await session.rollback()
        await callback.answer("Сейчас отметить оплату нельзя.", show_alert=True)
        return
    await callback.answer("Оплата отмечена")
    if callback.message is not None:
        await callback.message.answer(
            f"Заявка №{order.public_no}: оплата отмечена. Отменить её больше нельзя.",
            reply_markup=await menu_for(session, callback.from_user.id),
        )


@router.callback_query(F.data.startswith("cancel:"))
async def on_cancel(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        await callback.answer()
        return
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user is None:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return
    try:
        order_id = order_id_from_callback(callback.data, "cancel:")
        order = await cancel_by_client(session, order_id=order_id, client_id=user.id)
        await session.commit()
    except (CancelNotAllowed, NotOrderClient) as exc:
        await session.rollback()
        await callback.answer(str(exc), show_alert=True)
        return
    except (IllegalOrderTransition, LookupError, ValueError):
        await session.rollback()
        await callback.answer("Эту заявку отменить нельзя.", show_alert=True)
        return
    await callback.answer("Заявка отменена")
    if callback.message is not None:
        await callback.message.answer(
            f"Заявка №{order.public_no} отменена.",
            reply_markup=client_order_keyboard(order) or await menu_for(session, callback.from_user.id),
        )
