"""♻️ Session String Revoke — koi bhi user apni purani string band (logout) kar sakta hai aur nayi le sakta hai.

Flow: string paste karo (library apne aap pehchani jaati hai) -> confirm -> (API ID/HASH agar bot me default nahi)
-> Telegram par us string ka logout (auth key hamesha ke liye band) -> nayi string ke liye library buttons.
Kuch bhi save nahi hota.
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
from telethon.errors import ApiIdInvalidError, AuthKeyUnregisteredError, FloodWaitError
from telethon.sessions import StringSession

from . import sessfmt
from .config import API_HASH, API_ID

log = logging.getLogger(__name__)

KEY = "sr"
TIMEOUT = 600


def _kb(rows):
    return InlineKeyboardMarkup(rows)


CANCEL = [B("✖️ Cancel", callback_data="sr:cancel")]


def new_string_kb():
    return _kb([
        [B("🐍 Telethon", callback_data="sg:lib:telethon"), B("🔥 Kurigram", callback_data="sg:lib:kurigram")],
        [B("📦 mtcute", callback_data="sg:lib:mtcute"), B("🟨 GramJS", callback_data="sg:lib:gramjs")],
        [B("🐹 GoTG", callback_data="sg:lib:gotg")],
        [B("« Menu", callback_data="m:home")],
    ])


def _private(update: Update) -> bool:
    return update.effective_chat.type == ChatType.PRIVATE


def clear(context):
    context.user_data.pop(KEY, None)


async def _delete(msg):
    try:
        await msg.delete()
    except TelegramError:
        pass


async def start(msg, context):
    from .sessgen import _cleanup
    await _cleanup(context)  # chal raha generator flow band
    context.user_data[KEY] = {"step": "string", "ts": time.time()}
    await msg.reply_html(
        "<b>♻️ Session String Revoke</b>\n\n"
        "Jo string band (revoke) karni hai, wo yahan paste kijiye.\n"
        "Telethon, mtcute, Kurigram, GramJS, GoTG — library apne aap pehchan li jayegi.\n\n"
        "<i>Aapka message turant delete ho jayega. Revoke ke baad wo string kabhi kaam nahi karegi, "
        "aur aap nayi string le sakte hain.</i>",
        reply_markup=_kb([CANCEL]),
    )


async def cmd_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _private(update):
        await update.effective_message.reply_text("🔐 Ye sirf bot ke private chat me chalta hai. Mujhe DM kijiye.")
        return
    await start(update.effective_message, context)


async def _do_revoke(context, st, chat_id):
    p: sessfmt.ParsedSession = st["parsed"]
    wait = await context.bot.send_message(chat_id, "⏳ Telegram par string band kar raha hoon…")
    s = StringSession(sessfmt.telethon_string(p.dc_id, p.ip, p.port, p.key))
    client = TelegramClient(s, st["api_id"], st["api_hash"], device_model="Session Generator")
    clear(context)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            await wait.edit_text(
                "ℹ️ Ye string pehle se band (revoked / logged out) hai — isse koi login nahi ho sakta.\n\n"
                "Nayi string chahiye? Library chuniye 👇", reply_markup=new_string_kb())
            return
        me = await client.get_me()
        name = html.escape(" ".join(x for x in (me.first_name, me.last_name) if x) or str(me.id))
        ok = await client.log_out()
    except AuthKeyUnregisteredError:
        await wait.edit_text("ℹ️ Ye string pehle se band hai.\n\nNayi string chahiye? Library chuniye 👇",
                             reply_markup=new_string_kb())
        return
    except ApiIdInvalidError:
        await wait.edit_text("❌ API ID / API HASH galat hai. /revoke se dobara try karein.")
        return
    except FloodWaitError as e:
        await wait.edit_text(f"⏳ Telegram ne limit lagayi hai. {e.seconds} second baad try karein.")
        return
    except Exception as e:
        log.warning("revoke failed: %s", e)
        await wait.edit_text(f"❌ Revoke nahi ho paya ({type(e).__name__}). /revoke se dobara try karein.")
        return
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
    if not ok:
        await wait.edit_text("❌ Telegram ne logout mana kar diya. Telegram → Settings → Devices se session terminate kar dein.")
        return
    await wait.edit_text(
        f"✅ <b>Revoked!</b> {name} ki <b>{sessfmt.LIBS[p.lib]}</b> string ab hamesha ke liye band ho gayi.\n"
        "Koi bhi us string se ab aapka account use nahi kar sakta.\n\n"
        "🔑 <b>Nayi string</b> ke liye library chuniye 👇",
        parse_mode=ParseMode.HTML, reply_markup=new_string_kb())


async def _after_parsed(msg, context, st):
    p = st["parsed"]
    st["step"] = "confirm"
    who = f"\nUser ID: <code>{p.user_id}</code>" if p.user_id else ""
    await msg.reply_html(
        f"🔎 <b>{sessfmt.LIBS[p.lib]}</b> string mili (DC {p.dc_id}).{who}\n\n"
        "Pakka revoke karna hai? Iske baad ye string aur jahan-jahan ye lagi hai (bot/userbot), sab band ho jayenge.",
        reply_markup=_kb([[B("🗑 Haan, revoke karo", callback_data="sr:go")], CANCEL]),
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not _private(update):
        await q.answer("🔐 Ye sirf bot ke private chat me chalta hai.", show_alert=True)
        return
    action = q.data.split(":")[1]
    if action == "start":
        await q.answer()
        await start(q.message, context)
        return
    if action == "cancel":
        clear(context)
        await q.answer("❌ Cancelled")
        try:
            await q.message.edit_reply_markup(None)
        except TelegramError:
            pass
        await q.message.reply_text("❌ Cancelled. /revoke se dobara shuru karein.")
        return
    st = context.user_data.get(KEY)
    if action == "go":
        if not st or st.get("step") != "confirm" or time.time() - st["ts"] > TIMEOUT:
            clear(context)
            await q.answer("Time khatam, /revoke se dobara shuru karein.", show_alert=True)
            return
        await q.answer()
        try:
            await q.message.edit_reply_markup(None)
        except TelegramError:
            pass
        if API_ID and API_HASH:
            st["api_id"], st["api_hash"] = API_ID, API_HASH
            await _do_revoke(context, st, q.message.chat.id)
        else:
            st["step"] = "api_id"
            await q.message.reply_html(
                "Apna <b>API ID</b> bhejiye (number) — <a href=\"https://my.telegram.org\">my.telegram.org</a> se.",
                reply_markup=_kb([CANCEL]), disable_web_page_preview=True)
        return
    await q.answer()


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    st = context.user_data.get(KEY)
    msg = update.effective_message
    if not st or not msg or not msg.text:
        return
    text = msg.text.strip()
    if time.time() - st["ts"] > TIMEOUT:
        clear(context)
        await msg.reply_text("⌛ Time khatam. /revoke se dobara shuru karein.")
        raise ApplicationHandlerStop
    step = st["step"]
    if step == "string":
        await _delete(msg)
        p = sessfmt.parse(text)
        if not p:
            await msg.reply_html(
                "⚠️ Ye valid session string nahi lagi (Telethon / mtcute / Kurigram / GramJS / GoTG).\n"
                "Poori string bina kuch kaate dobara paste kijiye.", reply_markup=_kb([CANCEL]))
            raise ApplicationHandlerStop
        st["parsed"] = p
        await _after_parsed(msg, context, st)
        raise ApplicationHandlerStop
    if step == "api_id":
        if not text.isdigit():
            await msg.reply_text("⚠️ API ID sirf number hota hai. Dobara bhejiye.", reply_markup=_kb([CANCEL]))
            raise ApplicationHandlerStop
        st["api_id"], st["step"] = int(text), "api_hash"
        await msg.reply_html("Ab <b>API HASH</b> bhejiye (32 characters).", reply_markup=_kb([CANCEL]))
        raise ApplicationHandlerStop
    if step == "api_hash":
        await _delete(msg)
        if not re.fullmatch(r"[0-9a-fA-F]{32}", text):
            await msg.reply_text("⚠️ API HASH 32 character ka hota hai. Dobara bhejiye.", reply_markup=_kb([CANCEL]))
            raise ApplicationHandlerStop
        st["api_hash"] = text
        await _do_revoke(context, st, msg.chat.id)
        raise ApplicationHandlerStop
    raise ApplicationHandlerStop  # confirm step: button ka intezaar


async def cancel_flow(update: Update, context) -> bool:
    if context.user_data.pop(KEY, None):
        await update.effective_message.reply_text("❌ Cancelled.")
        return True
    return False
