import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.menus import menu_for
from app.bot.trader.keyboards import dispute_skip_keyboard, order_id_from_callback, trader_order_keyboard
from app.bot.trader.states import DisputeFlow, SbpFlow, WithdrawFlow
from app.bot.trader.texts import (
    MENU_ACTIVE,
    MENU_BALANCE,
    MENU_ONLINE,
    MENU_SBP,
    MENU_STATS,
    MENU_TIER,
    MENU_WITHDRAW,
    format_balance,
    format_online,
    format_sbp,
    format_stats,
    format_tier,
    format_trader_order,
)
from app.config import wallet_backend
from app.disputes.service import EvidenceInput, add_dispute_evidence, open_dispute
from app.ledger.service import trader_balances
from app.orders.payment import ConfirmTooEarly, NotOrderTrader, confirm_receipt
from app.wallets.deposits import ensure_deposit_address
from app.wallets.errors import PayoutBroadcastError, WalletError
from app.wallets.factory import get_wallet_adapter
from app.orders.service import IllegalOrderTransition
from app.routing.service import AcceptExpired, NotEligible, OrderAlreadyTaken, accept_order
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
        await message.answer("Раздел доступен трейдеру.")
        return
    balances = await trader_balances(session, user.id)
    deposit_address = None
    address_note = None
    if wallet_backend() == "electrum" and str(trader.status) == "active":
        try:
            deposit_address = await ensure_deposit_address(session, user.id, get_wallet_adapter())
        except WalletError:
            address_note = "Адрес пополнения testnet сейчас недоступен."
    text = format_balance(balances, deposit_address)
    if address_note:
        text = f"{text}\n{address_note}"
    await message.answer(text, reply_markup=await menu_for(session, message.from_user.id))


@router.message(F.text == MENU_ONLINE)
async def menu_online(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    if message.from_user is None:
        return
    user = await _known_user(session, message.from_user.id)
    trader = None if user is None else await get_trader(session, user.id)
    if user is None or trader is None:
        await message.answer("Раздел доступен трейдеру.")
        return
    try:
        updated = await set_online(session, user.id, not trader.is_online)
    except (NeedSbp, TraderNotActive) as exc:
        await message.answer(str(exc), reply_markup=await menu_for(session, message.from_user.id))
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
        await message.answer("Раздел доступен трейдеру.")
        return
    orders = await list_active_orders(session, user.id)
    markup = await menu_for(session, message.from_user.id)
    if not orders:
        await message.answer("Активных заявок нет.", reply_markup=markup)
        return
    await message.answer("Активные заявки", reply_markup=markup)
    for order in orders:
        await message.answer(format_trader_order(order), reply_markup=trader_order_keyboard(order))


@router.message(F.text == MENU_STATS)
async def menu_stats(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    if message.from_user is None:
        return
    user = await _known_user(session, message.from_user.id)
    trader = None if user is None else await get_trader(session, user.id)
    if user is None or trader is None:
        await message.answer("Раздел доступен трейдеру.")
        return
    stats = await trader_stats(session, user.id)
    await message.answer(format_stats(stats), reply_markup=await menu_for(session, message.from_user.id))


@router.message(F.text == MENU_TIER)
async def menu_tier(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    if message.from_user is None:
        return
    user = await _known_user(session, message.from_user.id)
    trader = None if user is None else await get_trader(session, user.id)
    if user is None or trader is None:
        await message.answer("Раздел доступен трейдеру.")
        return
    await message.answer(format_tier(trader), reply_markup=await menu_for(session, message.from_user.id))


@router.message(F.text == MENU_SBP)
async def menu_sbp(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if message.from_user is None:
        return
    user = await _known_user(session, message.from_user.id)
    trader = None if user is None else await get_trader(session, user.id)
    if user is None or trader is None:
        await state.clear()
        await message.answer("Раздел доступен трейдеру.")
        return
    method = await active_sbp(session, user.id)
    await state.set_state(SbpFlow.phone)
    await message.answer(format_sbp(method))


@router.message(SbpFlow.phone, F.text, ~F.text.startswith("/"))
async def sbp_phone(message: Message, state: FSMContext) -> None:
    await state.update_data(phone=message.text or "")
    await state.set_state(SbpFlow.bank)
    await message.answer("Введите название банка. Бот его не определяет.")


@router.message(SbpFlow.bank, F.text, ~F.text.startswith("/"))
async def sbp_bank(message: Message, state: FSMContext) -> None:
    await state.update_data(bank=message.text or "")
    await state.set_state(SbpFlow.holder)
    await message.answer("Введите имя получателя.")


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
        await message.answer(str(exc))
        return
    await state.clear()
    await message.answer("Реквизиты СБП сохранены.\n" + format_sbp(method), reply_markup=await menu_for(session, user.telegram_id))


@router.message(F.text == MENU_WITHDRAW)
async def menu_withdraw(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if message.from_user is None:
        return
    user = await _known_user(session, message.from_user.id)
    trader = None if user is None else await get_trader(session, user.id)
    if user is None or trader is None:
        await state.clear()
        await message.answer("Раздел доступен трейдеру.")
        return
    balances = await trader_balances(session, user.id)
    await state.set_state(WithdrawFlow.amount)
    await message.answer(
        "Введите сумму вывода в BTC, например 0.01.\n"
        f"Доступно: {format_balance(balances).splitlines()[1]}\n"
        "Это заявка оператору. Автовыплаты нет."
    )


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
        await message.answer("Введите сумму в BTC, например 0.01.")
        return
    try:
        await request_withdrawal(session, user.id, sats)
    except WithdrawalRejected as exc:
        await message.answer(str(exc))
        return
    await state.clear()
    await message.answer(
        "Заявка на вывод отправлена оператору. Автовыплаты нет.",
        reply_markup=await menu_for(session, user.telegram_id),
    )


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
    except OrderAlreadyTaken as exc:
        await session.rollback()
        await callback.answer(str(exc), show_alert=True)
        return
    except AcceptExpired as exc:
        await session.rollback()
        await callback.answer(str(exc), show_alert=True)
        return
    except NotEligible as exc:
        await session.rollback()
        await callback.answer(str(exc), show_alert=True)
        return
    except (LookupError, ValueError):
        await session.rollback()
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    await callback.answer("Заявка принята")
    if callback.message is not None:
        await callback.message.answer(f"Заявка №{order.public_no} ваша. Ждём оплату клиента.")


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
        await callback.answer("Выплата не отправлена", show_alert=True)
        if callback.message is not None:
            await callback.message.answer(str(exc))
        return
    except ConfirmTooEarly as exc:
        await session.rollback()
        await callback.answer(str(exc), show_alert=True)
        return
    except (NotOrderTrader, IllegalOrderTransition) as exc:
        await session.rollback()
        await callback.answer(str(exc), show_alert=True)
        return
    except (LookupError, ValueError):
        await session.rollback()
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    await callback.answer("Оплата подтверждена")
    if callback.message is not None:
        if order.payout_wallet_tx_id is None:
            done = f"Заявка №{order.public_no} завершена. Отправка в сеть в этой версии не выполняется."
        else:
            done = f"Заявка №{order.public_no} завершена. Выплата отправлена в testnet."
        await callback.message.answer(done)


@router.callback_query(F.data.startswith("dispute:"))
async def on_dispute(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if callback.from_user is None or callback.data is None:
        await callback.answer()
        return
    if callback.data == "dispute:skip":
        await state.clear()
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer("Спор открыт. Эскроу остаётся замороженным.")
        return
    user = await _known_user(session, callback.from_user.id)
    if user is None:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return
    try:
        order_id = order_id_from_callback(callback.data, "dispute:")
        await open_dispute(session, order_id=order_id, trader_user_id=user.id, reason="спор")
        await session.commit()
    except (NotOrderTrader, IllegalOrderTransition) as exc:
        await session.rollback()
        await callback.answer(str(exc), show_alert=True)
        return
    except (LookupError, ValueError):
        await session.rollback()
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    await state.set_state(DisputeFlow.evidence)
    await state.update_data(order_id=str(order_id))
    await callback.answer("Спор открыт")
    if callback.message is not None:
        await callback.message.answer(
            "Спор открыт. Эскроу остаётся замороженным. "
            "Пришлите текст или скриншот, либо нажмите «Без вложения». "
            "Скриншот не подтверждает оплату.",
            reply_markup=dispute_skip_keyboard(),
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
    await message.answer(
        "Вложение сохранено. Оплата не подтверждена.",
        reply_markup=await menu_for(session, user.telegram_id),
    )


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
    await message.answer(
        "Комментарий сохранён. Оплата не подтверждена.",
        reply_markup=await menu_for(session, user.telegram_id),
    )
