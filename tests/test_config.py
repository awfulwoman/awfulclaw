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

    assert settings.backend.claude_model == "claude-sonnet-4-6"
    assert settings.backend.ollama_model == "llama3.2"
    assert settings.backend.provider == "claude"
    assert settings.backend.fallback == "ollama"
    assert settings.backend.ollama_url == "http://localhost:11434"
    assert settings.backend.failure_threshold == 3
    assert settings.backend.probe_interval == 600
    assert settings.governance_model == "claude-haiku-4-5-20251001"
    assert settings.state_path == Path("state")
    assert settings.profile_path == Path("profile")
    assert settings.mcp_config == Path("config/mcp_servers.json")
    assert settings.poll_interval == 5
    assert settings.idle_interval == 14400
    assert settings.checkin_interval == 86400
    assert settings.imap is None
    assert settings.eventkit is None
    assert settings.contacts is None
    assert settings.owntracks is None


def test_env_vars_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    env = make_telegram_env()
    env["AWFULCLAW_BACKEND__CLAUDE_MODEL"] = "claude-sonnet-4-6"
    env["AWFULCLAW_POLL_INTERVAL"] = "10"
    env["AWFULCLAW_STATE_PATH"] = "/tmp/state"
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.backend.claude_model == "claude-sonnet-4-6"
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


def test_backend_settings_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    env = make_telegram_env()
    env["AWFULCLAW_BACKEND__PROVIDER"] = "ollama"
    env["AWFULCLAW_BACKEND__FALLBACK"] = ""
    env["AWFULCLAW_BACKEND__OLLAMA_URL"] = "http://gpu-box:11434"
    env["AWFULCLAW_BACKEND__OLLAMA_MODEL"] = "phi4"
    env["AWFULCLAW_BACKEND__FAILURE_THRESHOLD"] = "5"
    env["AWFULCLAW_BACKEND__PROBE_INTERVAL"] = "300"
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    s = Settings()  # type: ignore[call-arg]
    assert s.backend.provider == "ollama"
    assert s.backend.fallback == ""
    assert s.backend.ollama_url == "http://gpu-box:11434"
    assert s.backend.ollama_model == "phi4"
    assert s.backend.failure_threshold == 5
    assert s.backend.probe_interval == 300


def test_transcription_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in make_telegram_env().items():
        monkeypatch.setenv(k, v)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.transcription_enabled is True
    assert settings.parakeet_model == "nvidia/parakeet-tdt-0.6b-v3"


def test_transcription_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    env = make_telegram_env()
    env["AWFULCLAW_TRANSCRIPTION_ENABLED"] = "false"
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.transcription_enabled is False


def test_parakeet_model_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    env = make_telegram_env()
    env["AWFULCLAW_PARAKEET_MODEL"] = "nvidia/parakeet-tdt-0.6b-v2"
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.parakeet_model == "nvidia/parakeet-tdt-0.6b-v2"
