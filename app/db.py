from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Optional


class MemoryStore:
    def __init__(self, sqlite_path: str) -> None:
        self.sqlite_path = sqlite_path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        db_path = Path(self.sqlite_path)
        if str(db_path.parent) not in ("", "."):
            db_path.parent.mkdir(parents=True, exist_ok=True)

        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_messages_chat_created
                ON messages(chat_id, id DESC);

                CREATE TABLE IF NOT EXISTS kv_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL UNIQUE,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS scheduled_jobs (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    cron TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                """
            )
            conn.commit()

    def add_message(self, chat_id: str, role: str, content: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO messages(chat_id, role, content) VALUES (?, ?, ?)",
                (chat_id, role, content),
            )
            conn.commit()

    def get_recent_messages(self, chat_id: str, limit: int) -> list[dict[str, str]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT role, content
                FROM messages
                WHERE chat_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (chat_id, limit),
            ).fetchall()
        ordered = list(reversed(rows))
        return [{"role": row["role"], "content": row["content"]} for row in ordered]

    def set_state(self, key: str, value: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO kv_state(key, value, updated_at)
                VALUES(?, ?, datetime('now'))
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = datetime('now')
                """,
                (key, value),
            )
            conn.commit()

    def get_state(self, key: str) -> Optional[str]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT value FROM kv_state WHERE key = ?",
                (key,),
            ).fetchone()
        return row["value"] if row else None

    # --- Persistent named memories ---

    def set_memory(self, key: str, value: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO memories(key, value, updated_at)
                VALUES(?, ?, datetime('now'))
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = datetime('now')
                """,
                (key, value),
            )
            conn.commit()

    def get_memory(self, key: str) -> Optional[str]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT value FROM memories WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def list_memories(self) -> list[dict[str, str]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT key, value, updated_at FROM memories ORDER BY updated_at DESC"
            ).fetchall()
        return [{"key": r["key"], "value": r["value"], "updated_at": r["updated_at"]} for r in rows]

    def delete_memory(self, key: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM memories WHERE key = ?", (key,))
            conn.commit()

    # --- Agent-scheduled jobs ---

    def add_scheduled_job(self, job_id: str, label: str, cron: str, prompt: str, chat_id: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO scheduled_jobs(id, label, cron, prompt, chat_id)
                VALUES(?, ?, ?, ?, ?)
                """,
                (job_id, label, cron, prompt, chat_id),
            )
            conn.commit()

    def remove_scheduled_job(self, job_id: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM scheduled_jobs WHERE id = ?", (job_id,))
            conn.commit()

    def list_scheduled_jobs(self) -> list[dict[str, str]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, label, cron, prompt, chat_id, created_at FROM scheduled_jobs"
            ).fetchall()
        return [dict(r) for r in rows]
