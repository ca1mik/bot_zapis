# src/main.py
import os
from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

import asyncio
import logging
from datetime import datetime, date, timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import BaseMiddleware
from contextlib import suppress

from src.config import cfg
from src.states import BookingFSM
from src.parsing import parse_date_human, normalize_range, parse_hhmm
from src.sheets import sheets
from src import keyboards as kb
from src.calendar_kb import build_month_kb

# Функция для безопасного удаления сообщений
async def _delete_silent(msg):
    try:
        await msg.delete()
    except Exception:
        pass

class AutoDeleteUserTextMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        # Проверяем, что это личный чат и сообщение пользователя
        if isinstance(event, Message) and event.chat.type == "private" and (event.text or "").strip():
            # Сначала даём хендлерам отработать
            result = await handler(event, data)
            # Потом удаляем сообщение пользователя
            with suppress(Exception):
                await event.delete()
            return result

        # Если не текст или не личка — пропускаем дальше
        return await handler(event, data)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("qwesade.bot")

router = Router()

# Невидимый символ как «якорь» для reply-клавы
ANCHOR_TEXT = "\u2063"

# --- Webhook config (для Render) ---
WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "change_me")  # поставь случайную строку в ENV
# Render сам даёт внешний URL в переменной RENDER_EXTERNAL_URL — используем как базу
WEBHOOK_BASE = os.getenv("WEBHOOK_BASE") or os.getenv("RENDER_EXTERNAL_URL", "")
WEBHOOK_URL = f"{WEBHOOK_BASE}{WEBHOOK_PATH}" if WEBHOOK_BASE else ""


# ---------- Reply-клава снизу ----------

def _reply_markup(mode: str) -> ReplyKeyboardMarkup:
    if mode == "menu":
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🆕 Новая заявка")]],
            resize_keyboard=True
        )
    # mode == flow
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅ Назад"), KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )

async def _delete_msg_by_id(bot, chat_id: int, msg_id: int | None):
    if not msg_id:
        return
    try:
        await bot.delete_message(chat_id, msg_id)
    except Exception:
        pass

async def _set_reply_mode(bot: Bot, chat_id: int, state: FSMContext, mode: str):
    data = await state.get_data()
    if data.get("reply_mode") == mode and data.get("reply_msg_id"):
        return
    # удалить старый якорь
    if data.get("reply_msg_id"):
        try:
            await bot.delete_message(chat_id, data["reply_msg_id"])
        except Exception:
            pass
    m = await bot.send_message(chat_id, ANCHOR_TEXT, reply_markup=_reply_markup(mode))
    await state.update_data(reply_msg_id=m.message_id, reply_mode=mode)


async def send_step(bot: Bot, chat_id: int, state: FSMContext, text: str, inline_markup=None, reply_mode: str = "flow"):
    if not (text or "").strip():
        text = "."
    await _set_reply_mode(bot, chat_id, state, reply_mode)

    data = await state.get_data()
    old_id = data.get("step_msg_id")
    if old_id:
        try:
            await bot.delete_message(chat_id, old_id)
        except Exception:
            pass

    m = await bot.send_message(chat_id, text, reply_markup=inline_markup)
    await state.update_data(step_msg_id=m.message_id)


async def goto_menu(bot: Bot, chat_id: int, state: FSMContext, title: str | None = None):
    await state.set_state()
    await send_step(bot, chat_id, state, title or "Выбери действие:", kb.kb_main_menu().as_markup(), reply_mode="menu")


async def goto_flow(bot: Bot, chat_id: int, state: FSMContext):
    await state.set_state(BookingFSM.choosing_service)
    await send_step(bot, chat_id, state, "Что хочется?", kb.kb_services().as_markup(), reply_mode="flow")

def admin_kb(row: dict) -> InlineKeyboardMarkup:
    req_id = row["RequestID"]
    uid = row["TelegramID"]
    username = (row.get("Username") or "").strip()
    contact_url = f"https://t.me/{username}" if username else f"tg://user?id={uid}"

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"adm:ok:{req_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm:no:{req_id}")],
        [InlineKeyboardButton(text="👤 Связаться", url=contact_url)],
    ])

# ---------- Команды ----------

# /start — показать меню (и удалить команду из чата)
# /start — показать меню (и удалить команду из чата)
@router.message(F.text.regexp(r"^/start(\s|$)"))
async def cmd_start(message: Message, state: FSMContext):
    try: await message.delete()
    except: pass
    await goto_menu(message.bot, message.chat.id, state, "Привет! Это запись на активности @qwesade.")

# кнопка реплай "🆕 Новая заявка" — сразу в поток (и удалить сообщение пользователя)
@router.message(F.text == "🆕 Новая заявка")
async def msg_new(message: Message, state: FSMContext):
    try:
        await message.delete()
    except Exception:
        pass
    await goto_flow(message.bot, message.chat.id, state)



@router.message(F.text == "/new")
@router.callback_query(F.data == "new")
async def cmd_new(evt, state: FSMContext):
    bot = evt.bot
    chat_id = evt.message.chat.id if isinstance(evt, CallbackQuery) else evt.chat.id
    await goto_flow(bot, chat_id, state)


@router.message(F.text == "/help")
async def cmd_help(message: Message):
    try: await message.delete()
    except: pass
    await message.answer("/start — меню\n/new — новая запись\n/avail — доступность\n/mine — мои заявки\n/agenda — ближайшие подтверждённые")

@router.message(F.text == "/new")
async def cmd_new_msg(message: Message, state: FSMContext):
    try: await message.delete()
    except: pass
    await goto_flow(message.bot, message.chat.id, state)

# ---------- Инфо-разделы ----------

@router.callback_query(F.data == "mine")
async def cb_mine(cb: CallbackQuery, state: FSMContext):
    rows = sheets.user_recent(cb.from_user.id, limit=5)
    if not rows:
        return await cb.answer("Заявок нет", show_alert=True)
    text = "Ваши последние заявки:\n\n" + "\n\n".join(
        f"• {r['RequestID']} — {r['Service']} — {r['DateText']} {r['TimeSlot']}\n"
        f"  Район: {r['District'] or '—'}\n"
        f"  Пожелания: {r['Wishes'] or '—'}\n"
        f"  Статус: {r['Status'] or 'Новая'}"
        for r in rows
    )
    await send_step(cb.bot, cb.message.chat.id, state, text, kb.kb_main_menu().as_markup(), reply_mode="menu")
    await cb.answer()


@router.message(F.text == "/agenda")
async def cmd_agenda(message: Message):
    rows = sheets.ws_book.get_all_records()
    now = datetime.now()
    until = now + timedelta(days=60)

    def parse_dt(r):
        iso = r.get("DateISO", "")
        slot = str(r.get("TimeSlot", ""))
        try:
            dt = datetime.fromisoformat(iso)
        except Exception:
            return None
        import re
        m = re.search(r"(\d{1,2}):(\d{2})", slot)
        if m:
            dt = dt.replace(hour=int(m.group(1)), minute=int(m.group(2)))
        return dt

    items = []
    for r in rows:
        if r.get("Status") != "Подтверждена":
            continue
        dt = parse_dt(r)
        if not dt or dt < now or dt > until:
            continue
        items.append((dt, r))
    items.sort(key=lambda x: x[0])

    if not items:
        return await message.answer("Ближайших подтверждённых записей нет.")
    lines = ["Ближайшие записи:\n"]
    for dt, r in items[:20]:
        lines.append(f"{dt:%d.%m %H:%M} — {r.get('Service')} (@{r.get('Username') or r.get('TelegramID')})")
    await message.answer("\n".join(lines))


# ---------- Сценарий записи ----------

@router.callback_query(BookingFSM.choosing_service, F.data.startswith("svc:"))
async def on_service(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    service = cb.data.split(":", 1)[1]
    await state.update_data(service=service)
    await state.set_state(BookingFSM.choosing_date)
    await send_step(cb.bot, cb.message.chat.id, state, "Когда удобно?", kb.kb_dates().as_markup())


# Календарь (компактный)
@router.callback_query(BookingFSM.choosing_date, F.data.startswith("cal:nav:"))
async def cal_nav(cb: CallbackQuery):
    await cb.answer()
    y, m = map(int, cb.data.split(":")[2].split("-"))
    await cb.message.edit_reply_markup(reply_markup=build_month_kb(y, m).as_markup())


@router.callback_query(BookingFSM.choosing_date, F.data.startswith("cal:pick:"))
async def cal_pick(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    iso = cb.data.split(":")[2]
    await state.update_data(date_iso=iso, date_text=iso)
    await state.set_state(BookingFSM.choosing_time)
    await send_step(cb.bot, cb.message.chat.id, state, "Во сколько?", kb.kb_times().as_markup())


@router.callback_query(BookingFSM.choosing_date, F.data.startswith("date:"))
async def on_date_preset(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    val = cb.data.split(":", 1)[1]
    if val == "Выбрать дату":
        today = date.today()
        return await cb.message.edit_reply_markup(reply_markup=build_month_kb(today.year, today.month).as_markup())
    iso = parse_date_human(val)
    await state.update_data(date_iso=iso, date_text=val)
    await state.set_state(BookingFSM.choosing_time)
    await send_step(cb.bot, cb.message.chat.id, state, "Во сколько?", kb.kb_times().as_markup())


# Кнопки времени
@router.callback_query(BookingFSM.choosing_time, F.data.startswith("time:"))
async def on_time_button(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    val = cb.data.split(":", 1)[1]
    if val == "__interval__":
        await state.set_state(BookingFSM.getting_time_start)
        return await send_step(cb.bot, cb.message.chat.id, state,
                               "Напиши интервал: <b>HH:MM–HH:MM</b>\nНапр.: <code>11:23–14:45</code>")
    await state.update_data(time_slot=val)
    await state.set_state(BookingFSM.getting_district)
    await send_step(cb.bot, cb.message.chat.id, state, "Какой район/локация? (можно 'без разницы')")


# Ввод времени текстом (одним сообщением — интервал или «весь день»)
@router.message(BookingFSM.choosing_time)
async def on_time_text_one(message: Message, state: FSMContext):
    txt = (message.text or "").strip()
    if txt in {"⬅ Назад", "❌ Отмена"}:
        if txt == "⬅ Назад":
            return await on_back(message, state)
        else:
            return await on_cancel(message, state)
    await message.delete()

    low = txt.lower().replace("ё", "е")
    if low in {"весь день", "весьдень"}:
        await state.update_data(time_slot="Весь день")
        await state.set_state(BookingFSM.getting_district)
        return await send_step(message.bot, message.chat.id, state, "Какой район/локация? (можно 'без разницы')")

    import re
    # допускаем 11.23-19.45 и разные тире
    norm = txt.replace("—", "-").replace("–", "-").replace(".", ":").replace(" ", "")
    if re.fullmatch(r"\d{1,2}:\d{2}-\d{1,2}:\d{2}", norm):
        a, b = norm.split("-")
        slot = f"{a}–{b}"
        await state.update_data(time_slot=slot)
        await state.set_state(BookingFSM.getting_district)
        return await send_step(message.bot, message.chat.id, state, "Какой район/локация? (можно 'без разницы')")

    if parse_hhmm(txt):
        # ввели только начало — попросим конец (но в рамках нашего состояния getting_time_start)
        await state.update_data(_t_start=txt)
        await state.set_state(BookingFSM.getting_time_end)
        return await send_step(message.bot, message.chat.id, state, "Конец: <b>HH:MM</b>")

    await send_step(message.bot, message.chat.id, state,
                    "Не понял время. Введи, например: <code>11:30–17:45</code> или <b>Весь день</b>.")


# Совместимость: сюда попадём и по «Выбрать интервал»
@router.message(BookingFSM.getting_time_start)
async def on_time_start(message: Message, state: FSMContext):
    txt = (message.text or "").strip()
    if txt in {"⬅ Назад", "❌ Отмена"}:
        if txt == "⬅ Назад":
            return await on_back(message, state)
        else:
            return await on_cancel(message, state)
    await message.delete()

    # сразу интервал — принимаем
    import re
    norm = txt.replace("—", "-").replace("–", "-").replace(".", ":").replace(" ", "")
    if re.fullmatch(r"\d{1,2}:\d{2}-\d{1,2}:\d{2}", norm):
        a, b = norm.split("-")
        slot = f"{a}–{b}"
        await state.update_data(time_slot=slot)
        await state.set_state(BookingFSM.getting_district)
        return await send_step(message.bot, message.chat.id, state, "Какой район/локация? (можно 'без разницы')")

    # иначе ждём начало как HH:MM
    if not parse_hhmm(txt):
        return await send_step(message.bot, message.chat.id, state, "Не понял время. Пример: <code>11:30–17:45</code>")
    await state.update_data(_t_start=txt)
    await state.set_state(BookingFSM.getting_time_end)
    await send_step(message.bot, message.chat.id, state, "Конец: <b>HH:MM</b>")


@router.message(BookingFSM.getting_time_end)
async def on_time_end(message: Message, state: FSMContext):
    txt = (message.text or "").strip()
    if txt in {"⬅ Назад", "❌ Отмена"}:
        if txt == "⬅ Назад":
            return await on_back(message, state)
        else:
            return await on_cancel(message, state)
    await message.delete()
    data = await state.get_data()
    slot = normalize_range(data.get("_t_start", ""), txt)
    if not slot:
        return await send_step(message.bot, message.chat.id, state, "Интервал некорректный. Пример: 11:30–17:45")
    await state.update_data(time_slot=slot)
    await state.set_state(BookingFSM.getting_district)
    await send_step(message.bot, message.chat.id, state, "Какой район/локация? (можно 'без разницы')")


# Район
@router.message(BookingFSM.getting_district)
async def on_district(message: Message, state: FSMContext):
    txt = (message.text or "").strip()
    if txt in {"⬅ Назад", "❌ Отмена"}:
        if txt == "⬅ Назад":
            return await on_back(message, state)
        else:
            return await on_cancel(message, state)
    await message.delete()
    await state.update_data(district=txt)
    await state.set_state(BookingFSM.getting_wishes)
    await send_step(message.bot, message.chat.id, state, "Пожелания/детали? (можно написать 'нет')")


# Пожелания -> подтверждение
@router.message(BookingFSM.getting_wishes)
async def on_wishes(message: Message, state: FSMContext):
    wishes_text = (message.text or "").strip()
    await message.delete()
    if wishes_text.lower() in {"нет", "-", "—"}:
        wishes_text = ""
    await state.update_data(wishes=wishes_text)
    data = await state.get_data()
    text = (
        f"Проверь заявку:\n\n"
        f"• Услуга: {data.get('service')}\n"
        f"• Когда: {data.get('date_text')}\n"
        f"• Время: {data.get('time_slot')}\n"
        f"• Район: {data.get('district')}\n"
        f"• Пожелания: {wishes_text or '—'}\n"
    )
    await state.set_state(BookingFSM.confirming)
    await send_step(message.bot, message.chat.id, state, text, kb.kb_confirm().as_markup())


@router.callback_query(BookingFSM.confirming, F.data == "edit")
async def on_edit(cb: CallbackQuery, state: FSMContext):
    await cb.answer("Заново")
    await goto_flow(cb.bot, cb.message.chat.id, state)


# Уведомление админов (поддержка admin_ids и admin_chat_id)
async def _notify_admins(bot: Bot, text: str, markup: InlineKeyboardMarkup | None = None):
    admin_ids = list(getattr(cfg, "admin_ids", []) or [])
    if not admin_ids and getattr(cfg, "admin_chat_id", 0):
        admin_ids = [cfg.admin_chat_id]
    for aid in admin_ids:
        try:
            await bot.send_message(aid, text, reply_markup=markup)
        except Exception as e:
            log.warning("Admin notify failed (%s): %s", aid, e)


@router.callback_query(BookingFSM.confirming, F.data == "confirm")
async def on_confirm(cb: CallbackQuery, state: FSMContext, bot: Bot):
    await cb.answer()
    data = await state.get_data()
    date_iso = data.get("date_iso") or parse_date_human(data.get("date_text", "") or "")
    slot = data.get("time_slot", "")
    if not date_iso:
        await state.clear()
        return await goto_menu(bot, cb.message.chat.id, state, "Не распознал дату, начнём заново.")

    if sheets.is_occupied(date_iso, slot):
        avail = sheets.get_availability(date_iso)
        free_list = [s for s, v in avail.items() if not (v or "").strip()]
        text = "Этот слот занят."
        if free_list:
            text += "\nСвободно:\n" + "\n".join(f"• {s}" for s in free_list)

        # Удаляем старое сообщение бота перед очисткой
        data = await state.get_data()
        await _delete_msg_by_id(cb.bot, cb.message.chat.id, data.get("step_msg_id"))
        await _delete_msg_by_id(cb.bot, cb.message.chat.id, data.get("reply_msg_id"))

        await state.clear()
        return await goto_menu(bot, cb.message.chat.id, state, text)

    req_id = f"RQ-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    row = {
        "Timestamp": datetime.now().isoformat(timespec="seconds"),
        "RequestID": req_id,
        "TelegramID": cb.from_user.id,
        "Username": cb.from_user.username or "",
        "Name": cb.from_user.full_name or "",
        "Service": data.get("service", ""),
        "DateISO": date_iso,
        "DateText": data.get("date_text", date_iso),
        "TimeSlot": slot,
        "District": data.get("district", ""),
        "Wishes": data.get("wishes", ""),
        "Status": "Новая",
        "AdminComment": "",
    }

    try:
        sheets.append_booking(row)
        cell_text = f"{row['Service']} (@{row['Username'] or row['TelegramID']})\n{row['District'] or ''}".strip()
        ok = sheets.mark_slot(date_iso, slot, cell_text)
        if not ok:
            await state.clear()
            return await goto_menu(bot, cb.message.chat.id, state, "Ой, слот только что заняли. Попробуй другой.")
    except Exception as e:
        # Удаляем старое сообщение бота перед очисткой
        data = await state.get_data()
        await _delete_msg_by_id(cb.bot, cb.message.chat.id, data.get("step_msg_id"))
        await _delete_msg_by_id(cb.bot, cb.message.chat.id, data.get("reply_msg_id"))

        await state.clear()
        return await goto_menu(bot, cb.message.chat.id, state, f"Не удалось записать в таблицу: {e}")

    await send_step(bot, cb.message.chat.id, state, f"Заявка отправлена ✅\nID: {req_id}",
                    kb.kb_main_menu().as_markup(), reply_mode="menu")

    text = (
        f"Новая заявка: {req_id}\n"
        f"От: @{cb.from_user.username or cb.from_user.id} ({cb.from_user.full_name})\n"
        f"Услуга: {row['Service']}\nКогда: {row['DateText']} {row['TimeSlot']}\n"
        f"Район: {row['District']}\nПожелания: {row['Wishes'] or '—'}\n"
        f"ДатаISO: {row['DateISO']}"
    )
    await _notify_admins(bot, text, markup=admin_kb(row))
    await state.clear()


# ---------- Reply-кнопки Назад/Отмена ----------

@router.message(F.text == "❌ Отмена")
async def on_cancel(message: Message, state: FSMContext):
    bot, chat_id = message.bot, message.chat.id

    # удалить сообщение пользователя ("Отмена")
    try:
        await message.delete()
    except Exception:
        pass

    # удалить прошлые сообщения бота (шаг и якорь)
    data = await state.get_data()
    await _delete_msg_by_id(bot, chat_id, data.get("step_msg_id"))
    await _delete_msg_by_id(bot, chat_id, data.get("reply_msg_id"))

    # очистить стейт
    await state.clear()

    # показать меню (если не нужен текст — поставь title=None)
    await send_step(bot, chat_id, state, "Отменено.", kb.kb_main_menu().as_markup(), reply_mode="menu")


@router.message(F.text == "⬅ Назад")
async def on_back(message: Message, state: FSMContext):
    # удалить сообщение пользователя ("Назад")
    try:
        await message.delete()
    except Exception:
        pass

    st = await state.get_state()
    bot, chat_id = message.bot, message.chat.id

    if st == BookingFSM.getting_wishes.state:
        await state.set_state(BookingFSM.getting_district)
        return await send_step(bot, chat_id, state, "Какой район/локация? (можно 'без разницы')")

    if st == BookingFSM.getting_district.state:
        await state.set_state(BookingFSM.choosing_time)
        return await send_step(bot, chat_id, state, "Во сколько?", kb.kb_times().as_markup())

    if st in (BookingFSM.getting_time_end.state, BookingFSM.getting_time_start.state, BookingFSM.choosing_time.state):
        await state.set_state(BookingFSM.choosing_date)
        return await send_step(bot, chat_id, state, "Когда удобно?", kb.kb_dates().as_markup())

    if st in (BookingFSM.choosing_date.state, BookingFSM.choosing_service.state, BookingFSM.confirming.state):
        return await goto_flow(bot, chat_id, state)

    await goto_menu(bot, chat_id, state)


# ---------- Доступность ----------

@router.message(F.text == "/avail")
@router.callback_query(F.data == "avail")
async def cmd_avail(evt, state: FSMContext):
    msg = evt.message if isinstance(evt, CallbackQuery) else evt
    await send_step(msg.bot, msg.chat.id, state, "Когда показать?", kb.kb_dates(prefix="date:").as_markup(), reply_mode="menu")


@router.callback_query(F.data.startswith("adv_date:"))
async def on_avail_date(cb: CallbackQuery):
    await cb.answer()
    val = cb.data.split(":", 1)[1]
    if val == "Выбрать дату":
        today = date.today()
        return await cb.message.edit_reply_markup(reply_markup=build_month_kb(today.year, today.month).as_markup())
    iso = parse_date_human(val)
    await _show_availability(cb.message, iso, val)


@router.message(F.text.regexp(r"\d{1,2}[./-]\d{1,2}([./-]\d{4})?"))
async def on_avail_date_text(message: Message):
    iso = parse_date_human(message.text)
    if not iso:
        return await message.answer("Не распознал дату. Пример: 26.08.2025")
    await _show_availability(message, iso, message.text.strip())


async def _show_availability(dst_msg: Message, date_iso: str | None, label: str):
    if not date_iso:
        return await dst_msg.answer("Не распознал дату")
    avail = sheets.get_availability(date_iso)
    lines = [f"📅 Доступность на {label} ({date_iso}):"]
    for s in cfg.time_slots:
        lines.append(f"• {s} — {'❌ занято' if (avail.get(s, '') or '').strip() else '✅ свободно'}")
    await dst_msg.answer("\n".join(lines))

def _is_admin(user_id: int) -> bool:
    ids = set(getattr(cfg, "admin_ids", []) or [])
    if getattr(cfg, "admin_chat_id", 0):
        ids.add(cfg.admin_chat_id)
    return user_id in ids

@router.callback_query(F.data.startswith("adm:"))
async def on_admin_action(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)

    _, action, req_id = cb.data.split(":", 2)
    row = sheets.get_by_request_id(req_id)

    if not row:
        return await cb.answer("Заявка не найдена", show_alert=True)

    try:
        if action == "ok":
            sheets.set_status(req_id, "Подтверждена")
            try:
                await cb.bot.send_message(
                    row["TelegramID"],
                    f"Ваша заявка {req_id} подтверждена ✅\n"
                    f"{row['Service']} — {row['DateText']} {row['TimeSlot']}"
                )
            except:
                pass

            await cb.message.edit_text(cb.message.text + "\n\n✅ Подтверждено", reply_markup=None)
            await cb.answer("Подтверждено")

        elif action == "no":
            sheets.set_status(req_id, "Отклонена")
            try:
                sheets.clear_slot(row["DateISO"], row["TimeSlot"])
            except:
                pass
            try:
                await cb.bot.send_message(
                    row["TelegramID"],
                    f"К сожалению, заявка {req_id} отклонена ❌.\n"
                    "Можно выбрать другой слот."
                )
            except:
                pass

            await cb.message.edit_text(cb.message.text + "\n\n❌ Отклонено", reply_markup=None)
            await cb.answer("Отклонено")
        else:
            await cb.answer("Неизвестное действие", show_alert=True)

    except Exception as e:
        log.exception("Admin action failed: %s", e)
        await cb.answer("Ошибка при изменении статуса", show_alert=True)

# ---------- Launcher ----------

# ---------- Launcher (polling + webhook) ----------

async def _build_dp_and_bot():
    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    return dp, bot

async def main_polling():
    dp, bot = await _build_dp_and_bot()
    await dp.start_polling(bot)

def main_webhook():
    app = web.Application()

    # healthcheck
    app.router.add_get("/", lambda r: web.Response(text="ok"))  # опционально для корня
    app.router.add_get("/ping", lambda r: web.Response(text="ok"))  # собственно «пинг»
    # соберём dp/bot заранее (НЕ в on_startup)
    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    # регистрируем вебхуковый хендлер и интеграцию с aiohttp
    SimpleRequestHandler(dp, bot, secret_token=WEBHOOK_SECRET).register(app, WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    async def on_startup(_):
        if not WEBHOOK_URL:
            raise RuntimeError("WEBHOOK_BASE/RENDER_EXTERNAL_URL не задан. См. переменные окружения Render.")
        await bot.set_webhook(WEBHOOK_URL, secret_token=WEBHOOK_SECRET)

    async def on_shutdown(_):
        await bot.delete_webhook(drop_pending_updates=True)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", "10000")))


if __name__ == "__main__":
    mode = os.getenv("MODE", "webhook")  # webhook (по умолчанию) или polling
    if mode == "polling":
        asyncio.run(main_polling())
    else:
        main_webhook()

@router.message(F.text)
async def fallback_text(message: Message):
    # не трогаем state — просто покажем подсказку
    await message.answer("Нажмите /start или кнопку в меню.")