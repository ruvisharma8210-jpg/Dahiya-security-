"""🤖 Instant One-Click Bot Cloner.

Koi bhi user bot ke private chat me:  /clone <BotFather_Token>
-> token check hota hai, naya clone isi process me background me LIVE ho jata hai (same features),
-> clone ka naam, username, token aur banane wale ki ID turant record (owner panel → Clone Management).
Restart par saare active clones apne aap dobara chalu ho jaate hain.
"""
import asyncio
import html
import logging
import re

from telegram import Bot, Update
from telegram.constants import ChatType
from telegram.error import InvalidToken, TelegramError
from telegram.ext import Application, ContextTypes

from . import store as st

log = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"\b(\d{6,12}:[A-Za-z0-9_-]{30,50})\b")
RUNNING: dict[int, Application] = {}
_shared: dict = {}  # master ka db / sessions / store — clones bhi wahi use karte hain

USAGE = (
    "<b>🤖 Apna khud ka clone bot banaiye</b>\n\n"
    "1. @BotFather me <code>/newbot</code> se naya bot banaiye aur token copy kijiye\n"
    "2. Yahan bhejiye:\n<code>/clone 123456789:ABCdef...</code>\n\n"
    "Bas! Aapka bot turant live ho jayega — saare features ke saath. "
    "<i>(Token wala message main turant delete kar deta hoon.)</i>"
)


def init(master_app: Application) -> None:
    for k in ("db", "sessions", "store"):
        _shared[k] = master_app.bot_data[k]
    _shared["master_id"] = master_app.bot.id if master_app.bot else None


def running_tokens() -> list[str]:
    return [a.bot.token for a in RUNNING.values()]


def is_running(bot_id: int) -> bool:
    return bot_id in RUNNING


async def start_clone(token: str, owner_id: int) -> Application:
    from . import wiring  # circular import se bachne ke liye yahan

    app = Application.builder().token(token).build()
    app.bot_data.update(_shared)
    app.bot_data["is_clone"] = True
    app.bot_data["clone_owner"] = owner_id
    wiring.register(app)
    await app.initialize()  # get_me — galat token par InvalidToken
    bot_id = app.bot.id

    def _on_poll_error(exc: TelegramError) -> None:
        log.warning("clone @%s polling error: %s", app.bot.username, exc)
        s = st.get()
        if s:
            s.set_clone_state(bot_id, error=str(exc)[:200])

    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True,
                                    error_callback=_on_poll_error)
    RUNNING[bot_id] = app
    try:
        await wiring.set_commands(app, master=False)
    except TelegramError:
        pass
    log.info("Clone live: @%s (%s)", app.bot.username, bot_id)
    return app


async def stop_clone(bot_id: int) -> bool:
    app = RUNNING.pop(bot_id, None)
    if app is None:
        return False
    for step in (app.updater.stop, app.stop, app.shutdown):
        try:
            await step()
        except Exception as e:
            log.warning("clone %s stop step failed: %s", bot_id, e)
    return True


async def stop_all() -> None:
    for bid in list(RUNNING):
        await stop_clone(bid)


async def boot_all() -> None:
    """Restart ke baad saare active clones dobara chalu."""
    s = st.get()
    if s is None:
        return
    for c in s.clones(active_only=True):
        token = s.clone_token(c["bot_id"])
        if not token:
            s.set_clone_state(c["bot_id"], error="token decrypt nahi hua (SESSION_SECRET badla?)")
            continue
        try:
            await start_clone(token, c["owner_id"])
            s.set_clone_state(c["bot_id"], error=None)
        except Exception as e:
            log.warning("clone %s boot failed: %s", c["bot_id"], e)
            s.set_clone_state(c["bot_id"], error=f"{type(e).__name__}: {e}"[:200])
            st.log("clone_error", detail=f"@{c['username']} boot: {type(e).__name__}", bot="master")
        await asyncio.sleep(0.5)


async def verify_token(token: str):
    """(bot User | None, error str)"""
    try:
        async with Bot(token) as b:
            return await b.get_me(), ""
    except InvalidToken:
        return None, "❌ Token galat hai ya BotFather se revoke ho chuka hai."
    except TelegramError as e:
        return None, f"❌ Telegram error: {html.escape(str(e))}"
    except Exception as e:
        return None, f"❌ Token check nahi ho paya: {html.escape(type(e).__name__)}"


async def cmd_clone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, user, chat = update.effective_message, update.effective_user, update.effective_chat
    m = TOKEN_RE.search(msg.text or "")
    if chat.type != ChatType.PRIVATE:
        if m:  # group me token aa gaya — turant hatao
            try:
                await msg.delete()
            except TelegramError:
                pass
        await msg.reply_text("🔐 /clone sirf bot ke private chat me chalta hai — mujhe DM kijiye.")
        return
    if not m:
        await msg.reply_html(USAGE)
        return
    token = m.group(1)
    try:
        await msg.delete()  # token chat me na rahe
    except TelegramError:
        pass
    s = st.get()
    wait = await context.bot.send_message(chat.id, "⏳ Token check kar raha hoon…")
    me, err = await verify_token(token)
    if me is None:
        await wait.edit_text(err, parse_mode="HTML")
        return
    if me.id == _shared.get("master_id") or me.id == context.bot.id:
        await wait.edit_text("❌ Ye isi bot ka token hai — apne naye bot ka token bhejiye.")
        return
    old = s.clone(me.id) if s else None
    if old and old["owner_id"] != user.id:
        await wait.edit_text("⛔ Ye bot kisi aur ke naam par pehle se clone hai. Admin se contact kijiye.")
        return
    if is_running(me.id):
        await stop_clone(me.id)  # naya token — restart
    try:
        await start_clone(token, user.id)
    except Exception as e:
        log.warning("clone start failed: %s", e)
        await wait.edit_text(f"❌ Clone start nahi hua: {html.escape(type(e).__name__)}", parse_mode="HTML")
        return
    is_new = s.save_clone(me.id, me.username or "", me.full_name or "", token, user.id, user.full_name or "")
    kind = "clone_created" if is_new else "clone_updated"
    st.log(kind, user=user, chat=chat, detail=f"@{me.username} ({me.full_name}) id={me.id}")
    await wait.edit_text(
        f"✅ <b>Clone LIVE ho gaya!</b>\n\n🤖 {html.escape(me.full_name or '')} — @{html.escape(me.username or '')}\n"
        f"🆔 Bot ID: <code>{me.id}</code>\n👤 Owner: <code>{user.id}</code>\n\n"
        f"Ab @{html.escape(me.username or '')} ko group me add karke <b>Admin</b> banaiye aur <code>/panel</code> bhejiye.",
        parse_mode="HTML",
    )
