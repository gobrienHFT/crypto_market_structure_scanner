import pandas as pd

from terminal_engine import apply_terminal_model
from timing_engine import apply_timing_model, build_timing_card


def test_timing_model_identifies_triggering_setup() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "PLAYUSDT",
                "terminal_edge_score": 72.0,
                "short_account_pct": 61.0,
                "oi_delta_pct": 3.2,
                "hour_return_pct": 2.4,
                "day_return_pct": 8.0,
                "hour_volume_multiple": 2.1,
                "daily_quote_volume_multiple": 1.7,
                "hour_trade_count_multiple": 1.8,
                "hour_close_location_pct": 78.0,
                "hour_upper_wick_pct": 8.0,
                "distance_to_high_5d_pct": 1.5,
                "distance_to_high_20d_pct": 4.0,
                "ask_depth_to_24h_volume_pct": 0.08,
            }
        ]
    )

    row = apply_timing_model(frame).iloc[0]

    assert row["timing_score"] > 60
    assert row["timing_state"] in {"Triggering", "Confirmed"}
    assert "OI expanding" in row["timing_observed_trigger"]
    assert "short accounts 61.0%" in row["timing_observed_trigger"]


def test_timing_model_penalizes_late_wicky_move() -> None:
    row = apply_timing_model(
        pd.DataFrame(
            [
                {
                    "symbol": "LATEUSDT",
                    "terminal_edge_score": 82.0,
                    "short_account_pct": 45.0,
                    "oi_delta_pct": -1.5,
                    "hour_return_pct": 26.0,
                    "day_return_pct": 120.0,
                    "hour_volume_multiple": 7.0,
                    "hour_upper_wick_pct": 48.0,
                    "hour_close_location_pct": 28.0,
                    "convexity_late_penalty": 85.0,
                }
            ]
        )
    ).iloc[0]

    assert row["timing_too_late_score"] > 70
    assert row["timing_state"] == "Extended / fragile"
    assert row["timing_score"] < 55


def test_timing_card_uses_research_language() -> None:
    row = apply_timing_model(apply_terminal_model(pd.DataFrame([{"symbol": "RAVEUSDT", "short_account_pct": 55.0}]))).iloc[0]
    card = build_timing_card(row)

    assert "/RAVEUSDT" in card
    assert "Timing Score:" in card
    assert "Research constraint:" in card
    assert "buy" not in card.lower()
