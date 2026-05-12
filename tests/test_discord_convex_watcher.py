import pandas as pd

import discord_convex_watcher as watcher


def test_terminal_timing_alert_source_requires_both_scores(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_WATCHER_MIN_TERMINAL_SCORE", "60")
    monkeypatch.setenv("DISCORD_WATCHER_MIN_TIMING_SCORE", "55")
    frame = pd.DataFrame(
        [
            {
                "symbol": "BOTHUSDT",
                "terminal_edge_score": 72,
                "timing_score": 64,
                "timing_state": "Triggering",
                "centralized_ownership_score": 80,
                "low_float_score": 75,
                "float_trap_score": 70,
                "short_dominance_score": 85,
                "short_account_build_score": 70,
                "short_liquidation_fuel_score": 65,
                "price_volume_ignition_score": 70,
                "convexity_preignition_score": 65,
                "convexity_runway_score": 80,
                "clean_convex_setup_score": 70,
                "short_account_pct": 62,
                "oi_delta_pct": 3.2,
                "hour_return_pct": 2.4,
                "hour_volume_multiple": 2.1,
                "hour_trade_count_multiple": 1.8,
                "hour_close_location_pct": 78,
                "distance_to_high_5d_pct": 1.5,
            },
            {
                "symbol": "TERMONLYUSDT",
                "terminal_edge_score": 81,
                "timing_score": 30,
                "timing_state": "Coiling",
                "centralized_ownership_score": 90,
                "low_float_score": 90,
                "float_trap_score": 90,
                "convexity_runway_score": 80,
                "short_account_pct": 35,
                "oi_delta_pct": 0.0,
                "hour_return_pct": 0.0,
            },
            {
                "symbol": "TIMEONLYUSDT",
                "terminal_edge_score": 42,
                "timing_score": 80,
                "timing_state": "Confirmed",
                "centralized_ownership_score": 5,
                "low_float_score": 5,
                "short_account_pct": 65,
                "oi_delta_pct": 4.0,
                "hour_return_pct": 2.0,
                "hour_volume_multiple": 3.0,
                "hour_trade_count_multiple": 2.0,
                "hour_close_location_pct": 80,
            },
            {
                "symbol": "LATEUSDT",
                "terminal_edge_score": 84,
                "timing_score": 78,
                "timing_state": "Extended / fragile",
                "centralized_ownership_score": 90,
                "low_float_score": 90,
                "float_trap_score": 90,
                "short_dominance_score": 80,
                "price_volume_ignition_score": 80,
                "short_account_pct": 65,
                "oi_delta_pct": 4.0,
                "hour_return_pct": 26.0,
                "day_return_pct": 120.0,
                "hour_volume_multiple": 7.0,
                "hour_upper_wick_pct": 48.0,
                "hour_close_location_pct": 28.0,
                "convexity_late_penalty": 85.0,
            },
        ]
    )

    selected = watcher._select_alert_candidates(frame, alert_source="terminal_timing", top_n=10)

    assert selected["symbol"].tolist() == ["BOTHUSDT"]
    assert float(selected.iloc[0]["watcher_alert_score"]) > 0


def test_timing_alert_source_excludes_fragile_states(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_WATCHER_MIN_TIMING_SCORE", "55")
    frame = pd.DataFrame(
        [
            {
                "symbol": "GOODUSDT",
                "terminal_edge_score": 42,
                "timing_score": 74,
                "timing_state": "Triggering",
                "short_account_pct": 65,
                "oi_delta_pct": 3.0,
                "hour_return_pct": 2.0,
                "hour_volume_multiple": 2.5,
                "hour_trade_count_multiple": 2.0,
                "hour_close_location_pct": 82,
            },
            {
                "symbol": "BADUSDT",
                "terminal_edge_score": 82,
                "timing_score": 76,
                "timing_state": "Extended / fragile",
                "short_account_pct": 65,
                "oi_delta_pct": -2.0,
                "hour_return_pct": 26.0,
                "day_return_pct": 120,
                "hour_volume_multiple": 7.0,
                "hour_upper_wick_pct": 48,
                "hour_close_location_pct": 28,
                "convexity_late_penalty": 90,
            },
        ]
    )

    selected = watcher._select_alert_candidates(frame, alert_source="timing", top_n=10)

    assert selected["symbol"].tolist() == ["GOODUSDT"]


def test_terminal_alert_source_sorts_by_terminal_score(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_WATCHER_MIN_TERMINAL_SCORE", "50")
    frame = pd.DataFrame(
        [
            {
                "symbol": "LOWUSDT",
                "terminal_edge_score": 58,
                "centralized_ownership_score": 65,
                "low_float_score": 60,
                "float_trap_score": 60,
                "short_dominance_score": 55,
            },
            {
                "symbol": "HIGHUSDT",
                "terminal_edge_score": 81,
                "centralized_ownership_score": 90,
                "low_float_score": 90,
                "float_trap_score": 90,
                "short_dominance_score": 80,
                "pre_pump_precision_flag": True,
            },
        ]
    )

    selected = watcher._select_alert_candidates(frame, alert_source="terminal", top_n=10)

    assert selected["symbol"].tolist() == ["HIGHUSDT", "LOWUSDT"]
