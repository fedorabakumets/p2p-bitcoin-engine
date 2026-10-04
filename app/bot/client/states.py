from aiogram.fsm.state import State, StatesGroup


class BuyFlow(StatesGroup):
    amount = State()
    address = State()
    confirm = State()
