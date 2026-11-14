"""Inline-button panels. Callback data format:
  p:<panel>                    -> open panel
  t:<panel>:<path>             -> toggle boolean setting
  s:<panel>:<path>:<value>     -> set value
  i:<panel>:<kind>             -> ask admin for text input
  a:<panel>:<action>           -> run an action
"""
import html

from telegram import InlineKeyboardButton as B
from telegram import InlineKeyboardMarkup

from .db import DB
from .utils import fmt_dur


def onoff(v: bool, on="🟢 ON", off="🔴 OFF") -> str:
    return on if v else off


def pick(label: str, selected: bool) -> str:
    return f"✅ {label}" if selected else label


def hdr(text: str) -> B:
    return B(f"— {text} —", callback_data="noop")


def back(to: str) -> list:
    return [B("« Back", callback_data=f"p:{to}")]


def main_panel(s, db, chat_id, title):
    text = (
        f"<b>⚙️ Control Panel</b>\n<i>{html.escape(title or '')}</i>\n\n"
        f"Auto-Accept: {onoff(s['auto_accept'])}\n"
        f"Lockdown: {onoff(s['lockdown'], '🔒 ON', '🔓 OFF')}\n\n"
        "Section chuniye:"
    )
    kb = [
        [B("⚙️ Welcome & Auto-Accept", callback_data="p:welcome")],
        [B("🛡️ Security & Moderation", callback_data="p:sec")],
        [B("⏳ Punishment & Warnings", callback_data="p:punish")],
        [B("✖️ Close", callback_data="x")],
    ]
    return text, kb


def welcome_panel(s, db, chat_id, title):
    text = (
        "<b>⚙️ Auto-Accept & Welcome</b>\n\n"
        f"Auto-Accept join requests: {onoff(s['auto_accept'])}\n"
        f"Welcome message: {onoff(s['welcome_on'])}\n\n"
        f"<b>Current text:</b>\n<code>{html.escape(s['welcome_text'])}</code>\n\n"
        "<i>Placeholders: {name} {first_name} {username} {id} {mention} {group}</i>"
    )
    kb = [
        [B(f"Auto-Accept: {onoff(s['auto_accept'])}", callback_data="t:welcome:auto_accept")],
        [B(f"Welcome: {onoff(s['welcome_on'])}", callback_data="t:welcome:welcome_on")],
        [B("✏️ Edit Welcome Text", callback_data="i:welcome:welcome"),
         B("👁️ Preview", callback_data="a:welcome:preview")],
        [B("♻️ Reset to Default", callback_data="a:welcome:welcome_reset")],
        back("main"),
    ]
    return text, kb


def sec_panel(s, db, chat_id, title):
    fl = s["flood"]
    text = (
        "<b>🛡️ Security & Moderation</b>\n\n"
        f"🔗 Anti-Link: {onoff(s['antilink']['on'])} · action <b>{s['antilink']['action']}</b>\n"
        f"🚫 Bad Words: {onoff(s['badwords']['on'])} · {len(db.words(chat_id))} words\n"
        f"🌊 Anti-Flood: {onoff(fl['on'])} · {fl['limit']} msgs / {fl['window']}s\n"
        f"🚪 Anti-Left: {onoff(s['antileft']['on'])} · {s['antileft']['window']}s\n"
        f"🔒 Lockdown: {onoff(s['lockdown'], '🔒 ON', '🔓 OFF')}"
    )
    kb = [
        [B(f"🔗 Anti-Link {onoff(s['antilink']['on'], '🟢', '🔴')}", callback_data="p:link"),
         B(f"🚫 Bad Words {onoff(s['badwords']['on'], '🟢', '🔴')}", callback_data="p:words")],
        [B(f"🌊 Anti-Flood {onoff(fl['on'], '🟢', '🔴')}", callback_data="p:flood"),
         B(f"🚪 Anti-Raid {onoff(s['antileft']['on'], '🟢', '🔴')}", callback_data="p:raid")],
        [B(f"Lockdown: {onoff(s['lockdown'], '🔒 ON', '🔓 OFF')}", callback_data="a:sec:lockdown")],
        back("main"),
    ]
    return text, kb


def link_panel(s, db, chat_id, title):
    al = s["antilink"]
    doms = db.domains(chat_id)
    text = (
        "<b>🔗 Anti-Link Settings</b>\n\n"
        f"Status: {onoff(al['on'], '🟢 Active', '🔴 Inactive')}\n"
        f"Action: <b>{al['action']}</b>  (mute time {fmt_dur(al['mute_secs'])})\n"
        f"Allowed domains: {', '.join(doms) if doms else '<i>none</i>'}\n\n"
        "<i>Link wala message hamesha delete hoga; action uske upar extra hai.</i>"
    )
    a = al["action"]
    m = al["mute_secs"]
    kb = [
        [B(f"Status: {onoff(al['on'], '🟢 Active', '🔴 Inactive')}", callback_data="t:link:antilink.on")],
        [hdr("Action")],
        [B(pick("🗑 Delete Only", a == "delete"), callback_data="s:link:antilink.action:delete"),
         B(pick("⚠️ Warn", a == "warn"), callback_data="s:link:antilink.action:warn")],
        [B(pick(f"🔇 Mute {fmt_dur(m)}", a == "mute"), callback_data="s:link:antilink.action:mute"),
         B(pick("⛔ Permanent Ban", a == "pban"), callback_data="s:link:antilink.action:pban")],
        [hdr("Mute time")],
        [B(pick("10m", m == 600), callback_data="s:link:antilink.mute_secs:600"),
         B(pick("1h", m == 3600), callback_data="s:link:antilink.mute_secs:3600"),
         B(pick("24h", m == 86400), callback_data="s:link:antilink.mute_secs:86400")],
        [hdr("Allowed / Trusted links")],
        [B("➕ Add Domain", callback_data="i:link:add_domain"),
         B("➖ Remove Domain", callback_data="i:link:rm_domain")],
        back("sec"),
    ]
    return text, kb


def words_panel(s, db, chat_id, title):
    n = len(db.words(chat_id))
    lim = s["warn_limit"]
    fa = s["final_action"]
    text = (
        "<b>🚫 Bad Words / Blacklist</b>\n\n"
        f"Status: {onoff(s['badwords']['on'], '🟢 Active', '🔴 Inactive')}\n"
        f"Words in list: <b>{n}</b>\n"
        f"Har bad word = message delete + 1 warning\n"
        f"<b>{lim}</b> warnings ke baad: <b>{final_label(s)}</b>"
    )
    kb = [
        [B(f"Status: {onoff(s['badwords']['on'], '🟢 Active', '🔴 Inactive')}", callback_data="t:words:badwords.on")],
        [B("➕ Add Word", callback_data="i:words:add_word"),
         B("🗑️ Remove Word", callback_data="i:words:rm_word")],
        [B("📋 View List", callback_data="a:words:list_words")],
        [hdr("Warning limit")],
        [B(pick("3", lim == 3), callback_data="s:words:warn_limit:3"),
         B(pick("5", lim == 5), callback_data="s:words:warn_limit:5"),
         B("✏️ Custom" if lim in (3, 5) else f"✅ {lim} ✏️", callback_data="i:words:warn_custom")],
        [hdr("Limit ke baad action")],
        [B(pick(f"🔇 Mute {fmt_dur(s['mute_duration'])}", fa == "mute"), callback_data="s:words:final_action:mute"),
         B(pick(f"⛔ Ban {fmt_dur(s['ban_duration'])}", fa == "ban"), callback_data="s:words:final_action:ban")],
        [B(pick("☠️ Permanent Ban", fa == "pban"), callback_data="s:words:final_action:pban")],
        [B("⏳ Durations change karein", callback_data="p:punish")],
        back("sec"),
    ]
    return text, kb


def flood_panel(s, db, chat_id, title):
    fl = s["flood"]
    a = fl["action"]
    text = (
        "<b>🌊 Anti-Flood & Spam</b>\n\n"
        f"Status: {onoff(fl['on'], '🟢 Active', '🔴 Inactive')}\n"
        f"Rule: <b>{fl['window']} second</b> me <b>{fl['limit']}</b> se zyada messages = spam\n"
        f"Action: <b>{flood_label(a)}</b>"
    )
    kb = [
        [B(f"Status: {onoff(fl['on'], '🟢 Active', '🔴 Inactive')}", callback_data="t:flood:flood.on")],
        [hdr("Max messages")],
        [B(pick(str(n), fl["limit"] == n), callback_data=f"s:flood:flood.limit:{n}") for n in (3, 4, 5, 8)],
        [hdr("Time window (seconds)")],
        [B(pick(f"{n}s", fl["window"] == n), callback_data=f"s:flood:flood.window:{n}") for n in (3, 5, 10)],
        [hdr("Action")],
        [B(pick("Mute 5m", a == "m300"), callback_data="s:flood:flood.action:m300"),
         B(pick("Mute 30m", a == "m1800"), callback_data="s:flood:flood.action:m1800"),
         B(pick("Mute 1h", a == "m3600"), callback_data="s:flood:flood.action:m3600")],
        [B(pick("⛔ Direct Ban", a == "pban"), callback_data="s:flood:flood.action:pban")],
        back("sec"),
    ]
    return text, kb


def raid_panel(s, db, chat_id, title):
    al = s["antileft"]
    w = al["window"]
    text = (
        "<b>🚪 Anti-Left / Anti-Raid Shield</b>\n\n"
        f"Auto-Ban on Quick Exit: {onoff(al['on'], '🟢 Enabled', '🔴 Disabled')}\n"
        f"Join karke <b>{fmt_dur(w) if w >= 60 else str(w) + 's'}</b> ke andar left = permanent ban\n\n"
        f"Lockdown: {onoff(s['lockdown'], '🔒 ON — koi message nahi bhej sakta', '🔓 OFF')}"
    )
    kb = [
        [B(f"Quick Exit Ban: {onoff(al['on'], '🟢 Enabled', '🔴 Disabled')}", callback_data="t:raid:antileft.on")],
        [hdr("Quick exit window")],
        [B(pick("30s", w == 30), callback_data="s:raid:antileft.window:30"),
         B(pick("60s", w == 60), callback_data="s:raid:antileft.window:60"),
         B(pick("5m", w == 300), callback_data="s:raid:antileft.window:300")],
        [B(f"🚨 Lockdown: {onoff(s['lockdown'], '🔒 ON', '🔓 OFF')}", callback_data="a:raid:lockdown")],
        back("sec"),
    ]
    return text, kb


def punish_panel(s, db, chat_id, title):
    md, bd, lim = s["mute_duration"], s["ban_duration"], s["warn_limit"]
    text = (
        "<b>⏳ Punishment & Warning Durations</b>\n\n"
        f"🔇 Mute duration: <b>{fmt_dur(md)}</b>\n"
        f"⛔ Ban duration: <b>{fmt_dur(bd)}</b>\n"
        f"⚠️ Warning limit: <b>{lim}</b> → phir <b>{final_label(s)}</b>"
    )
    custom_md = md not in (600, 3600, 86400, 0)
    kb = [
        [hdr("Mute duration")],
        [B(pick("10m", md == 600), callback_data="s:punish:mute_duration:600"),
         B(pick("1h", md == 3600), callback_data="s:punish:mute_duration:3600"),
         B(pick("24h", md == 86400), callback_data="s:punish:mute_duration:86400")],
        [B(pick("Permanent", md == 0), callback_data="s:punish:mute_duration:0"),
         B(f"✅ {fmt_dur(md)} ✏️" if custom_md else "✏️ Custom", callback_data="i:punish:mute_custom")],
        [hdr("Ban duration")],
        [B(pick("1 Day", bd == 86400), callback_data="s:punish:ban_duration:86400"),
         B(pick("7 Days", bd == 604800), callback_data="s:punish:ban_duration:604800"),
         B(pick("Permanent", bd == 0), callback_data="s:punish:ban_duration:0")],
        [hdr("Warning count limit")],
        [B(pick("3", lim == 3), callback_data="s:punish:warn_limit:3"),
         B(pick("5", lim == 5), callback_data="s:punish:warn_limit:5"),
         B("✏️ Custom" if lim in (3, 5) else f"✅ {lim} ✏️", callback_data="i:punish:warn_custom")],
        [hdr("Final action")],
        [B(pick("🔇 Mute", s["final_action"] == "mute"), callback_data="s:punish:final_action:mute"),
         B(pick("⛔ Ban", s["final_action"] == "ban"), callback_data="s:punish:final_action:ban"),
         B(pick("☠️ Perm Ban", s["final_action"] == "pban"), callback_data="s:punish:final_action:pban")],
        back("main"),
    ]
    return text, kb


def final_label(s) -> str:
    fa = s["final_action"]
    if fa == "mute":
        return f"Mute {fmt_dur(s['mute_duration'])}"
    if fa == "ban":
        return f"Ban {fmt_dur(s['ban_duration'])}"
    return "Permanent Ban"


def flood_label(a: str) -> str:
    return "Direct Ban" if a == "pban" else f"Mute {fmt_dur(int(a[1:]))}"


PANELS = {
    "main": main_panel,
    "welcome": welcome_panel,
    "sec": sec_panel,
    "link": link_panel,
    "words": words_panel,
    "flood": flood_panel,
    "raid": raid_panel,
    "punish": punish_panel,
}


def build(panel: str, db: DB, chat_id: int, title: str):
    fn = PANELS.get(panel, main_panel)
    text, kb = fn(db.get(chat_id), db, chat_id, title)
    return text, InlineKeyboardMarkup(kb)
