"""Tests for memory.py."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def tmp_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect memory root to a temp dir for each test."""
    monkeypatch.chdir(tmp_path)


def test_write_and_read() -> None:
    import awfulclaw.memory as mem

    mem.write("facts/hello.md", "hello world")
    assert mem.read("facts/hello.md") == "hello world"


def test_read_missing() -> None:
    import awfulclaw.memory as mem

    assert mem.read("facts/nope.md") == ""


def test_write_creates_parents() -> None:
    import awfulclaw.memory as mem

    mem.write("people/deep/nested.md", "content")
    assert mem.read("people/deep/nested.md") == "content"


def test_list_files() -> None:
    import awfulclaw.memory as mem

    mem.write("tasks/a.md", "task a")
    mem.write("tasks/b.md", "task b")
    files = mem.list_files("tasks")
    assert files == ["a.md", "b.md"]


def test_list_empty_subdir() -> None:
    import awfulclaw.memory as mem

    assert mem.list_files("conversations") == []


def test_search_finds_match() -> None:
    import awfulclaw.memory as mem

    mem.write("people/alice.md", "name: Alice\nphone: +1234567890")
    results = mem.search("people", "alice")
    assert results == [("alice.md", "name: Alice")]


def test_search_case_insensitive() -> None:
    import awfulclaw.memory as mem

    mem.write("facts/weather.md", "It is Sunny today")
    results = mem.search("facts", "sunny")
    assert len(results) == 1
    assert results[0][0] == "weather.md"


def test_search_no_match() -> None:
    import awfulclaw.memory as mem

    mem.write("facts/note.md", "nothing here")
    assert mem.search("facts", "xyzzy") == []


def test_root_created_on_first_run() -> None:
    import awfulclaw.memory as mem

    mem._ensure_root()  # pyright: ignore[reportPrivateUsage]
    assert Path("memory").is_dir()


def test_search_all_finds_across_subdirs() -> None:
    import awfulclaw.memory as mem

    mem.write("notes/note.md", "I love Python")
    mem.write("tips/tip.md", "We talked about Python yesterday")
    results = mem.search_all("python", subdirs=["notes", "tips"])
    paths = [r[0] for r in results]
    assert "notes/note.md" in paths
    assert "tips/tip.md" in paths


def test_search_all_returns_empty_when_no_matches() -> None:
    import awfulclaw.memory as mem

    mem.write("facts/note.md", "nothing here")
    assert mem.search_all("xyzzy") == []


def test_path_traversal_blocked() -> None:
    import awfulclaw.memory as mem

    with pytest.raises(ValueError, match="escapes memory root"):
        mem.write("../../etc/evil.txt", "bad")

    with pytest.raises(ValueError, match="escapes memory root"):
        mem.read("../../etc/passwd")


def test_write_atomic_result() -> None:
    from pathlib import Path

    import awfulclaw.memory as mem

    mem.write("facts/atomic.md", "atomic content")
    assert Path("memory/facts/atomic.md").exists()
    assert Path("memory/facts/atomic.md").read_text() == "atomic content"
    assert not Path("memory/facts/atomic.tmp").exists()


def test_search_all_respects_subdirs_filter() -> None:
    import awfulclaw.memory as mem

    mem.write("facts/note.md", "match this")
    mem.write("tasks/work.md", "match this too")
    results = mem.search_all("match", subdirs=["facts"])
    paths = [r[0] for r in results]
    assert "facts/note.md" in paths
    assert all(not p.startswith("tasks/") for p in paths)
