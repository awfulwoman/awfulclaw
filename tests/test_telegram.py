"""Tests for TelegramConnector.poll_new_messages."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from awfulclaw.telegram import TelegramConnector


def _make_connector() -> TelegramConnector:
    with (
        patch.dict(
            "os.environ",
            {"TELEGRAM_BOT_TOKEN": "fake-token", "TELEGRAM_CHAT_ID": "99"},
        )
    ):
        return TelegramConnector()


def _make_update(update_id: int, payload: dict) -> dict:
    return {"update_id": update_id, "message": {"chat": {"id": 99}, "date": 1700000000, "from": {"id": 1}, **payload}}


def _mock_response(updates: list[dict]) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {"result": updates}
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture()
def connector() -> TelegramConnector:
    return _make_connector()


def test_text_message_returned(connector: TelegramConnector) -> None:
    update = _make_update(1, {"text": "hello"})
    with patch("httpx.get", return_value=_mock_response([update])):
        msgs = connector.poll_new_messages(datetime.now(tz=timezone.utc))
    assert len(msgs) == 1
    assert msgs[0].body == "hello"


def test_location_message_returned(connector: TelegramConnector) -> None:
    update = _make_update(2, {"location": {"latitude": 51.5074, "longitude": -0.1278}})
    with patch("httpx.get", return_value=_mock_response([update])):
        msgs = connector.poll_new_messages(datetime.now(tz=timezone.utc))
    assert len(msgs) == 1
    assert msgs[0].body == "[Location: 51.5074, -0.1278]"


def test_unknown_message_type_skipped(connector: TelegramConnector) -> None:
    update = _make_update(3, {"sticker": {"file_id": "abc"}})
    with patch("httpx.get", return_value=_mock_response([update])):
        msgs = connector.poll_new_messages(datetime.now(tz=timezone.utc))
    assert msgs == []
