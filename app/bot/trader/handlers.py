import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.common.ui import clear_inline, edit_or_send, inline_with_back
from app.bot.menus import menu_for
from app.bot.trader.keyboards import (
    dispute_skip_keyboard,
    order_id_from_callback,
    trader_order_keyboard,
    trader_orders_keyboard,
)
from app.bot.trader.states import DisputeFlow, SbpFlow, WithdrawFlow
from app.bot.trader.texts import (
    DISPUTE_NOTE,
    DISPUTE_OPEN,
    DISPUTE_SAVED,
    EMPTY_TRADER_ORDERS,
    MENU_ACTIVE,
    MENU_BALANCE,
    MENU_OFFLINE,
    MENU_ONLINE,
    MENU_SBP,
    MENU_STATS,
    MENU_WITHDRAW,
    SBP_BANK_PROMPT,
    SBP_HOLDER_PROMPT,
    TRADER_ONLY,
    TRADER_ORDERS_PAGE,
    WITHDRAW_BAD_AMOUNT,
    WITHDRAW_SENT,
    format_balance,
    format_online,
    format_sbp,
    format_stats,
    format_trader_order,
    format_trader_orders,
    withdraw_prompt,
)
from app.config import bitcoin_network, wallet_backend
from app.formatting import esc, html_card, status_label
from app.disputes.service import EvidenceInput, add_dispute_evidence, open_dispute
from app.models import Order, OrderStatus
from app.ledger.service import trader_balances
from app.orders.payment import ConfirmTooEarly, NotOrderTrader, confirm_receipt
from app.wallets.deposits import ensure_deposit_address
from app.wallets.errors import PayoutBroadcastError, WalletError
from app.wallets.factory import get_wallet_adapter
from app.orders.service import IllegalOrderTransition
from app.routing.service import ALREADY_TAKEN_TEXT, AcceptExpired, NotEligible, OrderAlreadyTaken, accept_order
from app.traders.service import (
    InvalidPaymentMethod,
    NeedSbp,
    TraderNotActive,
    WithdrawalRejected,
    active_sbp,
    get_trader,
    list_active_orders,
    request_withdrawal,
    save_sbp,
    set_online,
    trader_stats,
)
from app.users.service import get_user_by_telegram_id

router = Router(name="trader")


async def _known_user(session: AsyncSession, telegram_id: int):
    return await get_user_by_telegram_id(session, telegram_id)


@router.message(F.text == MENU_BALANCE)
async def menu_balance(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    if message.from_user is None:
        return
    user = await _known_user(session, message.from_user.id)
    trader = None if user is None else await get_trader(session, user.id)
    if user is None or trader is None:
        await message.answer(TRADER_ONLY)
        return
    balances = await trader_balances(session, user.id)
    deposit_address = None
    address_note = None
    if wallet_backend() == "electrum" and str(trader.status) == "active":
        try:
            deposit_address = await ensure_deposit_address(session, user.id, get_wallet_adapter())
        except WalletError:
            network = bitcoin_network().strip().lower()
            if network == "testnet":
                address_note = "Адрес пополнения testnet сейчас недоступен."
            elif network == "mainnet":
                address_note = "Адрес пополнения mainnet сейчас недоступен."
            else:
                address_note = "Адрес пополнения сейчас недоступен."
    text = format_balance(balances, deposit_address)
    if address_note:
        text = f"{text}\n{address_note}"
    await message.answer(text, reply_markup=await menu_for(session, message.from_user.id))


@router.message(F.text.in_({MENU_ONLINE, MENU_OFFLINE}))
async def menu_online(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    if message.from_user is None:
        return
    user = await _known_user(session, message.from_user.id)
    trader = None if user is None else await get_trader(session, user.id)
    if user is None or trader is None:
        await message.answer(TRADER_ONLY)
        return
    try:
        updated = await set_online(session, user.id, not trader.is_online)
    except (NeedSbp, TraderNotActive) as exc:
        await message.answer(html_card("Линия", esc(str(exc))), reply_markup=await menu_for(session, message.from_user.id))
        return
    await message.answer(format_online(updated.is_online), reply_markup=await menu_for(session, message.from_user.id))


@router.message(F.text == MENU_ACTIVE)
async def menu_active(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    if message.from_user is None:
        return
    user = await _known_user(session, message.from_user.id)
    trader = None if user is None else await get_trader(session, user.id)
    if user is None or trader is None:
        await message.answer(TRADER_ONLY)
        return
    orders = (await list_active_orders(session, user.id))[:TRADER_ORDERS_PAGE]
    markup = await menu_for(session, message.from_user.id)
    if not orders:
        await message.answer(EMPTY_TRADER_ORDERS, reply_markup=markup)
        return
    await message.answer(format_trader_orders(orders), reply_markup=trader_orders_keyboard(orders))


@router.message(F.text == MENU_STATS)
async def menu_stats(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    if message.from_user is None:
        return
    user = await _known_user(session, message.from_user.id)
    trader = None if user is None else await get_trader(session, user.id)
    if user is None or trader is None:
        await message.answer(TRADER_ONLY)
        return
    stats = await trader_stats(session, user.id)
    await message.answer(format_stats(stats), reply_markup=await menu_for(session, message.from_user.id))


@router.message(F.text == MENU_SBP)
async def menu_sbp(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if message.from_user is None:
        return
    user = await _known_user(session, message.from_user.id)
    trader = None if user is None else await get_trader(session, user.id)
    if user is None or trader is None:
        await state.clear()
        await message.answer(TRADER_ONLY)
        return
    method = await active_sbp(session, user.id)
    await state.set_state(SbpFlow.phone)
    await message.answer(format_sbp(method))


@router.message(SbpFlow.phone, F.text, ~F.text.startswith("/"))
async def sbp_phone(message: Message, state: FSMContext) -> None:
    await state.update_data(phone=message.text or "")
    await state.set_state(SbpFlow.bank)
    await message.answer(SBP_BANK_PROMPT)


@router.message(SbpFlow.bank, F.text, ~F.text.startswith("/"))
async def sbp_bank(message: Message, state: FSMContext) -> None:
    await state.update_data(bank=message.text or "")
    await state.set_state(SbpFlow.holder)
    await message.answer(SBP_HOLDER_PROMPT)


@router.message(SbpFlow.holder, F.text, ~F.text.startswith("/"))
async def sbp_holder(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if message.from_user is None:
        return
    user = await _known_user(session, message.from_user.id)
    if user is None:
        await state.clear()
        return
    data = await state.get_data()
    try:
        method = await save_sbp(
            session,
            user.id,
            phone=str(data.get("phone") or ""),
            bank_name=str(data.get("bank") or ""),
            holder_name=message.text or "",
        )
    except InvalidPaymentMethod as exc:
        await state.set_state(SbpFlow.phone)
        await message.answer(html_card("Реквизиты", esc(str(exc))))
        return
    await state.clear()
    await message.answer(format_sbp(method), reply_markup=await menu_for(session, user.telegram_id))


@router.message(F.text == MENU_WITHDRAW)
async def menu_withdraw(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if message.from_user is None:
        return
    user = await _known_user(session, message.from_user.id)
    trader = None if user is None else await get_trader(session, user.id)
    if user is None or trader is None:
        await state.clear()
        await message.answer(TRADER_ONLY)
        return
    balances = await trader_balances(session, user.id)
    await state.set_state(WithdrawFlow.amount)
    await message.answer(withdraw_prompt(balances.available_sats))


@router.message(WithdrawFlow.amount, F.text, ~F.text.startswith("/"))
async def withdraw_amount(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if message.from_user is None:
        return
    user = await _known_user(session, message.from_user.id)
    if user is None:
        await state.clear()
        return
    from decimal import Decimal, ROUND_HALF_UP

    raw = (message.text or "").replace(",", ".").replace(" ", "")
    try:
        btc = Decimal(raw)
        sats = int((btc * Decimal(100_000_000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except Exception:
        await message.answer(WITHDRAW_BAD_AMOUNT)
        return
    try:
        await request_withdrawal(session, user.id, sats)
    except WithdrawalRejected as exc:
        await message.answer(html_card("Вывод", esc(str(exc))))
        return
    await state.clear()
    await message.answer(WITHDRAW_SENT, reply_markup=await menu_for(session, user.telegram_id))


@router.callback_query(F.data.startswith("accept:"))
async def on_accept(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        await callback.answer()
        return
    user = await _known_user(session, callback.from_user.id)
    if user is None or await get_trader(session, user.id) is None:
        await callback.answer("Раздел доступен трейдеру.", show_alert=True)
        return
    try:
        order_id = order_id_from_callback(callback.data, "accept:")
        order = await accept_order(session, order_id=order_id, trader_user_id=user.id)
        await session.commit()
    except OrderAlreadyTaken:
        await session.rollback()
        await callback.answer(ALREADY_TAKEN_TEXT, show_alert=True)
        await edit_or_send(callback, html_card("Заявка", esc(ALREADY_TAKEN_TEXT)), clear_inline())
        return
    except AcceptExpired as exc:
        await session.rollback()
        line = str(exc).splitlines()[0]
        await callback.answer(line, show_alert=True)
        await edit_or_send(callback, html_card("Заявка", esc(line)), clear_inline())
        return
    except NotEligible as exc:
        await session.rollback()
        await callback.answer(str(exc).splitlines()[0], show_alert=True)
        return
    except (LookupError, ValueError):
        await session.rollback()
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    await callback.answer("Заявка принята")
    await edit_or_send(
        callback,
        html_card(
            f"Заявка №{order.public_no}",
            f"{status_label(OrderStatus.WAITING_PAYMENT)}\nРеквизиты ушли клиенту.",
        ),
        clear_inline(),
    )


@router.callback_query(F.data.startswith("confirm:"))
async def on_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        await callback.answer()
        return
    user = await _known_user(session, callback.from_user.id)
    if user is None:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return
    try:
        order_id = order_id_from_callback(callback.data, "confirm:")
        order = await confirm_receipt(session, order_id=order_id, trader_id=user.id)
        await session.commit()
    except PayoutBroadcastError as exc:
        network = bitcoin_network().strip().lower() or "testnet"
        await callback.answer("Выплата не ушла.", show_alert=True)
        await edit_or_send(
            callback,
            html_card(
                f"Заявка №{exc.public_no}",
                f"{status_label(OrderStatus.RELEASING)}\n"
                f"Сеть: {esc(network)}.\n"
                "Заморозка на месте: сатоши не вернулись и второй раз не списываются.",
            ),
            clear_inline(),
        )
        return
    except ConfirmTooEarly as exc:
        await session.rollback()
        await callback.answer(str(exc).splitlines()[0], show_alert=True)
        return
    except NotOrderTrader as exc:
        await session.rollback()
        await callback.answer(str(exc).splitlines()[0], show_alert=True)
        return
    except IllegalOrderTransition:
        await session.rollback()
        await callback.answer("Сейчас это действие недоступно.", show_alert=True)
        return
    except (LookupError, ValueError):
        await session.rollback()
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    await callback.answer("Оплата подтверждена")
    if order.payout_wallet_tx_id is None:
        done = html_card(
            f"Заявка №{order.public_no}",
            f"{status_label(OrderStatus.COMPLETED)}\nВ сеть не отправляли.",
        )
    else:
        network = bitcoin_network().strip().lower() or "testnet"
        done = html_card(
            f"Заявка №{order.public_no}",
            f"{status_label(OrderStatus.COMPLETED)}\nСеть: {esc(network)}",
        )
    await edit_or_send(callback, done, clear_inline())


@router.callback_query(F.data.startswith("dispute:"))
async def on_dispute(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if callback.from_user is None or callback.data is None:
        await callback.answer()
        return
    if callback.data == "dispute:skip":
        await state.clear()
        await callback.answer()
        await edit_or_send(callback, html_card("Спор", "Эскроу заморожен."), clear_inline())
        return
    user = await _known_user(session, callback.from_user.id)
    if user is None:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return
    try:
        order_id = order_id_from_callback(callback.data, "dispute:")
        await open_dispute(session, order_id=order_id, trader_user_id=user.id, reason="спор")
        await session.commit()
    except NotOrderTrader as exc:
        await session.rollback()
        await callback.answer(str(exc).splitlines()[0], show_alert=True)
        return
    except IllegalOrderTransition:
        await session.rollback()
        await callback.answer("Сейчас это действие недоступно.", show_alert=True)
        return
    except (LookupError, ValueError):
        await session.rollback()
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    await state.set_state(DisputeFlow.evidence)
    await state.update_data(order_id=str(order_id))
    await callback.answer("Спор открыт")
    await edit_or_send(callback, DISPUTE_OPEN, dispute_skip_keyboard())


async def _trader_orders_view(session: AsyncSession, user_id: uuid.UUID):
    orders = (await list_active_orders(session, user_id))[:TRADER_ORDERS_PAGE]
    if not orders:
        return EMPTY_TRADER_ORDERS, clear_inline()
    return format_trader_orders(orders), trader_orders_keyboard(orders) or clear_inline()


@router.callback_query(F.data == "torders:back")
async def trader_orders_back(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None:
        await callback.answer()
        return
    user = await _known_user(session, callback.from_user.id)
    trader = None if user is None else await get_trader(session, user.id)
    if user is None or trader is None:
        await callback.answer("Раздел доступен трейдеру.", show_alert=True)
        return
    text, keyboard = await _trader_orders_view(session, user.id)
    await callback.answer()
    await edit_or_send(callback, text, keyboard)


@router.callback_query(F.data.startswith("tord:"))
async def open_trader_order(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        await callback.answer()
        return
    user = await _known_user(session, callback.from_user.id)
    trader = None if user is None else await get_trader(session, user.id)
    if user is None or trader is None:
        await callback.answer("Раздел доступен трейдеру.", show_alert=True)
        return
    try:
        order_id = order_id_from_callback(callback.data, "tord:")
    except ValueError:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    order = await session.get(Order, order_id)
    if order is None or order.trader_id != user.id:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    await callback.answer()
    await edit_or_send(
        callback,
        format_trader_order(order),
        inline_with_back(trader_order_keyboard(order), "torders:back"),
    )


@router.message(DisputeFlow.evidence, F.photo)
async def dispute_photo(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if message.from_user is None or not message.photo:
        return
    data = await state.get_data()
    raw_id = data.get("order_id")
    if not isinstance(raw_id, str):
        await state.clear()
        return
    user = await _known_user(session, message.from_user.id)
    if user is None:
        await state.clear()
        return
    file_id = message.photo[-1].file_id
    await add_dispute_evidence(
        session,
        order_id=uuid.UUID(raw_id),
        user_id=user.id,
        evidence=EvidenceInput(telegram_file_id=file_id, kind="screenshot"),
        reason=message.caption,
    )
    await state.clear()
    await message.answer(DISPUTE_SAVED, reply_markup=await menu_for(session, user.telegram_id))


@router.message(DisputeFlow.evidence, F.text, ~F.text.startswith("/"))
async def dispute_text(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if message.from_user is None:
        return
    data = await state.get_data()
    raw_id = data.get("order_id")
    if not isinstance(raw_id, str):
        await state.clear()
        return
    user = await _known_user(session, message.from_user.id)
    if user is None:
        await state.clear()
        return
    marker = f"text:{message.message_id}"
    await add_dispute_evidence(
        session,
        order_id=uuid.UUID(raw_id),
        user_id=user.id,
        evidence=EvidenceInput(telegram_file_id=marker, kind="text"),
        reason=message.text,
    )
    await state.clear()
    await message.answer(DISPUTE_NOTE, reply_markup=await menu_for(session, user.telegram_id))
