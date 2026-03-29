"""Tests for config module."""

import pytest

import awfulclaw.config as cfg
from awfulclaw.imessage import IMessageConnector
from awfulclaw.telegram import TelegramConnector


def test_get_phone_returns_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWFULCLAW_PHONE", "+15550001234")
    assert cfg.get_phone() == "+15550001234"


def test_get_phone_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWFULCLAW_PHONE", raising=False)
    with pytest.raises(RuntimeError, match="AWFULCLAW_PHONE"):
        cfg.get_phone()


def test_get_connector_default_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWFULCLAW_CHANNEL", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    assert isinstance(cfg.get_connector(), TelegramConnector)


def test_get_connector_imessage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWFULCLAW_CHANNEL", "imessage")
    monkeypatch.setenv("AWFULCLAW_PHONE", "+15550001234")
    assert isinstance(cfg.get_connector(), IMessageConnector)


def test_get_connector_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWFULCLAW_CHANNEL", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    assert isinstance(cfg.get_connector(), TelegramConnector)


def test_get_connector_unknown_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWFULCLAW_CHANNEL", "discord")
    with pytest.raises(RuntimeError, match="discord"):
        cfg.get_connector()
