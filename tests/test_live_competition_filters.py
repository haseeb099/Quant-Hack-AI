"""Tests for live competition filter merge behaviour."""

from __future__ import annotations

from src.engine.config import QuantAIConfig
from src.engine.trading_engine import TradingEngine


def test_live_filters_block_union_with_phase_rules(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("SENTIMENT_AGENT_ENABLED", "false")

    filters_path = tmp_path / "live_competition_filters.json"
    filters_path.write_text(
        '{"blocked_symbols": ["BTC/USD"], "max_new_entries_per_cycle": 4}',
        encoding="utf-8",
    )

    config = QuantAIConfig.load(phase="round2", auto_phase=False)
    engine = TradingEngine(config=config, simulation=True)

    with monkeypatch.context() as m:
        m.setattr(
            TradingEngine,
            "_load_live_competition_filters",
            staticmethod(lambda: {"blocked_symbols": ["BTC/USD"], "max_new_entries_per_cycle": 4}),
        )
        live = engine._load_live_competition_filters()
        phase_blocked = set(config.phase_rules.get("blocked_symbols", []))
        merged = set(live.get("blocked_symbols", [])) | phase_blocked
        assert "BTC/USD" in merged
        assert "XRP/USD" in merged
        assert "ETH/USD" not in merged

        max_new = int(live.get("max_new_entries_per_cycle") or config.phase_rules.get("max_new_entries_per_cycle", 99))
        assert max_new == 4


def test_round2_phase_defaults_unblock_crypto() -> None:
    config = QuantAIConfig.load(phase="round2", auto_phase=False)
    blocked = set(config.phase_rules.get("blocked_symbols", []))
    assert "BTC/USD" not in blocked
    assert config.phase_rules.get("session_symbol_filter") is False
    assert config.cycle_minutes() == 8


def test_round3_crypto_only_if_dd_normal() -> None:
    config = QuantAIConfig.load(phase="round3", auto_phase=False)
    assert config.phase_rules.get("crypto_only_if_dd_normal") is True
