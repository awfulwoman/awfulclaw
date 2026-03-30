"""Tests for ModuleRegistry hot-reload support."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

from awfulclaw.modules import ModuleRegistry
from awfulclaw.modules.base import Module, SkillTag

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_check_for_changes_no_changes() -> None:
    reg = ModuleRegistry()
    reg.discover()
    # After discovery, mtimes are recorded — no changes should be detected
    assert reg.check_for_changes() is False


def test_check_for_changes_detects_modified_file(tmp_path: Path) -> None:
    """Modifying an mtime-tracked file should trigger a reload."""
    reg = ModuleRegistry()
    # Simulate a tracked file with a past mtime
    fake_file = tmp_path / "fake.py"
    fake_file.write_text("# v1")
    pkg = "awfulclaw.modules.fake"
    reg.mtimes[pkg] = {fake_file: 0.0}  # old mtime = epoch

    with patch.object(reg, "reload") as mock_reload:
        result = reg.check_for_changes()

    assert result is True
    mock_reload.assert_called_once()


def test_check_for_changes_detects_new_directory(tmp_path: Path) -> None:
    """A new module subdirectory should trigger a reload."""
    reg = ModuleRegistry()
    new_pkg_dir = tmp_path / "newmod"
    new_pkg_dir.mkdir()
    (new_pkg_dir / "__init__.py").write_text("def create_module(): pass\n")

    # Patch __file__ to point at tmp_path so discover() sees new_pkg_dir
    with patch("awfulclaw.modules.__file__", str(tmp_path / "__init__.py")):
        with patch.object(reg, "reload") as mock_reload:
            result = reg.check_for_changes()

    assert result is True
    mock_reload.assert_called_once()


def test_reload_uses_importlib_reload_for_existing_module() -> None:
    """reload() should call importlib.reload on already-imported packages."""
    reg = ModuleRegistry()
    reg.discover()

    with patch("awfulclaw.modules.importlib.reload") as mock_reload:
        reg.reload()

    # importlib.reload should have been called at least once (for known modules)
    assert mock_reload.called


def test_reload_clears_and_rediscovers() -> None:
    reg = ModuleRegistry()

    class FakeModule(Module):
        @property
        def name(self) -> str:
            return "fake"

        @property
        def skill_tags(self) -> list[SkillTag]:
            return []

        @property
        def system_prompt_fragment(self) -> str:
            return ""

        def dispatch(
            self, tag_match: re.Match[str], history: list[dict[str, str]], system: str
        ) -> str:
            return ""

    reg.register(FakeModule())
    assert len(reg.get_all()) == 1
    reg.reload()
    # After reload, fake module (not in modules dir) should be gone
    assert reg.get("fake") is None
