"""Import legacy facts and people from a legacy SQLite database.

Usage:
    uv run python scripts/import_memory.py /path/to/legacy.db

Legacy schema:
    facts  (key TEXT PRIMARY KEY, content TEXT, updated_at TEXT)
    people (name TEXT PRIMARY KEY, content TEXT, updated_at TEXT)

New schema mapping:
    facts.content  -> facts.value  (embeddings are generated during import)
    people.name    -> people.id + people.name  (phone defaults to None)
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path
from typing import Optional


def _default_db_path() -> Optional[Path]:
    candidates = [
        Path("data/agent.db"),
        Path.home() / ".local" / "share" / "awfulclaw" / "agent.db",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _read_legacy(legacy_path: Path) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """Read facts and people from the legacy DB.

    Returns:
        (facts, people) where facts is [(key, content, updated_at), ...]
        and people is [(name, content, updated_at), ...]
    """
    conn = sqlite3.connect(legacy_path)
    conn.row_factory = sqlite3.Row
    try:
        facts: list[tuple[str, str, str]] = []
        try:
            rows = conn.execute("SELECT key, content, updated_at FROM facts ORDER BY key").fetchall()
            facts = [(r["key"], r["content"], r["updated_at"]) for r in rows]
        except sqlite3.OperationalError:
            pass  # table may not exist

        people: list[tuple[str, str, str]] = []
        try:
            rows = conn.execute("SELECT name, content, updated_at FROM people ORDER BY name").fetchall()
            people = [(r["name"], r["content"], r["updated_at"]) for r in rows]
        except sqlite3.OperationalError:
            pass  # table may not exist
    finally:
        conn.close()
    return facts, people


async def run(
    legacy_path: Path,
    db_path: Optional[Path] = None,
) -> tuple[int, int, int, int]:
    """Import facts and people from legacy_path into the new DB.

    Returns:
        (facts_imported, facts_skipped, people_imported, people_skipped)
    """
    from agent.store import Store

    resolved_db = db_path or _default_db_path()
    if resolved_db is None:
        print("ERROR: database not found", file=sys.stderr)
        sys.exit(1)

    facts_raw, people_raw = _read_legacy(legacy_path)

    store = await Store.connect(resolved_db)
    try:
        facts_imported = 0
        facts_skipped = 0
        for key, content, _updated_at in facts_raw:
            existing = await store.get_fact(key)
            if existing is not None:
                print(f"  skip fact (duplicate): {key}")
                facts_skipped += 1
                continue
            await store.set_fact(key, content)
            print(f"  imported fact: {key}")
            facts_imported += 1

        people_imported = 0
        people_skipped = 0
        for name, content, _updated_at in people_raw:
            existing = await store.get_person(name)
            if existing is not None:
                print(f"  skip person (duplicate): {name}")
                people_skipped += 1
                continue
            # Use name as id (legacy DB has no separate id column)
            await store.set_person(name, name, content)
            print(f"  imported person: {name}")
            people_imported += 1

        print(
            f"\nDone. "
            f"facts: imported={facts_imported} skipped={facts_skipped}  "
            f"people: imported={people_imported} skipped={people_skipped}"
        )
        return facts_imported, facts_skipped, people_imported, people_skipped
    finally:
        await store.close()


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: import_memory.py <path/to/legacy.db>", file=sys.stderr)
        sys.exit(1)

    legacy_path = Path(sys.argv[1])
    if not legacy_path.exists():
        print(f"ERROR: file not found: {legacy_path}", file=sys.stderr)
        sys.exit(1)

    asyncio.run(run(legacy_path))


if __name__ == "__main__":
    main()
