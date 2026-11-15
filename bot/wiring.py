"""Handlers ka registration — master bot aur har clone dono yahi use karte hain."""
from telegram import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatJoinRequestHandler,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from . import cloner
from . import guard
from . import handlers as h
from . import hub
from . import owner
from . import sessgen as sg
from . import sessions as ss
from . import sessrevoke as sr
from . import store as st
from .config import OWNER_IDS


async def _track_update(update: Update, context) -> None:
    """group=-11: kis bot par update aaya + users record + request counter. Kuch block nahi karta."""
    st.current_bot.set("clone:@" + (context.bot.username or "") if context.bot_data.get("is_clone") else "master")
    s = st.get()
    if s is None:
        return
    try:
        if update.effective_user:
            s.touch_user(update.effective_user)
        msg = update.effective_message
        if update.callback_query or (msg and msg.text and msg.text.startswith("/")):
            s.incr("requests")
    except Exception:
        pass


def register(app: Application) -> None:
    app.add_handler(TypeHandler(Update, _track_update), group=-11)
    # Hub activity report — kisi handler ko rokta nahi
    app.add_handler(MessageHandler(filters.COMMAND, hub.on_any_command), group=-10)
    app.add_handler(ChatMemberHandler(hub.on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER), group=-10)
    # Group Admin check: bot admin nahi to group me kuch nahi chalega (warning milegi)
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.StatusUpdate.ALL, guard.gate_message), group=-9)
    app.add_handler(CallbackQueryHandler(guard.gate_callback), group=-9)
    app.add_handler(ChatMemberHandler(guard.on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER), group=-9)

    app.add_handler(CommandHandler("start", h.cmd_start))
    app.add_handler(CommandHandler(["help", "menu"], h.cmd_start))
    app.add_handler(CommandHandler("id", h.cmd_id))
    app.add_handler(CommandHandler(["panel", "settings", "admin"], owner.cmd_panel))
    app.add_handler(CommandHandler("clone", cloner.cmd_clone))
    app.add_handler(CommandHandler("welcome", h.cmd_welcome))
    app.add_handler(CommandHandler(["approve", "autoapprove"], h.cmd_approve))
    app.add_handler(CommandHandler("secpanel", h.cmd_secpanel))
    app.add_handler(CommandHandler("punish", h.cmd_punish))
    app.add_handler(CommandHandler("lockdown", h.cmd_lockdown))
    app.add_handler(CommandHandler("unlock", h.cmd_unlock))
    app.add_handler(CommandHandler("warn", h.cmd_warn))
    app.add_handler(CommandHandler("unwarn", h.cmd_unwarn))
    app.add_handler(CommandHandler("warns", h.cmd_warns))
    app.add_handler(CommandHandler("cancel", owner.cmd_cancel))
    app.add_handler(CommandHandler(["session", "genstring", "string"], sg.cmd_session))
    app.add_handler(CommandHandler(["revoke", "revokestring"], sr.cmd_revoke))
    app.add_handler(CommandHandler("sessions", ss.cmd_sessions))
    app.add_handler(CallbackQueryHandler(owner.on_callback, pattern=r"^op:"))
    app.add_handler(CallbackQueryHandler(sg.on_callback, pattern=r"^sg:"))
    app.add_handler(CallbackQueryHandler(sr.on_callback, pattern=r"^sr:"))
    app.add_handler(CallbackQueryHandler(ss.on_session_callback, pattern=r"^ss:"))
    app.add_handler(CallbackQueryHandler(h.on_menu_callback, pattern=r"^(m:|g:)"))
    app.add_handler(CallbackQueryHandler(h.on_callback))
    app.add_handler(ChatJoinRequestHandler(h.on_join_request))
    app.add_handler(ChatMemberHandler(h.on_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(h.on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    private_text = filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND
    # private text: owner panel input, session revoke, generator, group-settings input, sessions manager
    app.add_handler(MessageHandler(private_text, owner.on_text), group=-4)
    app.add_handler(MessageHandler(private_text, sr.on_text), group=-3)
    app.add_handler(MessageHandler(private_text, sg.on_text), group=-2)
    app.add_handler(MessageHandler(private_text, h.on_private_input), group=-1)
    app.add_handler(MessageHandler(private_text, ss.on_private_text), group=0)
    # group: admin ka text input pehle (group 0), phir moderation (group 1)
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, h.on_text_input), group=0)
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.StatusUpdate.ALL, h.moderate), group=1)
    app.add_error_handler(on_error)


async def on_error(update: object, context) -> None:
    s = st.get()
    if s:
        try:
            s.incr("failed")
        except Exception:
            pass
    await h.on_error(update, context)


GROUP_CMDS = [
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
]
PRIVATE_CMDS = [
    BotCommand("start", "Main menu"),
    BotCommand("clone", "🤖 Apna clone bot banao"),
    BotCommand("session", "🔑 Session string generator"),
    BotCommand("revoke", "♻️ Session string revoke karo"),
    BotCommand("panel", "⚙️ Group settings"),
    BotCommand("welcome", "👋 Welcome message"),
    BotCommand("approve", "✅ Auto-approve requests"),
    BotCommand("id", "Apni Telegram ID dekho"),
    BotCommand("cancel", "Cancel"),
]


async def set_commands(app: Application, master: bool) -> None:
    await app.bot.set_my_commands(GROUP_CMDS, scope=BotCommandScopeAllGroupChats())
    await app.bot.set_my_commands(PRIVATE_CMDS, scope=BotCommandScopeAllPrivateChats())
    if not master:
        return
    owner_cmds = [BotCommand("panel", "🎛️ Owner Control Center")] + [c for c in PRIVATE_CMDS if c.command != "panel"]
    owner_cmds.append(BotCommand("sessions", "📂 Saved sessions manager"))
    for oid in OWNER_IDS:
        try:
            await app.bot.set_my_commands(owner_cmds, scope=BotCommandScopeChat(oid))
        except Exception:
            pass
