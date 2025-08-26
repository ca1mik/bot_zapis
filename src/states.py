from aiogram.fsm.state import State, StatesGroup

class BookingFSM(StatesGroup):
    choosing_service = State()
    choosing_date = State()
    choosing_time = State()
    getting_time_start = State()  # NEW
    getting_time_end = State()    # NEW
    getting_district = State()
    getting_wishes = State()
    confirming = State()

class AdminReschedule(StatesGroup):
    waiting_slot = State()  # ждём "dd.mm.yyyy HH:MM–HH:MM"