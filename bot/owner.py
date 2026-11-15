"""🎛️ Owner Control Center — /panel (sirf OWNER_IDS, bot ke private chat me).

📊 Live Dashboard · 🤖 Clone Management · 🔑 Session Whitelist · 🌐 Connected Groups (remote kick)
🛡️ Security (Anti-Screenshot/Recording) · 📜 Activity Logs (A-Z)
Callback data: op:<action>[:args]
"""
import html
import logging
import re
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton as B
from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import ApplicationHandlerStop, ContextTypes

from . import cloner, guard
from . import handlers as h
from . import store as st
from .config import API_HASH, API_ID, OWNER_IDS

log = logging.getLogger(__name__)

PAGE = 8
LOG_PAGE = 10
IST = timezone(timedelta(hours=5, minutes=30))
ID_RE = re.compile(r"\d{5,}")
E = html.escape

KIND_ICON = {
    "command": "⌨️", "clone_created": "🤖", "clone_updated": "✏️", "clone_deleted": "🗑", "clone_started": "▶️",
    "clone_stopped": "⏹", "clone_error": "⚠️", "session_generated": "🔑", "session_denied": "⛔",
    "whitelist_add": "➕", "whitelist_remove": "➖", "moderation": "🛡️", "join_approved": "✅",
    "bot_added": "📥", "bot_removed": "📤", "group_kicked": "🚪", "admin_missing": "⚠️", "antiss": "📵",
}
FILTER_LABELS = [("all", "Sab"), ("clone", "🤖 Clones"), ("sess", "🔑 Sessions"),
                 ("mod", "🛡️ Moderation"), ("grp", "🌐 Groups"), ("cmd", "⌨️ Commands")]


def is_owner(update: Update, context) -> bool:
    u = update.effective_user
    return bool(u and u.id in OWNER_IDS and not context.bot_data.get("is_clone"))


def _s() -> st.Store:
    s = st.get()
    if s is None:
        raise RuntimeError("store not ready")
    return s


def _ts(ts: float) -> str:
    return datetime.fromtimestamp(ts, IST).strftime("%d %b %H:%M")


def _short(token: str) -> str:
    return token[:6] + "••••••••" + token[-4:] if token else "—"


def _pager(prefix: str, page: int, total: int, per: int, back: str) -> list:
    pages = max(1, -(-total // per))
    row = []
    if page > 0:
        row.append(B("« Prev", callback_data=f"{prefix}:{page - 1}"))
    row.append(B(f"{page + 1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        row.append(B("Next »", callback_data=f"{prefix}:{page + 1}"))
    return [row, [B("« Control Center", callback_data=back)]]


# ------------------------------------------------------------------ screens
def home_screen():
    s = _s()
    text = (
        "<b>🎛️ Owner Control Center</b>\n\n"
        f"🛡️ Anti-Screenshot: {'🟢 ON' if s.flag(guard.ANTISS_FLAG) else '🔴 OFF'}\n"
        f"🤖 Active clones: <b>{len(cloner.RUNNING)}</b>\n"
        f"🔑 Whitelisted users: <b>{len(s.whitelist())}</b>\n\n"
        "Section chuniye:"
    )
    kb = [
        [B("📊 Live Dashboard & Stats", callback_data="op:dash")],
        [B("🤖 Clone Management", callback_data="op:cl:0")],
        [B("🔑 Session Whitelist", callback_data="op:wl:0")],
        [B("🌐 Connected Groups", callback_data="op:gr:0")],
        [B("🛡️ Security & Privacy", callback_data="op:sec")],
        [B("📜 Activity Logs", callback_data="op:lg:all:0")],
        [B("⚙️ Group Settings", callback_data="g:list:main"), B("📂 Saved Sessions", callback_data="ss:home")],
        [B("✖️ Close", callback_data="op:close")],
    ]
    return text, InlineKeyboardMarkup(kb)


def all_groups(context) -> list[tuple[int, int, str, str]]:
    """[(bot_id, chat_id, title, bot_label)] — master + running clones."""
    s = _s()
    out = []
    for bot_id, chat_id, title in s.bot_groups():
        if bot_id == context.bot.id:
            label = "master"
        elif bot_id in cloner.RUNNING:
            label = "@" + (cloner.RUNNING[bot_id].bot.username or str(bot_id))
        else:
            continue
        out.append((bot_id, chat_id, title, label))
    return out


def bot_for(context, bot_id: int):
    if bot_id == context.bot.id:
        return context.bot
    app = cloner.RUNNING.get(bot_id)
    return app.bot if app else None


def dash_screen(context):
    s = _s()
    total, day = s.user_counts()
    reqs, failed = s.counter("requests"), s.counter("failed")
    passed = max(0, reqs - failed)
    clones = s.clones()
    live = sum(1 for c in clones if cloner.is_running(c["bot_id"]))
    text = (
        "<b>📊 Live Dashboard</b>\n\n"
        f"👥 Total users: <b>{total}</b> (24h active: {day})\n"
        f"✅ Requests passed: <b>{passed}</b>\n"
        f"❌ Requests failed: <b>{failed}</b>\n"
        f"👋 Join requests approved: <b>{s.count_kind('join_approved')}</b>\n"
        f"🔑 Session strings generated: <b>{s.count_kind('session_generated')}</b>\n"
        f"🤖 Clones: <b>{live}</b> live / {len(clones)} total\n"
        f"🌐 Connected groups: <b>{len(all_groups(context))}</b>\n"
        f"🛡️ Anti-Screenshot: {'🟢 ON' if s.flag(guard.ANTISS_FLAG) else '🔴 OFF'}\n\n"
        f"<i>Updated {datetime.now(IST).strftime('%d %b %H:%M:%S')} IST</i>"
    )
    kb = [[B("🔄 Refresh", callback_data="op:dash")], [B("« Control Center", callback_data="op:home")]]
    return text, InlineKeyboardMarkup(kb)


def clones_screen(page: int):
    s = _s()
    clones = s.clones()
    page = max(0, min(page, max(0, (len(clones) - 1) // PAGE)))
    chunk = clones[page * PAGE:(page + 1) * PAGE]
    text = f"<b>🤖 Clone Management</b>\n\nTotal clones: <b>{len(clones)}</b>"
    if not clones:
        text += "\n\n<i>Abhi koi clone nahi hai. Koi bhi user bot ko <code>/clone TOKEN</code> bhejkar bana sakta hai.</i>"
    kb = []
    for c in chunk:
        icon = "🟢" if cloner.is_running(c["bot_id"]) else "🔴"
        kb.append([B(f"{icon} @{c['username'] or c['bot_id']} · 👤{c['owner_id']}"[:60], callback_data=f"op:cd:{c['bot_id']}")])
    kb.append([B("➕ Add Clone (token)", callback_data="op:ca")])
    kb += _pager("op:cl", page, len(clones), PAGE, "op:home")
    return text, InlineKeyboardMarkup(kb)


def clone_detail_screen(bot_id: int, reveal: bool = False):
    s = _s()
    c = s.clone(bot_id)
    if not c:
        return None
    token = s.clone_token(bot_id) or ""
    live = cloner.is_running(bot_id)
    text = (
        f"<b>🤖 @{E(c['username'] or '')}</b>\n\n"
        f"📛 Naam: {E(c['name'] or '—')}\n"
        f"🆔 Bot ID: <code>{bot_id}</code>\n"
        f"👤 Owner: <code>{c['owner_id']}</code> ({E(c['owner_name'] or '—')})\n"
        f"🕒 Bana: {_ts(c['created_at'])} IST\n"
        f"📡 Status: {'🟢 LIVE' if live else '🔴 Stopped'}\n"
        f"🔐 Token: <code>{E(token) if reveal else _short(token)}</code>\n"
    )
    if c.get("last_error"):
        text += f"⚠️ Last error: <code>{E(c['last_error'])}</code>\n"
    kb = [
        [B("🙈 Hide Token" if reveal else "👁 Show Token", callback_data=f"op:cd:{bot_id}:{0 if reveal else 1}")],
        [B("⏹ Stop" if live else "▶️ Start", callback_data=f"op:ct:{bot_id}")],
        [B("✏️ Edit Token", callback_data=f"op:ce:{bot_id}:t"), B("👤 Change Owner", callback_data=f"op:ce:{bot_id}:o")],
        [B("🗑 Delete Clone", callback_data=f"op:cx:{bot_id}")],
        [B("« Clones", callback_data="op:cl:0")],
    ]
    return text, InlineKeyboardMarkup(kb)


def whitelist_screen(page: int):
    s = _s()
    rows = s.whitelist()
    page = max(0, min(page, max(0, (len(rows) - 1) // PAGE)))
    chunk = rows[page * PAGE:(page + 1) * PAGE]
    text = (
        "<b>🔑 Session String Whitelist</b>\n\n"
        "Sirf owner aur ye users Session String Generator use kar sakte hain.\n"
        f"Total: <b>{len(rows)}</b>"
    )
    if not rows:
        text += "\n\n<i>List khaali hai — ➕ Add se Telegram ID jodiye.</i>"
    kb = []
    for r in chunk:
        name = s.user_name(r["user_id"]) or r.get("note") or ""
        kb.append([B(f"🗑 {r['user_id']} {name}"[:60], callback_data=f"op:wr:{r['user_id']}:{page}")])
    kb.append([B("➕ Add Telegram ID", callback_data="op:wa")])
    kb += _pager("op:wl", page, len(rows), PAGE, "op:home")
    text += "\n<i>Button par tap = us ID ko hata do.</i>" if rows else ""
    return text, InlineKeyboardMarkup(kb)


def groups_screen(context, page: int):
    groups = all_groups(context)
    page = max(0, min(page, max(0, (len(groups) - 1) // PAGE)))
    chunk = groups[page * PAGE:(page + 1) * PAGE]
    text = f"<b>🌐 Connected Groups</b>\n\nTotal: <b>{len(groups)}</b> (master + clones)"
    if not groups:
        text += "\n\n<i>Bot abhi kisi group me nahi hai.</i>"
    kb = [[B(f"👥 {title or chat_id} · {label}"[:60], callback_data=f"op:gd:{bot_id}:{chat_id}")]
          for bot_id, chat_id, title, label in chunk]
    kb += _pager("op:gr", page, len(groups), PAGE, "op:home")
    return text, InlineKeyboardMarkup(kb)


def security_screen():
    s = _s()
    on = s.flag(guard.ANTISS_FLAG)
    text = (
        "<b>🛡️ Security &amp; Privacy Control</b>\n\n"
        f"📵 Anti-Screenshot &amp; Screen-Recording Lock: {'🟢 ON' if on else '🔴 OFF'}\n\n"
        "ON karte hi bot ke saare groups me Telegram ka <i>Restrict Saving Content</i> lag jata hai — "
        "members chat/media ka screenshot, screen recording, forward ya save nahi kar paate. "
        "Naye groups me bhi apne aap lagta hai.\n\n"
        "<i>Telegram ye setting sirf group Owner (ya session wale account) ko deta hai; jahan fail ho wahan result me dikhega.</i>"
    )
    if not (API_ID and API_HASH):
        text += "\n\n⚠️ <b>API_ID / API_HASH</b> .env me set nahi hain — bina inke lock group me apply nahi ho sakta."
    kb = [
        [B("🔴 Turn OFF" if on else "🟢 Turn ON", callback_data="op:ss:" + ("0" if on else "1"))],
        [B("🔁 Re-apply to all groups", callback_data="op:ss:r")] if on else [],
        [B("« Control Center", callback_data="op:home")],
    ]
    return text, InlineKeyboardMarkup([r for r in kb if r])


def logs_screen(flt: str, page: int):
    s = _s()
    if flt not in st.LOG_FILTERS:
        flt = "all"
    page = max(0, page)
    rows, total = s.logs(flt, offset=page * LOG_PAGE, limit=LOG_PAGE)
    pages = max(1, -(-total // LOG_PAGE))
    if page >= pages:
        page = pages - 1
        rows, total = s.logs(flt, offset=page * LOG_PAGE, limit=LOG_PAGE)
    lines = [f"<b>📜 Activity Logs</b> — {dict(FILTER_LABELS)[flt]} ({total})\n"]
    for r in rows:
        who = ""
        if r["user_id"]:
            who = f" 👤{E(('@' + r['username']) if r['username'] and ' ' not in r['username'] else str(r['user_id']))}"
        where = f" 💬{E(r['chat_title'][:20])}" if r["chat_title"] else ""
        det = f" — {E(r['detail'])}" if r["detail"] else ""
        lines.append(f"{KIND_ICON.get(r['kind'], '•')} <code>{_ts(r['ts'])}</code> [{E(r['bot'] or '?')}]"
                     f"{who}{where} <b>{E(r['kind'])}</b>{det}")
    if not rows:
        lines.append("<i>Abhi koi record nahi.</i>")
    text = "\n".join(lines)[:3900]
    fl = [B(("✅ " if k == flt else "") + lbl, callback_data=f"op:lg:{k}:0") for k, lbl in FILTER_LABELS]
    kb = [fl[:3], fl[3:]]
    nav = []
    if page > 0:
        nav.append(B("« Newer", callback_data=f"op:lg:{flt}:{page - 1}"))
    nav.append(B(f"{page + 1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(B("Older »", callback_data=f"op:lg:{flt}:{page + 1}"))
    kb += [nav, [B("🔄 Refresh", callback_data=f"op:lg:{flt}:{page}"), B("« Control Center", callback_data="op:home")]]
    return text, InlineKeyboardMarkup(kb)


# ------------------------------------------------------------------ handlers
async def cmd_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE and update.effective_user.id in OWNER_IDS and not context.bot_data.get("is_clone"):
        text, kb = home_screen()
        await update.effective_message.reply_html(text, reply_markup=kb)
        return
    await h.cmd_panel(update, context)


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == ChatType.PRIVATE and context.user_data.pop("op_await", None):
        await update.effective_message.reply_text("❌ Cancelled.")
        return
    await h.cmd_cancel(update, context)


async def _show(q, text, kb):
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


def _ask(context, kind: str, **extra):
    context.user_data["op_await"] = {"kind": kind, **extra}


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.message is None or q.message.chat.type != ChatType.PRIVATE or not is_owner(update, context):
        await q.answer("⛔ Ye panel sirf owner ke liye hai.", show_alert=True)
        return
    p = (q.data or "").split(":")[1:]
    act, args = p[0], p[1:]
    s = _s()
    try:
        if act == "close":
            context.user_data.pop("op_await", None)
            await q.answer()
            try:
                await q.message.delete()
            except TelegramError:
                pass
        elif act == "home":
            context.user_data.pop("op_await", None)
            await q.answer()
            await _show(q, *home_screen())
        elif act == "dash":
            await q.answer("🔄")
            await _show(q, *dash_screen(context))
        elif act == "cl":
            await q.answer()
            context.user_data.pop("op_await", None)
            await _show(q, *clones_screen(int(args[0])))
        elif act == "cd":
            scr = clone_detail_screen(int(args[0]), reveal=len(args) > 1 and args[1] == "1")
            await q.answer()
            await _show(q, *(scr or clones_screen(0)))
        elif act == "ct":
            await _toggle_clone(q, context, int(args[0]))
        elif act == "ca":
            _ask(context, "clone_add")
            await q.answer()
            await q.message.reply_html(
                "➕ <b>Naya clone</b>\nBotFather wala token bhejiye (message turant delete ho jayega).\n/cancel se wapas.")
        elif act == "ce":
            bot_id, what = int(args[0]), args[1]
            _ask(context, "clone_token" if what == "t" else "clone_owner", bot_id=bot_id)
            await q.answer()
            await q.message.reply_html(
                "✏️ Is bot ka <b>naya token</b> bhejiye." if what == "t" else "👤 Naye owner ki <b>Telegram ID</b> bhejiye.")
        elif act == "cx":
            await _delete_clone_flow(q, context, int(args[0]), args[1:])
        elif act == "wl":
            await q.answer()
            context.user_data.pop("op_await", None)
            await _show(q, *whitelist_screen(int(args[0])))
        elif act == "wa":
            _ask(context, "wl_add")
            await q.answer()
            await q.message.reply_html(
                "➕ Jin users ko Session String ki permission deni hai unki <b>Telegram ID</b> bhejiye "
                "(ek saath kai IDs bhi — space/comma se alag). /cancel se wapas.")
        elif act == "wr":
            uid, page = int(args[0]), int(args[1])
            if s.remove_whitelist(uid):
                st.log("whitelist_remove", user=update.effective_user, detail=f"removed {uid}", bot="master")
                await q.answer(f"🗑 {uid} hata diya")
            else:
                await q.answer("Ye ID list me nahi mili")
            await _show(q, *whitelist_screen(page))
        elif act == "gr":
            await q.answer()
            await _show(q, *groups_screen(context, int(args[0])))
        elif act == "gd":
            await _group_detail(q, context, int(args[0]), int(args[1]))
        elif act == "gk":
            await _group_kick(q, context, int(args[0]), int(args[1]), args[2:])
        elif act == "sec":
            await q.answer()
            await _show(q, *security_screen())
        elif act == "ss":
            await _toggle_antiss(q, context, args[0])
        elif act == "lg":
            await q.answer()
            await _show(q, *logs_screen(args[0], int(args[1])))
        else:
            await q.answer()
    except TelegramError as e:
        log.warning("owner panel: %s", e)
        try:
            await q.answer("⚠️ Telegram error, dobara try karein", show_alert=True)
        except TelegramError:
            pass


# ------------------------------------------------------------------ clone actions
async def _toggle_clone(q, context, bot_id: int):
    s = _s()
    c = s.clone(bot_id)
    if not c:
        await q.answer("Clone nahi mila", show_alert=True)
        return
    if cloner.is_running(bot_id):
        await cloner.stop_clone(bot_id)
        s.set_clone_state(bot_id, active=False)
        st.log("clone_stopped", user=q.from_user, detail=f"@{c['username']}", bot="master")
        await q.answer("⏹ Stopped")
    else:
        token = s.clone_token(bot_id)
        try:
            if not token:
                raise RuntimeError("token decrypt nahi hua")
            await cloner.start_clone(token, c["owner_id"])
            s.set_clone_state(bot_id, active=True, error=None)
            st.log("clone_started", user=q.from_user, detail=f"@{c['username']}", bot="master")
            await q.answer("▶️ Live")
        except Exception as e:
            s.set_clone_state(bot_id, error=f"{type(e).__name__}: {e}"[:200])
            await q.answer(f"❌ Start nahi hua: {type(e).__name__}", show_alert=True)
    await _show(q, *clone_detail_screen(bot_id))


async def _delete_clone_flow(q, context, bot_id: int, rest: list[str]):
    s = _s()
    c = s.clone(bot_id)
    if not c:
        await q.answer("Clone nahi mila")
        await _show(q, *clones_screen(0))
        return
    if not rest:
        await q.answer()
        kb = InlineKeyboardMarkup([[B("🗑 Haan, delete karo", callback_data=f"op:cx:{bot_id}:y")],
                                   [B("« Cancel", callback_data=f"op:cd:{bot_id}")]])
        await _show(q, f"⚠️ <b>@{E(c['username'] or '')}</b> clone ko delete karna hai?\n"
                       "Bot band ho jayega aur record hat jayega.", kb)
        return
    await cloner.stop_clone(bot_id)
    s.delete_clone(bot_id)
    st.log("clone_deleted", user=q.from_user, detail=f"@{c['username']} id={bot_id}", bot="master")
    await q.answer("🗑 Deleted")
    await _show(q, *clones_screen(0))


# ------------------------------------------------------------------ groups
async def _group_detail(q, context, bot_id: int, chat_id: int):
    bot = bot_for(context, bot_id)
    row = next((g for g in all_groups(context) if g[0] == bot_id and g[1] == chat_id), None)
    if bot is None or row is None:
        await q.answer("Group nahi mila", show_alert=True)
        await _show(q, *groups_screen(context, 0))
        return
    await q.answer()
    admin = await guard.bot_is_admin(bot, chat_id)
    try:
        members = await bot.get_chat_member_count(chat_id)
    except TelegramError:
        members = "?"
    text = (
        f"<b>👥 {E(row[2] or str(chat_id))}</b>\n\n"
        f"🆔 <code>{chat_id}</code>\n🤖 Bot: {E(row[3])}\n"
        f"👤 Members: {members}\n👮 Bot admin: {'✅' if admin else '❌ nahi'}"
    )
    kb = InlineKeyboardMarkup([
        [B("🚪 Remove bot (Kick)", callback_data=f"op:gk:{bot_id}:{chat_id}")],
        [B("« Groups", callback_data="op:gr:0")],
    ])
    await _show(q, text, kb)


async def _group_kick(q, context, bot_id: int, chat_id: int, rest: list[str]):
    bot = bot_for(context, bot_id)
    if bot is None:
        await q.answer("Bot nahi mila", show_alert=True)
        return
    if not rest:
        await q.answer()
        kb = InlineKeyboardMarkup([[B("🚪 Haan, bot nikalo", callback_data=f"op:gk:{bot_id}:{chat_id}:y")],
                                   [B("« Cancel", callback_data=f"op:gd:{bot_id}:{chat_id}")]])
        await _show(q, "⚠️ Bot is group se <b>remotely leave</b> kar jayega. Pakka?", kb)
        return
    s = _s()
    title = next((g[2] for g in all_groups(context) if g[0] == bot_id and g[1] == chat_id), "")
    try:
        await bot.leave_chat(chat_id)
    except TelegramError as e:
        await q.answer(f"❌ {e}"[:190], show_alert=True)
        return
    s.forget_bot_group(bot_id, chat_id)
    if bot_id == context.bot.id:
        h.db_of(context).forget_chat(chat_id)
    st.log("group_kicked", user=q.from_user, detail=f"left {title or chat_id} ({chat_id})", bot="master")
    await q.answer("🚪 Bot group se nikal gaya")
    await _show(q, *groups_screen(context, 0))


# ------------------------------------------------------------------ anti-screenshot
async def _toggle_antiss(q, context, arg: str):
    s = _s()
    if arg in ("0", "1"):
        s.set_flag(guard.ANTISS_FLAG, arg == "1")
    on = s.flag(guard.ANTISS_FLAG)
    st.log("antiss", user=q.from_user, detail=("ON" if on else "OFF") + (" (re-apply)" if arg == "r" else ""), bot="master")
    await q.answer("⏳ Groups me lagaya ja raha hai…")
    await _show(q, *security_screen())
    groups = all_groups(context)
    chat_ids = []
    for bot_id, chat_id, _t, _l in groups:
        bot = bot_for(context, bot_id)
        if bot and await guard.bot_is_admin(bot, chat_id):
            chat_ids.append(chat_id)
    if not chat_ids:
        await q.message.reply_text("ℹ️ Setting save ho gayi. Abhi koi group nahi jahan bot admin ho — naye groups me apne aap lagegi.")
        return
    tokens = [context.bot.token] + cloner.running_tokens()
    res = await guard.set_protection(tokens, chat_ids, on, context.bot_data.get("sessions"))
    if res["no_api"]:
        await q.message.reply_html("⚠️ <b>API_ID / API_HASH</b> .env me daaliye (my.telegram.org) — tabhi Telegram ka lock group me lagega.")
        return
    titles = {g[1]: g[2] for g in groups}
    msg = f"{'📵 Lock ON' if on else '📱 Lock OFF'} — <b>{len(res['ok'])}</b>/{len(chat_ids)} groups me lag gaya."
    if res["failed"]:
        names = "\n".join(f"• {E(titles.get(c) or str(c))}" for c in res["failed"][:15])
        msg += (f"\n\n⚠️ Ye groups me Telegram ne allow nahi kiya (sirf group Owner ye badal sakta hai):\n{names}\n"
                "<i>Group Owner ka account /sessions me add kar dijiye, ya group → Edit → <b>Restrict saving content</b> khud ON kijiye.</i>")
    await q.message.reply_html(msg)


# ------------------------------------------------------------------ text input (group -4)
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    aw = context.user_data.get("op_await")
    if not aw or not is_owner(update, context):
        return
    msg, user = update.effective_message, update.effective_user
    text = (msg.text or "").strip()
    s = _s()
    kind = aw["kind"]
    done = False
    if kind == "wl_add":
        ids = [int(x) for x in ID_RE.findall(text)]
        if not ids:
            await msg.reply_text("❌ Sahi Telegram ID bhejiye (sirf numbers), ya /cancel.")
            raise ApplicationHandlerStop
        added = [i for i in dict.fromkeys(ids) if s.add_whitelist(i, user.id)]
        for i in added:
            st.log("whitelist_add", user=user, detail=f"added {i}", bot="master")
        done = True
        await msg.reply_text(f"✅ {len(added)} ID jodi gayi" + (f" ({len(ids) - len(added)} pehle se thi)" if len(added) != len(ids) else ""))
        t, kb = whitelist_screen(0)
        await msg.reply_html(t, reply_markup=kb)
    elif kind in ("clone_add", "clone_token"):
        m = cloner.TOKEN_RE.search(text)
        if not m:
            await msg.reply_text("❌ Ye token jaisa nahi lag raha. Dobara bhejiye ya /cancel.")
            raise ApplicationHandlerStop
        try:
            await msg.delete()
        except TelegramError:
            pass
        me, err = await cloner.verify_token(m.group(1))
        if me is None:
            await context.bot.send_message(msg.chat_id, err, parse_mode="HTML")
            raise ApplicationHandlerStop
        if kind == "clone_token" and me.id != aw["bot_id"]:
            await context.bot.send_message(msg.chat_id, "❌ Ye token kisi aur bot ka hai. Isi bot ka naya token bhejiye.")
            raise ApplicationHandlerStop
        if me.id == context.bot.id:
            await context.bot.send_message(msg.chat_id, "❌ Ye master bot ka token hai.")
            raise ApplicationHandlerStop
        old = s.clone(me.id)
        owner_id = old["owner_id"] if old else user.id
        owner_name = old["owner_name"] if old else (user.full_name or "")
        if cloner.is_running(me.id):
            await cloner.stop_clone(me.id)
        try:
            await cloner.start_clone(m.group(1), owner_id)
        except Exception as e:
            await context.bot.send_message(msg.chat_id, f"❌ Clone start nahi hua: {E(type(e).__name__)}", parse_mode="HTML")
            raise ApplicationHandlerStop
        is_new = s.save_clone(me.id, me.username or "", me.full_name or "", m.group(1), owner_id, owner_name)
        st.log("clone_created" if is_new else "clone_updated", user=user, detail=f"@{me.username} id={me.id} (panel)", bot="master")
        done = True
        scr = clone_detail_screen(me.id)
        await context.bot.send_message(msg.chat_id, "✅ Clone LIVE hai.")
        await context.bot.send_message(msg.chat_id, scr[0], reply_markup=scr[1], parse_mode="HTML")
    elif kind == "clone_owner":
        ids = ID_RE.findall(text)
        if not ids:
            await msg.reply_text("❌ Sahi Telegram ID bhejiye, ya /cancel.")
            raise ApplicationHandlerStop
        c = s.clone(aw["bot_id"])
        if c:
            token = s.clone_token(c["bot_id"]) or ""
            name = s.user_name(int(ids[0])) or ""
            s.save_clone(c["bot_id"], c["username"], c["name"], token, int(ids[0]), name)
            if cloner.is_running(c["bot_id"]):
                cloner.RUNNING[c["bot_id"]].bot_data["clone_owner"] = int(ids[0])
            st.log("clone_updated", user=user, detail=f"@{c['username']} owner → {ids[0]}", bot="master")
        done = True
        scr = clone_detail_screen(aw["bot_id"])
        if scr:
            await msg.reply_html("✅ Owner badal diya.\n\n" + scr[0], reply_markup=scr[1])
    if done:
        context.user_data.pop("op_await", None)
    raise ApplicationHandlerStop
