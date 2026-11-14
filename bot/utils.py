import html
import logging
import re
import time
from datetime import datetime, timedelta, timezone

from telegram import Bot, Chat, ChatPermissions, User
from telegram.error import TelegramError

from .config import OWNER_IDS

log = logging.getLogger(__name__)

ANON_ADMIN_ID = 1087968824  # @GroupAnonymousBot
_ADMIN_CACHE: dict[int, tuple[float, set[int]]] = {}

DEFAULT_PERMS = ChatPermissions(
    can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True,
    can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True, can_send_polls=True,
    can_send_other_messages=True, can_add_web_page_previews=True, can_invite_users=True,
)


async def admin_ids(bot: Bot, chat_id: int, fresh: bool = False) -> set[int]:
    now = time.time()
    cached = _ADMIN_CACHE.get(chat_id)
    if cached and not fresh and now - cached[0] < 300:
        return cached[1]
    try:
        ids = {a.user.id for a in await bot.get_chat_administrators(chat_id)}
    except TelegramError as e:
        log.warning("admin list failed for %s: %s", chat_id, e)
        ids = cached[1] if cached else set()
    _ADMIN_CACHE[chat_id] = (now, ids)
    return ids


async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    if user_id in OWNER_IDS:
        return True
    if user_id in await admin_ids(bot, chat_id):
        return True
    # naya admin bana ho to cache refresh karke dobara check
    return user_id in await admin_ids(bot, chat_id, fresh=True)


def mention(user: User) -> str:
    return f'<a href="tg://user?id={user.id}">{html.escape(user.full_name or str(user.id))}</a>'


def fmt_dur(secs: int) -> str:
    secs = int(secs or 0)
    if secs <= 0:
        return "Permanent"
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs % size == 0:
            return f"{secs // size}{unit}"
    return f"{secs}s"


_DUR_RE = re.compile(r"^(\d+)\s*([smhdw]?)$")


def parse_dur(text: str) -> int | None:
    """'15m' -> 900, '2h' -> 7200, '3d', '1w', 'perm' -> 0. Invalid -> None."""
    t = text.strip().lower()
    if t in {"perm", "permanent", "forever", "0", "p"}:
        return 0
    m = _DUR_RE.match(t)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2) or "m"
    secs = n * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
    if secs < 60 or secs > 365 * 86400:
        return None
    return secs


def _until(secs: int):
    return None if not secs else datetime.now(timezone.utc) + timedelta(seconds=secs)


async def mute(bot: Bot, chat_id: int, user_id: int, secs: int) -> bool:
    try:
        await bot.restrict_chat_member(chat_id, user_id, ChatPermissions.no_permissions(), until_date=_until(secs))
        return True
    except TelegramError as e:
        log.warning("mute failed: %s", e)
        return False


async def ban(bot: Bot, chat_id: int, user_id: int, secs: int) -> bool:
    try:
        await bot.ban_chat_member(chat_id, user_id, until_date=_until(secs))
        return True
    except TelegramError as e:
        log.warning("ban failed: %s", e)
        return False


async def safe_delete(message) -> None:
    try:
        await message.delete()
    except TelegramError:
        pass


def render_welcome(template: str, user: User, chat: Chat) -> str:
    text = html.escape(template)
    values = {
        "{mention}": mention(user),
        "{name}": html.escape(user.full_name or ""),
        "{first_name}": html.escape(user.first_name or ""),
        "{username}": "@" + user.username if user.username else html.escape(user.full_name or ""),
        "{id}": f"<code>{user.id}</code>",
        "{group}": html.escape(chat.title or ""),
    }
    for k, v in values.items():
        text = text.replace(k, v)
    return text
