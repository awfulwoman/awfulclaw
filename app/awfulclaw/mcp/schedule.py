"""MCP server for schedule management (create, list, delete)."""

from __future__ import annotations

from datetime import datetime, timezone

from croniter import croniter  # type: ignore[import-untyped]
from mcp.server.fastmcp import FastMCP

import awfulclaw.scheduler as scheduler

mcp = FastMCP("schedule")


@mcp.tool()
def schedule_create(
    name: str,
    prompt: str,
    cron: str = "",
    at: str = "",
    condition: str = "",
) -> str:
    """Create or update a scheduled prompt.

    Provide either `cron` (a cron expression like '0 8 * * *') or `at`
    (an ISO-8601 datetime like '2025-12-31T09:00:00Z') — not both.
    Optionally provide `condition`: a shell command that returns
    {"wakeAgent": true/false} to conditionally suppress firing.
    """
    cond = condition.strip() or None

    if at.strip():
        try:
            fire_at = datetime.fromisoformat(at.strip())
            if fire_at.tzinfo is None:
                fire_at = fire_at.replace(tzinfo=timezone.utc)
        except ValueError:
            return f"[Schedule error: invalid datetime '{at}' for '{name}']"
        new_sched = scheduler.Schedule.create(
            name=name, prompt=prompt, fire_at=fire_at, condition=cond
        )
    elif cron.strip():
        if not croniter.is_valid(cron.strip()):
            return f"[Schedule error: invalid cron expression '{cron}' for '{name}']"
        new_sched = scheduler.Schedule.create(
            name=name, cron=cron.strip(), prompt=prompt, condition=cond
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
        preview = s.prompt[:80] + ("…" if len(s.prompt) > 80 else "")
        cond = f" [condition: {s.condition}]" if s.condition else ""
        lines.append(f"- {s.name} ({when}): {preview}{cond}")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
