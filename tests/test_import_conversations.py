"""Tests for scripts/import_conversations.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import import_conversations  # noqa: E402

SAMPLE_MD = """\
## user

Hello, how are you?

## assistant

I'm doing well, thanks for asking!

## user

What's the weather like today?

## assistant

I don't have real-time weather data, but I can help with other things.
"""

SAMPLE_MD_MIXED_CASE = """\
## User

Hi there.

## Assistant

Hello! How can I help?
"""

SAMPLE_MD_EMPTY_TURNS = """\
## user

First message.

## assistant

## user

Second message.
"""


def test_parse_file_basic(tmp_path: Path) -> None:
    """Parses a standard markdown file into turns."""
    p = tmp_path / "2024-01-15.md"
    p.write_text(SAMPLE_MD)

    turns = import_conversations.parse_file(p)
    assert len(turns) == 4

    assert turns[0][0] == "user"
    assert turns[0][1] == "Hello, how are you?"
    assert turns[0][2].startswith("2024-01-15")

    assert turns[1][0] == "assistant"
    assert turns[1][1] == "I'm doing well, thanks for asking!"

    assert turns[2][0] == "user"
    assert turns[3][0] == "assistant"


def test_parse_file_timestamps_increment(tmp_path: Path) -> None:
    """Each turn gets a distinct timestamp, incrementing by one second."""
    p = tmp_path / "2024-03-01.md"
    p.write_text(SAMPLE_MD)

    turns = import_conversations.parse_file(p)
    timestamps = [t[2] for t in turns]
    assert len(set(timestamps)) == len(timestamps), "timestamps must be unique"
    # All on the same date
    for ts in timestamps:
        assert ts.startswith("2024-03-01")


def test_parse_file_mixed_case(tmp_path: Path) -> None:
    """Role headers are parsed case-insensitively."""
    p = tmp_path / "2024-06-10.md"
    p.write_text(SAMPLE_MD_MIXED_CASE)

    turns = import_conversations.parse_file(p)
    assert len(turns) == 2
    assert turns[0][0] == "user"
    assert turns[1][0] == "assistant"


def test_parse_file_skips_empty_turns(tmp_path: Path) -> None:
    """Turns with no content after stripping are skipped."""
    p = tmp_path / "2024-07-04.md"
    p.write_text(SAMPLE_MD_EMPTY_TURNS)

    turns = import_conversations.parse_file(p)
    assert len(turns) == 2
    assert turns[0][1] == "First message."
    assert turns[1][1] == "Second message."


def test_parse_file_bad_name(tmp_path: Path) -> None:
    """Non-date filename raises ValueError."""
    p = tmp_path / "notes.md"
    p.write_text("## user\n\nHello.")
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        import_conversations.parse_file(p)


@pytest.mark.asyncio
async def test_run_imports_turns(tmp_path: Path) -> None:
    """Full run inserts turns from all markdown files into DB."""
    conv_dir = tmp_path / "conversations"
    conv_dir.mkdir()
    (conv_dir / "2024-01-15.md").write_text(SAMPLE_MD)
    (conv_dir / "2024-01-16.md").write_text(SAMPLE_MD_MIXED_CASE)

    db = tmp_path / "test.db"
    count = await import_conversations.run(conv_dir, db_path=db)
    assert count == 6  # 4 turns + 2 turns

    from agent.store import Store

    store = await Store.connect(db)
    try:
        turns = await store.recent_turns("legacy", 100)
        assert len(turns) == 6
        roles = [t.role for t in turns]
        assert roles.count("user") == 3
        assert roles.count("assistant") == 3
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_run_empty_dir(tmp_path: Path) -> None:
    """Empty directory returns 0 imported turns."""
    conv_dir = tmp_path / "conversations"
    conv_dir.mkdir()
    db = tmp_path / "test.db"
    count = await import_conversations.run(conv_dir, db_path=db)
    assert count == 0


@pytest.mark.asyncio
async def test_run_channel_set(tmp_path: Path) -> None:
    """Imported turns use the specified channel."""
    conv_dir = tmp_path / "conversations"
    conv_dir.mkdir()
    (conv_dir / "2024-02-01.md").write_text(SAMPLE_MD_MIXED_CASE)

    db = tmp_path / "test.db"
    await import_conversations.run(conv_dir, db_path=db, channel="telegram")

    from agent.store import Store

    store = await Store.connect(db)
    try:
        turns = await store.recent_turns("telegram", 10)
        assert len(turns) == 2
        assert all(t.channel == "telegram" for t in turns)
    finally:
        await store.close()
