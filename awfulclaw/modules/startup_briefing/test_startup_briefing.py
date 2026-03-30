"""Tests for startup self-briefing module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from awfulclaw.modules.startup_briefing._startup_briefing import StartupBriefingModule


@pytest.fixture(autouse=True)
def tmp_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def test_name_and_skill_tags() -> None:
    mod = StartupBriefingModule()
    assert mod.name == "startup_briefing"
    assert mod.skill_tags == []


def test_is_available() -> None:
    mod = StartupBriefingModule()
    assert mod.is_available()


def test_get_startup_prompt_without_existing_progress() -> None:
    mod = StartupBriefingModule()
    prompt = mod.get_startup_prompt()
    assert "You have just restarted" in prompt
    assert "previous progress note" not in prompt


def test_get_startup_prompt_with_existing_progress() -> None:
    import awfulclaw.memory as mem

    mem.write("progress.md", "Last discussed: weather API integration")
    mod = StartupBriefingModule()
    prompt = mod.get_startup_prompt()
    assert "previous progress note" in prompt
    assert "weather API integration" in prompt


def test_prompt_contains_memory_write_instruction() -> None:
    mod = StartupBriefingModule()
    prompt = mod.get_startup_prompt()
    assert '<memory:write path="progress.md">' in prompt


def test_prompt_prohibits_user_message() -> None:
    mod = StartupBriefingModule()
    prompt = mod.get_startup_prompt()
    assert "Do NOT send a message to the user" in prompt
