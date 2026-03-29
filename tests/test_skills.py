"""Tests for skills.py."""

from pathlib import Path

import pytest

import awfulclaw.skills as skills


@pytest.fixture(autouse=True)
def tmp_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    # Reset the module-level path to point to the tmp dir
    monkeypatch.setattr(skills, "_SKILLS_DIR", tmp_path / "memory" / "skills")


def _write_skill(tmp_path: Path, name: str, content: str) -> None:
    d = tmp_path / "memory" / "skills"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(content, encoding="utf-8")


def test_load_parses_frontmatter(tmp_path: Path) -> None:
    _write_skill(tmp_path, "coffee.md", "---\ntrigger: coffee, drink\ninstruction: Suggest oat milk.\n---\nExtra body.")
    loaded = skills.load_skills()
    assert len(loaded) == 1
    s = loaded[0]
    assert s.name == "coffee"
    assert s.triggers == ["coffee", "drink"]
    assert s.instruction == "Suggest oat milk."
    assert s.body == "Extra body."


def test_load_skips_malformed_no_frontmatter(tmp_path: Path) -> None:
    _write_skill(tmp_path, "bad.md", "No frontmatter here.")
    assert skills.load_skills() == []


def test_load_skips_missing_instruction(tmp_path: Path) -> None:
    _write_skill(tmp_path, "bad.md", "---\ntrigger: foo\n---\n")
    assert skills.load_skills() == []


def test_load_skips_missing_trigger(tmp_path: Path) -> None:
    _write_skill(tmp_path, "bad.md", "---\ninstruction: Do something.\n---\n")
    assert skills.load_skills() == []


def test_load_empty_dir(tmp_path: Path) -> None:
    assert skills.load_skills() == []


def test_match_returns_correct_skills(tmp_path: Path) -> None:
    _write_skill(tmp_path, "coffee.md", "---\ntrigger: coffee, drink\ninstruction: Suggest oat milk.\n---\n")
    _write_skill(tmp_path, "todo.md", "---\ntrigger: task, todo\ninstruction: Create a task file.\n---\n")
    loaded = skills.load_skills()
    matched = skills.match_skills("I want some coffee please", loaded)
    assert len(matched) == 1
    assert matched[0].name == "coffee"


def test_match_case_insensitive(tmp_path: Path) -> None:
    _write_skill(tmp_path, "coffee.md", "---\ntrigger: coffee\ninstruction: Suggest oat milk.\n---\n")
    loaded = skills.load_skills()
    matched = skills.match_skills("Let me have some COFFEE", loaded)
    assert len(matched) == 1


def test_match_whole_word_only(tmp_path: Path) -> None:
    _write_skill(tmp_path, "coffee.md", "---\ntrigger: coffee\ninstruction: Suggest oat milk.\n---\n")
    loaded = skills.load_skills()
    # "coffeeshop" should not match "coffee"
    matched = skills.match_skills("Let's go to the coffeeshop", loaded)
    assert matched == []


def test_match_no_match(tmp_path: Path) -> None:
    _write_skill(tmp_path, "coffee.md", "---\ntrigger: coffee\ninstruction: Suggest oat milk.\n---\n")
    loaded = skills.load_skills()
    assert skills.match_skills("nothing relevant here", loaded) == []
