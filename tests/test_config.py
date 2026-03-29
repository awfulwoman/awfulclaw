"""Tests for config.get_auth_token()."""

import json
from pathlib import Path

import pytest


def test_get_auth_token_prefers_env_var(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    import awfulclaw.config as cfg

    assert cfg.get_auth_token() == "sk-test-key"


def test_get_auth_token_reads_credentials_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    creds = tmp_path / ".credentials.json"
    creds.write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "oauth-token-abc", "refreshToken": "ref"}})
    )
    import awfulclaw.config as cfg

    monkeypatch.setattr(cfg, "_CREDENTIALS_FILE", creds)
    assert cfg.get_auth_token() == "oauth-token-abc"


def test_get_auth_token_missing_file_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import awfulclaw.config as cfg

    monkeypatch.setattr(cfg, "_CREDENTIALS_FILE", tmp_path / "nope.json")
    with pytest.raises(RuntimeError, match="claude auth login"):
        cfg.get_auth_token()


def test_get_auth_token_missing_field_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    creds = tmp_path / ".credentials.json"
    creds.write_text(json.dumps({"claudeAiOauth": {"refreshToken": "ref"}}))
    import awfulclaw.config as cfg

    monkeypatch.setattr(cfg, "_CREDENTIALS_FILE", creds)
    with pytest.raises(RuntimeError, match="claude auth login"):
        cfg.get_auth_token()


def test_get_auth_token_invalid_json_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    creds = tmp_path / ".credentials.json"
    creds.write_text("not json")
    import awfulclaw.config as cfg

    monkeypatch.setattr(cfg, "_CREDENTIALS_FILE", creds)
    with pytest.raises(RuntimeError, match="Failed to read"):
        cfg.get_auth_token()
