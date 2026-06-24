"""Tests for competition phase resolution."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.engine.config import resolve_phase

BST = ZoneInfo("Europe/London")


def test_resolve_phase_after_competition_holds_finals() -> None:
    phases = {
        "round1": {
            "start": "2026-06-21T22:00:00+01:00",
            "end": "2026-06-22T22:00:00+01:00",
        },
        "finals": {
            "start": "2026-06-24T22:00:00+01:00",
            "end": "2026-06-26T22:00:00+01:00",
        },
    }
    after = datetime(2026, 6, 27, 12, 0, tzinfo=BST)

    with patch("src.engine.config.load_yaml", return_value={"phases": phases}), patch(
        "src.engine.config.datetime",
    ) as mock_dt:
        mock_dt.now.return_value = after
        mock_dt.fromisoformat = datetime.fromisoformat
        assert resolve_phase(auto=True) == "finals"


def test_cycle_minutes_round1_from_config() -> None:
    from src.engine.config import QuantAIConfig

    config = QuantAIConfig.load(phase="round1", auto_phase=False)
    assert config.cycle_minutes() == 8
