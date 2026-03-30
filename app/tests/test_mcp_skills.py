"""Tests for MCP skills server."""

from __future__ import annotations

from pathlib import Path

import pytest
from awfulclaw_mcp.skills import skill_read


@pytest.fixture(autouse=True)
def _chdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def _make_skill(tmp_path: Path, name: str, content: str) -> None:
    d = tmp_path / "config" / "skills"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(content, encoding="utf-8")


def test_read_skill_returns_content(tmp_path: Path) -> None:
    _make_skill(tmp_path, "daily-briefing", "# Daily Briefing\nDo the thing.")
    result = skill_read("daily-briefing")
    assert "Daily Briefing" in result
    assert "Do the thing." in result


def test_read_skill_strips_md_suffix(tmp_path: Path) -> None:
    _make_skill(tmp_path, "foo", "foo content")
    assert skill_read("foo.md") == skill_read("foo")


def test_skill_not_found_no_dir() -> None:
    result = skill_read("nonexistent")
    assert "not found" in result
    assert "No skills are available" in result


def test_skill_not_found_lists_available(tmp_path: Path) -> None:
    _make_skill(tmp_path, "alpha", "alpha content")
    _make_skill(tmp_path, "beta", "beta content")
    result = skill_read("nonexistent")
    assert "not found" in result
    assert "alpha" in result
    assert "beta" in result
