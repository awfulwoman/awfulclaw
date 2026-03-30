"""Schedule data model and persistence backed by SQLite."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from croniter import croniter  # type: ignore[import-untyped]

from awfulclaw.db import get_db, init_db

_LEGACY_JSON = Path("memory/schedules.json")


@dataclass
class Schedule:
    id: str
    name: str
    cron: str
    prompt: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_run: datetime | None = field(default=None)
    fire_at: datetime | None = field(default=None)
    condition: str | None = field(default=None)

    @classmethod
    def create(
        cls,
        name: str,
        prompt: str,
        cron: str = "",
        fire_at: datetime | None = None,
        condition: str | None = None,
    ) -> "Schedule":
        return cls(
            id=uuid.uuid4().hex,
            name=name,
            cron=cron,
            prompt=prompt,
            created_at=datetime.now(timezone.utc),
            fire_at=fire_at,
            condition=condition,
        )


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _row_to_schedule(row: object) -> Schedule:
    # row is a sqlite3.Row
    import sqlite3

    r: sqlite3.Row = row  # type: ignore[assignment]
    created_at = _parse_dt(r["created_at"]) or datetime.now(timezone.utc)
    return Schedule(
        id=r["id"],
        name=r["name"],
        cron=r["cron"],
        prompt=r["prompt"],
        created_at=created_at,
        last_run=_parse_dt(r["last_run"]),
        fire_at=_parse_dt(r["fire_at"]),
        condition=r["condition"],
    )


def _migrate_from_json() -> None:
    """Import schedules.json into SQLite on first run, then rename it."""
    if not _LEGACY_JSON.exists():
        return
    try:
        with _LEGACY_JSON.open() as f:
            data: list[dict[str, object]] = json.load(f)
    except Exception:
        return
    with get_db() as conn:
        for d in data:
            conn.execute(
                """
                INSERT OR IGNORE INTO schedules
                    (id, name, cron, prompt, created_at, last_run, fire_at, condition)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(d.get("id", uuid.uuid4().hex)),
                    str(d.get("name", "")),
                    str(d.get("cron", "")),
                    str(d.get("prompt", "")),
                    str(d.get("created_at", datetime.now(timezone.utc).isoformat())),
                    d.get("last_run"),
                    d.get("fire_at"),
                    d.get("condition"),
                ),
            )
    _LEGACY_JSON.rename(_LEGACY_JSON.with_suffix(".json.bak"))


def load_schedules() -> list[Schedule]:
    """Read schedules from SQLite; migrates from JSON on first run."""
    init_db()
    _migrate_from_json()
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM schedules").fetchall()
    return [_row_to_schedule(r) for r in rows]


def save_schedules(schedules: list[Schedule]) -> None:
    """Persist schedules to SQLite (full replace of the set)."""
    init_db()
    ids = [s.id for s in schedules]
    with get_db() as conn:
        for s in schedules:
            conn.execute(
                """
                INSERT INTO schedules
                    (id, name, cron, prompt, created_at, last_run, fire_at, condition)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    cron=excluded.cron,
                    prompt=excluded.prompt,
                    created_at=excluded.created_at,
                    last_run=excluded.last_run,
                    fire_at=excluded.fire_at,
                    condition=excluded.condition
                """,
                (
                    s.id,
                    s.name,
                    s.cron,
                    s.prompt,
                    s.created_at.isoformat(),
                    s.last_run.isoformat() if s.last_run else None,
                    s.fire_at.isoformat() if s.fire_at else None,
                    s.condition,
                ),
            )
        if ids:
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"DELETE FROM schedules WHERE id NOT IN ({placeholders})", ids
            )
        else:
            conn.execute("DELETE FROM schedules")


def get_due(schedules: list[Schedule], now: datetime) -> list[Schedule]:
    """Return schedules due to fire at or before now.

    One-off schedules (fire_at set) fire once when now >= fire_at; cron is ignored.

    Cron schedules use created_at as the iteration anchor so that restarting
    after downtime does not cause catch-up firing for missed intervals.
    """
    due: list[Schedule] = []
    now_aware = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    for s in schedules:
        if s.fire_at is not None:
            fa = s.fire_at
            if fa.tzinfo is None:
                fa = fa.replace(tzinfo=timezone.utc)
            if now_aware >= fa:
                due.append(s)
            continue
        last_run = s.last_run
        if last_run is not None and last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=timezone.utc)
        threshold = last_run if last_run is not None else epoch
        # Iterate cron from created_at anchor to find next fire after last_run
        created = s.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        cron = croniter(s.cron, created)
        next_due: datetime | None = None
        for _ in range(10000):  # safety bound
            candidate: datetime = cron.get_next(datetime)
            if candidate.tzinfo is None:
                candidate = candidate.replace(tzinfo=timezone.utc)
            if candidate > threshold:
                next_due = candidate
                break
        if next_due is not None and next_due <= now_aware:
            due.append(s)
    return due
