"""🛰️ Dahiya Hub link — Session String permission + activity report (owner ke dashboard par).

- Session String button: har click par Hub se poocha jata hai "kya ye user allowed hai?".
  Sirf admin (Hub me set Telegram ID) aur admin ke diye hue users allowed hain.
  Bot ke apne OWNER_IDS se permission NAHI milti — isliye clone banane wala bhi use nahi kar payega.
- Activity: commands, join-request approvals, moderation, group add/remove — sab Hub ko bheja jata hai.
- Hub band ho to button deny karta hai (fail-closed); baaki bot normal chalta rehta hai.
"""
import asyncio
import html
import logging
import time

import httpx
from telegram import InlineKeyboardButton as B
from telegram import InlineKeyboardMarkup

from .config import OWNER_IDS

log = logging.getLogger(__name__)

HUB_URL = "https://project--a61d20a2-17fe-4434-8dd0-c8bd69216af6-dev.lovable.app/api/public/hub"
VERSION = "2.0"
FLUSH_EVERY = 15          # seconds
HEARTBEAT_EVERY = 300     # seconds
ALLOW_CACHE = 120         # allowed user ko 2 min tak dobara nahi poocha jata
MAX_QUEUE = 2000

_queue: list[dict] = []
_bot: dict = {}
_allow_cache: dict[int, float] = {}
_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10)
    return _client


def _remember_bot(bot) -> None:
    if _bot:
        return
    try:
        _bot.update(
            id=bot.id,
            username=bot.username or "",
            name=bot.first_name or "",
            owner_ids=",".join(str(x) for x in sorted(OWNER_IDS))[:256],
            version=VERSION,
        )
    except Exception:  # bot abhi initialize nahi hua
        pass


def track(kind: str, chat=None, user=None, detail: str = "") -> None:
    """Event queue me daalo (non-blocking). Har 15s me Hub ko bheja jata hai."""
    ev: dict = {"kind": kind}
    if detail:
        ev["detail"] = str(detail)[:300]
    if chat is not None:
        ev["chat_id"] = chat.id
        title = getattr(chat, "title", None) or getattr(chat, "full_name", None) or ""
        if title:
            ev["chat_title"] = str(title)[:128]
    if user is not None:
        ev["user_id"] = user.id
        name = user.username or getattr(user, "full_name", "") or ""
        if name:
            ev["username"] = str(name)[:64]
    if len(_queue) < MAX_QUEUE:
        _queue.append(ev)


async def setup(app) -> None:
    """post_init se call hota hai."""
    _remember_bot(app.bot)
    try:
        for cid, title in app.bot_data["db"].chats():
            _queue.append({"kind": "group_sync", "chat_id": cid, "chat_title": (title or "")[:128]})
    except Exception as e:
        log.warning("hub: group list read failed: %s", e)
    _queue.append({"kind": "heartbeat"})
    app.bot_data["hub_task"] = asyncio.create_task(_loop())


async def flush() -> None:
    if not _bot:
        return
    while _queue:
        batch = _queue[:100]
        try:
            r = await _http().post(f"{HUB_URL}/events", json={"bot": _bot, "events": batch})
            r.raise_for_status()
        except Exception as e:
            log.warning("hub: report failed (%s) — baad me dobara", e)
            return
        del _queue[: len(batch)]


async def _loop() -> None:
    last_beat = time.time()
    while True:
        try:
            await asyncio.sleep(FLUSH_EVERY)
            if time.time() - last_beat >= HEARTBEAT_EVERY:
                _queue.append({"kind": "heartbeat"})
                last_beat = time.time()
            await flush()
        except asyncio.CancelledError:
            return
        except Exception as e:  # loop kabhi band na ho
            log.warning("hub loop: %s", e)


async def check_access(bot, user) -> dict:
    """{'allowed': bool, 'contact_url': str, 'contact_text': str, 'offline'?: True}"""
    _remember_bot(bot)
    now = time.time()
    if _allow_cache.get(user.id, 0) > now:
        return {"allowed": True}
    payload = {
        "bot": _bot or {"id": bot.id},
        "user": {"id": user.id, "username": (user.username or "")[:64], "name": (user.full_name or "")[:128]},
    }
    try:
        r = await _http().post(f"{HUB_URL}/access", json=payload)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning("hub: access check failed: %s", e)
        return {"allowed": False, "offline": True}
    if data.get("allowed"):
        _allow_cache[user.id] = now + ALLOW_CACHE
    else:
        _allow_cache.pop(user.id, None)
    return data


def denied_panel(res: dict, user):
    if res.get("offline"):
        text = (
            "⚠️ <b>Abhi permission check nahi ho payi.</b>\n"
            "Thodi der baad dobara try karein."
        )
        return text, InlineKeyboardMarkup([[B("« Menu", callback_data="m:home")]])
    msg = res.get("contact_text") or "⛔ Contact to admin for use this button."
    text = (
        f"🔒 <b>Session String Generator</b>\n\n{html.escape(msg)}\n\n"
        f"🆔 Aapki Telegram ID: <code>{user.id}</code>\n"
        "<i>Ye ID admin ko bhejiye — permission milte hi button chal jayega.</i>"
    )
    rows = []
    url = (res.get("contact_url") or "").strip()
    if url.startswith(("https://", "http://", "tg://")):
        rows.append([B("📩 Contact Admin", url=url)])
    rows.append([B("« Menu", callback_data="m:home")])
    return text, InlineKeyboardMarkup(rows)


# ------------------------------------------------------------------ handlers (group=-10, kuch block nahi karte)
async def on_any_command(update, context) -> None:
    msg = update.effective_message
    if not msg or not msg.text or not msg.text.startswith("/"):
        return
    cmd = msg.text.split()[0].split("@")[0][:40]  # sirf command, arguments nahi
    track("command", chat=update.effective_chat, user=update.effective_user, detail=cmd)


async def on_my_chat_member(update, context) -> None:
    cmu = update.my_chat_member
    if not cmu or cmu.chat.type == "private":
        return
    status = cmu.new_chat_member.status
    kind = "bot_removed" if status in ("left", "kicked") else "bot_added"
    old = cmu.old_chat_member.status
    if kind == "bot_added" and old in ("member", "administrator") and status in ("member", "administrator"):
        detail = "admin bana" if status == "administrator" else "admin hataya"
    else:
        detail = ""
    track(kind, chat=cmu.chat, user=cmu.from_user, detail=detail)
