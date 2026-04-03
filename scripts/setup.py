"""First-run setup for awfulclaw.

Creates all directories and config files that are excluded from version control:
  config/mcp_servers.json   — MCP server definitions (uv path varies per machine)
  config/skills/            — user-authored skill fragments
  profile/                  — PERSONALITY.md, PROTOCOLS.md, USER.md, CHECKIN.md
  state/                    — runtime state directory (SQLite DB)

Run once after cloning:
  uv run python scripts/setup.py
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def find_uv() -> str:
    uv = shutil.which("uv")
    if uv is None:
        sys.exit("ERROR: uv not found in PATH. Install it from https://docs.astral.sh/uv/")
    return uv


def create_mcp_config(uv: str) -> None:
    path = ROOT / "config" / "mcp_servers.json"
    if path.exists():
        print(f"  exists   {path.relative_to(ROOT)}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "mcpServers": {
            "memory": {
                "command": uv,
                "args": ["run", "python", "-m", "agent.mcp.memory"],
                "env": {"DB_PATH": "state/store.db"},
            },
            "schedule": {
                "command": uv,
                "args": ["run", "python", "-m", "agent.mcp.schedule"],
                "env": {"DB_PATH": "state/store.db"},
            },
            "skills": {
                "command": uv,
                "args": ["run", "python", "-m", "agent.mcp.skills"],
            },
        }
    }
    path.write_text(json.dumps(config, indent=2) + "\n")
    print(f"  created  {path.relative_to(ROOT)}")


def create_skills_dir() -> None:
    path = ROOT / "config" / "skills"
    path.mkdir(parents=True, exist_ok=True)
    print(f"  ok       {path.relative_to(ROOT)}/")


def create_state_dir() -> None:
    path = ROOT / "state"
    path.mkdir(exist_ok=True)
    print(f"  ok       {path.relative_to(ROOT)}/")


_PROFILE_TEMPLATES: dict[str, str] = {
    "PERSONALITY.md": """\
# Personality

Describe the agent's character, tone, and values here.

Example:
- Warm and direct, no corporate speak
- Honest about uncertainty
- Concise by default; expands when asked
""",
    "PROTOCOLS.md": """\
# Protocols

Operating rules and procedures for the agent.

Example:
- Always confirm before sending emails or creating calendar events
- Check the calendar before scheduling anything
- Summarise long documents before quoting them
""",
    "USER.md": """\
# User Profile

Facts about the user the agent should always know.

Example:
- Name: Your Name
- Location: Your City
- Timezone: Europe/London
""",
    "CHECKIN.md": """\
# Check-in

A short patrol checklist the agent runs periodically.

Example:
- Any overdue reminders?
- Any calendar conflicts in the next 24 hours?
- Any urgent unread emails?
""",
}


def create_profile_files() -> None:
    profile = ROOT / "profile"
    profile.mkdir(exist_ok=True)
    for filename, content in _PROFILE_TEMPLATES.items():
        path = profile / filename
        if path.exists():
            print(f"  exists   profile/{filename}")
        else:
            path.write_text(content)
            print(f"  created  profile/{filename}")


def main() -> None:
    print("awfulclaw setup")
    print(f"root: {ROOT}\n")

    uv = find_uv()
    print(f"uv:   {uv}\n")

    print("config/")
    create_mcp_config(uv)
    create_skills_dir()

    print("\nprofile/")
    create_profile_files()

    print("\nstate/")
    create_state_dir()

    print("\nDone. Edit profile/*.md to configure the agent, then start with:")
    print("  uv run python -m agent.main")


if __name__ == "__main__":
    main()
