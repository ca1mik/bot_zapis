# src/calendar_kb.py
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import date
from calendar import monthrange

# берём данные из таблицы, чтобы подсветить занятые дни
from src.sheets import sheets

RU_MONTHS = ["Янв","Фев","Мар","Апр","Май","Июн","Июл","Авг","Сен","Окт","Ноя","Дек"]


def _prev_month(y: int, m: int) -> tuple[int, int]:
    return (y - 1, 12) if m == 1 else (y, m - 1)


def _next_month(y: int, m: int) -> tuple[int, int]:
    return (y + 1, 1) if m == 12 else (y, m + 1)


def _busy_days_for_month(y: int, m: int) -> set[int]:
    """
    Собираем дни месяца, где уже есть заявки (Новая/Подтверждена/Ожидает связи).
    Если хочешь подсвечивать только подтверждённые — оставь лишь 'Подтверждена'.
    """
    month_prefix = f"{y:04d}-{m:02d}"
    busy: set[int] = set()
    for r in sheets.ws_book.get_all_records():
        iso = str(r.get("DateISO") or "")
        if not iso.startswith(month_prefix):
            continue
        status = str(r.get("Status") or "").strip()
        if status not in {"Новая", "Подтверждена", "Ожидает связи"}:
            continue
        try:
            busy.add(int(iso[8:10]))
        except Exception:
            pass
    return busy


def build_month_kb(year: int, month: int) -> InlineKeyboardBuilder:
    """
    Компактный календарь:
      ┌ ‹  Авг 2025  › ┐
      ├ 1 2 3 4 5 6 7 ┤
      ├ 8 9 10 ...    ┤
      └ Сегодня | Назад┘
    Кнопки:
      cal:nav:YYYY-MM  — перелистывание
      cal:pick:YYYY-MM-DD — выбор дня
    """
    kb = InlineKeyboardBuilder()

    py, pm = _prev_month(year, month)
    ny, nm = _next_month(year, month)

    # верхняя строка — навигация
    kb.button(text="«", callback_data=f"cal:nav:{py:04d}-{pm:02d}")
    kb.button(text=f"{RU_MONTHS[month-1]} {year}", callback_data="noop")
    kb.button(text="»", callback_data=f"cal:nav:{ny:04d}-{nm:02d}")

    # сетка дат: просто 1..N, без «дней недели»
    days = monthrange(year, month)[1]
    busy = _busy_days_for_month(year, month)

    for d in range(1, days + 1):
        text = f"{d}•" if d in busy else str(d)
        iso = f"{year:04d}-{month:02d}-{d:02d}"
        kb.button(text=text, callback_data=f"cal:pick:{iso}")

    # нижняя строка
    today = date.today()
    kb.button(text="Сегодня", callback_data=f"cal:pick:{today:%Y-%m-%d}")
    kb.button(text="⬅ Назад", callback_data="back")

    # раскладка: 1 строка навигации, потом по 7 в ряд, и нижняя из 2-х кнопок
    rows_for_days = (days + 6) // 7
    layout = [3] + [7] * rows_for_days + [2]
    kb.adjust(*layout)

    return kb
