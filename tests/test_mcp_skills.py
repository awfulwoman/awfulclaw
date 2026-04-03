"""Unit tests for agent/mcp/skills.py"""
from __future__ import annotations

from pathlib import Path

import pytest

import agent.mcp.skills as sk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_skills_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    monkeypatch.setenv("SKILLS_DIR", str(skills_dir))
    return skills_dir


# ---------------------------------------------------------------------------
# skill_list tests
# ---------------------------------------------------------------------------


def test_skill_list_returns_filenames(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skills_dir = _setup_skills_dir(tmp_path, monkeypatch)
    (skills_dir / "alpha.md").write_text("content a")
    (skills_dir / "beta.md").write_text("content b")

    result = sk.skill_list()
    assert result == ["alpha.md", "beta.md"]


def test_skill_list_empty_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_skills_dir(tmp_path, monkeypatch)
    assert sk.skill_list() == []


def test_skill_list_missing_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKILLS_DIR", str(tmp_path / "nonexistent"))
    assert sk.skill_list() == []


# ---------------------------------------------------------------------------
# skill_read tests
# ---------------------------------------------------------------------------


def test_skill_read_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skills_dir = _setup_skills_dir(tmp_path, monkeypatch)
    (skills_dir / "demo.md").write_text("# Demo skill")

    result = sk.skill_read("demo.md")
    assert result == "# Demo skill"


def test_skill_read_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_skills_dir(tmp_path, monkeypatch)
    result = sk.skill_read("ghost.md")
    assert "Not found" in result
    assert "ghost.md" in result


def test_skill_read_rejects_path_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_skills_dir(tmp_path, monkeypatch)
    result = sk.skill_read("../secret.txt")
    assert "Rejected" in result


def test_skill_read_rejects_dotdot_in_subpath(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_skills_dir(tmp_path, monkeypatch)
    result = sk.skill_read("sub/../../etc/passwd")
    assert "Rejected" in result


def test_skill_read_rejects_absolute_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_skills_dir(tmp_path, monkeypatch)
    result = sk.skill_read("/etc/passwd")
    assert "Rejected" in result
