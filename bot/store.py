"""🎛️ Owner Control Center storage (same SQLite file as the rest of the bot).

Tables: whitelist · clones · activity (A-Z logs) · users · flags · counters
Clone tokens Fernet se encrypted rehte hain (sessions wali hi key: SESSION_SECRET / secret.key).
"""
import contextvars
import sqlite3
import threading
import time

from cryptography.fernet import Fernet, InvalidToken

# Har update ke handlers ek hi task me chalte hain, isliye yahan set ki gayi value
# us update ke saare handlers (aur hub.track) ko dikhti hai — log me "kis bot par hua" aata hai.
current_bot: contextvars.ContextVar[str] = contextvars.ContextVar("current_bot", default="")

STORE: "Store | None" = None
MAX_LOGS = 50_000

# Log filters (owner panel) -> kinds
LOG_FILTERS = {
    "all": None,
    "clone": ("clone_created", "clone_updated", "clone_deleted", "clone_started", "clone_stopped", "clone_error"),
    "sess": ("session_generated", "whitelist_add", "whitelist_remove", "session_denied"),
    "mod": ("moderation", "join_approved", "antiss"),
    "grp": ("bot_added", "bot_removed", "group_kicked", "group_sync", "admin_missing"),
    "cmd": ("command",),
}


def get() -> "Store | None":
    return STORE


def log(kind: str, user=None, chat=None, detail: str = "", bot: str | None = None) -> None:
    """Sirf local A-Z log (Hub ko nahi jata). Kabhi exception nahi uthata."""
    if STORE is None:
        return
    try:
        STORE.log_event(kind, user=user, chat=chat, detail=detail, bot=bot)
    except Exception:
        pass


class Store:
    def __init__(self, path: str, key: bytes):
        self.fernet = Fernet(key)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self._seen: dict[int, float] = {}
        self._inserts = 0
        with self.lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS whitelist (user_id INTEGER PRIMARY KEY, note TEXT,
                                                      added_by INTEGER, added_at REAL);
                CREATE TABLE IF NOT EXISTS clones (bot_id INTEGER PRIMARY KEY, username TEXT, name TEXT,
                                                   token BLOB NOT NULL, owner_id INTEGER, owner_name TEXT,
                                                   created_at REAL, active INTEGER DEFAULT 1, last_error TEXT);
                CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, bot TEXT,
                                                     kind TEXT, chat_id INTEGER, chat_title TEXT,
                                                     user_id INTEGER, username TEXT, detail TEXT);
                CREATE INDEX IF NOT EXISTS idx_activity_kind ON activity (kind, id);
                CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, name TEXT,
                                                  first_seen REAL, last_seen REAL);
                CREATE TABLE IF NOT EXISTS bot_groups (bot_id INTEGER, chat_id INTEGER, title TEXT,
                                                       PRIMARY KEY (bot_id, chat_id));
                CREATE TABLE IF NOT EXISTS flags (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS counters (key TEXT PRIMARY KEY, n INTEGER NOT NULL DEFAULT 0);
                """
            )
            self.conn.commit()

    # ------------------------------------------------------------------ flags & counters
    def flag(self, key: str, default: bool = False) -> bool:
        with self.lock:
            row = self.conn.execute("SELECT value FROM flags WHERE key=?", (key,)).fetchone()
        return default if row is None else row[0] == "1"

    def set_flag(self, key: str, on: bool) -> None:
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO flags (key, value) VALUES (?, ?)", (key, "1" if on else "0"))
            self.conn.commit()

    def get_value(self, key: str) -> str | None:
        with self.lock:
            row = self.conn.execute("SELECT value FROM flags WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_value(self, key: str, value: str) -> None:
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO flags (key, value) VALUES (?, ?)", (key, value))
            self.conn.commit()

    def del_value(self, key: str) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM flags WHERE key=?", (key,))
            self.conn.commit()

    def incr(self, key: str, by: int = 1) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO counters (key, n) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET n = n + ?", (key, by, by))
            self.conn.commit()

    def counter(self, key: str) -> int:
        with self.lock:
            row = self.conn.execute("SELECT n FROM counters WHERE key=?", (key,)).fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------ users
    def touch_user(self, user) -> None:
        """Har user ko record karo (10 min me max ek write per user)."""
        now = time.time()
        if self._seen.get(user.id, 0) > now - 600:
            return
        self._seen[user.id] = now
        with self.lock:
            self.conn.execute(
                "INSERT INTO users (user_id, username, name, first_seen, last_seen) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, name=excluded.name, "
                "last_seen=excluded.last_seen",
                (user.id, user.username or "", (user.full_name or "")[:128], now, now))
            self.conn.commit()

    def user_name(self, user_id: int) -> str:
        with self.lock:
            row = self.conn.execute("SELECT username, name FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return ""
        return f"@{row[0]}" if row[0] else (row[1] or "")

    def user_counts(self) -> tuple[int, int]:
        """(total users, last 24h active)"""
        with self.lock:
            total = self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            day = self.conn.execute("SELECT COUNT(*) FROM users WHERE last_seen > ?", (time.time() - 86400,)).fetchone()[0]
        return total, day

    # ------------------------------------------------------------------ connected groups (per bot)
    def remember_bot_group(self, bot_id: int, chat_id: int, title: str) -> None:
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO bot_groups (bot_id, chat_id, title) VALUES (?, ?, ?)",
                              (bot_id, chat_id, (title or "")[:128]))
            self.conn.commit()

    def forget_bot_group(self, bot_id: int, chat_id: int) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM bot_groups WHERE bot_id=? AND chat_id=?", (bot_id, chat_id))
            self.conn.commit()

    def bot_groups(self) -> list[tuple[int, int, str]]:
        with self.lock:
            return self.conn.execute("SELECT bot_id, chat_id, title FROM bot_groups ORDER BY title").fetchall()

    # ------------------------------------------------------------------ whitelist
    def whitelist(self) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT user_id, note, added_by, added_at FROM whitelist ORDER BY added_at").fetchall()
        return [dict(zip(("user_id", "note", "added_by", "added_at"), r)) for r in rows]

    def is_whitelisted(self, user_id: int) -> bool:
        with self.lock:
            return self.conn.execute("SELECT 1 FROM whitelist WHERE user_id=?", (user_id,)).fetchone() is not None

    def add_whitelist(self, user_id: int, added_by: int, note: str = "") -> bool:
        with self.lock:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO whitelist (user_id, note, added_by, added_at) VALUES (?, ?, ?, ?)",
                (user_id, note[:64], added_by, time.time()))
            self.conn.commit()
            return cur.rowcount > 0

    def remove_whitelist(self, user_id: int) -> bool:
        with self.lock:
            cur = self.conn.execute("DELETE FROM whitelist WHERE user_id=?", (user_id,))
            self.conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------ clones
    _CLONE_COLS = ("bot_id", "username", "name", "owner_id", "owner_name", "created_at", "active", "last_error")

    def save_clone(self, bot_id: int, username: str, name: str, token: str, owner_id: int, owner_name: str) -> bool:
        """True = naya clone, False = purana update hua."""
        enc = self.fernet.encrypt(token.encode())
        with self.lock:
            exists = self.conn.execute("SELECT 1 FROM clones WHERE bot_id=?", (bot_id,)).fetchone() is not None
            if exists:
                self.conn.execute(
                    "UPDATE clones SET username=?, name=?, token=?, owner_id=?, owner_name=?, active=1, last_error=NULL "
                    "WHERE bot_id=?", (username, name, enc, owner_id, owner_name, bot_id))
            else:
                self.conn.execute(
                    "INSERT INTO clones (bot_id, username, name, token, owner_id, owner_name, created_at, active) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 1)", (bot_id, username, name, enc, owner_id, owner_name, time.time()))
            self.conn.commit()
        return not exists

    def clones(self, active_only: bool = False) -> list[dict]:
        q = f"SELECT {', '.join(self._CLONE_COLS)} FROM clones"
        if active_only:
            q += " WHERE active=1"
        with self.lock:
            rows = self.conn.execute(q + " ORDER BY created_at DESC").fetchall()
        return [dict(zip(self._CLONE_COLS, r)) for r in rows]

    def clone(self, bot_id: int) -> dict | None:
        return next((c for c in self.clones() if c["bot_id"] == bot_id), None)

    def clone_token(self, bot_id: int) -> str | None:
        with self.lock:
            row = self.conn.execute("SELECT token FROM clones WHERE bot_id=?", (bot_id,)).fetchone()
        if not row:
            return None
        try:
            return self.fernet.decrypt(row[0]).decode()
        except InvalidToken:
            return None

    def token_in_use(self, token: str) -> int | None:
        for c in self.clones():
            if self.clone_token(c["bot_id"]) == token:
                return c["bot_id"]
        return None

    def set_clone_state(self, bot_id: int, active: bool | None = None, error: str | None = "") -> None:
        with self.lock:
            if active is not None:
                self.conn.execute("UPDATE clones SET active=? WHERE bot_id=?", (1 if active else 0, bot_id))
            if error != "":
                self.conn.execute("UPDATE clones SET last_error=? WHERE bot_id=?", (error, bot_id))
            self.conn.commit()

    def delete_clone(self, bot_id: int) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM clones WHERE bot_id=?", (bot_id,))
            self.conn.commit()

    # ------------------------------------------------------------------ activity logs
    def log_event(self, kind: str, user=None, chat=None, detail: str = "", bot: str | None = None,
                  user_id: int | None = None, username: str = "", chat_id: int | None = None,
                  chat_title: str = "") -> None:
        if user is not None:
            user_id = user.id
            username = user.username or getattr(user, "full_name", "") or ""
        if chat is not None:
            chat_id = chat.id
            chat_title = getattr(chat, "title", None) or getattr(chat, "full_name", None) or ""
        with self.lock:
            self.conn.execute(
                "INSERT INTO activity (ts, bot, kind, chat_id, chat_title, user_id, username, detail) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (time.time(), bot if bot is not None else current_bot.get(), kind, chat_id,
                 str(chat_title or "")[:128], user_id, str(username or "")[:64], str(detail or "")[:300]))
            self._inserts += 1
            if self._inserts % 500 == 0:  # purane logs trim (sirf latest MAX_LOGS rakhte hain)
                self.conn.execute(
                    "DELETE FROM activity WHERE id <= (SELECT MAX(id) FROM activity) - ?", (MAX_LOGS,))
            self.conn.commit()

    def logs(self, flt: str = "all", offset: int = 0, limit: int = 12) -> tuple[list[dict], int]:
        kinds = LOG_FILTERS.get(flt)
        where, args = "", []
        if kinds:
            where = f"WHERE kind IN ({','.join('?' * len(kinds))})"
            args = list(kinds)
        cols = ("id", "ts", "bot", "kind", "chat_id", "chat_title", "user_id", "username", "detail")
        with self.lock:
            total = self.conn.execute(f"SELECT COUNT(*) FROM activity {where}", args).fetchone()[0]
            rows = self.conn.execute(
                f"SELECT {', '.join(cols)} FROM activity {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                args + [limit, offset]).fetchall()
        return [dict(zip(cols, r)) for r in rows], total

    def count_kind(self, *kinds: str) -> int:
        with self.lock:
            return self.conn.execute(
                f"SELECT COUNT(*) FROM activity WHERE kind IN ({','.join('?' * len(kinds))})", kinds).fetchone()[0]
