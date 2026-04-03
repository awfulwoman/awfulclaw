from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import aiosqlite

if TYPE_CHECKING:
    from agent.handlers import Handler, Verdict


_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    embedding BLOB,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS people (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT,
    content TEXT NOT NULL,
    embedding BLOB,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schedules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    cron TEXT,
    fire_at TEXT,
    prompt TEXT NOT NULL,
    silent INTEGER NOT NULL DEFAULT 0,
    tz TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    last_run TEXT
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS personality_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry TEXT NOT NULL,
    verdict TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    expires_at TEXT
);
"""

_EXPECTED_TABLES = {"facts", "people", "conversations", "schedules", "kv", "personality_log"}


@dataclass
class Turn:
    id: int
    channel: str
    role: str
    content: str
    timestamp: str


@dataclass
class Schedule:
    id: str
    name: str
    cron: Optional[str]
    fire_at: Optional[str]
    prompt: str
    silent: bool
    tz: str
    created_at: str
    last_run: Optional[str]


@dataclass
class Fact:
    key: str
    value: str
    updated_at: str


@dataclass
class Person:
    id: str
    name: str
    phone: Optional[str]
    content: str
    updated_at: str


class GovernanceRejected(Exception):
    """Raised when governance rejects a proposed write."""


class Store:
    def __init__(self, db: aiosqlite.Connection, governance: "Optional[Handler]" = None) -> None:
        self._db = db
        self._governance = governance

    @classmethod
    async def connect(cls, db_path: Path, governance: "Optional[Handler]" = None) -> "Store":
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db = await aiosqlite.connect(db_path)
        await db.executescript(_SCHEMA)
        await db.commit()
        return cls(db, governance=governance)

    async def check_schema(self) -> None:
        cursor = await self._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        rows = await cursor.fetchall()
        existing = {row[0] for row in rows}
        missing = _EXPECTED_TABLES - existing
        if missing:
            raise RuntimeError(f"Missing tables: {', '.join(sorted(missing))}")

    async def close(self) -> None:
        await self._db.close()

    async def _govern(self, write_type: str, value: str) -> "Verdict":
        """Run governance check. Returns verdict. Raises GovernanceRejected if rejected."""
        from agent.handlers import Verdict

        if self._governance is None:
            return Verdict.approved
        verdict = await self._governance.check(write_type, value)
        if verdict == Verdict.rejected:
            raise GovernanceRejected(f"Governance rejected {write_type} write")
        return verdict

    async def _flag_escalation(self, write_type: str, value: str) -> None:
        """Store a kv notification for escalated writes."""
        import json
        notification = json.dumps({"write_type": write_type, "value": value})
        await self.kv_set("governance_escalation", notification)

    # --- kv ---

    async def kv_get(self, key: str) -> Optional[str]:
        cursor = await self._db.execute("SELECT value FROM kv WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else None

    async def kv_set(self, key: str, value: str) -> None:
        await self._db.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await self._db.commit()

    async def kv_delete(self, key: str) -> None:
        await self._db.execute("DELETE FROM kv WHERE key = ?", (key,))
        await self._db.commit()

    # --- facts ---

    async def get_fact(self, key: str) -> Optional[Fact]:
        cursor = await self._db.execute(
            "SELECT key, value, updated_at FROM facts WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return Fact(key=row[0], value=row[1], updated_at=row[2]) if row else None

    async def set_fact(self, key: str, value: str) -> None:
        from agent.handlers import Verdict

        verdict = await self._govern("fact", value)
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO facts (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, now),
        )
        await self._db.commit()
        if verdict == Verdict.escalated:
            await self._flag_escalation("fact", value)

    async def list_facts(self) -> list[Fact]:
        cursor = await self._db.execute("SELECT key, value, updated_at FROM facts ORDER BY key")
        rows = await cursor.fetchall()
        return [Fact(key=r[0], value=r[1], updated_at=r[2]) for r in rows]

    # --- people ---

    async def get_person(self, id: str) -> Optional[Person]:
        cursor = await self._db.execute(
            "SELECT id, name, phone, content, updated_at FROM people WHERE id = ?", (id,)
        )
        row = await cursor.fetchone()
        return Person(id=row[0], name=row[1], phone=row[2], content=row[3], updated_at=row[4]) if row else None

    async def set_person(self, id: str, name: str, content: str, phone: Optional[str] = None) -> None:
        from agent.handlers import Verdict

        verdict = await self._govern("person", content)
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO people (id, name, phone, content, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name, phone = excluded.phone, "
            "content = excluded.content, updated_at = excluded.updated_at",
            (id, name, phone, content, now),
        )
        await self._db.commit()
        if verdict == Verdict.escalated:
            await self._flag_escalation("person", content)

    async def list_people(self) -> list[Person]:
        cursor = await self._db.execute(
            "SELECT id, name, phone, content, updated_at FROM people ORDER BY name"
        )
        rows = await cursor.fetchall()
        return [Person(id=r[0], name=r[1], phone=r[2], content=r[3], updated_at=r[4]) for r in rows]

    # --- conversations ---

    async def add_turn(self, channel: str, role: str, content: str) -> Turn:
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.execute(
            "INSERT INTO conversations (channel, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (channel, role, content, now),
        )
        await self._db.commit()
        assert cursor.lastrowid is not None
        return Turn(id=cursor.lastrowid, channel=channel, role=role, content=content, timestamp=now)

    async def recent_turns(self, channel: str, limit: int) -> list[Turn]:
        cursor = await self._db.execute(
            "SELECT id, channel, role, content, timestamp FROM conversations "
            "WHERE channel = ? ORDER BY timestamp DESC LIMIT ?",
            (channel, limit),
        )
        rows = await cursor.fetchall()
        return list(reversed([Turn(id=r[0], channel=r[1], role=r[2], content=r[3], timestamp=r[4]) for r in rows]))

    # --- schedules ---

    async def list_schedules(self) -> list[Schedule]:
        cursor = await self._db.execute(
            "SELECT id, name, cron, fire_at, prompt, silent, tz, created_at, last_run FROM schedules ORDER BY name"
        )
        rows = await cursor.fetchall()
        return [
            Schedule(id=r[0], name=r[1], cron=r[2], fire_at=r[3], prompt=r[4], silent=bool(r[5]), tz=r[6], created_at=r[7], last_run=r[8])
            for r in rows
        ]

    async def upsert_schedule(self, schedule: Schedule) -> None:
        from agent.handlers import Verdict

        verdict = await self._govern("schedule_prompt", schedule.prompt)
        await self._db.execute(
            "INSERT INTO schedules (id, name, cron, fire_at, prompt, silent, tz, created_at, last_run) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name, cron = excluded.cron, "
            "fire_at = excluded.fire_at, prompt = excluded.prompt, silent = excluded.silent, "
            "tz = excluded.tz, last_run = excluded.last_run",
            (schedule.id, schedule.name, schedule.cron, schedule.fire_at, schedule.prompt,
             int(schedule.silent), schedule.tz, schedule.created_at, schedule.last_run),
        )
        await self._db.commit()
        if verdict == Verdict.escalated:
            await self._flag_escalation("schedule_prompt", schedule.prompt)

    async def delete_schedule(self, id: str) -> None:
        await self._db.execute("DELETE FROM schedules WHERE id = ?", (id,))
        await self._db.commit()

    # --- personality_log ---

    async def add_personality_log(self, entry: str, expires_at: Optional[str] = None) -> None:
        from agent.handlers import Verdict

        verdict = await self._govern("personality_log", entry)
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO personality_log (entry, verdict, timestamp, expires_at) VALUES (?, ?, ?, ?)",
            (entry, verdict.value, now, expires_at),
        )
        await self._db.commit()
        if verdict == Verdict.escalated:
            await self._flag_escalation("personality_log", entry)

    async def list_personality_log(self) -> list[dict[str, Optional[str]]]:
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.execute(
            "SELECT entry, verdict, timestamp, expires_at FROM personality_log "
            "WHERE verdict IN ('approved', 'escalated') "
            "AND (expires_at IS NULL OR expires_at > ?) ORDER BY timestamp",
            (now,),
        )
        rows = await cursor.fetchall()
        return [
            {"entry": r[0], "verdict": r[1], "timestamp": r[2], "expires_at": r[3]}
            for r in rows
        ]
