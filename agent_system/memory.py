"""SQLite-backed memory and run history.

The database is intentionally small enough to inspect with the sqlite3 CLI.
Each method opens a short-lived connection so the threaded local server can use
the store without sharing connection state between requests.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY,
    user_message TEXT NOT NULL,
    reply TEXT NOT NULL,
    mode TEXT NOT NULL,
    iterations INTEGER NOT NULL,
    trace_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

TURN_COLUMNS = {
    "status": "TEXT NOT NULL DEFAULT 'completed'",
    "error": "TEXT",
}


def _literal_like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class MemoryStore:
    """Durable local facts plus an inspectable ledger of agent turns."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(turns)")}
            for name, definition in TURN_COLUMNS.items():
                if name not in columns:
                    conn.execute(f"ALTER TABLE turns ADD COLUMN {name} {definition}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=3)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=3000")
        return conn

    def remember(self, key: str, value: str) -> dict:
        key = " ".join(key.strip().split())[:80]
        value = " ".join(value.strip().split())[:500]
        if not key or not value:
            raise ValueError("key and value must not be empty")
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO memories (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=datetime('now')""",
                (key, value),
            )
            conn.commit()
        return {"saved": True, "key": key, "value": value}

    def recall(self, query: str = "", limit: int = 8) -> list[dict]:
        limit = max(1, min(int(limit), 20))
        query = " ".join(query.strip().split())[:80]
        with self._connect() as conn:
            if query:
                needle = _literal_like_pattern(query)
                rows = conn.execute(
                    """SELECT key, value, updated_at FROM memories
                    WHERE key LIKE ? ESCAPE '\\' OR value LIKE ? ESCAPE '\\'
                    ORDER BY updated_at DESC, id DESC LIMIT ?""",
                    (needle, needle, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT key, value, updated_at FROM memories
                    ORDER BY updated_at DESC, id DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def record_turn(
        self,
        *,
        user_message: str,
        reply: str,
        mode: str,
        iterations: int,
        trace: list[dict],
        status: str = "completed",
        error: str | None = None,
    ) -> int:
        if status not in {"completed", "failed"}:
            raise ValueError("status must be completed or failed")
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO turns
                (user_message, reply, mode, iterations, trace_json, status, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_message,
                    reply,
                    mode,
                    iterations,
                    json.dumps(trace, ensure_ascii=False),
                    status,
                    error,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def recent_turns(self, limit: int = 10) -> list[dict]:
        limit = max(1, min(int(limit), 50))
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, user_message, reply, mode, iterations, status, error, created_at
                FROM turns ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
