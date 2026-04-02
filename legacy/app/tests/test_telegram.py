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
    return {"update_id": update_id, "message": {"chat": {"id": 99}, "date": 1700000000, "from": {"id": 99}, **payload}}  # noqa: E501


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


def test_photo_message_with_caption(connector: TelegramConnector) -> None:
    photo_payload = [
        {"file_id": "small", "file_size": 100},
        {"file_id": "large", "file_size": 5000},
    ]
    update = _make_update(4, {"photo": photo_payload, "caption": "look at this"})

    get_file_resp = MagicMock()
    get_file_resp.json.return_value = {"result": {"file_path": "photos/large.jpg"}}
    get_file_resp.raise_for_status = MagicMock()

    dl_resp = MagicMock()
    dl_resp.content = b"fake-image-bytes"
    dl_resp.raise_for_status = MagicMock()

    poll_resp = _mock_response([update])

    call_count = 0

    def _fake_get(url: str, **kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if "getUpdates" in url:
            return poll_resp
        if "getFile" in url:
            return get_file_resp
        return dl_resp

    with patch("httpx.get", side_effect=_fake_get):
        msgs = connector.poll_new_messages(datetime.now(tz=timezone.utc))

    assert len(msgs) == 1
    assert msgs[0].body == "look at this"
    assert msgs[0].image_data == b"fake-image-bytes"
    assert msgs[0].image_mime == "image/jpeg"


def test_photo_message_no_caption_uses_placeholder(connector: TelegramConnector) -> None:
    photo_payload = [{"file_id": "only", "file_size": 1000}]
    update = _make_update(5, {"photo": photo_payload})

    get_file_resp = MagicMock()
    get_file_resp.json.return_value = {"result": {"file_path": "photos/only.jpg"}}
    get_file_resp.raise_for_status = MagicMock()

    dl_resp = MagicMock()
    dl_resp.content = b"img"
    dl_resp.raise_for_status = MagicMock()

    poll_resp = _mock_response([update])

    def _fake_get(url: str, **kwargs: object) -> MagicMock:
        if "getUpdates" in url:
            return poll_resp
        if "getFile" in url:
            return get_file_resp
        return dl_resp

    with patch("httpx.get", side_effect=_fake_get):
        msgs = connector.poll_new_messages(datetime.now(tz=timezone.utc))

    assert len(msgs) == 1
    assert msgs[0].body == "[image]"


def test_rate_limit_drops_excess_messages(connector: TelegramConnector) -> None:
    from awfulclaw.telegram import _RATE_LIMIT_MAX

    updates = [_make_update(i, {"text": f"msg{i}"}) for i in range(_RATE_LIMIT_MAX + 3)]
    with patch("httpx.get", return_value=_mock_response(updates)):
        msgs = connector.poll_new_messages(datetime.now(tz=timezone.utc))
    assert len(msgs) == _RATE_LIMIT_MAX


def test_long_message_truncated(connector: TelegramConnector) -> None:
    from awfulclaw.telegram import _MAX_MESSAGE_LENGTH

    long_text = "x" * (_MAX_MESSAGE_LENGTH + 500)
    update = _make_update(1, {"text": long_text})
    with patch("httpx.get", return_value=_mock_response([update])):
        msgs = connector.poll_new_messages(datetime.now(tz=timezone.utc))
    assert len(msgs) == 1
    assert len(msgs[0].body) == _MAX_MESSAGE_LENGTH + len("\n[truncated]")
    assert msgs[0].body.endswith("[truncated]")
