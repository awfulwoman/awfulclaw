"""Schedule data model and persistence backed by memory/schedules.json."""

from __future__ import annotations

import json
import logging
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from croniter import croniter  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

_SCHEDULES_PATH = Path("memory/schedules.json")


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
    silent: bool = field(default=False)

    @classmethod
    def create(
        cls,
        name: str,
        prompt: str,
        cron: str = "",
        fire_at: datetime | None = None,
        condition: str | None = None,
        silent: bool = False,
    ) -> "Schedule":
        return cls(
            id=uuid.uuid4().hex,
            name=name,
            cron=cron,
            prompt=prompt,
            created_at=datetime.now(timezone.utc),
            fire_at=fire_at,
            condition=condition,
            silent=silent,
        )


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt



def _schedule_to_dict(s: Schedule) -> dict[str, object]:
    return {
        "id": s.id,
        "name": s.name,
        "cron": s.cron,
        "prompt": s.prompt,
        "created_at": s.created_at.isoformat(),
        "last_run": s.last_run.isoformat() if s.last_run else None,
        "fire_at": s.fire_at.isoformat() if s.fire_at else None,
        "condition": s.condition,
        "silent": s.silent,
    }


def _dict_to_schedule(d: dict[str, object]) -> Schedule:
    return Schedule(
        id=str(d["id"]),
        name=str(d["name"]),
        cron=str(d.get("cron", "")),
        prompt=str(d["prompt"]),
        created_at=_parse_dt(str(d["created_at"])) or datetime.now(timezone.utc),
        last_run=_parse_dt(str(d["last_run"])) if d.get("last_run") else None,
        fire_at=_parse_dt(str(d["fire_at"])) if d.get("fire_at") else None,
        condition=str(d["condition"]) if d.get("condition") else None,
        silent=bool(d.get("silent", False)),
    )


def load_schedules() -> list[Schedule]:
    """Read schedules from memory/schedules.json."""
    if not _SCHEDULES_PATH.exists():
        return []
    try:
        data: list[dict[str, object]] = json.loads(_SCHEDULES_PATH.read_text(encoding="utf-8"))
        return [_dict_to_schedule(d) for d in data]
    except Exception as exc:
        logger.warning("Could not load schedules.json: %s", exc)
        return []


def save_schedules(schedules: list[Schedule]) -> None:
    """Persist schedules to memory/schedules.json."""
    _SCHEDULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SCHEDULES_PATH.write_text(
        json.dumps([_schedule_to_dict(s) for s in schedules], indent=2),
        encoding="utf-8",
    )


def should_wake(condition: str) -> bool:
    """Run condition command; return True if Claude should be invoked.

    Returns True (fail open) on command error, timeout, or invalid JSON.
    Returns False only when the command succeeds and wakeAgent is False.
    """
    import shlex

    try:
        result = subprocess.run(
            shlex.split(condition),
            shell=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning(
                "Schedule condition exited %d — proceeding with Claude call", result.returncode
            )
            return True
        data = json.loads(result.stdout)
        wake = data.get("wakeAgent", True)
        return bool(wake)
    except subprocess.TimeoutExpired:
        logger.warning("Schedule condition timed out — proceeding with Claude call")
        return True
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("Schedule condition error: %s — proceeding with Claude call", exc)
        return True


def run_due() -> list[Schedule]:
    """Check for due schedules and return those that fired.

    The caller is responsible for invoking Claude with sched.prompt and
    respecting sched.silent. One-off schedules are removed after being returned.
    """
    now = datetime.now(timezone.utc)
    schedules = load_schedules()
    due = get_due(schedules, now)
    fired: list[Schedule] = []
    one_off_ids: set[str] = set()

    for sched in due:
        if sched.condition is not None and not should_wake(sched.condition):
            logger.debug("Schedule '%s' suppressed by condition", sched.name)
            if sched.fire_at is None:
                sched.last_run = now
            continue
        fired.append(sched)
        if sched.fire_at is not None:
            one_off_ids.add(sched.id)
        else:
            sched.last_run = now

    if one_off_ids:
        schedules[:] = [s for s in schedules if s.id not in one_off_ids]
    if due:
        save_schedules(schedules)

    return fired


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
