from __future__ import annotations
import json
from typing import Dict, List
import gspread
from google.oauth2 import service_account
from .config import cfg

HEADERS_BOOK = [
    "Timestamp", "RequestID", "TelegramID", "Username", "Name",
    "Service", "DateISO", "DateText", "TimeSlot", "District", "Wishes", "Status", "AdminComment"
]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

class Sheets:
    def __init__(self):
        raw_json = cfg.google_creds_json
        try:
            info = json.loads(raw_json)
        except Exception as e:
            raise RuntimeError(f"GOOGLE_CREDS_JSON невалиден: {e}")

        pk = info.get("private_key", "")
        # если в значении встречается литеральная последовательность \n — заменим на реальный перевод строки
        if isinstance(pk, str) and "\\n" in pk:
            info["private_key"] = pk.replace("\\n", "\n").replace("\r\n", "\n")

        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)

        self.gc = gspread.authorize(creds)
        self.sh = self.gc.open_by_key(cfg.spreadsheet_id)
        self.ws_book = self._get_or_create_ws(cfg.sheet_bookings, cols=len(HEADERS_BOOK))
        self.ws_cal = self._get_or_create_ws(cfg.sheet_calendar, cols=1 + len(cfg.time_slots))
        self._ensure_headers()

    # --------------------- internal utils ---------------------

    def _get_or_create_ws(self, title: str, cols: int):
        try:
            return self.sh.worksheet(title)
        except gspread.WorksheetNotFound:
            return self.sh.add_worksheet(title=title, rows=1000, cols=cols)

    def _ensure_headers(self):
        vals = self.ws_book.get_values("1:1")
        if not vals or vals[0] != HEADERS_BOOK:
            self.ws_book.update("A1", [HEADERS_BOOK])

        cal_hdrs = ["Date"] + cfg.time_slots
        vals_c = self.ws_cal.get_values("1:1")
        if not vals_c or vals_c[0] != cal_hdrs:
            self.ws_cal.update("A1", [cal_hdrs])

    def _cal_header_map(self) -> dict:
        headers = self.ws_cal.row_values(1)
        return {h: i + 1 for i, h in enumerate(headers)}

    def _book_header_map(self) -> dict:
        # индексы колонок на листе заявок
        return {h: i + 1 for i, h in enumerate(HEADERS_BOOK)}

    # --------------------- bookings ---------------------------

    def find_row_by_request_id(self, request_id: str) -> int | None:
        ws = self.ws_book
        col = self._book_header_map()['RequestID']
        values = ws.col_values(col)
        for i, v in enumerate(values[1:], start=2):  # пропускаем шапку
            if str(v).strip() == str(request_id):
                return i
        return None

    def get_by_request_id(self, request_id: str) -> dict | None:
        row_i = self.find_row_by_request_id(request_id)
        if not row_i:
            return None
        row_vals = self.ws_book.row_values(row_i)
        if len(row_vals) < len(HEADERS_BOOK):
            row_vals += [""] * (len(HEADERS_BOOK) - len(row_vals))
        return dict(zip(HEADERS_BOOK, row_vals))

    def set_status(self, request_id: str, status: str,
                   admin_comment: str | None = None,
                   date_iso: str | None = None,
                   time_slot: str | None = None):
        row = self.find_row_by_request_id(request_id)
        if not row:
            raise ValueError("RequestID not found")

        ws = self.ws_book
        h = self._book_header_map()

        if status is not None:
            ws.update_cell(row, h['Status'], status)
        if admin_comment is not None:
            ws.update_cell(row, h['AdminComment'], admin_comment)
        if date_iso is not None:
            ws.update_cell(row, h['DateISO'], date_iso)
        if time_slot is not None:
            ws.update_cell(row, h['TimeSlot'], time_slot)

    def append_booking(self, row: Dict):
        ordered = [row.get(h, "") for h in HEADERS_BOOK]
        self.ws_book.append_row(ordered, value_input_option="USER_ENTERED")

    def update_status(self, request_id: str, status: str, admin_comment: str = "") -> bool:
        cells = self.ws_book.findall(request_id)
        target_row = None
        for c in cells:
            if c.col == HEADERS_BOOK.index("RequestID")+1:
                target_row = c.row
                break
        if not target_row:
            return False
        self.ws_book.update_cell(target_row, HEADERS_BOOK.index("Status")+1, status)
        if admin_comment:
            self.ws_book.update_cell(target_row, HEADERS_BOOK.index("AdminComment")+1, admin_comment)
        return True

    def user_recent(self, telegram_id: int, limit: int = 5) -> List[Dict]:
        values = self.ws_book.get_all_records()
        rows = [r for r in values if str(r.get("TelegramID")) == str(telegram_id)]
        rows.sort(key=lambda r: r.get("Timestamp",""), reverse=True)
        return rows[:limit]

    # --------------------- calendar ---------------------------

    def ensure_day_row(self, date_iso: str) -> int:
        all_vals = self.ws_cal.get_all_values()
        idx = {r[0]: i+1 for i, r in enumerate(all_vals) if r}
        if date_iso in idx:
            return idx[date_iso]
        next_row = len(all_vals) + 1
        if next_row == 1:
            self._ensure_headers()
            next_row = 2
        self.ws_cal.update(f"A{next_row}", [[date_iso] + [""]*len(cfg.time_slots)])
        return next_row

    def get_availability(self, date_iso: str) -> Dict[str, str]:
        from .parsing import slot_to_minutes
        row = self.ensure_day_row(date_iso)
        headers = self.ws_cal.row_values(1)
        hdr = {h: i + 1 for i, h in enumerate(headers)}
        # если «Весь день» уже стоит — все занято
        col_all = hdr.get("Весь день")
        if col_all:
            if (self.ws_cal.cell(row, col_all).value or "").strip():
                return {h: "ALL_DAY" for h in headers[1:]}
        # обычный случай
        end_col = chr(ord('A') + len(headers) - 1)
        cells = (self.ws_cal.get(f"A{row}:{end_col}{row}") or [[]])[0]
        return {h: (cells[i] if i < len(cells) else "") for i, h in enumerate(headers[1:], start=1)}

    def mark_slot(self, date_iso: str, slot: str, text: str) -> bool:
        from .parsing import slot_to_minutes
        row = self.ensure_day_row(date_iso)
        hdr = self._cal_header_map()
        # защита от «Весь день»
        if slot != "Весь день":
            col_all = hdr.get("Весь день")
            if col_all and (self.ws_cal.cell(row, col_all).value or "").strip():
                return False
        # «Весь день» нельзя ставить, если есть что-то в день
        if slot == "Весь день":
            row_vals = self.ws_cal.row_values(row)
            if any((c or "").strip() for c in (row_vals[1:] or [])):
                return False
        # проверка пересечений
        if self.is_occupied(date_iso, slot):
            return False
        # найдём/создадим колонку слота
        col = hdr.get(slot)
        if not col:
            headers = self.ws_cal.row_values(1)
            self.ws_cal.update("A1", [headers + [slot]])
            hdr = self._cal_header_map()
            col = hdr.get(slot)
        # финально пишем
        cur = self.ws_cal.cell(row, col).value or ""
        if cur.strip():
            return False
        self.ws_cal.update_cell(row, col, text)
        return True

    def clear_slot(self, date_iso: str, slot: str) -> bool:
        row = self.ensure_day_row(date_iso)
        hdr = self._cal_header_map()
        col = hdr.get(slot)
        if not col:
            return False
        cur = self.ws_cal.cell(row, col).value or ""
        if not cur.strip():
            return False
        self.ws_cal.update_cell(row, col, "")
        return True

    def is_occupied(self, date_iso: str, slot: str) -> bool:
        from .parsing import slot_to_minutes
        row = self.ensure_day_row(date_iso)
        hdr = self._cal_header_map()
        # день целиком?
        if slot == "Весь день":
            row_vals = self.ws_cal.row_values(row)
            # занято, если что-то уже стоит в любом слоте
            return any((c or "").strip() for c in (row_vals[1:] or []))
        # если в дне уже «Весь день» — любой слот занят
        col_all = hdr.get("Весь день")
        if col_all and (self.ws_cal.cell(row, col_all).value or "").strip():
            return True
        # проверка пересечений интервалов
        req = slot_to_minutes(slot)
        if not req:
            # если не распознали — fallback: занято, если ячейка слота непуста
            col = hdr.get(slot)
            if not col: return False
            return bool((self.ws_cal.cell(row, col).value or "").strip())
        rs, re = req if isinstance(req, tuple) else (None, None)
        # пробегаем все занятые слоты дня
        headers = self.ws_cal.row_values(1)
        row_vals = self.ws_cal.row_values(row)
        for i, h in enumerate(headers[1:], start=2):
            val = (row_vals[i - 1] if i - 1 < len(row_vals) else "") or ""
            if not val.strip():
                continue
            if h == "Весь день":
                return True
            existed = slot_to_minutes(h)
            if not existed:
                # неподдающийся парсингу слот — считаем конфликтным с кастомным
                if hdr.get(slot) == i:
                    return True
                continue
            es, ee = existed
            # проверка пересечения [rs,re) & [es,ee)
            if not (re <= es or ee <= rs):
                return True
        return False

    # NEW: список занятых дат в месяце (есть хотя бы одно занятие в день)
    def busy_dates_for_month(self, year:int, month:int) -> set[str]:
        vals = self.ws_cal.get_all_values()
        busy = set()
        for r in vals[1:]:
            if not r:
                continue
            d = r[0]  # YYYY-MM-DD
            if len(d) >= 10 and d[:7] == f"{year:04d}-{month:02d}":
                if any((c or "").strip() for c in r[1:]):
                    busy.add(d)
        return busy

sheets = Sheets()
