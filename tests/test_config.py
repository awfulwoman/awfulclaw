"""Tests for config module."""

import pytest

import awfulclaw.config as cfg


def test_get_phone_returns_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWFULCLAW_PHONE", "+15550001234")
    assert cfg.get_phone() == "+15550001234"


def test_get_phone_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWFULCLAW_PHONE", raising=False)
    with pytest.raises(RuntimeError, match="AWFULCLAW_PHONE"):
        cfg.get_phone()
