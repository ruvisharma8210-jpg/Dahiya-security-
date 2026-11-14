import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DB_PATH = os.getenv("DB_PATH", "bot.db").strip() or "bot.db"
OWNER_IDS = {
    int(x) for x in os.getenv("OWNER_IDS", "").replace(" ", "").split(",") if x.isdigit()
}
API_ID = int(os.getenv("API_ID", "0").strip() or 0)
API_HASH = os.getenv("API_HASH", "").strip()
SESSION_SECRET = os.getenv("SESSION_SECRET", "").strip()
