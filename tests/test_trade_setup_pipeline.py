from __future__ import annotations

import pandas as pd

from trade_setup_pipeline import TradeBotConfig, estimate_quarter_kelly, select_trade_candidate


def test_select_trade_candidate_requires_terminal_timing_and_convex_gates() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "WEAKUSDT",
                "trade_bucket": "Convex Long",
                "terminal_edge_score": 80,
                "timing_score": 40,
                "trade_bucket_score": 90,
                "timing_state": "Dormant watch",
            },
            {
                "symbol": "PLAYUSDT",
                "trade_bucket": "Convex Long",
                "terminal_edge_score": 76,
                "timing_score": 66,
                "trade_bucket_score": 84,
                "timing_state": "Triggering",
            },
            {
                "symbol": "LATEUSDT",
                "trade_bucket": "Convex Long",
                "terminal_edge_score": 95,
                "timing_score": 90,
                "trade_bucket_score": 95,
                "timing_state": "Extended / fragile",
            },
        ]
    )
    row = select_trade_candidate(frame, TradeBotConfig())
    assert row is not None
    assert row["symbol"] == "PLAYUSDT"


def test_select_trade_candidate_returns_none_without_all_three_gates() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "WATCHUSDT",
                "trade_bucket": "Watch",
                "terminal_edge_score": 90,
                "timing_score": 90,
                "trade_bucket_score": 90,
                "timing_state": "Confirmed",
            }
        ]
    )
    assert select_trade_candidate(frame, TradeBotConfig()) is None


def test_quarter_kelly_uses_default_when_sample_is_thin() -> None:
    config = TradeBotConfig(default_equity_fraction=0.007, max_equity_fraction=0.02, min_kelly_sample=20)
    estimate = estimate_quarter_kelly([], config=config)
    assert estimate.sample_size == 0
    assert estimate.capped_fraction == 0.007
    assert estimate.source == "default_fraction_insufficient_outcomes"


def test_quarter_kelly_caps_position_fraction() -> None:
    records = []
    for idx in range(30):
        records.append(
            {
                "flag_id": f"win-{idx}",
                "max_upside_24h_pct": 60 if idx < 24 else 5,
                "max_drawdown_pct": -8,
            }
        )
    config = TradeBotConfig(max_equity_fraction=0.02, min_kelly_sample=20)
    estimate = estimate_quarter_kelly(records, config=config)
    assert estimate.sample_size == 30
    assert estimate.quarter_kelly_fraction > 0.02
    assert estimate.capped_fraction == 0.02
    assert estimate.source == "proof_archive_quarter_kelly"
