from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from src.config import cfg

SERVICES = [
    "Прогулка", "Кафе", "Кино",
    "Спорт/зал/активность", "Выезд на природу",
    "Разговор по душам", "Другое"
]

DATE_PRESETS = ["Сегодня", "Завтра", "Ближайшие выходные", "Выбрать дату"]

# ---------- нижние (persistent) клавиатуры ----------
def reply_kb_flow() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        resize_keyboard=True,
        keyboard=[[KeyboardButton(text="⬅ Назад"), KeyboardButton(text="✖ Отмена")]]
    )

def reply_kb_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        resize_keyboard=True,
        keyboard=[
            [KeyboardButton(text="🆕 Новая заявка")],
            [KeyboardButton(text="📋 Мои заявки")]
        ]
    )

# ---------- инлайн-клавиатуры ----------
def kb_main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🗓 Записаться", callback_data="new")
    kb.button(text="📋 Мои заявки", callback_data="mine")
    kb.adjust(2, 1)
    return kb

def kb_services():
    kb = InlineKeyboardBuilder()
    for s in SERVICES:
        kb.button(text=s, callback_data=f"svc:{s}")
    kb.adjust(2)
    return kb

def kb_dates(prefix: str = "date:"):
    kb = InlineKeyboardBuilder()
    for d in DATE_PRESETS:
        kb.button(text=d, callback_data=f"{prefix}{d}")
    kb.adjust(2)
    return kb

def kb_times():
    kb = InlineKeyboardBuilder()
    for t in cfg.time_slots:
        kb.button(text=t, callback_data=f"time:{t}")
    kb.button(text="⏱ Выбрать интервал", callback_data="time:__interval__")
    kb.adjust(2)
    return kb

def kb_confirm():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data="confirm")
    kb.button(text="✏️ Исправить", callback_data="edit")
    kb.adjust(2)
    return kb

def admin_booking_kb(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"adm:ok:{request_id}"),
            InlineKeyboardButton(text="❌ Отклонить",   callback_data=f"adm:no:{request_id}")
        ],
        [InlineKeyboardButton(text="🕓 Перенести (время)", callback_data=f"adm:res:{request_id}")]
    ])

def kb_admin_actions(req_id: str, username: str | None):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data=f"admin:approve:{req_id}")
    kb.button(text="❌ Отклонить", callback_data=f"admin:decline:{req_id}")
    if username:
        kb.button(text="✍️ Связаться", url=f"https://t.me/{username}")
    kb.adjust(2, 1)
    return kb
