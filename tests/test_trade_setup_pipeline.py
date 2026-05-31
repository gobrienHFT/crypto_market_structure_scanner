from __future__ import annotations

import pandas as pd

from trade_setup_pipeline import TradeBotConfig, estimate_quarter_kelly, select_trade_candidate


def _thesis_fields(contract_suffix: str = "1") -> dict[str, object]:
    suffix = contract_suffix[-1] if contract_suffix else "1"
    return {
        "binance_perp_universe": True,
        "bitget_volume_share_pct": 1.0,
        "token_platform": "ethereum",
        "token_contract": f"0x{suffix * 40}",
        "holder_source": "Etherscan holder endpoint",
        "top10_holder_pct": 94.0,
        "top100_holder_pct": 99.0,
        "history_days": 180,
        "recent_max_pump_60d_pct": 6.0,
        "recent_pump_60d_days": 60,
        "no_large_pump_60d_flag": True,
        "low_float_score": 82.0,
        "float_trap_score": 78.0,
        "fdv_to_market_cap": 8.0,
        "short_account_pct": 63.0,
        "short_account_build_score": 52.0,
        "pre_pump_precision_score": 76.0,
    }


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
                **_thesis_fields("1"),
            },
            {
                "symbol": "PLAYUSDT",
                "trade_bucket": "Convex Long",
                "terminal_edge_score": 76,
                "timing_score": 66,
                "trade_bucket_score": 84,
                "timing_state": "Triggering",
                **_thesis_fields("2"),
            },
            {
                "symbol": "LATEUSDT",
                "trade_bucket": "Convex Long",
                "terminal_edge_score": 95,
                "timing_score": 90,
                "trade_bucket_score": 95,
                "timing_state": "Extended / fragile",
                **_thesis_fields("3"),
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


def test_select_trade_candidate_rejects_ungated_convex_long_rows() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "UNGATEDUSDT",
                "trade_bucket": "Convex Long",
                "terminal_edge_score": 90,
                "timing_score": 90,
                "trade_bucket_score": 90,
                "timing_state": "Confirmed",
                "thesis_gate": True,
            }
        ]
    )

    assert select_trade_candidate(frame, TradeBotConfig()) is None


def test_select_trade_candidate_requires_core_squeeze_fuel_gate() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "SHORTONLYUSDT",
                "trade_bucket": "Convex Long",
                "terminal_edge_score": 90,
                "timing_score": 90,
                "trade_bucket_score": 90,
                "timing_state": "Confirmed",
                **{
                    **_thesis_fields("4"),
                    "short_account_pct": 72.0,
                    "short_account_build_score": 0.0,
                    "early_pump_short_squeeze_score": 95.0,
                },
            },
            {
                "symbol": "FUELUSDT",
                "trade_bucket": "Convex Long",
                "terminal_edge_score": 82,
                "timing_score": 82,
                "trade_bucket_score": 82,
                "timing_state": "Confirmed",
                **_thesis_fields("5"),
            },
        ]
    )

    row = select_trade_candidate(frame, TradeBotConfig())

    assert row is not None
    assert row["symbol"] == "FUELUSDT"


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
