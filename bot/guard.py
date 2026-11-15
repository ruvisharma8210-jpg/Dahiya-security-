"""🛡️ Group Admin Validation + Anti-Screenshot / Screen-Recording lock.

1. Bot group me tabhi kaam karta hai jab wo Admin ho. Admin nahi hai to commands/buttons par warning:
   "इस ग्रुप में काम करने के लिए कृपया मुझे पहले Admin बनाइए!"
2. Anti-Screenshot (owner panel ka master toggle): Telegram ka "Restrict Saving Content" (noforwards)
   bot ke saare groups me ON/OFF. Isse members screenshot / screen recording / forward / save nahi kar paate.
   Telegram Bot API me iska method nahi hai, isliye Telethon (MTProto) se lagaya jata hai:
   pehle bot account se, phir owner ke Saved Sessions (/sessions) wale accounts se (agar wo group ke owner/admin hon).
   Iske liye .env me API_ID + API_HASH zaroori hain.
"""
import asyncio
import logging
import time

from telegram import Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.error import TelegramError
from telegram.ext import ApplicationHandlerStop, ContextTypes

from . import store as st
from .config import API_HASH, API_ID

log = logging.getLogger(__name__)

GROUPS = (ChatType.GROUP, ChatType.SUPERGROUP)
ADMIN_WARNING = "⚠️ इस ग्रुप में काम करने के लिए कृपया मुझे पहले Admin बनाइए!"
ANTISS_FLAG = "anti_screenshot"
_CACHE_SECS = 60
_WARN_EVERY = 30

_admin_cache: dict[tuple[int, int], tuple[float, bool]] = {}
_last_warn: dict[tuple[int, int], float] = {}


def forget(bot_id: int, chat_id: int) -> None:
    _admin_cache.pop((bot_id, chat_id), None)


async def bot_is_admin(bot, chat_id: int) -> bool:
    key = (bot.id, chat_id)
    hit = _admin_cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    try:
        m = await bot.get_chat_member(chat_id, bot.id)
        ok = m.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except TelegramError:
        ok = False
    except Exception:  # network glitch — group ko block mat karo
        return True
    _admin_cache[key] = (time.time() + _CACHE_SECS, ok)
    return ok


_known: set[tuple[int, int]] = set()


def _seen_group(context, chat) -> None:
    key = (context.bot.id, chat.id)
    if key in _known:
        return
    _known.add(key)
    s = st.get()
    if s:
        s.remember_bot_group(context.bot.id, chat.id, chat.title or "")


def _can_warn(bot_id: int, chat_id: int) -> bool:
    key, now = (bot_id, chat_id), time.time()
    if _last_warn.get(key, 0) > now - _WARN_EVERY:
        return False
    _last_warn[key] = now
    return True


# ------------------------------------------------------------------ handlers (group=-9)
async def gate_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Group message: bot admin nahi hai to aage ke saare handlers band; command par warning."""
    chat, msg = update.effective_chat, update.effective_message
    if chat is None or chat.type not in GROUPS:
        return
    if await bot_is_admin(context.bot, chat.id):
        _seen_group(context, chat)
        return
    if msg and msg.text and msg.text.startswith("/"):
        target = msg.text.split()[0].partition("@")[2].lower()
        mine = not target or target == (context.bot.username or "").lower()
        if mine and _can_warn(context.bot.id, chat.id):
            try:
                await msg.reply_text(ADMIN_WARNING)
            except TelegramError:
                pass
            st.log("admin_missing", user=update.effective_user, chat=chat, detail=msg.text.split()[0][:40])
    raise ApplicationHandlerStop


async def gate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None or q.message is None or q.message.chat.type not in GROUPS:
        return
    if await bot_is_admin(context.bot, q.message.chat.id):
        return
    try:
        await q.answer(ADMIN_WARNING, show_alert=True)
    except TelegramError:
        pass
    raise ApplicationHandlerStop


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cmu = update.my_chat_member
    if not cmu or cmu.chat.type not in GROUPS:
        return
    forget(context.bot.id, cmu.chat.id)
    status = cmu.new_chat_member.status
    s = st.get()
    if s:
        if status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
            s.forget_bot_group(context.bot.id, cmu.chat.id)
        else:
            s.remember_bot_group(context.bot.id, cmu.chat.id, cmu.chat.title or "")
    if status == ChatMemberStatus.MEMBER:
        # add hua ya admin se hataya gaya — admin banane ko bolo
        try:
            await context.bot.send_message(cmu.chat.id, ADMIN_WARNING)
        except TelegramError:
            pass
    elif status == ChatMemberStatus.ADMINISTRATOR:
        if s and s.flag(ANTISS_FLAG):
            # naye group me bhi anti-screenshot apne aap lagao
            sessions = context.bot_data.get("sessions")
            asyncio.create_task(set_protection([context.bot.token], [cmu.chat.id], True, sessions))


# ------------------------------------------------------------------ Anti-Screenshot (noforwards)
def _not_modified(e: Exception) -> bool:
    return "NOT_MODIFIED" in str(e).upper() or "not modified" in str(e).lower()


async def _toggle_with(client, pending: list[int], on: bool, done: dict[int, str], via: str) -> None:
    from telethon.tl.functions.messages import ToggleNoForwardsRequest
    for cid in list(pending):
        try:
            peer = await client.get_input_entity(cid)
            await client(ToggleNoForwardsRequest(peer=peer, enabled=on))
            done[cid] = via
            pending.remove(cid)
        except Exception as e:
            if _not_modified(e):
                done[cid] = via
                pending.remove(cid)
            else:
                log.info("antiss %s via %s: %s", cid, via, e)


async def set_protection(bot_tokens: list[str], chat_ids: list[int], on: bool, sessions=None) -> dict:
    """Return {'ok': {chat_id: via}, 'failed': [chat_id], 'no_api': bool}"""
    pending = list(dict.fromkeys(chat_ids))
    done: dict[int, str] = {}
    if not (API_ID and API_HASH):
        return {"ok": done, "failed": pending, "no_api": True}
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    # 1) bot accounts (master + clones)
    for token in bot_tokens:
        if not pending:
            break
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        try:
            await client.start(bot_token=token)
            await _toggle_with(client, pending, on, done, "bot")
        except Exception as e:
            log.warning("antiss bot login failed: %s", e)
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    # 2) owner ke saved session accounts (group owner/admin hon to)
    if pending and sessions is not None:
        for s in sessions.all():
            if not pending:
                break
            if s.get("status") != "alive":
                continue
            secret = sessions.secret(s["id"])
            if not secret:
                continue
            client = TelegramClient(StringSession(secret), API_ID, API_HASH, device_model="GroupGuard Manager")
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    continue
                await client.get_dialogs(limit=200)  # entity cache bharo
                await _toggle_with(client, pending, on, done, f"session:{s.get('name') or s['id']}")
            except Exception as e:
                log.warning("antiss session %s failed: %s", s["id"], e)
            finally:
                try:
                    await client.disconnect()
                except Exception:
                    pass
    return {"ok": done, "failed": pending, "no_api": False}
