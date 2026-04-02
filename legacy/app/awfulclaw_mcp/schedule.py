"""MCP server for schedule management (create, list, delete)."""

from __future__ import annotations

from datetime import datetime, timezone as _utc_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import awfulclaw.scheduler as scheduler
from croniter import croniter  # type: ignore[import-untyped]
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("schedule")


@mcp.tool()
def schedule_create(
    name: str,
    prompt: str,
    cron: str = "",
    at: str = "",
    condition: str = "",
    timezone: str = "",
) -> str:
    """Create or update a scheduled prompt.

    Provide either `cron` (a cron expression like '0 9 * * *') or `at`
    (an ISO-8601 datetime like '2025-12-31T09:00:00Z') — not both.

    Use `timezone` (IANA name, e.g. 'Europe/Berlin') so cron expressions are
    interpreted in local time. Without it, cron times are UTC. The `at`
    parameter is always treated as an absolute moment in time (use a Z suffix
    or +HH:MM offset to be explicit).

    Optionally provide `condition`: a shell command that returns
    {"wakeAgent": true/false} to conditionally suppress firing.
    """
    cond = condition.strip() or None
    tz = timezone.strip()

    if tz:
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, KeyError):
            return f"[Schedule error: unknown timezone '{tz}' for '{name}']"

    if at.strip():
        try:
            fire_at = datetime.fromisoformat(at.strip())
            if fire_at.tzinfo is None:
                fire_at = fire_at.replace(tzinfo=ZoneInfo(tz) if tz else _utc_timezone.utc)
        except ValueError:
            return f"[Schedule error: invalid datetime '{at}' for '{name}']"
        new_sched = scheduler.Schedule.create(
            name=name, prompt=prompt, fire_at=fire_at, condition=cond, tz=tz
        )
    elif cron.strip():
        if not croniter.is_valid(cron.strip()):
            return f"[Schedule error: invalid cron expression '{cron}' for '{name}']"
        new_sched = scheduler.Schedule.create(
            name=name, cron=cron.strip(), prompt=prompt, condition=cond, tz=tz
        )
    else:
        return f"[Schedule error: must provide either 'cron' or 'at' for '{name}']"

    schedules = scheduler.load_schedules()
    idx = next(
        (i for i, s in enumerate(schedules) if s.name.lower() == name.lower()),
        None,
    )
    if idx is not None:
        schedules[idx] = new_sched
        scheduler.save_schedules(schedules)
        return f"[Schedule '{name}' updated]"
    else:
        schedules.append(new_sched)
        scheduler.save_schedules(schedules)
        return f"[Schedule '{name}' created]"


@mcp.tool()
def schedule_delete(name: str) -> str:
    """Delete a schedule by name."""
    schedules = scheduler.load_schedules()
    before = len(schedules)
    schedules[:] = [s for s in schedules if s.name.lower() != name.lower()]
    if len(schedules) < before:
        scheduler.save_schedules(schedules)
        return f"[Schedule '{name}' deleted]"
    return f"[Schedule '{name}' not found]"


@mcp.tool()
def schedule_list() -> str:
    """List all active schedules."""
    schedules = scheduler.load_schedules()
    if not schedules:
        return "[No schedules]"
    lines: list[str] = []
    for s in schedules:
        when = s.fire_at.isoformat() if s.fire_at else s.cron
        tz_suffix = f" [{s.tz}]" if s.tz else ""
        preview = s.prompt[:80] + ("…" if len(s.prompt) > 80 else "")
        cond = f" [condition: {s.condition}]" if s.condition else ""
        lines.append(f"- {s.name} ({when}{tz_suffix}): {preview}{cond}")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
