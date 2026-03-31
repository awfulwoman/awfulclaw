"""Location helpers — timezone resolution, USER.md updates, OwnTracks integration."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


def _user_timezone() -> str:
    """Extract timezone from memory/USER.md, or return '' if not set/unknown."""
    from awfulclaw import memory

    content = memory.read("USER.md")
    m = re.search(r"(?i)^Timezone:\s*(.+)$", content, re.MULTILINE)
    if not m:
        return ""
    tz_name = m.group(1).strip().split()[0]
    return "" if tz_name.lower() in ("unknown", "") else tz_name


def _update_user_timezone(new_tz: str) -> None:
    """Update the Timezone: line in memory/USER.md in-place."""
    from awfulclaw import memory

    content = memory.read("USER.md")
    if not content:
        return
    if re.search(r"(?im)^Timezone:", content):
        updated = re.sub(
            r"(?im)^(Timezone:\s*)(.+)$",
            lambda m: m.group(1) + new_tz,
            content,
        )
    else:
        updated = content.rstrip() + f"\nTimezone: {new_tz}\n"
    if updated != content:
        memory.write("USER.md", updated)
