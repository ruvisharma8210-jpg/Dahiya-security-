"""/start message ko owner panel se badalna: text, apne link buttons, aur built-in buttons chhupana.

Sab kuch Store ke flags table me save hota hai (keys "start:*"). Sirf master bot par lagta hai; clones default dikhate hain.
"""
import html
import json
import re

from . import store as st

DEFAULT_TEXT = (
    "<b>👋 Group Guard Bot</b>\n\n"
    "Neeche buttons se sab kuch kijiye:\n"
    "• <b>➕ Add to Group</b> — mujhe group me add karke admin banaiye\n"
    "• <b>⚙️ Group Settings</b> — Welcome, Auto-Approve, Security sab yahin se\n"
    "• <b>🔑 Session String</b> 🔒 — sirf admin ki permission wale users ke liye\n"
    "• <b>♻️ Revoke</b> — purani string band karke nayi lijiye\n"
    "• <b>🤖 Clone</b> — <code>/clone TOKEN</code> se apna khud ka bot\n\n"
    "Aapki Telegram ID: {id}"
)

# key -> label (owner panel me dikhane ke liye)
BUILTINS = [
    ("add", "➕ Add to Group"),
    ("settings", "⚙️ Group Settings"),
    ("welapp", "👋 Welcome + ✅ Auto-Approve"),
    ("sess", "🔑 Session String Generator"),
    ("revoke", "♻️ Revoke Session String"),
    ("clone", "🤖 Apna Clone Bot banao"),
]
MAX_BUTTONS = 20
MAX_TEXT = 3500
MAX_LABEL = 40

K_TEXT, K_BTNS, K_HIDE = "start:text", "start:buttons", "start:hidden"
_URL_RE = re.compile(r"^(https?://|tg://)[^\s]+$", re.I)


def _s():
    return st.get()


def _get(key):
    s = _s()
    return s.get_value(key) if s else None


def _set(key, value):
    s = _s()
    if s is None:
        raise RuntimeError("store not ready")
    if value is None:
        s.del_value(key)
    else:
        s.set_value(key, value)


# ------------------------------------------------------------------ text
def raw_text() -> str:
    return _get(K_TEXT) or DEFAULT_TEXT


def is_custom_text() -> bool:
    return bool(_get(K_TEXT))


def set_text(html_text: str | None) -> None:
    _set(K_TEXT, html_text or None)


def render_text(user_id: int, first_name: str = "") -> str:
    return (raw_text()
            .replace("{id}", f"<code>{user_id}</code>")
            .replace("{name}", html.escape(first_name or "")))


# ------------------------------------------------------------------ custom buttons
def buttons() -> list[dict]:
    try:
        data = json.loads(_get(K_BTNS) or "[]")
        return [b for b in data if isinstance(b, dict) and b.get("text") and b.get("url")]
    except (ValueError, TypeError):
        return []


def _save_buttons(btns: list[dict]) -> None:
    _set(K_BTNS, json.dumps(btns, ensure_ascii=False) if btns else None)


def normalize_url(link: str) -> str | None:
    link = link.strip().strip("<>")
    if link.startswith("@") and len(link) > 1:
        link = "https://t.me/" + link[1:]
    elif re.match(r"^(t\.me|telegram\.me|www\.)", link, re.I) or re.match(r"^[\w-]+(\.[\w-]+)+(/\S*)?$", link):
        link = "https://" + link
    return link if _URL_RE.match(link) else None


def parse_line(line: str) -> tuple[str, str] | None:
    """'Naam - link' / 'Naam | link' / 'Naam link' -> (naam, url)."""
    line = line.strip()
    if not line:
        return None
    parts = line.rsplit(None, 1)
    if len(parts) != 2:
        return None
    label, link = parts[0].strip().rstrip("-|:–—").strip(), parts[1]
    url = normalize_url(link)
    if not label or not url:
        return None
    return label[:MAX_LABEL], url


def add_buttons(text: str) -> tuple[list[tuple[str, str]], list[str], bool]:
    """Har line ek button. Returns (jode gaye, galat lines, limit poori hui?)."""
    btns = buttons()
    added, bad, full = [], [], False
    for line in text.splitlines():
        if not line.strip():
            continue
        p = parse_line(line)
        if p is None:
            bad.append(line.strip()[:60])
            continue
        if len(btns) >= MAX_BUTTONS:
            full = True
            break
        btns.append({"text": p[0], "url": p[1]})
        added.append(p)
    if added:
        _save_buttons(btns)
    return added, bad, full


def remove_button(index: int) -> dict | None:
    btns = buttons()
    if 0 <= index < len(btns):
        gone = btns.pop(index)
        _save_buttons(btns)
        return gone
    return None


def move_button(index: int, delta: int) -> bool:
    btns = buttons()
    j = index + delta
    if 0 <= index < len(btns) and 0 <= j < len(btns):
        btns[index], btns[j] = btns[j], btns[index]
        _save_buttons(btns)
        return True
    return False


# ------------------------------------------------------------------ built-in buttons on/off
def hidden() -> set[str]:
    try:
        return set(json.loads(_get(K_HIDE) or "[]"))
    except (ValueError, TypeError):
        return set()


def toggle_builtin(key: str) -> bool:
    """Returns True agar ab dikh raha hai."""
    if key not in dict(BUILTINS):
        return True
    h = hidden()
    if key in h:
        h.discard(key)
    else:
        h.add(key)
    _set(K_HIDE, json.dumps(sorted(h)) if h else None)
    return key not in h


def reset_all() -> None:
    for k in (K_TEXT, K_BTNS, K_HIDE):
        _set(k, None)
