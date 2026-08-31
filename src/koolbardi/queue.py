from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phase TEXT NOT NULL,
    shard_key TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    worker TEXT,
    claimed_at REAL,
    finished_at REAL,
    error TEXT,
    UNIQUE(phase, shard_key)
);
CREATE INDEX IF NOT EXISTS tasks_status_phase ON tasks(status, phase, id);
"""


@dataclass(frozen=True)
class Task:
    id: int
    phase: str
    shard_key: str
    payload: dict
    attempts: int


class TaskQueue:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=60, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA busy_timeout=60000")
        try:
            yield conn
        finally:
            conn.close()

    def add(self, phase: str, shard_key: str, payload: dict) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO tasks(phase, shard_key, payload) VALUES (?, ?, ?)",
                (phase, shard_key, json.dumps(payload, sort_keys=True)),
            )
            return cursor.rowcount == 1

    def claim(self, phase: str, worker: str | None = None) -> Task | None:
        worker = worker or f"{os.uname().nodename}:{os.getpid()}"
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM tasks WHERE phase=? AND status='pending' ORDER BY id LIMIT 1",
                (phase,),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            conn.execute(
                "UPDATE tasks SET status='running', attempts=attempts+1, worker=?, claimed_at=?, error=NULL WHERE id=?",
                (worker, time.time(), row["id"]),
            )
            conn.execute("COMMIT")
            return Task(row["id"], row["phase"], row["shard_key"], json.loads(row["payload"]), row["attempts"] + 1)

    def finish(self, task_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE tasks SET status='done', finished_at=?, worker=NULL WHERE id=?",
                (time.time(), task_id),
            )

    def fail(self, task_id: int, error: str, max_attempts: int) -> None:
        with self.connect() as conn:
            attempts = conn.execute("SELECT attempts FROM tasks WHERE id=?", (task_id,)).fetchone()[0]
            status = "pending" if attempts < max_attempts else "failed"
            conn.execute(
                "UPDATE tasks SET status=?, error=?, worker=NULL, claimed_at=NULL WHERE id=?",
                (status, error[-4000:], task_id),
            )

    def reset_stale(self, age_seconds: float) -> int:
        cutoff = time.time() - age_seconds
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE tasks SET status='pending', worker=NULL, claimed_at=NULL, error='reset stale claim' "
                "WHERE status='running' AND claimed_at < ?",
                (cutoff,),
            )
            return cursor.rowcount

    def status(self) -> list[dict]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT phase, status, COUNT(*) AS count FROM tasks GROUP BY phase, status ORDER BY phase, status"
            )]

