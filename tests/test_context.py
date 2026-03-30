"""Tests for context.py system prompt building."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from awfulclaw import context


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    for sub in ("facts", "people", "tasks", "skills"):
        (tmp_path / "memory" / sub).mkdir(parents=True, exist_ok=True)


def test_module_fragments_appear_in_prompt() -> None:
    """Module system_prompt_fragments should appear in the system prompt."""
    with patch("awfulclaw.modules.ModuleRegistry.get_system_prompt_fragments") as mock_frags:
        mock_frags.return_value = ["### TESTTOOL\nUse <skill:testtool/> to do stuff."]
        prompt = context.build_system_prompt("Hello")
    assert "## Available Skills" in prompt
    assert "TESTTOOL" in prompt


def test_no_skills_section_when_no_fragments() -> None:
    with patch("awfulclaw.modules.ModuleRegistry.get_system_prompt_fragments") as mock_frags:
        mock_frags.return_value = []
        prompt = context.build_system_prompt("Hello")
    assert "## Available Skills" not in prompt


def test_no_skills_section_when_no_available_modules() -> None:
    with patch("awfulclaw.modules.ModuleRegistry.get_available") as mock_avail:
        mock_avail.return_value = []
        prompt = context.build_system_prompt("Hello")
    assert "## Active Skills" not in prompt


def test_location_in_prompt_when_file_exists(tmp_path: Path) -> None:
    location_file = tmp_path / "memory" / "facts" / "location.md"
    location_file.write_text(
        "Last known location: 51.5074, -0.1278\nUpdated: 2026-03-29T20:00:00Z",
        encoding="utf-8",
    )
    prompt = context.build_system_prompt("Hello")
    assert "User's last known location: 51.5074, -0.1278 (as of 2026-03-29T20:00:00Z)" in prompt


def test_location_absent_when_file_missing() -> None:
    prompt = context.build_system_prompt("Hello")
    assert "last known location" not in prompt.lower()


def test_personality_overlay_appended_for_matching_sender(tmp_path: Path) -> None:
    """Personality section from a person file is appended to the soul when sender matches."""
    person_file = tmp_path / "memory" / "people" / "charlie.md"
    person_file.write_text(
        "# Charlie\nPhone: +1234567890\n\n## Personality\nBe terse. Skip pleasantries.\n",
        encoding="utf-8",
    )
    prompt = context.build_system_prompt("Hello", sender="+1234567890")
    assert "Personality overlay for this sender" in prompt
    assert "Be terse. Skip pleasantries." in prompt


def test_personality_overlay_appended_after_soul(tmp_path: Path) -> None:
    """Personality overlay comes after the base soul, not replacing it."""
    soul_file = tmp_path / "memory" / "SOUL.md"
    soul_file.write_text("You are a helpful assistant.", encoding="utf-8")
    person_file = tmp_path / "memory" / "people" / "charlie.md"
    person_file.write_text(
        "# Charlie\nPhone: +1234567890\n\n## Personality\nBe terse.\n",
        encoding="utf-8",
    )
    prompt = context.build_system_prompt("Hello", sender="+1234567890")
    soul_pos = prompt.index("You are a helpful assistant.")
    overlay_pos = prompt.index("Be terse.")
    assert soul_pos < overlay_pos


def test_no_personality_overlay_when_no_section(tmp_path: Path) -> None:
    """No overlay injected when person file has no ## Personality section."""
    person_file = tmp_path / "memory" / "people" / "charlie.md"
    person_file.write_text("# Charlie\nPhone: +1234567890\n", encoding="utf-8")
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


def test_personality_overlay_stops_at_next_heading(tmp_path: Path) -> None:
    """Personality overlay includes only content up to the next ## heading."""
    person_file = tmp_path / "memory" / "people" / "charlie.md"
    person_file.write_text(
        "# Charlie\nPhone: +1234567890\n\n## Personality\nBe terse.\n\n## Notes\nOther content.\n",
        encoding="utf-8",
    )
    prompt = context.build_system_prompt("Hello", sender="+1234567890")
    assert "Be terse." in prompt
    overlay_start = prompt.index("Personality overlay for this sender")
    assert "Other content" not in prompt[overlay_start : overlay_start + 200]


def test_no_overlay_when_personality_section_absent(tmp_path: Path) -> None:
    """No overlay added when person file has no ## Personality section."""
    person_file = tmp_path / "memory" / "people" / "charlie.md"
    person_file.write_text("# Charlie\nPhone: +1234567890\n", encoding="utf-8")
    prompt = context.build_system_prompt("Hello", sender="+1234567890")
    assert "Personality overlay" not in prompt
