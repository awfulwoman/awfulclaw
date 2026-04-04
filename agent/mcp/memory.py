"""memory MCP server — tools for reading and writing agent memory.

Exposes:
  memory_write(type, key, value)       — write a fact or person; routes through governance
  memory_search(query, type?, limit?)  — semantic search over facts and/or people

Run via stdio; configure with env vars DB_PATH and GOVERNANCE_MODEL.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite
import sqlite_vec  # type: ignore[import-untyped]
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("memory")


def _get_db_path() -> Path:
    return Path(os.environ.get("DB_PATH", "agent.db"))


def _get_governance_model() -> str:
    return os.environ.get("GOVERNANCE_MODEL", "claude-haiku-4-5-20251001")


def _get_state_path() -> str:
    return str(Path(os.environ.get("DB_PATH", "agent.db")).parent.resolve())


async def _check_governance(write_type: str, value: str) -> str:
    """Run governance check. Returns verdict value string."""
    from agent.handlers.governance import GovernanceHandler

    handler = GovernanceHandler(_get_governance_model(), state_path=_get_state_path())
    verdict = await handler.check(write_type, value)
    return verdict.value


def _embed(text: str) -> bytes:
    from agent.store import embed

    return embed(text)


async def _connect(db_path: Path) -> aiosqlite.Connection:
    db = await aiosqlite.connect(db_path)
    await db.enable_load_extension(True)
    await db.load_extension(sqlite_vec.loadable_path())
    await db.enable_load_extension(False)
    return db


@mcp.tool()
async def memory_write(type: str, key: str, value: str) -> str:
    """Write a memory entry (fact or person).

    type:  'fact' or 'person'
    key:   unique identifier (fact topic key, or person id)
    value: content to store; for people, format as 'Name\\ndetails...'

    The write is governance-checked before persisting.
    """
    if type not in ("fact", "person"):
        return "Error: type must be 'fact' or 'person'"

    verdict = await _check_governance(type, value)
    if verdict == "rejected":
        return f"Error: governance rejected the {type} write"

    now = datetime.now(timezone.utc).isoformat()
    db_path = _get_db_path()
    db = await _connect(db_path)
    try:
        if type == "fact":
            emb = _embed(f"{key}: {value}")
            await db.execute(
                "INSERT INTO facts (key, value, embedding, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "embedding = excluded.embedding, updated_at = excluded.updated_at",
                (key, value, emb, now),
            )
        else:
            lines = value.strip().split("\n", 1)
            name = lines[0].strip()
            content = lines[1].strip() if len(lines) > 1 else value
            emb = _embed(f"{name}: {content}")
            await db.execute(
                "INSERT INTO people (id, name, content, embedding, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET name = excluded.name, content = excluded.content, "
                "embedding = excluded.embedding, updated_at = excluded.updated_at",
                (key, name, content, emb, now),
            )
        await db.commit()
    finally:
        await db.close()

    return f"{type.capitalize()} {key!r} written"


@mcp.tool()
async def memory_search(
    query: str, type: Optional[str] = None, limit: int = 10
) -> list[dict]:
    """Semantic search over memory.

    query: natural language search query
    type:  'fact', 'person', or omitted to search both
    limit: max results per type (default 10)
    """
    if type is not None and type not in ("fact", "person"):
        return [{"error": "type must be 'fact', 'person', or omitted"}]

    query_emb = _embed(query)
    db_path = _get_db_path()
    db = await _connect(db_path)
    try:
        results: list[dict] = []

        if type in (None, "fact"):
            async with db.execute(
                "SELECT key, value, updated_at FROM facts "
                "WHERE embedding IS NOT NULL "
                "ORDER BY vec_distance_cosine(embedding, ?) "
                "LIMIT ?",
                (query_emb, limit),
            ) as cur:
                rows = await cur.fetchall()
            for r in rows:
                results.append(
                    {"type": "fact", "key": r[0], "value": r[1], "updated_at": r[2]}
                )

        if type in (None, "person"):
            async with db.execute(
                "SELECT id, name, phone, content, updated_at FROM people "
                "WHERE embedding IS NOT NULL "
                "ORDER BY vec_distance_cosine(embedding, ?) "
                "LIMIT ?",
                (query_emb, limit),
            ) as cur:
                rows = await cur.fetchall()
            for r in rows:
                results.append(
                    {
                        "type": "person",
                        "id": r[0],
                        "name": r[1],
                        "phone": r[2],
                        "content": r[3],
                        "updated_at": r[4],
                    }
                )

        return results
    finally:
        await db.close()


@mcp.tool()
async def memory_delete(type: str, key: str) -> str:
    """Delete a memory entry by key.

    type: 'fact' or 'person'
    key:  the fact key or person id to delete
    """
    if type not in ("fact", "person"):
        return "Error: type must be 'fact' or 'person'"

    db_path = _get_db_path()
    db = await _connect(db_path)
    try:
        if type == "fact":
            cur = await db.execute("DELETE FROM facts WHERE key = ?", (key,))
        else:
            cur = await db.execute("DELETE FROM people WHERE id = ?", (key,))
        await db.commit()
        if cur.rowcount == 0:
            return f"{type.capitalize()} {key!r} not found"
    finally:
        await db.close()

    return f"{type.capitalize()} {key!r} deleted"


if __name__ == "__main__":
    mcp.run()
