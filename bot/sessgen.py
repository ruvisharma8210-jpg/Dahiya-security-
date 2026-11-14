"""🔑 Session String Generator — public (har user apni string nikal sakta hai), sirf private chat me.

Flow: library chuno -> API ID/HASH (apna ya bot ka default) -> phone -> OTP -> (2FA) -> string.
Kuch bhi save nahi hota: na database me, na file me, na environment me. Login ke baad client disconnect hota hai
(logout nahi — warna string kaam nahi karegi).
"""
import asyncio
import html
import logging
import re
import time

from telegram import InlineKeyboardButton as B
from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import TelegramError
from telegram.ext import ApplicationHandlerStop, ContextTypes
from telethon import TelegramClient
from telethon.errors import (
    ApiIdInvalidError,
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeEmptyError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

from . import sessfmt
from .config import API_HASH, API_ID

log = logging.getLogger(__name__)

TIMEOUT = 600  # 10 min me flow khatam na ho to band
KEY = "sg"


def _kb(rows):
    return InlineKeyboardMarkup(rows)


def home_panel():
    text = (
        "<b>🔑 Session String Generator</b>\n\n"
        "Apni Telegram account ki session string nikaalein. Library chuniye:\n\n"
        "<i>Kuch bhi bot me save nahi hota. String sirf aapko is chat me milti hai.</i>"
    )
    kb = [
        [B("🐍 Telethon", callback_data="sg:lib:telethon"), B("🔥 Kurigram", callback_data="sg:lib:kurigram")],
        [B("📦 mtcute", callback_data="sg:lib:mtcute"), B("🟨 GramJS", callback_data="sg:lib:gramjs")],
        [B("🐹 GoTG", callback_data="sg:lib:gotg")],
        [B("♻️ Purani string Revoke karo", callback_data="sr:start")],
        [B("« Menu", callback_data="m:home")],
    ]
    return text, _kb(kb)


def _state(context) -> dict | None:
    return context.user_data.get(KEY)


async def _cleanup(context, st: dict | None = None):
    context.user_data.pop("sr", None)
    st = st or context.user_data.pop(KEY, None)
    context.user_data.pop(KEY, None)
    if not st:
        return
    t = st.get("timer")
    if t and not t.done():
        t.cancel()
    c = st.get("client")
    if c is not None:
        try:
            await c.disconnect()
        except Exception:
            pass
        st["client"] = None


async def _expire(context, st: dict, chat_id: int):
    try:
        await asyncio.sleep(TIMEOUT)
    except asyncio.CancelledError:
        return
    if context.user_data.get(KEY) is st:
        st["timer"] = None  # khud ko cancel na kare
        await _cleanup(context, st)
        try:
            await context.bot.send_message(chat_id, "⌛ Time khatam, session generation band kar diya. /session se dobara shuru karein.")
        except TelegramError:
            pass


def _guard(update: Update) -> str | None:
    if update.effective_chat.type != ChatType.PRIVATE:
        return "🔐 Session generator sirf bot ke private chat me chalta hai. Mujhe DM kijiye."
    return None


async def cmd_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reason = _guard(update)
    if reason:
        await update.effective_message.reply_text(reason)
        return
    await _cleanup(context)
    text, kb = home_panel()
    await update.effective_message.reply_html(text, reply_markup=kb)


async def _ask_api(msg, st):
    default_ok = bool(API_ID and API_HASH)
    kb = []
    if default_ok:
        kb.append([B("⚡ Bot ka default API use karo", callback_data="sg:defapi")])
    kb.append([B("✖️ Cancel", callback_data="sg:cancel")])
    st["step"] = "api_choice" if default_ok else "api_id"
    if default_ok:
        await msg.reply_html(
            f"<b>{sessfmt.LIBS[st['lib']]}</b> chuna ✅\n\n"
            "API ID / API HASH ka option chuniye (apna API <a href=\"https://my.telegram.org\">my.telegram.org</a> se milta hai).\n"
            "Apna API banana behtar hai — Kurigram string me API ID andar hi store hoti hai.",
            reply_markup=_kb([[B("✍️ Apna API ID/HASH daalunga", callback_data="sg:ownapi")]] + kb),
            disable_web_page_preview=True,
        )
    else:
        await msg.reply_html(
            f"<b>{sessfmt.LIBS[st['lib']]}</b> chuna ✅\n\n"
            "Apna <b>API ID</b> bhejiye (number). <a href=\"https://my.telegram.org\">my.telegram.org</a> → API development tools se milega.",
            reply_markup=_kb(kb), disable_web_page_preview=True,
        )


async def _ask_phone(msg, st):
    st["step"] = "phone"
    await msg.reply_html(
        "📱 Apna <b>phone number</b> country code ke saath bhejiye.\nExample: <code>+919876543210</code>",
        reply_markup=_kb([[B("✖️ Cancel", callback_data="sg:cancel")]]),
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    reason = _guard(update)
    if reason:
        await q.answer(reason, show_alert=True)
        return
    parts = q.data.split(":")
    action = parts[1]

    if action == "home":
        await _cleanup(context)
        await q.answer()
        text, kb = home_panel()
        try:
            await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except TelegramError:
            await q.message.reply_html(text, reply_markup=kb)
    elif action == "cancel":
        await _cleanup(context)
        await q.answer("❌ Cancelled")
        try:
            await q.message.edit_reply_markup(None)
        except TelegramError:
            pass
        await q.message.reply_text("❌ Cancelled. /session se dobara shuru karein.")
    elif action == "lib":
        lib = parts[2]
        if lib not in sessfmt.LIBS:
            await q.answer()
            return
        await _cleanup(context)
        st = {"lib": lib, "step": "api", "ts": time.time()}
        context.user_data[KEY] = st
        st["timer"] = asyncio.create_task(_expire(context, st, q.message.chat.id))
        await q.answer()
        await _ask_api(q.message, st)
    elif action in ("defapi", "ownapi"):
        st = _state(context)
        if not st:
            await q.answer("Session expire ho gaya, /session se dobara shuru karein.", show_alert=True)
            return
        await q.answer()
        if action == "defapi":
            st["api_id"], st["api_hash"] = API_ID, API_HASH
            await _ask_phone(q.message, st)
        else:
            st["step"] = "api_id"
            await q.message.reply_html(
                "Apna <b>API ID</b> bhejiye (number).",
                reply_markup=_kb([[B("✖️ Cancel", callback_data="sg:cancel")]]))
    else:
        await q.answer()


async def _delete(msg):
    try:
        await msg.delete()
    except TelegramError:
        pass


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Flow ke andar aane wale private text messages (api id, hash, phone, otp, password)."""
    st = _state(context)
    msg = update.effective_message
    if not st or not msg or not msg.text:
        return
    chat_id = msg.chat.id
    text = msg.text.strip()
    step = st["step"]

    if time.time() - st["ts"] > TIMEOUT:
        await _cleanup(context, st)
        await msg.reply_text("⌛ Time khatam. /session se dobara shuru karein.")
        raise ApplicationHandlerStop

    async def say(t, **kw):
        return await context.bot.send_message(chat_id, t, parse_mode=ParseMode.HTML, **kw)

    cancel_kb = _kb([[B("✖️ Cancel", callback_data="sg:cancel")]])

    if step in ("api_choice", "api"):
        raise ApplicationHandlerStop

    if step == "api_id":
        if not text.isdigit():
            await say("⚠️ API ID sirf number hota hai. Dobara bhejiye.", reply_markup=cancel_kb)
            raise ApplicationHandlerStop
        st["api_id"] = int(text)
        st["step"] = "api_hash"
        await say("Ab <b>API HASH</b> bhejiye (32 characters).", reply_markup=cancel_kb)
        raise ApplicationHandlerStop

    if step == "api_hash":
        await _delete(msg)
        if not re.fullmatch(r"[0-9a-fA-F]{32}", text):
            await say("⚠️ API HASH 32 character ka hex hota hai. Dobara bhejiye.", reply_markup=cancel_kb)
            raise ApplicationHandlerStop
        st["api_hash"] = text
        await _ask_phone(msg, st)
        raise ApplicationHandlerStop

    if step == "phone":
        phone = re.sub(r"[\s\-()]", "", text)
        if not re.fullmatch(r"\+?\d{7,15}", phone):
            await say("⚠️ Number galat lag raha hai. Example: <code>+919876543210</code>", reply_markup=cancel_kb)
            raise ApplicationHandlerStop
        if not phone.startswith("+"):
            phone = "+" + phone
        await _delete(msg)
        wait = await say("⏳ Telegram se code mangwa raha hoon…")
        client = TelegramClient(StringSession(), st["api_id"], st["api_hash"], device_model="Session Generator")
        try:
            await client.connect()
            sent = await client.send_code_request(phone)
        except ApiIdInvalidError:
            await client.disconnect()
            st["step"] = "api_id"
            await wait.edit_text("❌ API ID / API HASH galat hai. Sahi <b>API ID</b> dobara bhejiye.",
                                 parse_mode=ParseMode.HTML, reply_markup=cancel_kb)
            raise ApplicationHandlerStop
        except PhoneNumberInvalidError:
            await client.disconnect()
            await wait.edit_text("❌ Phone number invalid hai. Dobara bhejiye.", reply_markup=cancel_kb)
            raise ApplicationHandlerStop
        except PhoneNumberBannedError:
            await client.disconnect()
            await _cleanup(context, st)
            await wait.edit_text("⛔ Ye number Telegram par banned hai.")
            raise ApplicationHandlerStop
        except FloodWaitError as e:
            await client.disconnect()
            await _cleanup(context, st)
            await wait.edit_text(f"⏳ Telegram ne limit lagayi hai. {e.seconds} second baad try karein.")
            raise ApplicationHandlerStop
        except ApplicationHandlerStop:
            raise
        except Exception as e:
            log.warning("send_code failed: %s", e)
            await client.disconnect()
            await _cleanup(context, st)
            await wait.edit_text(f"❌ Code nahi bhej paya ({type(e).__name__}). /session se dobara try karein.")
            raise ApplicationHandlerStop
        st.update(client=client, phone=phone, hash=sent.phone_code_hash, step="code")
        await wait.edit_text(
            "📨 Telegram app me aaya <b>login code</b> bhejiye.\n\n"
            "⚠️ <b>Code ko spaces ke saath likhiye</b>: <code>1 2 3 4 5</code>\n"
            "Seedha <code>12345</code> bhejne par Telegram code ko block kar deta hai.",
            parse_mode=ParseMode.HTML, reply_markup=cancel_kb)
        raise ApplicationHandlerStop

    if step == "code":
        await _delete(msg)
        code = re.sub(r"\D", "", text)
        if not code:
            await say("⚠️ Code me digits hone chahiye. Spaces ke saath bhejiye: <code>1 2 3 4 5</code>", reply_markup=cancel_kb)
            raise ApplicationHandlerStop
        client: TelegramClient = st["client"]
        try:
            await client.sign_in(st["phone"], code, phone_code_hash=st["hash"])
        except SessionPasswordNeededError:
            st["step"] = "password"
            await say("🔐 Is account par <b>2-step verification</b> on hai. Apna <b>password</b> bhejiye.\n"
                      "<i>(Message turant delete ho jayega.)</i>", reply_markup=cancel_kb)
            raise ApplicationHandlerStop
        except (PhoneCodeInvalidError, PhoneCodeEmptyError):
            await say("❌ Code galat hai. Dobara bhejiye (spaces ke saath).", reply_markup=cancel_kb)
            raise ApplicationHandlerStop
        except PhoneCodeExpiredError:
            await _cleanup(context, st)
            await say("⌛ Code expire ho gaya. /session se dobara shuru karein.")
            raise ApplicationHandlerStop
        except Exception as e:
            log.warning("sign_in failed: %s", e)
            await _cleanup(context, st)
            await say(f"❌ Login fail ({type(e).__name__}). /session se dobara try karein.")
            raise ApplicationHandlerStop
        await _finish(context, st, chat_id)
        raise ApplicationHandlerStop

    if step == "password":
        await _delete(msg)
        client = st["client"]
        try:
            await client.sign_in(password=text)
        except PasswordHashInvalidError:
            await say("❌ Password galat hai. Dobara bhejiye.", reply_markup=cancel_kb)
            raise ApplicationHandlerStop
        except Exception as e:
            log.warning("2fa failed: %s", e)
            await _cleanup(context, st)
            await say(f"❌ Login fail ({type(e).__name__}). /session se dobara try karein.")
            raise ApplicationHandlerStop
        await _finish(context, st, chat_id)
        raise ApplicationHandlerStop


async def _finish(context, st: dict, chat_id: int):
    client: TelegramClient = st["client"]
    lib = st["lib"]
    try:
        me = await client.get_me()
        s = client.session
        string = sessfmt.build(
            lib, dc_id=s.dc_id, ip=s.server_address, port=s.port, key=s.auth_key.key,
            api_id=st["api_id"], user_id=me.id,
        )
    except Exception as e:
        log.warning("finish failed: %s", e)
        await _cleanup(context, st)
        await context.bot.send_message(chat_id, f"❌ String banane me error ({type(e).__name__}). /session se dobara try karein.")
        return
    await _cleanup(context, st)  # sirf disconnect — logout nahi
    name = html.escape(" ".join(x for x in (me.first_name, me.last_name) if x) or str(me.id))
    usage = html.escape(sessfmt.USAGE[lib])
    extra = ""
    if lib == "kurigram":
        extra = f"\n<i>Is string me API ID <code>{st['api_id']}</code> hai — client me wahi API HASH use karein.</i>"
    if lib == "gotg":
        extra = "\n<i>GoTG native string (gotd session JSON, base64).</i>"
    await context.bot.send_message(
        chat_id,
        f"✅ <b>{sessfmt.LIBS[lib]}</b> session string ready — {name}\n\n"
        f"<code>{html.escape(string)}</code>\n\n"
        "👆 Tap karke copy karein.\n"
        "🚨 <b>Ye string kisi ko mat dijiye</b> — isse aapka account poora control ho sakta hai. "
        "Kabhi leak ho to /revoke se band karke nayi string le lijiye."
        f"{extra}\n\n<b>Use:</b>\n<pre>{usage}</pre>",
        parse_mode=ParseMode.HTML,
        reply_markup=_kb([
            [B("🔑 Dusri library ki string", callback_data="sg:home")],
            [B("♻️ Koi string Revoke karo", callback_data="sr:start")],
            [B("« Menu", callback_data="m:home")],
        ]),
    )


async def cancel_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if _state(context):
        await _cleanup(context)
        await update.effective_message.reply_text("❌ Cancelled.")
        return True
    return False
