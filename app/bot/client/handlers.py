from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User as TelegramUser
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.client.amount import parse_rub_to_kop
from app.bot.client.keyboards import client_order_keyboard, confirm_keyboard, searching_keyboard
from app.bot.client.states import BuyFlow
from app.bot.client.texts import (
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
    address_prompt,
    address_retry_text,
    format_orders,
    format_partner,
    format_quote,
    format_searching,
)
from app.bot.menus import menu_for
from app.bot.runtime import get_bot_username
from app.config import bitcoin_network
from app.models import TraderPaymentMethod
from app.notifications.messages import client_payment_text
from app.orders.service import InvalidBtcAddress, QuoteExpired, list_client_orders, open_searching_order
from app.pricing.formula import PricingError, QuoteSnapshot
from app.pricing.rates import EnvRateSource
from app.pricing.service import PricingService
from app.referrals.service import partner_summary
from app.users.service import UserBlocked, get_user_by_telegram_id, register_from_start
from app.wallets.btc_address import is_btc_address_for_network

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
    await message.answer(MAIN_MENU_TEXT, reply_markup=await menu_for(session, message.from_user.id))


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
    markup = await menu_for(session, message.from_user.id)
    await message.answer(format_orders(orders), reply_markup=markup)
    for order in orders:
        keyboard = client_order_keyboard(order)
        if keyboard is None:
            continue
        details = f"Заявка №{order.public_no}"
        if order.payment_method_id is not None and str(order.status) == "WAITING_PAYMENT":
            method = await session.get(TraderPaymentMethod, order.payment_method_id)
            if method is not None:
                details = client_payment_text(order, method)
        await message.answer(details, reply_markup=keyboard)


@router.message(F.text == MENU_PARTNER)
async def menu_partner(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    user = await _ensure_user(message, session)
    if user is None:
        return
    summary = await partner_summary(session, user.id)
    await message.answer(
        format_partner(
            code=user.referral_code,
            bot_username=get_bot_username(),
            invited=summary.invited,
            completed_invitees=summary.completed_invitees,
            turnover_rub_kop=summary.turnover_rub_kop,
            earned_sats=summary.earned_sats,
            available_sats=summary.available_sats,
            snapshot_rub_kop=summary.snapshot_rub_kop,
            estimate_rub_kop=summary.estimate_rub_kop,
        ),
        reply_markup=await menu_for(session, message.from_user.id),
    )


@router.message(F.text == MENU_SUPPORT)
async def menu_support(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    markup = await menu_for(session, None if message.from_user is None else message.from_user.id)
    await message.answer(SUPPORT_TEXT, reply_markup=markup)


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
    await message.answer(address_prompt(bitcoin_network()))


@router.message(BuyFlow.address)
async def buy_address(message: Message, session: AsyncSession, state: FSMContext) -> None:
    address = (message.text or "").strip()
    network = bitcoin_network()
    if not is_btc_address_for_network(address, network):
        await message.answer(address_retry_text(address, network))
        return
    data = await state.get_data()
    principal = data.get("principal_rub_kop")
    if not isinstance(principal, int):
        await state.clear()
        await message.answer(AMOUNT_PROMPT, reply_markup=await menu_for(session, message.from_user.id if message.from_user else None))
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
async def buy_cancel(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await _reply(callback, session, CANCELLED_TEXT)


@router.callback_query(BuyFlow.confirm, F.data == "buy:confirm")
async def buy_confirm(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    raw_snapshot = data.get("snapshot")
    address = data.get("address")
    if not isinstance(raw_snapshot, dict) or not isinstance(address, str):
        await state.clear()
        await callback.answer()
        await _reply(callback, session, QUOTE_EXPIRED)
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
        await _reply(callback, session, QUOTE_EXPIRED)
        return
    except UserBlocked:
        await state.clear()
        await session.rollback()
        await callback.answer()
        await _reply(callback, session, BLOCKED_TEXT)
        return
    except InvalidBtcAddress:
        await state.clear()
        await session.rollback()
        await callback.answer()
        await _reply(callback, session, address_retry_text(address, bitcoin_network()))
        return
    except (PricingError, ValueError):
        await state.clear()
        await session.rollback()
        await callback.answer()
        await _reply(callback, session, QUOTE_EXPIRED)
        return
    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(format_searching(order.public_no), reply_markup=searching_keyboard(order.id))
    elif callback.from_user is not None:
        await callback.bot.send_message(
            callback.from_user.id,
            format_searching(order.public_no),
            reply_markup=searching_keyboard(order.id),
        )


@router.message(StateFilter(None))
async def fallback(message: Message, session: AsyncSession) -> None:
    telegram_id = None if message.from_user is None else message.from_user.id
    await message.answer("Выберите пункт меню.", reply_markup=await menu_for(session, telegram_id))


async def _reply(callback: CallbackQuery, session: AsyncSession, text: str) -> None:
    telegram_id = None if callback.from_user is None else callback.from_user.id
    markup = await menu_for(session, telegram_id)
    if callback.message is not None:
        await callback.message.answer(text, reply_markup=markup)
    elif callback.from_user is not None:
        await callback.bot.send_message(callback.from_user.id, text, reply_markup=markup)
