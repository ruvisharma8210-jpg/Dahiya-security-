"""SQLite storage: per-group settings (JSON), bad words, allowed domains, warnings."""
import copy
import json
import sqlite3
import threading

DEFAULT_WELCOME = "Welcome {mention}, your ID is {id} 🎉"
DEFAULT_APPROVE_DM = "✅ Aapki request approve ho gayi! Welcome to {group} 🎉"

DEFAULTS = {
    "auto_accept": False,
    "welcome_on": True,
    "welcome_text": DEFAULT_WELCOME,
    "welcome_delete": 0,  # seconds ke baad welcome message auto-delete, 0 = kabhi nahi
    "welcome_clean": False,  # naya welcome aane par purana welcome delete
    "approve_delay": 0,  # join request approve karne se pehle wait (seconds)
    "approve_dm": False,  # approve hone par user ko DM
    "approve_dm_text": DEFAULT_APPROVE_DM,
    "approve_count": 0,
    "antilink": {"on": True, "action": "delete", "mute_secs": 3600},  # delete|warn|mute|pban
    "badwords": {"on": True},
    "warn_limit": 3,
    "final_action": "mute",  # mute|ban|pban  (warn limit poora hone par)
    "mute_duration": 3600,  # seconds, 0 = permanent
    "ban_duration": 86400,  # seconds, 0 = permanent
    "flood": {"on": True, "limit": 4, "window": 5, "action": "m300"},  # m<secs> | pban
    "antileft": {"on": False, "window": 60},
    "lockdown": False,
    "saved_perms": None,
}


def _merge(base: dict, data: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (data or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class DB:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (chat_id INTEGER PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS bad_words (chat_id INTEGER, word TEXT, PRIMARY KEY (chat_id, word));
                CREATE TABLE IF NOT EXISTS domains (chat_id INTEGER, domain TEXT, PRIMARY KEY (chat_id, domain));
                CREATE TABLE IF NOT EXISTS chats (chat_id INTEGER PRIMARY KEY, title TEXT);
                CREATE TABLE IF NOT EXISTS warns (chat_id INTEGER, user_id INTEGER, count INTEGER,
                                                  PRIMARY KEY (chat_id, user_id));
                """
            )
            self.conn.commit()

    # ---------- settings ----------
    def get(self, chat_id: int) -> dict:
        with self.lock:
            row = self.conn.execute("SELECT data FROM settings WHERE chat_id=?", (chat_id,)).fetchone()
        return _merge(DEFAULTS, json.loads(row[0]) if row else {})

    def save(self, chat_id: int, data: dict) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO settings (chat_id, data) VALUES (?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET data=excluded.data",
                (chat_id, json.dumps(data)),
            )
            self.conn.commit()

    def set(self, chat_id: int, path: str, value) -> dict:
        s = self.get(chat_id)
        node = s
        keys = path.split(".")
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value
        self.save(chat_id, s)
        return s

    def toggle(self, chat_id: int, path: str) -> bool:
        s = self.get(chat_id)
        node = s
        keys = path.split(".")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = not bool(node.get(keys[-1]))
        self.save(chat_id, s)
        return node[keys[-1]]

    # ---------- generic list helpers ----------
    def _add(self, table, col, chat_id, value) -> bool:
        with self.lock:
            cur = self.conn.execute(f"INSERT OR IGNORE INTO {table} (chat_id, {col}) VALUES (?, ?)", (chat_id, value))
            self.conn.commit()
            return cur.rowcount > 0

    def _remove(self, table, col, chat_id, value) -> bool:
        with self.lock:
            cur = self.conn.execute(f"DELETE FROM {table} WHERE chat_id=? AND {col}=?", (chat_id, value))
            self.conn.commit()
            return cur.rowcount > 0

    def _list(self, table, col, chat_id) -> list:
        with self.lock:
            rows = self.conn.execute(f"SELECT {col} FROM {table} WHERE chat_id=? ORDER BY {col}", (chat_id,)).fetchall()
        return [r[0] for r in rows]

    def add_word(self, chat_id, w): return self._add("bad_words", "word", chat_id, w.lower())
    def remove_word(self, chat_id, w): return self._remove("bad_words", "word", chat_id, w.lower())
    def words(self, chat_id): return self._list("bad_words", "word", chat_id)

    def add_domain(self, chat_id, d): return self._add("domains", "domain", chat_id, d.lower())
    def remove_domain(self, chat_id, d): return self._remove("domains", "domain", chat_id, d.lower())
    def domains(self, chat_id): return self._list("domains", "domain", chat_id)

    # ---------- known groups (private chat se manage karne ke liye) ----------
    def remember_chat(self, chat_id: int, title: str) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO chats (chat_id, title) VALUES (?, ?) ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title",
                (chat_id, title or ""),
            )
            self.conn.commit()

    def forget_chat(self, chat_id: int) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM chats WHERE chat_id=?", (chat_id,))
            self.conn.commit()

    def chats(self) -> list[tuple[int, str]]:
        with self.lock:
            return self.conn.execute("SELECT chat_id, title FROM chats ORDER BY title").fetchall()

    # ---------- warnings ----------
    def add_warn(self, chat_id: int, user_id: int) -> int:
        with self.lock:
            self.conn.execute(
                "INSERT INTO warns (chat_id, user_id, count) VALUES (?, ?, 1) "
                "ON CONFLICT(chat_id, user_id) DO UPDATE SET count=count+1",
                (chat_id, user_id),
            )
            self.conn.commit()
            return self.conn.execute(
                "SELECT count FROM warns WHERE chat_id=? AND user_id=?", (chat_id, user_id)
            ).fetchone()[0]

    def get_warns(self, chat_id: int, user_id: int) -> int:
        with self.lock:
            row = self.conn.execute("SELECT count FROM warns WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
        return row[0] if row else 0

    def reset_warns(self, chat_id: int, user_id: int) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM warns WHERE chat_id=? AND user_id=?", (chat_id, user_id))
            self.conn.commit()
