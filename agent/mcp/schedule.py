"""schedule MCP server — CRUD tools for schedule management.

Exposes four tools:
  schedule_list()                        — list all schedules
  schedule_create(name, cron|fire_at, prompt, silent, tz)
  schedule_update(id, ...)               — patch any fields; prompt is governance-checked
  schedule_delete(id)                    — remove a schedule

Prompts are passed through GovernanceHandler before being persisted.
After create/update/delete the scheduler_wake kv key is set so the scheduler
re-evaluates without waiting for its sleep to expire.

Run via stdio; configure with env vars DB_PATH and GOVERNANCE_MODEL.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("schedule")


def _get_db_path() -> Path:
    return Path(os.environ.get("DB_PATH", "agent.db"))


def _get_governance_model() -> str:
    return os.environ.get("GOVERNANCE_MODEL", "claude-haiku-4-5-20251001")


def _get_state_path() -> str:
    return str(Path(os.environ.get("DB_PATH", "agent.db")).parent.resolve())


async def _check_governance(prompt: str) -> str:
    """Run governance check on a schedule prompt. Returns verdict value string."""
    from agent.handlers.governance import GovernanceHandler

    handler = GovernanceHandler(_get_governance_model(), state_path=_get_state_path())
    verdict = await handler.check("schedule_prompt", prompt)
    return verdict.value


async def _set_wake_signal(db: aiosqlite.Connection) -> None:
    """Write scheduler_wake=1 to kv so the main-process scheduler re-evaluates."""
    await db.execute(
        "INSERT INTO kv (key, value) VALUES ('scheduler_wake', '1') "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
    )


@mcp.tool()
async def schedule_list() -> list[dict]:
    """Return all schedules as a list of dicts."""
    db_path = _get_db_path()
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT id, name, cron, fire_at, prompt, silent, tz, created_at, last_run "
            "FROM schedules ORDER BY name"
        ) as cur:
            rows = await cur.fetchall()
    return [
        {
            "id": r[0],
            "name": r[1],
            "cron": r[2],
            "fire_at": r[3],
            "prompt": r[4],
            "silent": bool(r[5]),
            "tz": r[6],
            "created_at": r[7],
            "last_run": r[8],
        }
        for r in rows
    ]


@mcp.tool()
async def schedule_create(
    name: str,
    prompt: str,
    cron: Optional[str] = None,
    fire_at: Optional[str] = None,
    silent: bool = False,
    tz: str = "",
) -> str:
    """Create a new schedule.

    One of cron or fire_at must be provided.
    The prompt is governance-checked before persisting.
    """
    if cron is None and fire_at is None:
        return "Error: one of cron or fire_at is required"

    verdict = await _check_governance(prompt)
    if verdict == "rejected":
        return "Error: governance rejected the schedule prompt"

    schedule_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    db_path = _get_db_path()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO schedules "
            "(id, name, cron, fire_at, prompt, silent, tz, created_at, last_run) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (schedule_id, name, cron, fire_at, prompt, int(silent), tz, created_at),
        )
        await _set_wake_signal(db)
        await db.commit()

    return f"Schedule {name!r} created with id {schedule_id!r}"


@mcp.tool()
async def schedule_update(
    id: str,
    name: Optional[str] = None,
    prompt: Optional[str] = None,
    cron: Optional[str] = None,
    fire_at: Optional[str] = None,
    silent: Optional[bool] = None,
    tz: Optional[str] = None,
) -> str:
    """Update fields on an existing schedule.

    If prompt is provided it is governance-checked before persisting.
    """
    if prompt is not None:
        verdict = await _check_governance(prompt)
        if verdict == "rejected":
            return "Error: governance rejected the schedule prompt"

    updates: list[str] = []
    params: list[object] = []

    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if prompt is not None:
        updates.append("prompt = ?")
        params.append(prompt)
    if cron is not None:
        updates.append("cron = ?")
        params.append(cron)
    if fire_at is not None:
        updates.append("fire_at = ?")
        params.append(fire_at)
    if silent is not None:
        updates.append("silent = ?")
        params.append(int(silent))
    if tz is not None:
        updates.append("tz = ?")
        params.append(tz)

    if not updates:
        return "No fields to update"

    params.append(id)
    db_path = _get_db_path()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            f"UPDATE schedules SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        await _set_wake_signal(db)
        await db.commit()

    return f"Schedule {id!r} updated"


@mcp.tool()
async def schedule_delete(id: str) -> str:
    """Delete a schedule by id."""
    db_path = _get_db_path()
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM schedules WHERE id = ?", (id,))
        await _set_wake_signal(db)
        await db.commit()
    return f"Schedule {id!r} deleted"


if __name__ == "__main__":
    mcp.run()
