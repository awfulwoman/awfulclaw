"""Tests for context.py system prompt building."""

from __future__ import annotations

from pathlib import Path

import pytest
from awfulclaw import context


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    for sub in ("tasks", "skills"):
        (tmp_path / "memory" / sub).mkdir(parents=True, exist_ok=True)
    from awfulclaw.db import init_db
    init_db()


def test_no_skills_section_in_prompt() -> None:
    """No Available Skills section should appear in the system prompt."""
    prompt = context.build_system_prompt("Hello")
    assert "## Available Skills" not in prompt


def test_no_memory_write_tag_docs_in_prompt() -> None:
    """The <memory:write> tag syntax should not appear in the system prompt."""
    prompt = context.build_system_prompt("Hello")
    assert "<memory:write" not in prompt


def test_location_in_prompt_when_file_exists() -> None:
    from awfulclaw.db import write_fact
    write_fact("location", "Last known location: 51.5074, -0.1278\nUpdated: 2026-03-29T20:00:00Z")
    prompt = context.build_system_prompt("Hello")
    assert "User's last known location: 51.5074, -0.1278 (as of 2026-03-29T20:00:00Z)" in prompt


def test_location_absent_when_file_missing() -> None:
    prompt = context.build_system_prompt("Hello")
    assert "last known location" not in prompt.lower()


def test_personality_overlay_appended_for_matching_sender() -> None:
    """Personality section from a person record is appended to the soul when sender matches."""
    from awfulclaw.db import write_person
    content = "# Charlie\nPhone: +1234567890\n\n## Personality\nBe terse. Skip pleasantries.\n"
    write_person("charlie", content)
    prompt = context.build_system_prompt("Hello", sender="+1234567890")
    assert "Personality overlay for this sender" in prompt
    assert "Be terse. Skip pleasantries." in prompt


def test_personality_overlay_appended_after_soul(tmp_path: Path) -> None:
    """Personality overlay comes after the base soul, not replacing it."""
    (tmp_path / "memory" / "SOUL.md").write_text("You are a helpful assistant.", encoding="utf-8")
    from awfulclaw.db import write_person
    write_person("charlie", "# Charlie\nPhone: +1234567890\n\n## Personality\nBe terse.\n")
    prompt = context.build_system_prompt("Hello", sender="+1234567890")
    soul_pos = prompt.index("You are a helpful assistant.")
    overlay_pos = prompt.index("Be terse.")
    assert soul_pos < overlay_pos


def test_no_personality_overlay_when_no_section() -> None:
    """No overlay injected when person record has no ## Personality section."""
    from awfulclaw.db import write_person
    write_person("charlie", "# Charlie\nPhone: +1234567890\n")
    prompt = context.build_system_prompt("Hello", sender="+1234567890")
    assert "Personality overlay" not in prompt


def test_no_overlay_when_sender_unknown() -> None:
    """No overlay when sender doesn't match any person file."""
    prompt = context.build_system_prompt("Hello", sender="+9999999999")
    assert "Personality overlay" not in prompt


def test_channel_soul_override(tmp_path: Path) -> None:
    """SOUL_<channel>.md is loaded instead of SOUL.md when it exists."""
    (tmp_path / "memory" / "SOUL.md").write_text("Default soul.", encoding="utf-8")
    (tmp_path / "memory" / "SOUL_telegram.md").write_text("Telegram soul.", encoding="utf-8")
    prompt = context.build_system_prompt("Hello", channel="telegram")
    assert "Telegram soul." in prompt
    assert "Default soul." not in prompt


def test_channel_soul_falls_back_to_default(tmp_path: Path) -> None:
    """Falls back to SOUL.md when no channel-specific soul file exists."""
    (tmp_path / "memory" / "SOUL.md").write_text("Default soul.", encoding="utf-8")
    prompt = context.build_system_prompt("Hello", channel="telegram")
    assert "Default soul." in prompt


def test_personality_overlay_stops_at_next_heading() -> None:
    """Personality overlay includes only content up to the next ## heading."""
    from awfulclaw.db import write_person
    content = (
        "# Charlie\nPhone: +1234567890\n\n## Personality\nBe terse.\n\n## Notes\nOther content.\n"
    )
    write_person("charlie", content)
    prompt = context.build_system_prompt("Hello", sender="+1234567890")
    assert "Be terse." in prompt
    overlay_start = prompt.index("Personality overlay for this sender")
    assert "Other content" not in prompt[overlay_start : overlay_start + 200]


def test_no_overlay_when_personality_section_absent() -> None:
    """No overlay added when person record has no ## Personality section."""
    from awfulclaw.db import write_person
    write_person("charlie", "# Charlie\nPhone: +1234567890\n")
    prompt = context.build_system_prompt("Hello", sender="+1234567890")
    assert "Personality overlay" not in prompt
