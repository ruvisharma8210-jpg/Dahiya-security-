import os
import re

from dotenv import load_dotenv

load_dotenv()


def _clean(v: str | None) -> str:
    # Render/Lovable me galti se quotes ya spaces aa jayein to bhi chale
    return (v or "").strip().strip('"').strip("'").strip()


def _ids(*names: str) -> set[int]:
    out: set[int] = set()
    for n in names:
        out |= {int(x) for x in re.findall(r"\d{5,}", os.getenv(n, ""))}
    return out


BOT_TOKEN = _clean(os.getenv("BOT_TOKEN"))
DB_PATH = _clean(os.getenv("DB_PATH")) or "bot.db"
# OWNER_IDS="123, 456" / "[123]" / OWNER_ID=123 — sab chalega
OWNER_IDS = _ids("OWNER_IDS", "OWNER_ID", "OWNER")
_api = re.findall(r"\d+", os.getenv("API_ID", ""))
API_ID = int(_api[0]) if _api else 0
API_HASH = _clean(os.getenv("API_HASH"))
SESSION_SECRET = _clean(os.getenv("SESSION_SECRET"))
