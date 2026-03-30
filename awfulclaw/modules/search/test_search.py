"""Tests for the search module."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def tmp_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    from awfulclaw.db import init_db
    init_db()


def _dispatch(query: str) -> str:
    from awfulclaw.modules.search._search import SearchModule

    mod = SearchModule()
    tag = mod.skill_tags[0]
    raw = f'<skill:search query="{query}"/>'
    m = tag.pattern.match(raw)
    assert m is not None
    return mod.dispatch(m, [], "")


def test_dispatch_returns_results() -> None:
    from awfulclaw.db import write_fact
    write_fact("hello", "the quick brown fox")
    result = _dispatch("quick")
    assert "quick" in result
    assert "facts/hello.md" in result


def test_dispatch_no_results() -> None:
    result = _dispatch("xyzzy_nonexistent")
    assert "No matches found" in result


def test_dispatch_multiple_files() -> None:
    from awfulclaw.db import write_fact
    write_fact("a", "apple pie is tasty")
    write_fact("b", "apple cider is good")
    result = _dispatch("apple")
    assert "facts/a.md" in result
    assert "facts/b.md" in result
    assert "apple pie" in result
    assert "apple cider" in result


def test_is_available() -> None:
    from awfulclaw.modules.search._search import SearchModule

    assert SearchModule().is_available() is True


def test_create_module() -> None:
    from awfulclaw.modules.search import create_module

    mod = create_module()
    assert mod.name == "search"
    assert len(mod.skill_tags) == 1
    assert mod.skill_tags[0].name == "search"
