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


def _to_dict(s: Schedule) -> dict[str, object]:
    d: dict[str, object] = {
        "id": s.id,
        "name": s.name,
        "cron": s.cron,
        "prompt": s.prompt,
        "created_at": s.created_at.isoformat(),
        "last_run": s.last_run.isoformat() if s.last_run else None,
        "fire_at": s.fire_at.isoformat() if s.fire_at else None,
    }
    if s.condition is not None:
        d["condition"] = s.condition
    return d


def _from_dict(d: dict[str, object]) -> Schedule:
    created_at_raw = d.get("created_at")
    if isinstance(created_at_raw, str):
        created_at = datetime.fromisoformat(created_at_raw)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
    else:
        created_at = datetime.now(timezone.utc)
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
    condition_raw = d.get("condition")
    condition = str(condition_raw) if isinstance(condition_raw, str) else None
    return Schedule(
        id=str(d["id"]),
        name=str(d["name"]),
        cron=str(d["cron"]),
        prompt=str(d["prompt"]),
        created_at=created_at,
        last_run=last_run,
        fire_at=fire_at,
        condition=condition,
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
