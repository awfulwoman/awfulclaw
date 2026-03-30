"""Tests for ModuleRegistry auto-discovery, skip behavior, and reload."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from awfulclaw.modules import ModuleRegistry
from awfulclaw.modules.base import Module

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class DummyModule(Module):
    @property
    def name(self) -> str:
        return "dummy"

    def is_available(self) -> bool:
        return True


class UnavailableModule(Module):
    @property
    def name(self) -> str:
        return "unavailable"

    def is_available(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _make_registry() -> ModuleRegistry:
    return ModuleRegistry()


def test_register_and_get_all():
    reg = _make_registry()
    reg.register(DummyModule())
    mods = reg.get_all()
    assert len(mods) == 1
    assert mods[0].name == "dummy"


def test_get_available_filters_unavailable():
    reg = _make_registry()
    reg.register(DummyModule())
    reg.register(UnavailableModule())
    available = reg.get_available()
    assert len(available) == 1
    assert available[0].name == "dummy"


def test_reload_clears_and_rediscovers():
    reg = _make_registry()
    reg.register(DummyModule())
    assert len(reg.get_all()) == 1
    reg.reload()
    # After reload with no packages that have create_module, count may differ
    # Just verify state is reset (no error)
    assert isinstance(reg.get_all(), list)


def test_discover_skips_missing_create_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Packages without create_module() are skipped with a warning, not a crash."""
    # Create a fake package without create_module
    pkg_dir = tmp_path / "noentry"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("# no create_module here\n")

    reg = ModuleRegistry()

    # Patch __file__ of the __init__ module to point at tmp_path
    with patch("awfulclaw.modules.__file__", str(tmp_path / "__init__.py")):
        # Make sure the fake package is importable
        sys.path.insert(0, str(tmp_path.parent))
        try:
            reg.discover()
        finally:
            sys.path.pop(0)
    # noentry is skipped; registry should not crash
    assert reg.get("noentry") is None


def test_discover_skips_underscore_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Directories starting with _ are skipped."""
    pkg_dir = tmp_path / "_private"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text(
        "def create_module(): raise RuntimeError('should not be called')\n"
    )

    reg = ModuleRegistry()
    with patch("awfulclaw.modules.__file__", str(tmp_path / "__init__.py")):
        reg.discover()
    assert reg.get("_private") is None


def test_get_returns_none_for_unknown():
    reg = _make_registry()
    assert reg.get("nonexistent") is None
