"""Migrate facts and people from SQLite to Obsidian vault.

Usage:
    uv run python scripts/migrate_facts_people_to_obsidian.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from awfulclaw.db import list_facts, list_people, read_fact, read_person
from dotenv import load_dotenv
import os

load_dotenv()

VAULT = os.getenv("OBSIDIAN_VAULT", "").strip()
if not VAULT:
    print("ERROR: OBSIDIAN_VAULT not set in .env")
    sys.exit(1)


def obsidian(*args: str) -> tuple[int, str]:
    result = subprocess.run(
        ["obsidian", f"vault={VAULT}", *args],
        capture_output=True, text=True, timeout=10,
    )
    return result.returncode, result.stdout.strip()


def migrate() -> None:
    facts = list_facts()
    people = list_people()

    if not facts and not people:
        print("Nothing to migrate.")
        return

    print(f"Migrating {len(facts)} facts and {len(people)} people to Obsidian vault '{VAULT}'...")

    for key in facts:
        content = read_fact(key)
        if not content:
            continue
        path = f"awfulclaw/facts/{key}.md"
        rc, out = obsidian("create", f"path={path}", f"content={content}", "overwrite")
        status = "OK" if rc == 0 else f"FAILED ({out})"
        print(f"  fact/{key}: {status}")

    for name in people:
        content = read_person(name)
        if not content:
            continue
        path = f"awfulclaw/people/{name}.md"
        rc, out = obsidian("create", f"path={path}", f"content={content}", "overwrite")
        status = "OK" if rc == 0 else f"FAILED ({out})"
        print(f"  people/{name}: {status}")

    print("Done. SQLite tables are still intact — delete them manually if desired.")


if __name__ == "__main__":
    migrate()
