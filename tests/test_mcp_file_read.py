"""Unit tests for agent/mcp/file_read.py"""
from __future__ import annotations

from pathlib import Path

import pytest

import agent.mcp.file_read as fr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# file_read tests
# ---------------------------------------------------------------------------


def test_file_read_valid_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _setup_project(tmp_path, monkeypatch)
    (project / "notes.txt").write_text("hello world")

    result = fr.file_read("notes.txt")
    assert result == "hello world"


def test_file_read_rejects_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _setup_project(tmp_path, monkeypatch)
    (project / ".env").write_text("SECRET=abc")

    result = fr.file_read(".env")
    assert "Rejected" in result
    assert ".env" in result


def test_file_read_rejects_path_outside_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_project(tmp_path, monkeypatch)
    result = fr.file_read("/etc/passwd")
    assert "Rejected" in result


def test_file_read_rejects_traversal_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _setup_project(tmp_path, monkeypatch)
    (project / "sub").mkdir()
    result = fr.file_read("sub/../../etc/passwd")
    assert "Rejected" in result


def test_file_read_rejects_symlink_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _setup_project(tmp_path, monkeypatch)
    outside = tmp_path.parent / "outside_secret.txt"
    outside.write_text("topsecret")
    link = project / "sneaky_link.txt"
    link.symlink_to(outside)

    result = fr.file_read("sneaky_link.txt")
    assert "Rejected" in result


def test_file_read_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_project(tmp_path, monkeypatch)
    result = fr.file_read("ghost.txt")
    assert "Not found" in result


def test_file_read_absolute_path_inside_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _setup_project(tmp_path, monkeypatch)
    (project / "readme.md").write_text("# readme")

    result = fr.file_read(str(project / "readme.md"))
    assert result == "# readme"
