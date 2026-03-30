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


def read_fact(key: str) -> str:
    """Return content of a fact by key, or empty string if not found."""
    with get_db() as conn:
        row = conn.execute("SELECT content FROM facts WHERE key = ?", (key,)).fetchone()
    return row["content"] if row else ""


def write_fact(key: str, content: str) -> None:
    """Upsert a fact by key."""
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO facts (key, content, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET"
            " content=excluded.content, updated_at=excluded.updated_at",
            (key, content, ts),
        )


def list_facts() -> list[str]:
    """Return all fact keys, sorted."""
    with get_db() as conn:
        rows = conn.execute("SELECT key FROM facts ORDER BY key").fetchall()
    return [r["key"] for r in rows]


def search_facts(query: str) -> list[tuple[str, str]]:
    """Return (key, matching_line) for facts containing query."""
    results: list[tuple[str, str]] = []
    query_lower = query.lower()
    with get_db() as conn:
        rows = conn.execute("SELECT key, content FROM facts ORDER BY key").fetchall()
    for row in rows:
        for line in row["content"].splitlines():
            if query_lower in line.lower():
                results.append((f"facts/{row['key']}.md", line))
                break
    return results


def read_person(name: str) -> str:
    """Return content of a person by name, or empty string if not found."""
    with get_db() as conn:
        row = conn.execute("SELECT content FROM people WHERE name = ?", (name,)).fetchone()
    return row["content"] if row else ""


def write_person(name: str, content: str) -> None:
    """Upsert a person record by name."""
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO people (name, content, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(name) DO UPDATE SET"
            " content=excluded.content, updated_at=excluded.updated_at",
            (name, content, ts),
        )


def list_people() -> list[str]:
    """Return all person names, sorted."""
    with get_db() as conn:
        rows = conn.execute("SELECT name FROM people ORDER BY name").fetchall()
    return [r["name"] for r in rows]


def search_people(query: str) -> list[tuple[str, str]]:
    """Return (name, matching_line) for people records containing query."""
    results: list[tuple[str, str]] = []
    query_lower = query.lower()
    with get_db() as conn:
        rows = conn.execute("SELECT name, content FROM people ORDER BY name").fetchall()
    for row in rows:
        for line in row["content"].splitlines():
            if query_lower in line.lower():
                results.append((f"people/{row['name']}.md", line))
                break
    return results


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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                key TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS people (
                name TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
