"""Small SQLite store: task history, approvals and the last Claude session per project."""

import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    created REAL NOT NULL,
    text TEXT NOT NULL,
    has_clipboard INTEGER DEFAULT 0,
    has_url INTEGER DEFAULT 0,
    has_image INTEGER DEFAULT 0,
    route TEXT,
    project TEXT,
    session TEXT,
    router_model TEXT,
    router_ms INTEGER,
    router_reason TEXT,
    status TEXT NOT NULL,
    summary TEXT,
    claude_session_id TEXT,
    finished REAL
);
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    created REAL NOT NULL,
    key_hash TEXT NOT NULL,
    tool TEXT NOT NULL,
    detail TEXT NOT NULL,
    decision TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    project TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    updated REAL NOT NULL,
    last_text TEXT NOT NULL
);
"""

TASK_FIELDS = {
    "route", "project", "session", "router_model", "router_ms", "router_reason",
    "status", "summary", "claude_session_id", "finished",
}


class Store:
    def __init__(self, path: Path):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)

    def _exec(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            self._conn.commit()
            return rows

    # tasks
    def add_task(self, task_id: str, text: str, clipboard: bool, url: bool, image: bool) -> None:
        self._exec(
            "INSERT INTO tasks (id, created, text, has_clipboard, has_url, has_image, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'queued')",
            (task_id, time.time(), text, int(clipboard), int(url), int(image)),
        )

    def update_task(self, task_id: str, **fields) -> None:
        unknown = set(fields) - TASK_FIELDS
        if unknown:
            raise ValueError(f"unknown task fields: {unknown}")
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._exec(f"UPDATE tasks SET {cols} WHERE id = ?", (*fields.values(), task_id))

    def get_task(self, task_id: str) -> dict | None:
        rows = self._exec("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return dict(rows[0]) if rows else None

    def recent_tasks(self, limit: int = 20) -> list[dict]:
        rows = self._exec("SELECT * FROM tasks ORDER BY created DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    # sessions
    def save_session(self, project: str, session_id: str, text: str) -> None:
        self._exec(
            "INSERT INTO sessions (project, session_id, updated, last_text) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(project) DO UPDATE SET session_id = excluded.session_id, "
            "updated = excluded.updated, last_text = excluded.last_text",
            (project, session_id, time.time(), text),
        )

    def sessions(self) -> dict[str, dict]:
        return {r["project"]: dict(r) for r in self._exec("SELECT * FROM sessions")}

    # approvals
    def add_approval(self, approval_id: str, key_hash: str, tool: str, detail: str) -> None:
        self._exec(
            "INSERT INTO approvals (id, created, key_hash, tool, detail) VALUES (?, ?, ?, ?, ?)",
            (approval_id, time.time(), key_hash, tool, detail),
        )

    def get_approval(self, approval_id: str) -> dict | None:
        rows = self._exec("SELECT * FROM approvals WHERE id = ?", (approval_id,))
        return dict(rows[0]) if rows else None

    def decide_approval(self, approval_id: str, decision: str) -> bool:
        """Set the decision once. Returns False if it was already decided."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE approvals SET decision = ? WHERE id = ? AND decision IS NULL",
                (decision, approval_id),
            )
            self._conn.commit()
            return cur.rowcount == 1
