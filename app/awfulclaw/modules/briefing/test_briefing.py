"""Tests for briefing module."""

from __future__ import annotations

from datetime import time
from unittest.mock import patch

from awfulclaw.modules.briefing._briefing import BriefingModule


def test_is_available_without_env_var() -> None:
    with patch("awfulclaw.modules.briefing._briefing.config.get_briefing_time", return_value=None):
        mod = BriefingModule()
        assert not mod.is_available()


def test_is_available_with_env_var() -> None:
    with patch(
        "awfulclaw.modules.briefing._briefing.config.get_briefing_time",
        return_value=time(8, 0),
    ):
        mod = BriefingModule()
        assert mod.is_available()


def test_check_and_fire_returns_prompt_at_correct_time() -> None:
    from datetime import datetime, timezone

    briefing_t = time(8, 0)
    now = datetime(2026, 3, 30, 8, 0, 5, tzinfo=timezone.utc)

    mod = BriefingModule()
    with patch(
        "awfulclaw.modules.briefing._briefing.config.get_briefing_time",
        return_value=briefing_t,
    ), patch("awfulclaw.modules.briefing._briefing.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = mod.check_and_fire(poll_interval=60)

    assert result is not None
    assert "briefing" in result.lower()


def test_check_and_fire_returns_none_if_already_fired_today() -> None:
    from datetime import date, datetime, timezone

    briefing_t = time(8, 0)
    now = datetime(2026, 3, 30, 8, 0, 5, tzinfo=timezone.utc)

    mod = BriefingModule()
    mod._last_briefing_date = date(2026, 3, 30)

    with patch(
        "awfulclaw.modules.briefing._briefing.config.get_briefing_time",
        return_value=briefing_t,
    ), patch("awfulclaw.modules.briefing._briefing.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = mod.check_and_fire(poll_interval=60)

    assert result is None


def test_check_and_fire_returns_none_outside_window() -> None:
    from datetime import datetime, timezone

    briefing_t = time(8, 0)
    now = datetime(2026, 3, 30, 14, 30, 0, tzinfo=timezone.utc)

    mod = BriefingModule()
    with patch(
        "awfulclaw.modules.briefing._briefing.config.get_briefing_time",
        return_value=briefing_t,
    ), patch("awfulclaw.modules.briefing._briefing.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = mod.check_and_fire(poll_interval=60)

    assert result is None


def test_check_and_fire_returns_none_when_not_configured() -> None:
    mod = BriefingModule()
    with patch(
        "awfulclaw.modules.briefing._briefing.config.get_briefing_time",
        return_value=None,
    ):
        result = mod.check_and_fire(poll_interval=60)

    assert result is None


def test_name() -> None:
    mod = BriefingModule()
    assert mod.name == "briefing"
