# src/config.py
import os, json
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def _split_ids(v: str | None) -> list[int]:
    if not v:
        return []
    out: list[int] = []
    for x in v.split(","):
        x = x.strip()
        if x.isdigit():
            out.append(int(x))
    return out

@dataclass
class Config:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    # один «главный» чат админа (для уведомлений):
    admin_chat_id: int = int(os.getenv("ADMIN_CHAT_ID", "0") or "0")
    # при желании — список админов (необязательно):
    admin_ids: list[int] = field(default_factory=lambda: _split_ids(os.getenv("ADMIN_IDS")))

    spreadsheet_id: str = os.getenv("SPREADSHEET_ID", "")
    sheet_bookings: str = os.getenv("SHEET_BOOKINGS", "Заявки")
    sheet_calendar: str = os.getenv("SHEET_CALENDAR", "Календарь")
    time_slots_env: str = os.getenv("TIME_SLOTS", "Весь день,10:00–12:00,13:00–15:00,16:00–18:00,19:00–21:00")

    # 3 способа задать ключ:
    google_creds_json: str = os.getenv("GOOGLE_CREDS_JSON", "")
    google_creds_path: str = os.getenv("GOOGLE_CREDS_JSON_PATH", "")

    @property
    def time_slots(self):
        return [s.strip() for s in self.time_slots_env.split(",") if s.strip()]

cfg = Config()

# ---- загрузка ключа из файла, если нужно ----
raw = cfg.google_creds_json.strip()
if not raw and cfg.google_creds_path:
    cfg.google_creds_json = Path(cfg.google_creds_path).read_text(encoding="utf-8")
elif raw.startswith("@"):
    path = raw[1:]
    cfg.google_creds_json = Path(path).read_text(encoding="utf-8")

# ---- валидация ----
assert cfg.bot_token, "BOT_TOKEN is required in .env"
assert cfg.spreadsheet_id, "SPREADSHEET_ID is required in .env"
assert cfg.google_creds_json, "GOOGLE_CREDS_JSON* обязательно (см. README)"

try:
    json.loads(cfg.google_creds_json)
except Exception as e:
    raise AssertionError(f"GOOGLE_CREDS_JSON не парсится как JSON: {e}")
