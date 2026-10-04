from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User as TelegramUser
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.client.amount import parse_rub_to_kop
from app.bot.client.keyboards import confirm_keyboard, main_menu
from app.bot.client.states import BuyFlow
from app.bot.client.texts import (
    ADDRESS_PROMPT,
    ADDRESS_RETRY,
    AMOUNT_PROMPT,
    AMOUNT_RETRY,
    AMOUNT_TOO_SMALL,
    BLOCKED_TEXT,
    CANCELLED_TEXT,
    MAIN_MENU_TEXT,
    MENU_BUY,
    MENU_ORDERS,
    MENU_PARTNER,
    MENU_SUPPORT,
    QUOTE_EXPIRED,
    SUPPORT_TEXT,
    format_orders,
    format_partner,
    format_quote,
    format_searching,
)
from app.bot.runtime import get_bot_username
from app.orders.service import InvalidBtcAddress, QuoteExpired, open_searching_order
from app.orders.service import list_client_orders
from app.pricing.formula import PricingError, QuoteSnapshot
from app.pricing.rates import EnvRateSource
from app.pricing.service import PricingService
from app.users.service import UserBlocked, get_user_by_telegram_id, invited_count, register_from_start
from app.wallets.btc_address import is_btc_mainnet_address

router = Router(name="client")


def _pricing() -> PricingService:
    return PricingService(EnvRateSource())


def _display_name(user: TelegramUser) -> str | None:
    parts = [user.first_name or "", user.last_name or ""]
    name = " ".join(part for part in parts if part).strip()
    return name or None


def _blocked(user: object) -> bool:
    return str(getattr(user, "status", "")) == "blocked"


async def _ensure_user(message: Message, session: AsyncSession):
    if message.from_user is None:
        return None
    user = await get_user_by_telegram_id(session, message.from_user.id)
    if user is None:
        user = await register_from_start(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            display_name=_display_name(message.from_user),
            start_payload=None,
        )
    return user


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    if message.from_user is None:
        return
    user = await register_from_start(
        session,
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        display_name=_display_name(message.from_user),
        start_payload=command.args,
    )
    if _blocked(user):
        await message.answer(BLOCKED_TEXT)
        return
    await message.answer(MAIN_MENU_TEXT, reply_markup=main_menu())


@router.message(F.text == MENU_BUY)
async def menu_buy(message: Message, session: AsyncSession, state: FSMContext) -> None:
    user = await _ensure_user(message, session)
    if user is None:
        return
    if _blocked(user):
        await message.answer(BLOCKED_TEXT)
        return
    await state.set_state(BuyFlow.amount)
    await message.answer(AMOUNT_PROMPT)


@router.message(F.text == MENU_ORDERS)
async def menu_orders(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    user = await _ensure_user(message, session)
    if user is None:
        return
    orders = await list_client_orders(session, user.id)
    await message.answer(format_orders(orders), reply_markup=main_menu())


@router.message(F.text == MENU_PARTNER)
async def menu_partner(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    user = await _ensure_user(message, session)
    if user is None:
        return
    invited = await invited_count(session, user.id)
    await message.answer(
        format_partner(code=user.referral_code, bot_username=get_bot_username(), invited=invited),
        reply_markup=main_menu(),
    )


@router.message(F.text == MENU_SUPPORT)
async def menu_support(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(SUPPORT_TEXT, reply_markup=main_menu())


@router.message(BuyFlow.confirm)
async def buy_confirm_text(message: Message) -> None:
    await message.answer("Нажмите «Продолжить» или «Отмена».")


@router.message(BuyFlow.amount)
async def buy_amount(message: Message, state: FSMContext) -> None:
    try:
        kopecks = parse_rub_to_kop(message.text or "")
    except ValueError:
        await message.answer(AMOUNT_RETRY)
        return
    await state.update_data(principal_rub_kop=kopecks)
    await state.set_state(BuyFlow.address)
    await message.answer(ADDRESS_PROMPT)


@router.message(BuyFlow.address)
async def buy_address(message: Message, session: AsyncSession, state: FSMContext) -> None:
    address = (message.text or "").strip()
    if not is_btc_mainnet_address(address):
        await message.answer(ADDRESS_RETRY)
        return
    data = await state.get_data()
    principal = data.get("principal_rub_kop")
    if not isinstance(principal, int):
        await state.clear()
        await message.answer(AMOUNT_PROMPT, reply_markup=main_menu())
        await state.set_state(BuyFlow.amount)
        return
    try:
        snapshot = await _pricing().quote(session, principal)
    except PricingError:
        await message.answer(AMOUNT_TOO_SMALL)
        return
    await state.update_data(address=address, snapshot=snapshot.to_dict())
    await state.set_state(BuyFlow.confirm)
    await message.answer(format_quote(snapshot), reply_markup=confirm_keyboard())


@router.callback_query(BuyFlow.confirm, F.data == "buy:cancel")
async def buy_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await _reply(callback, CANCELLED_TEXT)


@router.callback_query(BuyFlow.confirm, F.data == "buy:confirm")
async def buy_confirm(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    raw_snapshot = data.get("snapshot")
    address = data.get("address")
    if not isinstance(raw_snapshot, dict) or not isinstance(address, str):
        await state.clear()
        await callback.answer()
        await _reply(callback, QUOTE_EXPIRED)
        return
    snapshot = QuoteSnapshot.from_dict(raw_snapshot)
    if callback.from_user is None:
        await callback.answer()
        return
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user is None:
        user = await register_from_start(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            display_name=_display_name(callback.from_user),
            start_payload=None,
        )
    try:
        order = await open_searching_order(
            session,
            user_id=user.id,
            snapshot=snapshot,
            btc_address=address,
        )
        await session.commit()
    except QuoteExpired:
        await state.clear()
        await session.rollback()
        await callback.answer()
        await _reply(callback, QUOTE_EXPIRED)
        return
    except UserBlocked:
        await state.clear()
        await session.rollback()
        await callback.answer()
        await _reply(callback, BLOCKED_TEXT)
        return
    except InvalidBtcAddress:
        await state.clear()
        await session.rollback()
        await callback.answer()
        await _reply(callback, ADDRESS_RETRY)
        return
    except (PricingError, ValueError):
        await state.clear()
        await session.rollback()
        await callback.answer()
        await _reply(callback, QUOTE_EXPIRED)
        return
    await state.clear()
    await callback.answer()
    await _reply(callback, format_searching(order.public_no))


@router.message(StateFilter(None))
async def fallback(message: Message) -> None:
    await message.answer("Выберите пункт меню.", reply_markup=main_menu())


async def _reply(callback: CallbackQuery, text: str) -> None:
    if callback.message is not None:
        await callback.message.answer(text, reply_markup=main_menu())
    elif callback.from_user is not None:
        await callback.bot.send_message(callback.from_user.id, text, reply_markup=main_menu())
