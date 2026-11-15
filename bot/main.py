import logging
import sys

from telegram import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, Update
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
from . import sessgen as sg
from . import sessrevoke as sr
from . import sessions as ss
from .config import API_HASH, API_ID, BOT_TOKEN, DB_PATH, OWNER_IDS
from .db import DB
from . import keepalive
from . import hub

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)


async def post_init(app: Application):
    await hub.setup(app)
    await app.bot.set_my_commands([
        BotCommand("panel", "Full control panel"),
        BotCommand("welcome", "Welcome message settings"),
        BotCommand("approve", "Auto-approve join requests"),
        BotCommand("secpanel", "Security & moderation"),
        BotCommand("punish", "Punishment durations"),
        BotCommand("lockdown", "Emergency lock group"),
        BotCommand("unlock", "Unlock group"),
        BotCommand("warn", "Warn (reply)"),
        BotCommand("unwarn", "Reset warnings (reply)"),
        BotCommand("warns", "Check warnings"),
        BotCommand("cancel", "Cancel text input"),
    ], scope=BotCommandScopeAllGroupChats())
    private_cmds = [
        BotCommand("start", "Main menu"),
        BotCommand("session", "🔑 Session string generator"),
        BotCommand("revoke", "♻️ Session string revoke karo"),
        BotCommand("panel", "⚙️ Group settings"),
        BotCommand("welcome", "👋 Welcome message"),
        BotCommand("approve", "✅ Auto-approve requests"),
        BotCommand("id", "Apni Telegram ID dekho"),
        BotCommand("cancel", "Cancel"),
    ]
    await app.bot.set_my_commands(private_cmds, scope=BotCommandScopeAllPrivateChats())
    from telegram import BotCommandScopeChat
    for oid in OWNER_IDS:
        try:
            await app.bot.set_my_commands(
                private_cmds + [BotCommand("sessions", "📂 Saved sessions manager")], scope=BotCommandScopeChat(oid))
        except Exception:
            pass


def main():
    if not BOT_TOKEN:
        sys.exit("BOT_TOKEN missing — Render → Environment me apna token daaliye.")
    logging.info("Owner IDs loaded: %d · default API for generator: %s", len(OWNER_IDS), bool(API_ID and API_HASH))

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.bot_data["db"] = DB(DB_PATH)
    app.bot_data["sessions"] = ss.SessionStore(DB_PATH)

    # Hub activity report — sabse pehle (group -10), kisi handler ko rokta nahi
    app.add_handler(MessageHandler(filters.COMMAND, hub.on_any_command), group=-10)
    app.add_handler(ChatMemberHandler(hub.on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER), group=-10)
    app.add_handler(CommandHandler("start", h.cmd_start))
    app.add_handler(CommandHandler(["help", "menu"], h.cmd_start))
    app.add_handler(CommandHandler("id", h.cmd_id))
    app.add_handler(CommandHandler(["panel", "settings", "admin"], h.cmd_panel))
    app.add_handler(CommandHandler("welcome", h.cmd_welcome))
    app.add_handler(CommandHandler(["approve", "autoapprove"], h.cmd_approve))
    app.add_handler(CommandHandler("secpanel", h.cmd_secpanel))
    app.add_handler(CommandHandler("punish", h.cmd_punish))
    app.add_handler(CommandHandler("lockdown", h.cmd_lockdown))
    app.add_handler(CommandHandler("unlock", h.cmd_unlock))
    app.add_handler(CommandHandler("warn", h.cmd_warn))
    app.add_handler(CommandHandler("unwarn", h.cmd_unwarn))
    app.add_handler(CommandHandler("warns", h.cmd_warns))
    app.add_handler(CommandHandler("cancel", h.cmd_cancel))
    app.add_handler(CommandHandler(["session", "genstring", "string"], sg.cmd_session))
    app.add_handler(CommandHandler(["revoke", "revokestring"], sr.cmd_revoke))
    app.add_handler(CommandHandler("sessions", ss.cmd_sessions))
    app.add_handler(CallbackQueryHandler(sg.on_callback, pattern=r"^sg:"))
    app.add_handler(CallbackQueryHandler(sr.on_callback, pattern=r"^sr:"))
    app.add_handler(CallbackQueryHandler(ss.on_session_callback, pattern=r"^ss:"))
    app.add_handler(CallbackQueryHandler(h.on_menu_callback, pattern=r"^(m:|g:)"))
    app.add_handler(CallbackQueryHandler(h.on_callback))
    app.add_handler(ChatJoinRequestHandler(h.on_join_request))
    app.add_handler(ChatMemberHandler(h.on_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(h.on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    private_text = filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND
    # private text: pehle session generator, phir group-settings input, phir owner session manager
    app.add_handler(MessageHandler(private_text, sr.on_text), group=-3)
    app.add_handler(MessageHandler(private_text, sg.on_text), group=-2)
    app.add_handler(MessageHandler(private_text, h.on_private_input), group=-1)
    app.add_handler(MessageHandler(private_text, ss.on_private_text), group=0)
    # group: admin ka text input pehle (group 0), phir moderation (group 1)
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, h.on_text_input), group=0)
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.StatusUpdate.ALL, h.moderate), group=1)
    app.add_error_handler(h.on_error)

    keepalive.start()
    logging.info("Bot starting…")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
