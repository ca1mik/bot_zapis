from __future__ import annotations
import re
from datetime import date, timedelta
from typing import Optional

def parse_date_human(text: str) -> Optional[str]:
    """Примеры: сегодня/завтра/ближайшие выходные, 26.08(.2025) → ISO-дату"""
    t = (text or "").strip().lower()
    if not t:
        return None
    today = date.today()

    if "сегодня" in t:
        return today.isoformat()
    if "завтра" in t:
        return (today + timedelta(days=1)).isoformat()
    if "выходн" in t:
        delta = (5 - today.weekday()) % 7  # 5=Sat
        return (today + timedelta(days=delta)).isoformat()

    m = re.match(r"(\d{1,2})[./-](\d{1,2})(?:[./-](\d{4}))?$", t)
    if m:
        d = int(m.group(1)); mth = int(m.group(2)); yr = int(m.group(3) or today.year)
        try:
            return date(yr, mth, d).isoformat()
        except ValueError:
            return None
    return None

def parse_hhmm(s: str):
    if not s: return None
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", s)
    if not m: return None
    h = int(m.group(1)); mnt = int(m.group(2))
    if not (0 <= h < 24 and 0 <= mnt < 60): return None
    return h, mnt

def normalize_range(start_str: str, end_str: str):
    a = parse_hhmm(start_str); b = parse_hhmm(end_str)
    if not a or not b: return None
    sh, sm = a; eh, em = b
    if (eh, em) <= (sh, sm): return None
    return f"{sh:02d}:{sm:02d}–{eh:02d}:{em:02d}"

def slot_to_minutes(slot: str):
    if not slot: return None
    t = slot.strip().lower().replace("—","-").replace("–","-")
    if "весь день" in t:
        return ("all_day", None)
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*-\s*(\d{1,2})[:.](\d{2})\s*", t)
    if not m: return None
    sh, sm, eh, em = map(int, m.groups())
    if not (0<=sh<24 and 0<=eh<24 and 0<=sm<60 and 0<=em<60): return None
    s = sh*60+sm; e = eh*60+em
    if e <= s: return None
    return (s, e)