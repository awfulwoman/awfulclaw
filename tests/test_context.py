"""Tests for context.py skills injection."""

from pathlib import Path

import pytest

import awfulclaw.skills as skills_module
from awfulclaw import context


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(skills_module, "_SKILLS_DIR", tmp_path / "memory" / "skills")
    # Ensure memory subdirs exist
    for sub in ("facts", "people", "tasks"):
        (tmp_path / "memory" / sub).mkdir(parents=True, exist_ok=True)


def _write_skill(tmp_path: Path, name: str, trigger: str, instruction: str, body: str = "") -> None:
    d = tmp_path / "memory" / "skills"
    d.mkdir(parents=True, exist_ok=True)
    front = f"---\ntrigger: {trigger}\ninstruction: {instruction}\n---\n"
    (d / name).write_text(front + body, encoding="utf-8")


def test_matched_skill_appears_in_prompt(tmp_path: Path) -> None:
    _write_skill(tmp_path, "coffee.md", "coffee", "Always suggest oat milk.")
    prompt = context.build_system_prompt("Can I have some coffee?")
    assert "## Active Skills" in prompt
    assert "### coffee" in prompt
    assert "Always suggest oat milk." in prompt


def test_no_match_no_skills_section(tmp_path: Path) -> None:
    _write_skill(tmp_path, "coffee.md", "coffee", "Always suggest oat milk.")
    prompt = context.build_system_prompt("What is the weather like?")
    assert "## Active Skills" not in prompt


def test_skill_body_included_when_present(tmp_path: Path) -> None:
    _write_skill(tmp_path, "coffee.md", "coffee", "Suggest oat milk.", "Extra notes here.")
    prompt = context.build_system_prompt("I want coffee")
    assert "Extra notes here." in prompt


def test_no_skills_dir_no_error(tmp_path: Path) -> None:
    # skills dir doesn't exist at all — should not raise
    prompt = context.build_system_prompt("Hello")
    assert "## Active Skills" not in prompt
