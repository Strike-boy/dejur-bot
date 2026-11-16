import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS queue_state(
    queue_key TEXT PRIMARY KEY,
    position INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS publications(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    duty_date TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK(status IN ('pending','sent','failed')),
    chat_id INTEGER,
    message_id INTEGER,
    assignments TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    published_at TEXT
);
CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._c = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._c.row_factory = sqlite3.Row
        self._c.execute("PRAGMA journal_mode=WAL")
        self._c.execute("PRAGMA synchronous=FULL")
        self._c.execute("PRAGMA busy_timeout=5000")
        self._c.executescript(SCHEMA)

    @contextmanager
    def _tx(self):
        with self._lock:
            self._c.execute("BEGIN IMMEDIATE")
            try:
                yield self._c
            except BaseException:
                self._c.execute("ROLLBACK")
                raise
            else:
                self._c.execute("COMMIT")

    def close(self):
        with self._lock:
            self._c.close()

    # ---- queues
    def init_queues(self, keys):
        with self._tx() as c:
            for k in keys:
                c.execute("INSERT OR IGNORE INTO queue_state(queue_key, position, updated_at) VALUES(?,0,?)", (k, _now()))

    def get_positions(self) -> dict:
        with self._lock:
            return {r["queue_key"]: r["position"] for r in self._c.execute("SELECT queue_key, position FROM queue_state")}

    def reset_positions(self):
        with self._tx() as c:
            c.execute("UPDATE queue_state SET position=0, updated_at=?", (_now(),))

    # ---- settings
    def get_setting(self, key, default=None):
        with self._lock:
            r = self._c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return r["value"] if r else default

    def set_setting(self, key, value):
        with self._tx() as c:
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    # ---- publications
    def claim(self, duty_date: str, assignments: list):
        """Atomically claim a duty date. Returns ('already', message_id) or ('claimed', None)."""
        payload = json.dumps(assignments, ensure_ascii=False)
        with self._tx() as c:
            row = c.execute("SELECT status, message_id FROM publications WHERE duty_date=?", (duty_date,)).fetchone()
            if row and row["status"] == "sent":
                return "already", row["message_id"]
            if row:
                c.execute("UPDATE publications SET status='pending', assignments=?, error=NULL WHERE duty_date=?", (payload, duty_date))
            else:
                c.execute("INSERT INTO publications(duty_date,status,assignments,created_at) VALUES(?,'pending',?,?)", (duty_date, payload, _now()))
        return "claimed", None

    def mark_sent(self, duty_date: str, chat_id: int, message_id: int, new_positions: dict) -> bool:
        """Mark sent AND advance queues in one transaction. Idempotent: advances at most once."""
        with self._tx() as c:
            cur = c.execute(
                "UPDATE publications SET status='sent', chat_id=?, message_id=?, published_at=?, error=NULL "
                "WHERE duty_date=? AND status!='sent'",
                (chat_id, message_id, _now(), duty_date),
            )
            if cur.rowcount == 0:
                return False
            for k, pos in new_positions.items():
                c.execute("UPDATE queue_state SET position=?, updated_at=? WHERE queue_key=?", (pos, _now(), k))
            return True

    def mark_failed(self, duty_date: str, error: str):
        with self._tx() as c:
            c.execute("UPDATE publications SET status='failed', error=? WHERE duty_date=? AND status!='sent'", (error[:500], duty_date))

    def get_publication(self, duty_date: str):
        with self._lock:
            r = self._c.execute("SELECT * FROM publications WHERE duty_date=?", (duty_date,)).fetchone()
            return dict(r) if r else None

    def last_sent(self):
        with self._lock:
            r = self._c.execute("SELECT * FROM publications WHERE status='sent' ORDER BY duty_date DESC LIMIT 1").fetchone()
            return dict(r) if r else None
