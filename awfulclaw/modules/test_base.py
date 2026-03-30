"""Tests for simplified Module ABC."""

from __future__ import annotations

import pytest

from awfulclaw.modules.base import Module


class ConcreteModule(Module):
    @property
    def name(self) -> str:
        return "test"


def test_abc_cannot_be_instantiated():
    with pytest.raises(TypeError):
        Module()  # type: ignore[abstract]


def test_concrete_subclass_works():
    mod = ConcreteModule()
    assert mod.name == "test"
    assert mod.is_available() is True
