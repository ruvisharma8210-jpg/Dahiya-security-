import asyncio
import html
import logging
import re
import time
from collections import deque

from telegram import (
    ChatMember,
    ChatPermissions,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.constants import ChatType, MessageEntityType, ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ApplicationHandlerStop, ContextTypes

from . import hub
from .db import DEFAULT_APPROVE_DM, DEFAULT_WELCOME, DB
from .panels import build, final_label
from .utils import (
    ANON_ADMIN_ID,
    DEFAULT_PERMS,
    ban,
    fmt_dur,
    is_admin,
    mention,
    mute,
    parse_dur,
    render_welcome,
    safe_delete,
)

log = logging.getLogger(__name__)
GROUPS = (ChatType.GROUP, ChatType.SUPERGROUP)


def db_of(context: ContextTypes.DEFAULT_TYPE) -> DB:
    return context.bot_data["db"]


async def sender_is_admin(update: Update, context) -> bool:
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if msg and msg.sender_chat and msg.sender_chat.id == chat.id:  # anonymous admin
        return True
    if user is None or user.id == ANON_ADMIN_ID:
        return False
    return await is_admin(context.bot, chat.id, user.id)


async def require_group_admin(update: Update, context) -> bool:
    chat = update.effective_chat
    if chat.type not in GROUPS:
        await update.effective_message.reply_text("Ye command group me use karein (bot ko admin banake).")
        return False
    if not await sender_is_admin(update, context):
        await update.effective_message.reply_text("⛔ Sirf group admins ye use kar sakte hain.")
        return False
    return True


# ------------------------------------------------------------------ commands
def start_menu(user_id: int, bot_username: str):
    from .config import OWNER_IDS
    url = (
        f"https://t.me/{bot_username}?startgroup=true"
        "&admin=delete_messages+restrict_members+invite_users+pin_messages+manage_chat"
    )
    text = (
        "<b>👋 Group Guard Bot</b>\n\n"
        "Neeche buttons se sab kuch kijiye:\n"
        "• <b>➕ Add to Group</b> — mujhe group me add karke admin banaiye\n"
        "• <b>⚙️ Group Settings</b> — Welcome, Auto-Approve, Security sab yahin se\n"
        "• <b>🔑 Session String</b> 🔒 — sirf admin ki permission wale users ke liye\n"
        "• <b>♻️ Revoke</b> — purani string band karke nayi lijiye\n"
        "• <b>🤖 Clone</b> — <code>/clone TOKEN</code> se apna khud ka bot\n\n"
        f"Aapki Telegram ID: <code>{user_id}</code>"
    )
    kb = [
        [InlineKeyboardButton("➕ Add to Group", url=url)],
        [InlineKeyboardButton("⚙️ Group Settings", callback_data="g:list:main")],
        [InlineKeyboardButton("👋 Welcome Message", callback_data="g:list:welcome"),
         InlineKeyboardButton("✅ Auto-Approve", callback_data="g:list:approve")],
        [InlineKeyboardButton("🔑 Session String Generator 🔒", callback_data="sg:home")],
        [InlineKeyboardButton("♻️ Revoke Session String", callback_data="sr:start")],
        [InlineKeyboardButton("🤖 Apna Clone Bot banao", callback_data="m:clone")],
    ]
    if user_id in OWNER_IDS:
        kb.insert(0, [InlineKeyboardButton("🎛️ Owner Control Center", callback_data="op:home")])
        kb.append([InlineKeyboardButton("📂 Saved Sessions Manager (owner)", callback_data="ss:home")])
    return text, InlineKeyboardMarkup(kb)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in GROUPS:
        db_of(context).remember_chat(update.effective_chat.id, update.effective_chat.title)
        await update.effective_message.reply_text("✅ Bot active hai. Admins /panel use karein.")
        return
    me = await context.bot.get_me()
    text, kb = start_menu(update.effective_user.id, me.username)
    await update.effective_message.reply_html(text, reply_markup=kb)


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from .config import OWNER_IDS
    u = update.effective_user
    is_owner = "✅ haan" if u.id in OWNER_IDS else "❌ nahi"
    await update.effective_message.reply_html(
        f"🆔 Aapki ID: <code>{u.id}</code>\nChat ID: <code>{update.effective_chat.id}</code>\n"
        f"Bot ko owner IDs mili: <b>{len(OWNER_IDS)}</b> · Aap owner ho: {is_owner}"
    )


async def admin_groups(context, user_id: int) -> list[tuple[int, str]]:
    """Wo groups jahan bot hai aur user admin hai."""
    out = []
    db = db_of(context)
    for cid, title in db.chats():
        try:
            if await is_admin(context.bot, cid, user_id):
                out.append((cid, title))
        except TelegramError:
            continue
    return out


async def group_picker(context, user_id: int, panel: str):
    groups = await admin_groups(context, user_id)
    if not groups:
        text = (
            "<b>⚙️ Group Settings</b>\n\n"
            "<i>Mujhe aapka koi group nahi mila jahan aap admin ho.</i>\n\n"
            "1. ➕ Add to Group se mujhe group me add karein aur admin banaiye\n"
            "2. Group me ek baar <code>/start</code> ya <code>/panel</code> bhejiye\n"
            "3. Phir yahan wapas aaiye"
        )
        kb = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"g:list:{panel}")],
              [InlineKeyboardButton("« Menu", callback_data="m:home")]]
        return text, InlineKeyboardMarkup(kb)
    kb = [[InlineKeyboardButton(f"👥 {title or cid}"[:60], callback_data=f"g:sel:{panel}:{cid}")]
          for cid, title in groups[:40]]
    kb.append([InlineKeyboardButton("« Menu", callback_data="m:home")])
    return "<b>⚙️ Kaunsa group manage karna hai?</b>", InlineKeyboardMarkup(kb)


async def _open(update: Update, context, panel: str):
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE:
        text, kb = await group_picker(context, update.effective_user.id, panel)
        await update.effective_message.reply_html(text, reply_markup=kb)
        return
    if not await require_group_admin(update, context):
        return
    db_of(context).remember_chat(chat.id, chat.title)
    text, kb = build(panel, db_of(context), chat.id, chat.title)
    await update.effective_message.reply_html(text, reply_markup=kb)


async def cmd_panel(update, context): await _open(update, context, "main")
async def cmd_welcome(update, context): await _open(update, context, "welcome")
async def cmd_approve(update, context): await _open(update, context, "approve")
async def cmd_secpanel(update, context): await _open(update, context, "sec")
async def cmd_punish(update, context): await _open(update, context, "punish")


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == ChatType.PRIVATE:
        from .sessgen import cancel_flow
        from .sessions import cancel_private
        if context.user_data.pop("awaiting", None):
            await update.effective_message.reply_text("❌ Cancelled.")
            return
        if await cancel_flow(update, context):
            return
        from .sessrevoke import cancel_flow as cancel_revoke
        if await cancel_revoke(update, context):
            return
        await cancel_private(update, context)
        return
    aw = context.chat_data.get("awaiting")
    if aw and update.effective_user and aw["uid"] == update.effective_user.id:
        context.chat_data.pop("awaiting", None)
        await update.effective_message.reply_text("❌ Cancelled.")


async def set_lockdown(context, chat_id: int, on: bool) -> bool:
    db = db_of(context)
    try:
        if on:
            chat = await context.bot.get_chat(chat_id)
            if chat.permissions and not db.get(chat_id)["lockdown"]:
                db.set(chat_id, "saved_perms", chat.permissions.to_dict())
            await context.bot.set_chat_permissions(chat_id, ChatPermissions.no_permissions())
        else:
            saved = db.get(chat_id).get("saved_perms")
            perms = ChatPermissions.de_json(saved, context.bot) if saved else DEFAULT_PERMS
            if perms is None or not perms.can_send_messages:
                perms = DEFAULT_PERMS
            await context.bot.set_chat_permissions(chat_id, perms)
    except TelegramError as e:
        log.warning("lockdown failed: %s", e)
        return False
    db.set(chat_id, "lockdown", on)
    hub.track("moderation", chat=_ChatRef(chat_id, db_title(db, chat_id)), detail="lockdown ON" if on else "lockdown OFF")
    return True


def db_title(db, chat_id: int) -> str:
    return next((t for c, t in db.chats() if c == chat_id), "")


async def cmd_lockdown(update: Update, context):
    if not await require_group_admin(update, context):
        return
    ok = await set_lockdown(context, update.effective_chat.id, True)
    await update.effective_message.reply_text(
        "🔒 LOCKDOWN ON — ab koi member message nahi bhej sakta. /unlock se kholein." if ok
        else "⚠️ Lockdown fail hua. Bot ko 'Ban users / Restrict' admin right dein."
    )


async def cmd_unlock(update: Update, context):
    if not await require_group_admin(update, context):
        return
    ok = await set_lockdown(context, update.effective_chat.id, False)
    await update.effective_message.reply_text("🔓 Lockdown OFF — group khul gaya." if ok else "⚠️ Unlock fail hua.")


async def cmd_warn(update: Update, context):
    if not await require_group_admin(update, context):
        return
    msg = update.effective_message
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_text("Kisi message ko reply karke /warn likhein.")
        return
    target = msg.reply_to_message.from_user
    if await is_admin(context.bot, msg.chat.id, target.id):
        await msg.reply_text("Admin ko warn nahi kar sakte.")
        return
    reason = " ".join(context.args) or "admin warning"
    await warn_user(context, msg.chat, target, reason)


async def cmd_unwarn(update: Update, context):
    if not await require_group_admin(update, context):
        return
    msg = update.effective_message
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_text("Kisi message ko reply karke /unwarn likhein.")
        return
    target = msg.reply_to_message.from_user
    db_of(context).reset_warns(msg.chat.id, target.id)
    await msg.reply_html(f"✅ {mention(target)} ki saari warnings reset.")


async def cmd_warns(update: Update, context):
    msg = update.effective_message
    if msg.chat.type not in GROUPS:
        return
    target = msg.reply_to_message.from_user if msg.reply_to_message and msg.reply_to_message.from_user else msg.from_user
    s = db_of(context).get(msg.chat.id)
    n = db_of(context).get_warns(msg.chat.id, target.id)
    await msg.reply_html(f"⚠️ {mention(target)}: <b>{n}/{s['warn_limit']}</b> warnings")


# ------------------------------------------------------------------ punishments
async def apply_final(context, chat, user, s) -> str:
    fa = s["final_action"]
    if fa == "mute":
        await mute(context.bot, chat.id, user.id, s["mute_duration"])
    elif fa == "ban":
        await ban(context.bot, chat.id, user.id, s["ban_duration"])
    else:
        await ban(context.bot, chat.id, user.id, 0)
    return final_label(s)


async def warn_user(context, chat, user, reason: str):
    db = db_of(context)
    s = db.get(chat.id)
    count = db.add_warn(chat.id, user.id)
    limit = max(1, int(s["warn_limit"]))
    if count >= limit:
        db.reset_warns(chat.id, user.id)
        label = await apply_final(context, chat, user, s)
        hub.track("moderation", chat=chat, user=user, detail=f"{label} ({reason})")
        text = f"🚫 {mention(user)} ne {limit}/{limit} warnings poori kar li — <b>{label}</b>.\nReason: {html.escape(reason)}"
    else:
        hub.track("moderation", chat=chat, user=user, detail=f"warn {count}/{limit} ({reason})")
        text = f"⚠️ {mention(user)} warning <b>{count}/{limit}</b>\nReason: {html.escape(reason)}"
    try:
        await context.bot.send_message(chat.id, text, parse_mode=ParseMode.HTML)
    except TelegramError:
        pass


# ------------------------------------------------------------------ callbacks
class _ChatRef:
    """Private chat se group manage karte waqt group ki id/title."""
    def __init__(self, cid: int, title: str):
        self.id, self.title = cid, title


async def on_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """m:home (private menu) aur g:list / g:sel (group picker)."""
    q = update.callback_query
    data = q.data or ""
    if q.message is None or q.message.chat.type != ChatType.PRIVATE:
        await q.answer()
        return
    parts = data.split(":")
    if data == "m:clone":
        from .cloner import USAGE
        await q.answer()
        text, kb = USAGE, InlineKeyboardMarkup([[InlineKeyboardButton("« Menu", callback_data="m:home")]])
    elif parts[0] == "m":
        await q.answer()
        me = await context.bot.get_me()
        text, kb = start_menu(q.from_user.id, me.username)
    elif parts[1] == "list":
        await q.answer("⏳")
        text, kb = await group_picker(context, q.from_user.id, parts[2])
    else:  # g:sel:<panel>:<cid>
        panel, cid = parts[2], int(parts[3])
        if not await is_admin(context.bot, cid, q.from_user.id):
            await q.answer("⛔ Aap is group me admin nahi ho", show_alert=True)
            return
        title = dict(db_of(context).chats()).get(cid, str(cid))
        context.user_data["target"] = (cid, title)
        await q.answer()
        text, kb = build(panel, db_of(context), cid, title)
        kb = InlineKeyboardMarkup(list(kb.inline_keyboard) + [[InlineKeyboardButton("🔁 Group badlo", callback_data=f"g:list:{panel}")]])
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            await q.message.reply_html(text, reply_markup=kb)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    msg = q.message
    if msg is None:
        await q.answer()
        return
    if data == "noop":
        await q.answer()
        return
    if msg.chat.type in GROUPS:
        chat = _ChatRef(msg.chat.id, msg.chat.title)
    else:
        t = context.user_data.get("target")
        if not t:
            await q.answer("Pehle group chuniye: /panel", show_alert=True)
            return
        chat = _ChatRef(*t)
    if not await is_admin(context.bot, chat.id, q.from_user.id):
        await q.answer("⛔ Sirf admins ke liye", show_alert=True)
        return
    db = db_of(context)

    if data == "x":
        await q.answer()
        await safe_delete(msg)
        return

    kind, _, rest = data.partition(":")
    if kind == "p":
        await q.answer()
        await refresh(msg, db, rest, chat)
    elif kind == "t":
        panel, path = rest.split(":", 1)
        val = db.toggle(chat.id, path)
        await q.answer("🟢 ON" if val else "🔴 OFF")
        await refresh(msg, db, panel, chat)
    elif kind == "s":
        panel, path, raw = rest.split(":", 2)
        value = int(raw) if raw.lstrip("-").isdigit() else raw
        db.set(chat.id, path, value)
        await q.answer("✅ Saved")
        await refresh(msg, db, panel, chat)
    elif kind == "i":
        panel, what = rest.split(":", 1)
        await ask_input(q, context, panel, what, chat)
    elif kind == "a":
        panel, action = rest.split(":", 1)
        await run_action(q, context, panel, action, chat)
    else:
        await q.answer()


async def refresh(msg: Message, db: DB, panel: str, chat=None):
    chat = chat or msg.chat
    text, kb = build(panel, db, chat.id, chat.title)
    if msg.chat.type == ChatType.PRIVATE:
        kb = InlineKeyboardMarkup(list(kb.inline_keyboard) + [[InlineKeyboardButton("🔁 Group badlo", callback_data=f"g:list:{panel}")]])
    try:
        await msg.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            log.warning("edit failed: %s", e)


PROMPTS = {
    "welcome": "✏️ Naya welcome message bhejiye.\nPlaceholders: <code>{name}</code> <code>{first_name}</code> "
               "<code>{username}</code> <code>{id}</code> <code>{mention}</code> <code>{group}</code>\n"
               "Example: <code>Welcome {name}, your ID is {id}</code>",
    "approve_dm": "✏️ Approve hone par user ko jaane wala DM text bhejiye.\nPlaceholders: <code>{name}</code> "
                  "<code>{first_name}</code> <code>{username}</code> <code>{id}</code> <code>{mention}</code> <code>{group}</code>",
    "add_word": "➕ Ban karne wale word(s) bhejiye (comma ya new line se alag).",
    "rm_word": "🗑️ Hatane wale word(s) bhejiye (comma ya new line se alag).",
    "add_domain": "➕ Trusted domain bhejiye, jaise <code>youtube.com</code> ya <code>t.me/yourchannel</code>",
    "rm_domain": "➖ Hatane wala domain bhejiye.",
    "mute_custom": "⏳ Mute time bhejiye: <code>15m</code>, <code>2h</code>, <code>3d</code>, <code>1w</code> ya <code>perm</code>",
    "warn_custom": "⚠️ Warning limit number bhejiye (1–20).",
}


async def ask_input(q, context, panel: str, what: str, chat):
    await q.answer()
    aw = {
        "uid": q.from_user.id, "kind": what, "panel": panel, "cid": chat.id, "title": chat.title,
        "panel_msg": q.message.message_id, "panel_chat": q.message.chat.id, "ts": time.time(),
    }
    if q.message.chat.type == ChatType.PRIVATE:
        context.user_data["awaiting"] = aw
        await q.message.reply_html(f"{PROMPTS[what]}\n\n<i>/cancel se rokein</i>")
        return
    context.chat_data["awaiting"] = aw
    await q.message.reply_html(
        f"{mention(q.from_user)} {PROMPTS[what]}\n\n<i>Is message ko reply karein · /cancel</i>",
        reply_markup=ForceReply(selective=True),
    )


async def run_action(q, context, panel: str, action: str, chat):
    db = db_of(context)
    if action == "preview":
        s = db.get(chat.id)
        await q.answer()
        await q.message.reply_html("👁️ <b>Preview:</b>\n\n" + render_welcome(s["welcome_text"], q.from_user, chat))
    elif action == "welcome_reset":
        db.set(chat.id, "welcome_text", DEFAULT_WELCOME)
        await q.answer("♻️ Reset")
        await refresh(q.message, db, panel, chat)
    elif action == "approve_preview":
        s = db.get(chat.id)
        await q.answer()
        await q.message.reply_html("👁️ <b>DM Preview:</b>\n\n" + render_welcome(s["approve_dm_text"], q.from_user, chat))
    elif action == "approve_reset":
        db.set(chat.id, "approve_dm_text", DEFAULT_APPROVE_DM)
        await q.answer("♻️ Reset")
        await refresh(q.message, db, panel, chat)
    elif action == "lockdown":
        on = not db.get(chat.id)["lockdown"]
        ok = await set_lockdown(context, chat.id, on)
        if not ok:
            await q.answer("⚠️ Fail — bot ko Restrict/Ban rights dein", show_alert=True)
            return
        await q.answer("🔒 Group LOCKED" if on else "🔓 Group UNLOCKED", show_alert=True)
        await refresh(q.message, db, panel, chat)
        await context.bot.send_message(
            chat.id, "🚨 <b>LOCKDOWN ON</b> — admins ke alawa koi message nahi bhej sakta." if on
            else "🔓 <b>Lockdown OFF</b> — group normal ho gaya.", parse_mode=ParseMode.HTML)
    elif action == "list_words":
        words = db.words(chat.id)
        await q.answer()
        body = "\n".join(f"• {html.escape(w)}" for w in words) or "<i>List khaali hai.</i>"
        text = f"<b>📋 Banned words ({html.escape(chat.title or '')}) — {len(words)}</b>\n\n{body}"
        try:  # pehle admin ke DM me bhejo taaki group me words na dikhen
            await context.bot.send_message(q.from_user.id, text[:4000], parse_mode=ParseMode.HTML)
            if q.message.chat.type != ChatType.PRIVATE:
                await q.message.reply_text("📬 List aapke DM me bhej di.")
        except (Forbidden, BadRequest):
            await q.message.reply_html(f"<tg-spoiler>{text[:3900]}</tg-spoiler>\n\n<i>(Bot ko DM me /start karein to list private aayegi)</i>")
    else:
        await q.answer()


# ------------------------------------------------------------------ text input capture
DOMAIN_RE = re.compile(r"^(?:https?://)?(?:www\.)?([a-z0-9\-._~/]+)$", re.I)


async def _apply_input(context, aw: dict, msg: Message) -> None:
    db = db_of(context)
    chat_id = aw.get("cid", msg.chat.id)
    chat = _ChatRef(chat_id, aw.get("title") or msg.chat.title)
    text = msg.text.strip()
    kind = aw["kind"]
    items = [x.strip() for x in re.split(r"[,\n]", text) if x.strip()]

    if kind == "welcome":
        db.set(chat_id, "welcome_text", text[:3000])
        reply = "✅ Welcome message update ho gaya.\n\n👁️ " + render_welcome(text[:3000], msg.from_user, chat)
    elif kind == "approve_dm":
        db.set(chat_id, "approve_dm_text", text[:3000])
        reply = "✅ DM text update ho gaya.\n\n👁️ " + render_welcome(text[:3000], msg.from_user, chat)
    elif kind == "add_word":
        added = [w for w in items if db.add_word(chat_id, w)]
        reply = f"✅ {len(added)} word(s) add hue." if added else "ℹ️ Koi naya word nahi (pehle se list me hain)."
        await safe_delete(msg)  # bad word group me na dikhe
    elif kind == "rm_word":
        removed = [w for w in items if db.remove_word(chat_id, w)]
        reply = f"🗑️ {len(removed)} word(s) hata diye." if removed else "ℹ️ Ye word list me nahi mile."
        await safe_delete(msg)
    elif kind in ("add_domain", "rm_domain"):
        done = []
        for it in items:
            m = DOMAIN_RE.match(it.lower())
            if not m:
                continue
            d = m.group(1).rstrip("/")
            ok = db.add_domain(chat_id, d) if kind == "add_domain" else db.remove_domain(chat_id, d)
            if ok:
                done.append(d)
        verb = "add" if kind == "add_domain" else "remove"
        reply = f"✅ {verb}: {', '.join(done)}" if done else "ℹ️ Kuch change nahi hua."
    elif kind == "mute_custom":
        secs = parse_dur(text)
        if secs is None:
            reply = "⚠️ Galat format. Example: 15m, 2h, 3d, perm"
        else:
            db.set(chat_id, "mute_duration", secs)
            reply = f"✅ Mute duration: {fmt_dur(secs)}"
    elif kind == "warn_custom":
        if text.isdigit() and 1 <= int(text) <= 20:
            db.set(chat_id, "warn_limit", int(text))
            reply = f"✅ Warning limit: {int(text)}"
        else:
            reply = "⚠️ 1 se 20 ke beech number bhejiye."
    else:
        reply = "OK"

    await context.bot.send_message(msg.chat.id, reply, parse_mode=ParseMode.HTML)
    # panel message ko refresh karo
    t, kb = build(aw["panel"], db, chat_id, chat.title)
    if msg.chat.type == ChatType.PRIVATE:
        kb = InlineKeyboardMarkup(list(kb.inline_keyboard) + [[InlineKeyboardButton("🔁 Group badlo", callback_data=f"g:list:{aw['panel']}")]])
    try:
        await context.bot.edit_message_text(t, aw.get("panel_chat", msg.chat.id), aw["panel_msg"],
                                            reply_markup=kb, parse_mode=ParseMode.HTML)
    except TelegramError:
        pass


async def on_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    aw = context.chat_data.get("awaiting")
    if not aw or not msg or not msg.from_user or msg.from_user.id != aw["uid"] or not msg.text:
        return
    context.chat_data.pop("awaiting", None)
    if time.time() - aw["ts"] > 300:
        return
    await _apply_input(context, aw, msg)
    raise ApplicationHandlerStop


async def on_private_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Private chat se group settings ka text input (welcome text, words, ...)."""
    msg = update.effective_message
    aw = context.user_data.get("awaiting")
    if not aw or not msg or not msg.text:
        return
    context.user_data.pop("awaiting", None)
    if time.time() - aw["ts"] > 300:
        await msg.reply_text("⌛ Time khatam. Button dobara dabaiye.")
        raise ApplicationHandlerStop
    if not await is_admin(context.bot, aw["cid"], msg.from_user.id):
        await msg.reply_text("⛔ Aap is group me admin nahi ho.")
        raise ApplicationHandlerStop
    await _apply_input(context, aw, msg)
    raise ApplicationHandlerStop


# ------------------------------------------------------------------ moderation
def message_domains(msg: Message) -> list[str]:
    found = []
    for ents, text in ((msg.entities, msg.text), (msg.caption_entities, msg.caption)):
        if not ents or not text:
            continue
        for e in ents:
            if e.type == MessageEntityType.URL:
                found.append(msg.parse_entity(e) if text is msg.text else msg.parse_caption_entity(e))
            elif e.type == MessageEntityType.TEXT_LINK and e.url:
                found.append(e.url)
    return found


def is_allowed(url: str, allowed: list[str]) -> bool:
    u = re.sub(r"^(?:https?://)?(?:www\.)?", "", url.lower())
    for d in allowed:
        if u == d or u.startswith(d + "/") or u.startswith(d + "?"):
            return True
        host = u.split("/")[0]
        if "/" not in d and (host == d or host.endswith("." + d)):
            return True
    return False


def find_bad_word(text: str, words: list[str]) -> str | None:
    low = text.lower()
    for w in words:
        if w.isascii():
            if re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", low):
                return w
        elif w in low:
            return w
    return None


async def moderate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat or chat.type not in GROUPS:
        return
    user = msg.from_user
    if user is None or user.id == context.bot.id:
        return
    if msg.sender_chat and msg.sender_chat.id == chat.id:
        return
    if user.id != ANON_ADMIN_ID and await is_admin(context.bot, chat.id, user.id):
        return

    db = db_of(context)
    known = context.bot_data.setdefault("known_chats", set())
    if chat.id not in known:
        known.add(chat.id)
        db.remember_chat(chat.id, chat.title)
    s = db.get(chat.id)

    # 1) Anti-flood
    fl = s["flood"]
    if fl["on"]:
        bucket = context.chat_data.setdefault("flood", {})
        dq = bucket.setdefault(user.id, deque(maxlen=50))
        now = time.time()
        dq.append(now)
        while dq and now - dq[0] > fl["window"]:
            dq.popleft()
        if len(dq) > fl["limit"]:
            dq.clear()
            await safe_delete(msg)
            if fl["action"] == "pban":
                await ban(context.bot, chat.id, user.id, 0)
                label = "banned"
            else:
                secs = int(fl["action"][1:])
                await mute(context.bot, chat.id, user.id, secs)
                label = f"muted {fmt_dur(secs)}"
            hub.track("moderation", chat=chat, user=user, detail=f"flood: {label}")
            await context.bot.send_message(
                chat.id, f"🌊 {mention(user)} flooding ke liye <b>{label}</b>.", parse_mode=ParseMode.HTML)
            return

    text = msg.text or msg.caption or ""

    # 2) Anti-link
    al = s["antilink"]
    if al["on"]:
        urls = message_domains(msg)
        if not urls and re.search(r"(?:https?://|t\.me/|telegram\.me/)", text, re.I):
            urls = re.findall(r"(?:https?://|t\.me/|telegram\.me/)\S+", text, re.I)
        allowed = db.domains(chat.id)
        if any(not is_allowed(u, allowed) for u in urls):
            await safe_delete(msg)
            action = al["action"]
            if action != "warn":
                hub.track("moderation", chat=chat, user=user, detail=f"link: {action}")
            if action == "warn":
                await warn_user(context, chat, user, "link bhejna allowed nahi")
            elif action == "mute":
                await mute(context.bot, chat.id, user.id, al["mute_secs"])
                await context.bot.send_message(
                    chat.id, f"🔇 {mention(user)} link ke liye {fmt_dur(al['mute_secs'])} mute.", parse_mode=ParseMode.HTML)
            elif action == "pban":
                await ban(context.bot, chat.id, user.id, 0)
                await context.bot.send_message(
                    chat.id, f"⛔ {mention(user)} link ke liye permanently banned.", parse_mode=ParseMode.HTML)
            return

    # 3) Bad words
    if s["badwords"]["on"] and text:
        w = find_bad_word(text, db.words(chat.id))
        if w:
            await safe_delete(msg)
            await warn_user(context, chat, user, "banned word")


# ------------------------------------------------------------------ joins / leaves
def _in_chat(m: ChatMember) -> bool:
    if m.status in (ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER):
        return True
    return m.status == ChatMember.RESTRICTED and getattr(m, "is_member", False)


async def on_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmu = update.chat_member
    if not cmu:
        return
    chat = cmu.chat
    user = cmu.new_chat_member.user
    if user.is_bot:
        return
    was_in, now_in = _in_chat(cmu.old_chat_member), _in_chat(cmu.new_chat_member)
    s = db_of(context).get(chat.id)
    joins = context.bot_data.setdefault("joins", {})
    key = (chat.id, user.id)

    if not was_in and now_in:
        joins[key] = time.time()
        if s["welcome_on"]:
            await send_welcome(context, chat, user, s)
    elif was_in and not now_in:
        joined_at = joins.pop(key, None)
        left_self = cmu.new_chat_member.status == ChatMember.LEFT
        if (s["antileft"]["on"] and left_self and joined_at
                and time.time() - joined_at <= s["antileft"]["window"]):
            if await ban(context.bot, chat.id, user.id, 0):
                hub.track("moderation", chat=chat, user=user, detail="anti-left ban")
                await context.bot.send_message(
                    chat.id, f"🚪 {mention(user)} join karke turant left — <b>auto-banned</b>.",
                    parse_mode=ParseMode.HTML)


async def _delete_later(bot, chat_id: int, message_id: int, secs: int):
    await asyncio.sleep(secs)
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramError:
        pass


async def send_welcome(context, chat, user, s):
    last = context.bot_data.setdefault("last_welcome", {})
    try:
        m = await context.bot.send_message(chat.id, render_welcome(s["welcome_text"], user, chat),
                                           parse_mode=ParseMode.HTML)
    except TelegramError as e:
        log.warning("welcome failed: %s", e)
        return
    if s.get("welcome_clean") and chat.id in last:
        try:
            await context.bot.delete_message(chat.id, last[chat.id])
        except TelegramError:
            pass
    last[chat.id] = m.message_id
    if s.get("welcome_delete"):
        asyncio.create_task(_delete_later(context.bot, chat.id, m.message_id, int(s["welcome_delete"])))


async def _approve(context, req, s):
    delay = int(s.get("approve_delay") or 0)
    if delay:
        await asyncio.sleep(delay)
    try:
        await req.approve()
    except TelegramError as e:
        log.warning("approve failed: %s", e)
        return
    db = db_of(context)
    db.set(req.chat.id, "approve_count", int(db.get(req.chat.id).get("approve_count") or 0) + 1)
    hub.track("join_approved", chat=req.chat, user=req.from_user)
    if s.get("approve_dm"):
        try:
            await context.bot.send_message(req.user_chat_id or req.from_user.id,
                                           render_welcome(s["approve_dm_text"], req.from_user, req.chat),
                                           parse_mode=ParseMode.HTML)
        except TelegramError:
            pass  # user ne bot ko block kiya ho / DM band ho


async def on_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    req = update.chat_join_request
    if not req:
        return
    db = db_of(context)
    db.remember_chat(req.chat.id, req.chat.title)
    s = db.get(req.chat.id)
    if s["auto_accept"]:
        if s.get("approve_delay"):
            asyncio.create_task(_approve(context, req, s))
        else:
            await _approve(context, req, s)


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bot kisi group/channel me add ya remove hua — list update karo."""
    cmu = update.my_chat_member
    if not cmu or cmu.chat.type == ChatType.PRIVATE:
        return
    db = db_of(context)
    if cmu.new_chat_member.status in (ChatMember.LEFT, ChatMember.BANNED):
        db.forget_chat(cmu.chat.id)
        context.bot_data.setdefault("known_chats", set()).discard(cmu.chat.id)
    else:
        db.remember_chat(cmu.chat.id, cmu.chat.title)


_conflict = {"first": 0.0, "last_log": 0.0, "count": 0}


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    from telegram.error import Conflict
    if isinstance(context.error, Conflict):
        now = time.time()
        c = _conflict
        if now - c["last_log"] > 300:  # 5 min se koi conflict nahi tha — naya silsila
            c["first"], c["count"] = now, 0
        c["count"] += 1
        if c["count"] == 1 or now - c["last_log"] > 60:
            secs = int(now - c["first"])
            if secs < 90:
                # Render deploy ke time purana instance thodi der chalta hai — ye normal hai
                log.warning("⚠️ Conflict (%ds): purana deploy abhi band ho raha hoga — thoda ruko.", secs)
            else:
                log.error("❌ Conflict %d min se chal raha hai (%d baar): isi BOT_TOKEN se KOI DOOSRA bot "
                          "chal raha hai (doosri Render service, Replit, PC, Railway/Heroku). Use band kijiye "
                          "ya BotFather → /revoke se naya token lekar sirf yahan daaliye. Tab tak messages "
                          "doosre bot ko ja rahe hain.", secs // 60, c["count"])
        c["last_log"] = now
        return
    log.error("Unhandled error", exc_info=context.error)
