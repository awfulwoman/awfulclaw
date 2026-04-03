"""Import legacy conversation markdown files into the conversations table.

Usage:
    uv run python scripts/import_conversations.py /path/to/conversations/

Legacy format — one file per day named YYYY-MM-DD.md:
    ## user

    Message content here (may span multiple lines).

    ## assistant

    Response content here.

    ## user

    Next turn...

Role headers are case-insensitive. The date is taken from the filename;
turns are timestamped at second-level intervals starting at midnight UTC.
"""
from __future__ import annotations

import asyncio
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
_ROLE_RE = re.compile(r"^##\s+(user|assistant)\s*$", re.IGNORECASE)


def parse_file(path: Path) -> list[tuple[str, str, str]]:
    """Parse a YYYY-MM-DD.md file into (role, content, timestamp) tuples.

    Timestamps are generated as second-level intervals starting at midnight UTC
    for the date in the filename.
    """
    m = _DATE_RE.match(path.name)
    if not m:
        raise ValueError(f"filename is not YYYY-MM-DD.md: {path.name}")

    date_str = m.group(1)
    base_dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    turns: list[tuple[str, str]] = []  # (role, content)
    current_role: Optional[str] = None
    buf: list[str] = []

    def flush() -> None:
        if current_role is not None:
            content = "\n".join(buf).strip()
            if content:
                turns.append((current_role, content))

    for line in lines:
        role_m = _ROLE_RE.match(line)
        if role_m:
            flush()
            current_role = role_m.group(1).lower()
            buf = []
        else:
            buf.append(line)

    flush()

    result: list[tuple[str, str, str]] = []
    for idx, (role, content) in enumerate(turns):
        ts = (base_dt + timedelta(seconds=idx)).isoformat()
        result.append((role, content, ts))

    return result


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
    conversations_dir: Path,
    db_path: Optional[Path] = None,
    channel: str = "legacy",
    _return_counts: bool = False,
) -> int:
    from agent.store import Store

    resolved_db = db_path or _default_db_path()
    if resolved_db is None:
        print("ERROR: database not found", file=sys.stderr)
        sys.exit(1)

    md_files = sorted(conversations_dir.glob("????-??-??.md"))
    if not md_files:
        print("No YYYY-MM-DD.md files found.")
        return 0

    store = await Store.connect(resolved_db)
    try:
        imported = 0
        for md_file in md_files:
            turns = parse_file(md_file)
            for role, content, timestamp in turns:
                await store._db.execute(
                    "INSERT INTO conversations (channel, role, content, timestamp) VALUES (?, ?, ?, ?)",
                    (channel, role, content, timestamp),
                )
                imported += 1
            await store._db.commit()
            print(f"  {md_file.name}: {len(turns)} turns")

        print(f"\nDone. imported={imported}")
        return imported
    finally:
        await store.close()


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: import_conversations.py <path/to/conversations/>", file=sys.stderr)
        sys.exit(1)

    conversations_dir = Path(sys.argv[1])
    if not conversations_dir.is_dir():
        print(f"ERROR: not a directory: {conversations_dir}", file=sys.stderr)
        sys.exit(1)

    asyncio.run(run(conversations_dir))


if __name__ == "__main__":
    main()
