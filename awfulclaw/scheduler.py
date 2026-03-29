"""Schedule data model and persistence backed by memory/schedules.json."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from croniter import croniter  # type: ignore[import-untyped]

SCHEDULES_FILE = Path("memory/schedules.json")


@dataclass
class Schedule:
    id: str
    name: str
    cron: str
    prompt: str
    last_run: datetime | None = field(default=None)
    fire_at: datetime | None = field(default=None)

    @classmethod
    def create(
        cls,
        name: str,
        prompt: str,
        cron: str = "",
        fire_at: datetime | None = None,
    ) -> "Schedule":
        return cls(id=uuid.uuid4().hex, name=name, cron=cron, prompt=prompt, fire_at=fire_at)


def _to_dict(s: Schedule) -> dict[str, object]:
    return {
        "id": s.id,
        "name": s.name,
        "cron": s.cron,
        "prompt": s.prompt,
        "last_run": s.last_run.isoformat() if s.last_run else None,
        "fire_at": s.fire_at.isoformat() if s.fire_at else None,
    }


def _from_dict(d: dict[str, object]) -> Schedule:
    last_run_raw = d.get("last_run")
    last_run: datetime | None = None
    if isinstance(last_run_raw, str):
        last_run = datetime.fromisoformat(last_run_raw)
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=timezone.utc)
    fire_at_raw = d.get("fire_at")
    fire_at: datetime | None = None
    if isinstance(fire_at_raw, str):
        fire_at = datetime.fromisoformat(fire_at_raw)
        if fire_at.tzinfo is None:
            fire_at = fire_at.replace(tzinfo=timezone.utc)
    return Schedule(
        id=str(d["id"]),
        name=str(d["name"]),
        cron=str(d["cron"]),
        prompt=str(d["prompt"]),
        last_run=last_run,
        fire_at=fire_at,
    )


def load_schedules() -> list[Schedule]:
    """Read and deserialise schedules; returns [] if the file does not exist."""
    if not SCHEDULES_FILE.exists():
        return []
    with SCHEDULES_FILE.open() as f:
        data: list[dict[str, object]] = json.load(f)
    return [_from_dict(d) for d in data]


def save_schedules(schedules: list[Schedule]) -> None:
    """Serialise and write schedules atomically."""
    SCHEDULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SCHEDULES_FILE.with_suffix(".json.tmp")
    with tmp.open("w") as f:
        json.dump([_to_dict(s) for s in schedules], f, indent=2)
    os.replace(tmp, SCHEDULES_FILE)


def get_due(schedules: list[Schedule], now: datetime) -> list[Schedule]:
    """Return schedules whose cron was due since last_run (or ever) up to now.

    One-off schedules (fire_at set) fire once when now >= fire_at; cron is ignored.
    """
    due: list[Schedule] = []
    now_aware = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    for s in schedules:
        if s.fire_at is not None:
            fa = s.fire_at
            if fa.tzinfo is None:
                fa = fa.replace(tzinfo=timezone.utc)
            if now_aware >= fa:
                due.append(s)
            continue
        start = s.last_run if s.last_run is not None else datetime(1970, 1, 1, tzinfo=timezone.utc)
        # Ensure timezone-aware comparison
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        cron = croniter(s.cron, start)
        next_run: datetime = cron.get_next(datetime)
        if next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=timezone.utc)
        if next_run <= now_aware:
            due.append(s)
    return due
