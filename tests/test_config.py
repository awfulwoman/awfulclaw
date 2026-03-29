"""Tests for config module."""

import pytest

import awfulclaw.config as cfg
from awfulclaw.telegram import TelegramConnector


def test_get_connector_default_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWFULCLAW_CHANNEL", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    assert isinstance(cfg.get_connector(), TelegramConnector)


def test_get_connector_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWFULCLAW_CHANNEL", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    assert isinstance(cfg.get_connector(), TelegramConnector)


def test_get_connector_unknown_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWFULCLAW_CHANNEL", "discord")
    with pytest.raises(RuntimeError, match="discord"):
        cfg.get_connector()
