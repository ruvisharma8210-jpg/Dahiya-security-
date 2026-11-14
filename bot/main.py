import logging
import sys

from telegram import BotCommand, BotCommandScopeAllGroupChats, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatJoinRequestHandler,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from . import handlers as h
from . import sessions as ss
from .config import BOT_TOKEN, DB_PATH, OWNER_IDS
from .db import DB
from . import keepalive

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)


async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("panel", "Full control panel"),
        BotCommand("welcome", "Auto-accept & welcome settings"),
        BotCommand("secpanel", "Security & moderation"),
        BotCommand("punish", "Punishment durations"),
        BotCommand("lockdown", "Emergency lock group"),
        BotCommand("unlock", "Unlock group"),
        BotCommand("warn", "Warn (reply)"),
        BotCommand("unwarn", "Reset warnings (reply)"),
        BotCommand("warns", "Check warnings"),
        BotCommand("cancel", "Cancel text input"),
    ], scope=BotCommandScopeAllGroupChats())
    from telegram import BotCommandScopeChat
    for oid in OWNER_IDS:
        try:
            await app.bot.set_my_commands([
                BotCommand("sessions", "📂 Telethon Sessions Manager"),
                BotCommand("cancel", "Cancel input"),
            ], scope=BotCommandScopeChat(oid))
        except Exception:
            pass


def main():
    if not BOT_TOKEN:
        sys.exit("BOT_TOKEN missing — .env file me apna token daaliye.")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.bot_data["db"] = DB(DB_PATH)
    app.bot_data["sessions"] = ss.SessionStore(DB_PATH)

    app.add_handler(CommandHandler("start", h.cmd_start))
    app.add_handler(CommandHandler("help", h.cmd_start))
    app.add_handler(CommandHandler(["panel", "settings"], h.cmd_panel))
    app.add_handler(CommandHandler("welcome", h.cmd_welcome))
    app.add_handler(CommandHandler("secpanel", h.cmd_secpanel))
    app.add_handler(CommandHandler("punish", h.cmd_punish))
    app.add_handler(CommandHandler("lockdown", h.cmd_lockdown))
    app.add_handler(CommandHandler("unlock", h.cmd_unlock))
    app.add_handler(CommandHandler("warn", h.cmd_warn))
    app.add_handler(CommandHandler("unwarn", h.cmd_unwarn))
    app.add_handler(CommandHandler("warns", h.cmd_warns))
    app.add_handler(CommandHandler("cancel", h.cmd_cancel))
    app.add_handler(CommandHandler("sessions", ss.cmd_sessions))
    app.add_handler(CallbackQueryHandler(ss.on_session_callback, pattern=r"^ss:"))
    app.add_handler(CallbackQueryHandler(h.on_callback))
    app.add_handler(ChatJoinRequestHandler(h.on_join_request))
    app.add_handler(ChatMemberHandler(h.on_chat_member, ChatMemberHandler.CHAT_MEMBER))
    # admin ka text input pehle (group 0), phir moderation (group 1)
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, h.on_text_input), group=0)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, ss.on_private_text), group=0)
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.StatusUpdate.ALL, h.moderate), group=1)
    app.add_error_handler(h.on_error)

    keepalive.start()
    logging.info("Bot starting…")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
