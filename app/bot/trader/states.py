from aiogram.fsm.state import State, StatesGroup


class SbpFlow(StatesGroup):
    phone = State()
    bank = State()
    holder = State()


class WithdrawFlow(StatesGroup):
    amount = State()


class DisputeFlow(StatesGroup):
    evidence = State()
