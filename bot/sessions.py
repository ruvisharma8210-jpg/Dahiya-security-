"""📂 Telethon Session Manager (owner-only, private chat only).

/sessions -> [➕ Add New Session] [🔄 Refresh / Check Status] [❌ Revoke / Delete Session]
Session strings encrypted (Fernet) store hote hain; jo message me string aati hai wo turant delete hota hai.
"""
import html
import logging
import os
import sqlite3
import threading
import time

from cryptography.fernet import Fernet, InvalidToken
from telegram import InlineKeyboardButton as B
from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest
from telegram.ext import ApplicationHandlerStop, ContextTypes
from telethon import TelegramClient
from telethon.errors import AuthKeyUnregisteredError, UserDeactivatedBanError, UserDeactivatedError
from telethon.sessions import StringSession

from .config import API_HASH, API_ID, OWNER_IDS, SESSION_SECRET

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ crypto + storage
def _secret_to_key(secret: str) -> bytes:
    """SESSION_SECRET koi bhi text ho sakta hai. Agar wo already sahi Fernet key hai to wahi use hogi,
    warna usse SHA-256 se ek pakki Fernet key banti hai (har baar same)."""
    raw = secret.strip().strip('"').strip("'").encode()
    try:
        Fernet(raw)
        return raw
    except (ValueError, TypeError):
        import base64
        import hashlib
        return base64.urlsafe_b64encode(hashlib.sha256(raw).digest())


def _load_key() -> bytes:
    if SESSION_SECRET:
        return _secret_to_key(SESSION_SECRET)
    path = "secret.key"
    if os.path.exists(path):
        return open(path, "rb").read().strip()
    key = Fernet.generate_key()
    with open(path, "wb") as f:
        f.write(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    log.warning("SESSION_SECRET nahi mila — nayi key secret.key me save ki. Is file ka backup rakhein!")
    return key


class SessionStore:
    def __init__(self, path: str):
        self.fernet = Fernet(_load_key())
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.conn.execute(
                """CREATE TABLE IF NOT EXISTS tg_sessions (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       tg_user_id INTEGER, name TEXT, username TEXT, phone TEXT,
                       data BLOB NOT NULL, status TEXT, checked_at REAL, added_at REAL)"""
            )
            self.conn.commit()

    def add(self, session_str: str, me) -> int:
        enc = self.fernet.encrypt(session_str.encode())
        with self.lock:
            row = self.conn.execute("SELECT id FROM tg_sessions WHERE tg_user_id=?", (me.id,)).fetchone()
            vals = (me.id, full_name(me), me.username, me.phone, enc, "alive", time.time())
            if row:
                self.conn.execute(
                    "UPDATE tg_sessions SET tg_user_id=?, name=?, username=?, phone=?, data=?, status=?, checked_at=? "
                    "WHERE id=?", (*vals, row[0]))
                sid = row[0]
            else:
                cur = self.conn.execute(
                    "INSERT INTO tg_sessions (tg_user_id, name, username, phone, data, status, checked_at, added_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (*vals, time.time()))
                sid = cur.lastrowid
            self.conn.commit()
        return sid

    def all(self) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, tg_user_id, name, username, phone, status, checked_at FROM tg_sessions ORDER BY id").fetchall()
        keys = ("id", "tg_user_id", "name", "username", "phone", "status", "checked_at")
        return [dict(zip(keys, r)) for r in rows]

    def get(self, sid: int) -> dict | None:
        return next((s for s in self.all() if s["id"] == sid), None)

    def secret(self, sid: int) -> str | None:
        with self.lock:
            row = self.conn.execute("SELECT data FROM tg_sessions WHERE id=?", (sid,)).fetchone()
        if not row:
            return None
        try:
            return self.fernet.decrypt(row[0]).decode()
        except InvalidToken:
            return None

    def set_status(self, sid: int, status: str, me=None):
        with self.lock:
            if me is not None:
                self.conn.execute(
                    "UPDATE tg_sessions SET status=?, checked_at=?, name=?, username=?, phone=? WHERE id=?",
                    (status, time.time(), full_name(me), me.username, me.phone, sid))
            else:
                self.conn.execute("UPDATE tg_sessions SET status=?, checked_at=? WHERE id=?", (status, time.time(), sid))
            self.conn.commit()

    def delete(self, sid: int):
        with self.lock:
            self.conn.execute("DELETE FROM tg_sessions WHERE id=?", (sid,))
            self.conn.commit()


def full_name(me) -> str:
    return " ".join(x for x in (me.first_name, me.last_name) if x) or str(me.id)


def mask_phone(p: str | None) -> str:
    if not p:
        return "—"
    p = p if p.startswith("+") else "+" + p
    return p[:4] + "•" * max(0, len(p) - 6) + p[-2:]


# ------------------------------------------------------------------ telethon helpers
def _client(session_str: str) -> TelegramClient:
    return TelegramClient(StringSession(session_str), API_ID, API_HASH, device_model="GroupGuard Manager")


async def check_session(session_str: str):
    """Returns (status, me|None). status: alive | dead | banned | error:<msg>"""
    client = _client(session_str)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return "dead", None
        me = await client.get_me()
        return "alive", me
    except (UserDeactivatedError, UserDeactivatedBanError):
        return "banned", None
    except AuthKeyUnregisteredError:
        return "dead", None
    except Exception as e:  # network etc.
        return f"error: {type(e).__name__}", None
    finally:
        await client.disconnect()


async def revoke_session(session_str: str) -> bool:
    client = _client(session_str)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return True  # already dead
        return bool(await client.log_out())
    except Exception as e:
        log.warning("log_out failed: %s", e)
        return False
    finally:
        if client.is_connected():
            await client.disconnect()


# ------------------------------------------------------------------ UI
STATUS_ICON = {"alive": "🟢", "dead": "🔴", "banned": "⛔"}


def store_of(context) -> SessionStore:
    return context.bot_data["sessions"]


def panel(store: SessionStore):
    items = store.all()
    lines = ["<b>📂 Telethon Sessions Manager</b>\n"]
    if not items:
        lines.append("<i>Abhi koi session nahi hai.</i>")
    for s in items:
        icon = STATUS_ICON.get(s["status"], "🟡")
        uname = f" @{s['username']}" if s["username"] else ""
        ago = _ago(s["checked_at"])
        lines.append(f"{icon} <b>#{s['id']}</b> {html.escape(s['name'] or '')}{html.escape(uname)}\n"
                     f"    📱 {mask_phone(s['phone'])} · {html.escape(s['status'] or '?')} · checked {ago}")
    lines.append(f"\nTotal: <b>{len(items)}</b> · Alive: <b>{sum(1 for s in items if s['status'] == 'alive')}</b>")
    kb = [
        [B("➕ Add New Session", callback_data="ss:add")],
        [B("🔄 Refresh / Check Status", callback_data="ss:check")],
        [B("❌ Revoke / Delete Session", callback_data="ss:pick")],
        [B("🔑 Nayi string generate karo", callback_data="sg:home")],
        [B("✖️ Close", callback_data="ss:close")],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(kb)


def pick_panel(store: SessionStore):
    items = store.all()
    kb = [[B(f"{STATUS_ICON.get(s['status'], '🟡')} #{s['id']} {s['name'] or ''}"[:60], callback_data=f"ss:sel:{s['id']}")]
          for s in items]
    kb.append([B("« Back", callback_data="ss:home")])
    text = "<b>❌ Kaunsa session hatana hai?</b>" if items else "<i>Koi session nahi hai.</i>"
    return text, InlineKeyboardMarkup(kb)


def confirm_panel(s: dict):
    text = (
        f"<b>Session #{s['id']}</b> — {html.escape(s['name'] or '')}\n📱 {mask_phone(s['phone'])}\n\n"
        "🚪 <b>Revoke</b> = Telegram se logout (session hamesha ke liye khatam) + list se delete\n"
        "🗑 <b>Delete only</b> = sirf bot ki list se hatao (session Telegram par chalta rahega)"
    )
    kb = [
        [B("🚪 Revoke (Logout)", callback_data=f"ss:rev:{s['id']}"),
         B("🗑 Delete only", callback_data=f"ss:del:{s['id']}")],
        [B("« Back", callback_data="ss:pick")],
    ]
    return text, InlineKeyboardMarkup(kb)


def _ago(ts) -> str:
    if not ts:
        return "never"
    d = int(time.time() - ts)
    if d < 60:
        return f"{d}s ago"
    if d < 3600:
        return f"{d // 60}m ago"
    if d < 86400:
        return f"{d // 3600}h ago"
    return f"{d // 86400}d ago"


async def _edit(msg, text, kb):
    try:
        await msg.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


def _guard_reason(update: Update) -> str | None:
    if update.effective_chat.type != ChatType.PRIVATE:
        return "🔐 Session Manager sirf bot ke private chat me chalta hai."
    uid = update.effective_user.id
    if not OWNER_IDS:
        return (f"⚠️ Bot ko OWNER_IDS nahi mili. Render → Environment me OWNER_IDS = {uid} daalein, "
                "phir Save karke redeploy karein. (Apni string nikalni hai to /session use karein — usme kuch set nahi karna.)")
    if uid not in OWNER_IDS:
        return (f"⛔ Ye saved-sessions manager sirf owner ke liye hai. Aapki ID {uid} OWNER_IDS me nahi hai. "
                "Apni string nikalne ke liye /session use karein.")
    if not API_ID or not API_HASH:
        return "⚠️ Render → Environment me API_ID aur API_HASH daaliye (my.telegram.org se)."
    return None


# ------------------------------------------------------------------ handlers
async def cmd_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reason = _guard_reason(update)
    if reason:
        await update.effective_message.reply_text(reason)
        return
    text, kb = panel(store_of(context))
    await update.effective_message.reply_html(text, reply_markup=kb)


async def on_session_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    reason = _guard_reason(update)
    if reason:
        await q.answer(reason, show_alert=True)
        return
    store = store_of(context)
    parts = q.data.split(":")
    action = parts[1]

    if action == "home":
        await q.answer()
        await _edit(q.message, *panel(store))
    elif action == "close":
        await q.answer()
        await q.message.delete()
    elif action == "add":
        await q.answer()
        context.user_data["await_session"] = {"ts": time.time(), "panel_msg": q.message.message_id}
        await q.message.reply_html(
            "➕ <b>Session string bhejiye</b> (Telethon StringSession).\n\n"
            "• Message turant delete kar diya jayega aur string encrypt hokar save hogi.\n"
            "• String nahi hai? /session se 🔑 Session String Generator use karein.\n\n"
            "/cancel se rok sakte hain.")
    elif action == "check":
        await q.answer("🔄 Checking…")
        items = store.all()
        await _edit(q.message, f"🔄 {len(items)} session(s) check ho rahe hain…", None)
        for s in items:
            sec = store.secret(s["id"])
            if sec is None:
                store.set_status(s["id"], "error: decrypt")
                continue
            status, me = await check_session(sec)
            store.set_status(s["id"], status, me)
        await _edit(q.message, *panel(store))
    elif action == "pick":
        await q.answer()
        await _edit(q.message, *pick_panel(store))
    elif action == "sel":
        s = store.get(int(parts[2]))
        await q.answer()
        if not s:
            await _edit(q.message, *pick_panel(store))
            return
        await _edit(q.message, *confirm_panel(s))
    elif action in ("rev", "del"):
        sid = int(parts[2])
        if action == "rev":
            sec = store.secret(sid)
            ok = await revoke_session(sec) if sec else False
            if not ok:
                await q.answer("⚠️ Logout fail hua (network?). Dobara try karein ya 'Delete only' use karein.",
                               show_alert=True)
                return
            await q.answer("🚪 Session revoked & deleted", show_alert=True)
        else:
            await q.answer("🗑 Deleted from list")
        store.delete(sid)
        await _edit(q.message, *panel(store))


async def on_private_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner ne 'Add New Session' dabaya ho to agla private message session string maana jayega."""
    aw = context.user_data.get("await_session")
    msg = update.effective_message
    if not aw or not msg or not msg.text:
        return
    if update.effective_user.id not in OWNER_IDS:
        return
    context.user_data.pop("await_session", None)
    if time.time() - aw["ts"] > 300:
        await msg.reply_text("⌛ Time khatam. Dobara ➕ Add New Session dabaiye.")
        raise ApplicationHandlerStop

    session_str = msg.text.strip()
    try:
        await msg.delete()  # string chat me na rahe
    except BadRequest:
        pass
    wait = await context.bot.send_message(msg.chat.id, "⏳ Session verify ho raha hai…")
    if len(session_str) < 100 or " " in session_str:
        await wait.edit_text("⚠️ Ye valid Telethon session string nahi lag rahi.")
        raise ApplicationHandlerStop
    try:
        status, me = await check_session(session_str)
    except ValueError:
        status, me = "invalid", None
    if status != "alive" or me is None:
        await wait.edit_text(f"❌ Session kaam nahi kar raha ({status}). Save nahi kiya.")
        raise ApplicationHandlerStop
    store = store_of(context)
    sid = store.add(session_str, me)
    await wait.edit_text(
        f"✅ Session #{sid} save ho gaya — {html.escape(full_name(me))} ({mask_phone(me.phone)})",
        parse_mode=ParseMode.HTML)
    text, kb = panel(store)
    try:
        await context.bot.edit_message_text(text, msg.chat.id, aw["panel_msg"], reply_markup=kb,
                                            parse_mode=ParseMode.HTML)
    except BadRequest:
        await context.bot.send_message(msg.chat.id, text, reply_markup=kb, parse_mode=ParseMode.HTML)
    raise ApplicationHandlerStop


async def cancel_private(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if context.user_data.pop("await_session", None):
        await update.effective_message.reply_text("❌ Cancelled.")
        return True
    return False
