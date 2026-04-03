"""Import legacy schedules.json into the new schedules table.

Usage:
    uv run python scripts/import_schedules.py /path/to/schedules.json

Legacy format (array of schedule objects):
    [
      {
        "name": "daily-briefing",
        "cron": "0 8 * * *",
        "prompt": "Run the daily-briefing skill.",
        "silent": false,
        "tz": "Europe/Berlin"
      },
      ...
    ]

Fields id, fire_at, created_at, and last_run are optional in the legacy format;
they will be generated or defaulted if absent.
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
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


async def run(
    json_path: Path,
    db_path: Optional[Path] = None,
    _return_counts: bool = False,
) -> tuple[int, int]:
    from agent.store import Schedule, Store

    resolved_db = db_path or _default_db_path()
    if resolved_db is None:
        print("ERROR: database not found", file=sys.stderr)
        sys.exit(1)

    raw = json_path.read_text()
    items: list[dict] = json.loads(raw)  # type: ignore[assignment]
    if not isinstance(items, list):
        print("ERROR: expected a JSON array at the top level", file=sys.stderr)
        sys.exit(1)

    store = await Store.connect(resolved_db)
    try:
        existing = {s.name for s in await store.list_schedules()}
        imported = 0
        skipped = 0
        now = datetime.now(timezone.utc).isoformat()

        for item in items:
            name: str = item["name"]
            if name in existing:
                print(f"  skip (duplicate): {name}")
                skipped += 1
                continue

            schedule = Schedule(
                id=item.get("id") or str(uuid.uuid4()),
                name=name,
                cron=item.get("cron") or None,
                fire_at=item.get("fire_at") or None,
                prompt=item["prompt"],
                silent=bool(item.get("silent", False)),
                tz=item.get("tz", ""),
                created_at=item.get("created_at") or now,
                last_run=item.get("last_run") or None,
            )
            await store.upsert_schedule(schedule)
            print(f"  imported: {name}")
            imported += 1

        print(f"\nDone. imported={imported} skipped={skipped}")
        return imported, skipped
    finally:
        await store.close()


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: import_schedules.py <path/to/schedules.json>", file=sys.stderr)
        sys.exit(1)

    json_path = Path(sys.argv[1])
    if not json_path.exists():
        print(f"ERROR: file not found: {json_path}", file=sys.stderr)
        sys.exit(1)

    asyncio.run(run(json_path))


if __name__ == "__main__":
    main()
