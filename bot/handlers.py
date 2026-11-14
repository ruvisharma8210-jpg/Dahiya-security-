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

from .db import DEFAULT_WELCOME, DB
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
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in GROUPS:
        await update.effective_message.reply_text("✅ Bot active hai. Admins /panel use karein.")
        return
    me = await context.bot.get_me()
    url = (
        f"https://t.me/{me.username}?startgroup=true"
        "&admin=delete_messages+restrict_members+invite_users+pin_messages+manage_chat"
    )
    await update.effective_message.reply_html(
        "<b>👋 Group Guard Bot</b>\n\n"
        "Mujhe apne group me add karein aur <b>admin</b> banaiye (Delete, Ban/Restrict, Invite users).\n\n"
        "<b>Commands (group me):</b>\n"
        "/panel – full control panel\n"
        "/welcome – auto-accept & welcome settings\n"
        "/secpanel – security & moderation\n"
        "/punish – punishment durations\n"
        "/lockdown · /unlock – emergency lock\n"
        "/warn · /unwarn · /warns – reply karke\n"
        "/cancel – text input cancel\n\n"
        "<b>Owner (private chat):</b>\n/sessions – 📂 Telethon Sessions Manager",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Add to Group", url=url)]]),
    )


async def _open(update: Update, context, panel: str):
    if not await require_group_admin(update, context):
        return
    chat = update.effective_chat
    text, kb = build(panel, db_of(context), chat.id, chat.title)
    await update.effective_message.reply_html(text, reply_markup=kb)


async def cmd_panel(update, context): await _open(update, context, "main")
async def cmd_welcome(update, context): await _open(update, context, "welcome")
async def cmd_secpanel(update, context): await _open(update, context, "sec")
async def cmd_punish(update, context): await _open(update, context, "punish")


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == ChatType.PRIVATE:
        from .sessions import cancel_private
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
    return True


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
        text = f"🚫 {mention(user)} ne {limit}/{limit} warnings poori kar li — <b>{label}</b>.\nReason: {html.escape(reason)}"
    else:
        text = f"⚠️ {mention(user)} warning <b>{count}/{limit}</b>\nReason: {html.escape(reason)}"
    try:
        await context.bot.send_message(chat.id, text, parse_mode=ParseMode.HTML)
    except TelegramError:
        pass


# ------------------------------------------------------------------ callbacks
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    msg = q.message
    if msg is None or msg.chat.type not in GROUPS:
        await q.answer("Ye panel group me use karein.")
        return
    chat = msg.chat
    if data == "noop":
        await q.answer()
        return
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
        await refresh(msg, db, rest)
    elif kind == "t":
        panel, path = rest.split(":", 1)
        val = db.toggle(chat.id, path)
        await q.answer("🟢 ON" if val else "🔴 OFF")
        await refresh(msg, db, panel)
    elif kind == "s":
        panel, path, raw = rest.split(":", 2)
        value = int(raw) if raw.lstrip("-").isdigit() else raw
        db.set(chat.id, path, value)
        await q.answer("✅ Saved")
        await refresh(msg, db, panel)
    elif kind == "i":
        panel, what = rest.split(":", 1)
        await ask_input(q, context, panel, what)
    elif kind == "a":
        panel, action = rest.split(":", 1)
        await run_action(q, context, panel, action)
    else:
        await q.answer()


async def refresh(msg: Message, db: DB, panel: str):
    text, kb = build(panel, db, msg.chat.id, msg.chat.title)
    try:
        await msg.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            log.warning("edit failed: %s", e)


PROMPTS = {
    "welcome": "✏️ Naya welcome message bhejiye.\nPlaceholders: <code>{name}</code> <code>{first_name}</code> "
               "<code>{username}</code> <code>{id}</code> <code>{mention}</code> <code>{group}</code>\n"
               "Example: <code>Welcome {name}, your ID is {id}</code>",
    "add_word": "➕ Ban karne wale word(s) bhejiye (comma ya new line se alag).",
    "rm_word": "🗑️ Hatane wale word(s) bhejiye (comma ya new line se alag).",
    "add_domain": "➕ Trusted domain bhejiye, jaise <code>youtube.com</code> ya <code>t.me/yourchannel</code>",
    "rm_domain": "➖ Hatane wala domain bhejiye.",
    "mute_custom": "⏳ Mute time bhejiye: <code>15m</code>, <code>2h</code>, <code>3d</code>, <code>1w</code> ya <code>perm</code>",
    "warn_custom": "⚠️ Warning limit number bhejiye (1–20).",
}


async def ask_input(q, context, panel: str, what: str):
    await q.answer()
    context.chat_data["awaiting"] = {
        "uid": q.from_user.id, "kind": what, "panel": panel,
        "panel_msg": q.message.message_id, "ts": time.time(),
    }
    await q.message.reply_html(
        f"{mention(q.from_user)} {PROMPTS[what]}\n\n<i>Is message ko reply karein · /cancel</i>",
        reply_markup=ForceReply(selective=True),
    )


async def run_action(q, context, panel: str, action: str):
    db = db_of(context)
    chat = q.message.chat
    if action == "preview":
        s = db.get(chat.id)
        await q.answer()
        await q.message.reply_html("👁️ <b>Preview:</b>\n\n" + render_welcome(s["welcome_text"], q.from_user, chat))
    elif action == "welcome_reset":
        db.set(chat.id, "welcome_text", DEFAULT_WELCOME)
        await q.answer("♻️ Reset")
        await refresh(q.message, db, panel)
    elif action == "lockdown":
        on = not db.get(chat.id)["lockdown"]
        ok = await set_lockdown(context, chat.id, on)
        if not ok:
            await q.answer("⚠️ Fail — bot ko Restrict/Ban rights dein", show_alert=True)
            return
        await q.answer("🔒 Group LOCKED" if on else "🔓 Group UNLOCKED", show_alert=True)
        await refresh(q.message, db, panel)
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
            await q.message.reply_text("📬 List aapke DM me bhej di.")
        except (Forbidden, BadRequest):
            await q.message.reply_html(f"<tg-spoiler>{text[:3900]}</tg-spoiler>\n\n<i>(Bot ko DM me /start karein to list private aayegi)</i>")
    else:
        await q.answer()


# ------------------------------------------------------------------ text input capture
DOMAIN_RE = re.compile(r"^(?:https?://)?(?:www\.)?([a-z0-9\-._~/]+)$", re.I)


async def on_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    aw = context.chat_data.get("awaiting")
    if not aw or not msg or not msg.from_user or msg.from_user.id != aw["uid"] or not msg.text:
        return
    if time.time() - aw["ts"] > 300:
        context.chat_data.pop("awaiting", None)
        return
    context.chat_data.pop("awaiting", None)
    db = db_of(context)
    chat_id = msg.chat.id
    text = msg.text.strip()
    kind = aw["kind"]
    items = [x.strip() for x in re.split(r"[,\n]", text) if x.strip()]

    if kind == "welcome":
        db.set(chat_id, "welcome_text", text[:3000])
        reply = "✅ Welcome message update ho gaya.\n\n👁️ " + render_welcome(text[:3000], msg.from_user, msg.chat)
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

    await context.bot.send_message(chat_id, reply, parse_mode=ParseMode.HTML)
    # panel message ko refresh karo
    t, kb = build(aw["panel"], db, chat_id, msg.chat.title)
    try:
        await context.bot.edit_message_text(t, chat_id, aw["panel_msg"], reply_markup=kb, parse_mode=ParseMode.HTML)
    except TelegramError:
        pass
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
            try:
                await context.bot.send_message(chat.id, render_welcome(s["welcome_text"], user, chat),
                                               parse_mode=ParseMode.HTML)
            except TelegramError as e:
                log.warning("welcome failed: %s", e)
    elif was_in and not now_in:
        joined_at = joins.pop(key, None)
        left_self = cmu.new_chat_member.status == ChatMember.LEFT
        if (s["antileft"]["on"] and left_self and joined_at
                and time.time() - joined_at <= s["antileft"]["window"]):
            if await ban(context.bot, chat.id, user.id, 0):
                await context.bot.send_message(
                    chat.id, f"🚪 {mention(user)} join karke turant left — <b>auto-banned</b>.",
                    parse_mode=ParseMode.HTML)


async def on_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    req = update.chat_join_request
    if not req:
        return
    if db_of(context).get(req.chat.id)["auto_accept"]:
        try:
            await req.approve()
        except TelegramError as e:
            log.warning("approve failed: %s", e)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled error", exc_info=context.error)
