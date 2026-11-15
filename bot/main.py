import asyncio
import logging
import sys

from telegram import Update
from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError
from telegram.ext import Application

from . import cloner
from . import hub
from . import keepalive
from . import sessions as ss
from . import store as st
from . import wiring
from .config import API_HASH, API_ID, BOT_TOKEN, DB_PATH, OWNER_IDS
from .db import DB

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)


async def _seed_groups(app: Application) -> None:
    """Purane groups (is update se pehle wale) ko Connected Groups list me daalo."""
    s = st.get()
    for cid, title in app.bot_data["db"].chats():
        try:
            m = await app.bot.get_chat_member(cid, app.bot.id)
            if m.status not in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
                s.remember_bot_group(app.bot.id, cid, title or "")
        except TelegramError:
            pass
        except Exception:
            return
        await asyncio.sleep(0.05)


async def post_init(app: Application):
    me = app.bot
    log.info("✅ Token is bot ka hai: @%s (%s, id=%s) — Telegram me isi bot ko message kijiye",
             me.username, me.first_name, me.id)
    try:
        wh = await app.bot.get_webhook_info()
        if wh.url:
            log.warning("⚠️ Is token par webhook laga tha (%s) — hata raha hoon, warna polling ko messages nahi milte",
                        wh.url)
    except Exception as e:
        log.warning("webhook info nahi mili: %s", e)
    await hub.setup(app)
    await wiring.set_commands(app, master=True)
    cloner.init(app)
    app.bot_data["bg_tasks"] = [
        asyncio.create_task(cloner.boot_all()),   # saare active clones dobara live
        asyncio.create_task(_seed_groups(app)),
    ]


async def post_shutdown(app: Application):
    await cloner.stop_all()


def main():
    if not BOT_TOKEN:
        sys.exit("BOT_TOKEN missing — Render → Environment me apna token daaliye.")
    logging.info("Owner IDs loaded: %d · default API for generator: %s", len(OWNER_IDS), bool(API_ID and API_HASH))

    app = (Application.builder().token(BOT_TOKEN)
           .post_init(post_init).post_shutdown(post_shutdown).build())
    sessions = ss.SessionStore(DB_PATH)
    st.STORE = st.Store(DB_PATH, ss._load_key())
    app.bot_data["db"] = DB(DB_PATH)
    app.bot_data["sessions"] = sessions
    app.bot_data["store"] = st.STORE
    app.bot_data["is_clone"] = False
    wiring.register(app)

    keepalive.start()
    logging.info("Bot starting…")
    # drop_pending_updates=False: deploy ke dauraan bheje gaye commands ka bhi jawab milega
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)


if __name__ == "__main__":
    main()
