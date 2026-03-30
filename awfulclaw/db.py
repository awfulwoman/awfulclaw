"""Shared SQLite database connection for awfulclaw."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path("memory/awfulclaw.db")


def get_db() -> sqlite3.Connection:
    """Return a SQLite connection to memory/awfulclaw.db with WAL mode enabled."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schedules (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                cron TEXT NOT NULL DEFAULT '',
                prompt TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_run TEXT,
                fire_at TEXT,
                condition TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conv_timestamp ON conversations(timestamp)
        """)
