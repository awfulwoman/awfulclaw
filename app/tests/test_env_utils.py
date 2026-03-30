"""Tests for env_utils."""

from __future__ import annotations

from pathlib import Path

import pytest

from awfulclaw.env_utils import get_env_keys, set_env_var, validate_key


@pytest.fixture(autouse=True)
def tmp_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def test_set_creates_env_file(tmp_path: Path) -> None:
    set_env_var("MY_KEY", "myvalue")
    assert (tmp_path / ".env").exists()
    assert "MY_KEY=myvalue" in (tmp_path / ".env").read_text()


def test_set_updates_existing_key(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("MY_KEY=old\nOTHER=x\n")
    set_env_var("MY_KEY", "new")
    content = (tmp_path / ".env").read_text()
    assert "MY_KEY=new" in content
    assert "MY_KEY=old" not in content
    assert "OTHER=x" in content


def test_set_appends_new_key(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("EXISTING=yes\n")
    set_env_var("NEW_KEY", "val")
    content = (tmp_path / ".env").read_text()
    assert "EXISTING=yes" in content
    assert "NEW_KEY=val" in content


def test_set_quotes_value_with_spaces(tmp_path: Path) -> None:
    set_env_var("MY_KEY", "hello world")
    content = (tmp_path / ".env").read_text()
    assert 'MY_KEY="hello world"' in content


def test_set_quotes_value_with_hash(tmp_path: Path) -> None:
    set_env_var("MY_KEY", "val#comment")
    content = (tmp_path / ".env").read_text()
    assert 'MY_KEY="val#comment"' in content


def test_invalid_key_raises() -> None:
    with pytest.raises(ValueError, match="Invalid env key"):
        validate_key("lower_case")

    with pytest.raises(ValueError, match="Invalid env key"):
        validate_key("1STARTS_WITH_DIGIT")


def test_get_env_keys_empty(tmp_path: Path) -> None:
    assert get_env_keys() == []


def test_get_env_keys_returns_names_only(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("FOO=secret\nBAR=alsosecret\n# comment\n")
    keys = get_env_keys()
    assert keys == ["BAR", "FOO"]
    # Values must not appear
    assert "secret" not in keys
    assert "alsosecret" not in keys


def test_get_env_keys_skips_comments(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("# FOO=ignored\nBAR=val\n")
    assert get_env_keys() == ["BAR"]
