from __future__ import annotations

import pandas as pd

from archetype_scoring import apply_archetype_model
from early_pump_radar import apply_early_pump_radar
from terminal_engine import apply_terminal_model
from timing_engine import apply_timing_model


def _score(frame: pd.DataFrame) -> pd.DataFrame:
    return apply_early_pump_radar(apply_timing_model(apply_archetype_model(apply_terminal_model(frame))))


def test_early_pump_radar_prioritizes_target_flow_whales_and_shorts() -> None:
    scored = _score(
        pd.DataFrame(
            [
                {
                    "symbol": "PRIMEUSDT",
                    "cex_deposit_flow_score": 92,
                    "cex_deposit_flow_flag": True,
                    "cex_deposit_24h_count": 3,
                    "cex_deposit_24h_max_amount": 12_000_000,
                    "cex_deposit_24h_target_exchanges": "Binance, Bitget",
                    "cex_deposit_inventory_stress_score": 84,
                    "top10_holder_pct": 91,
                    "top100_holder_pct": 99,
                    "centralized_ownership_score": 86,
                    "low_float_score": 82,
                    "float_trap_score": 78,
                    "fdv_to_market_cap": 8,
                    "short_account_pct": 64,
                    "short_dominance_score": 80,
                    "short_account_build_score": 74,
                    "oi_delta_pct": 3.2,
                    "terminal_pre_ignition_quality_score": 78,
                    "dormant_short_fuse_score": 82,
                    "pre_pump_precision_score": 76,
                    "hour_return_pct": 1.6,
                    "day_return_pct": 6.0,
                    "hour_volume_multiple": 1.8,
                    "hour_trade_count_multiple": 1.5,
                    "hour_close_location_pct": 72,
                    "bitget_volume_share_pct": 2.4,
                }
            ]
        )
    )
    row = scored.iloc[0]

    assert row["early_pump_radar_score"] >= 75
    assert bool(row["early_pump_confirmed_target_flow"]) is True
    assert bool(row["early_pump_alert_flag"]) is True
    assert row["early_pump_state"] == "Prime early squeeze"
    assert "target CEX flow" in row["early_pump_primary_signal"]
    assert "absorbed" in row["early_pump_next_check"] or "OI expansion" in row["early_pump_next_check"]


def test_early_pump_radar_marks_late_heat_fragile() -> None:
    row = apply_early_pump_radar(
        pd.DataFrame(
            [
                {
                    "symbol": "LATEUSDT",
                    "cex_deposit_flow_score": 92,
                    "cex_deposit_flow_flag": True,
                    "cex_deposit_24h_count": 2,
                    "cex_deposit_24h_target_exchanges": "Gate",
                    "top100_holder_pct": 99,
                    "short_account_pct": 68,
                    "low_float_score": 90,
                    "timing_too_late_score": 88,
                    "day_return_pct": 140,
                    "hour_upper_wick_pct": 42,
                }
            ]
        )
    ).iloc[0]

    assert bool(row["early_pump_not_late_gate"]) is False
    assert row["early_pump_state"] == "Too late / fragile"
    assert bool(row["early_pump_alert_flag"]) is False


def test_early_pump_radar_handles_missing_target_exchange_text() -> None:
    row = apply_early_pump_radar(
        pd.DataFrame(
            [
                {
                    "symbol": "MISSINGUSDT",
                    "cex_deposit_flow_score": 0,
                    "cex_deposit_24h_target_exchanges": pd.NA,
                    "top100_holder_pct": 95,
                    "short_account_pct": 55,
                    "low_float_score": 72,
                }
            ]
        )
    ).iloc[0]

    assert row["early_pump_note"]
    assert "no confirmed target CEX" in row["early_pump_note"]
