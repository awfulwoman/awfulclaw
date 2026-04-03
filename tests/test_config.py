import pytest
from pathlib import Path
from pydantic import ValidationError

from agent.config import Settings, TelegramSettings


def make_telegram_env(**kwargs: object) -> dict[str, str]:
    """Return env vars for a valid TelegramSettings."""
    base = {
        "AWFULCLAW_TELEGRAM__BOT_TOKEN": "test-token",
        "AWFULCLAW_TELEGRAM__ALLOWED_CHAT_IDS": "[123456]",
    }
    base.update({str(k): str(v) for k, v in kwargs.items()})
    return base


def test_defaults_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in make_telegram_env().items():
        monkeypatch.setenv(k, v)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.model == "claude-sonnet-4-6"
    assert settings.governance_model == "claude-haiku-4-5-20251001"
    assert settings.state_path == Path("state")
    assert settings.profile_path == Path("profile")
    assert settings.mcp_config == Path("config/mcp_servers.json")
    assert settings.poll_interval == 5
    assert settings.idle_interval == 60
    assert settings.checkin_interval == 86400
    assert settings.imap is None
    assert settings.eventkit is None
    assert settings.contacts is None
    assert settings.owntracks is None


def test_env_vars_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    env = make_telegram_env()
    env["AWFULCLAW_MODEL"] = "claude-opus-4-6"
    env["AWFULCLAW_POLL_INTERVAL"] = "10"
    env["AWFULCLAW_STATE_PATH"] = "/tmp/state"
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.model == "claude-opus-4-6"
    assert settings.poll_interval == 10
    assert settings.state_path == Path("/tmp/state")


def test_missing_required_telegram_raises() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_telegram_settings_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in make_telegram_env().items():
        monkeypatch.setenv(k, v)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.telegram.bot_token == "test-token"
    assert settings.telegram.allowed_chat_ids == [123456]


def test_new_backend_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in make_telegram_env().items():
        monkeypatch.setenv(k, v)

    s = Settings()  # type: ignore[call-arg]
    assert s.primary_backend == "claude"
    assert s.fallback_backend == "ollama"
    assert s.ollama_url == "http://localhost:11434"
    assert s.ollama_model == "llama3.2"
    assert s.fallback_failure_threshold == 3
    assert s.fallback_probe_interval == 600
