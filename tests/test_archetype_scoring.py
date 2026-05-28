from __future__ import annotations

import pandas as pd

from archetype_scoring import apply_archetype_model


def test_lab_style_archetype_prioritizes_controlled_float_cex_inventory() -> None:
    scored = apply_archetype_model(
        pd.DataFrame(
            [
                {
                    "symbol": "LABUSDT",
                    "terminal_control_plane_score": 84,
                    "terminal_distribution_pressure_score": 82,
                    "cex_deposit_flow_score": 88,
                    "cex_deposit_inventory_stress_score": 90,
                    "venue_support_score": 70,
                    "top10_holder_pct": 91,
                    "cex_deposit_flow_flag": True,
                }
            ]
        )
    )
    row = scored.iloc[0]

    assert row["archetype_lab_score"] >= 80
    assert row["archetype_best_match"] == "LAB-style venue-inventory stress"
    assert row["archetype_reference_symbol"] == "LABUSDT"
    assert row["archetype_reference_date"] == "2026-05-11"
    assert "controlled float" in row["archetype_match_note"]
    assert "LABUSDT 2026-05-11" in row["archetype_match_note"]


def test_rave_style_archetype_includes_historical_anchor_date() -> None:
    row = apply_archetype_model(
        pd.DataFrame(
            [
                {
                    "symbol": "RAVEUSDT",
                    "top10_holder_pct": 94,
                    "top100_holder_pct": 99.8,
                    "terminal_hidden_float_reflexivity_score": 88,
                    "terminal_control_plane_score": 84,
                    "ath_multiple": 55,
                    "fdv_to_market_cap": 11,
                    "terminal_distribution_pressure_score": 70,
                }
            ]
        )
    ).iloc[0]

    assert row["archetype_rave_score"] >= 70
    assert row["archetype_best_match"] == "RAVE-style cap-table reflexivity"
    assert row["archetype_reference_symbol"] == "RAVEUSDT"
    assert row["archetype_reference_date"] == "2026-04-18"
    assert "RAVEUSDT 2026-04-18" in row["archetype_match_note"]


def test_siren_style_archetype_scores_short_fuse_pre_ignition() -> None:
    scored = apply_archetype_model(
        pd.DataFrame(
            [
                {
                    "symbol": "SIRENUSDT",
                    "terminal_pre_ignition_quality_score": 86,
                    "terminal_short_pressure_score": 78,
                    "short_account_pct": 63,
                    "oi_delta_pct": 2.8,
                    "low_volatility_coil_score": 88,
                    "pre_pump_compression_score": 84,
                    "terminal_control_plane_score": 62,
                    "hour_return_pct": 1.2,
                    "day_return_pct": 6.5,
                    "terminal_risk_score": 8,
                }
            ]
        )
    )
    row = scored.iloc[0]

    assert row["archetype_siren_score"] >= 70
    assert row["archetype_best_match"] == "SIREN-style short-fuse compression"


def test_river_style_archetype_scores_runway_breakout() -> None:
    scored = apply_archetype_model(
        pd.DataFrame(
            [
                {
                    "symbol": "RIVERUSDT",
                    "terminal_runway_score": 88,
                    "range_breakout_score": 82,
                    "venue_support_score": 76,
                    "terminal_ignition_score": 66,
                    "hour_close_location_pct": 78,
                    "hour_volume_multiple": 2.2,
                    "ath_multiple": 22,
                    "terminal_edge_score": 70,
                    "terminal_risk_score": 12,
                }
            ]
        )
    )
    row = scored.iloc[0]

    assert row["archetype_river_score"] >= 70
    assert row["archetype_best_match"] == "RIVER-style runway breakout"


def test_sto_style_archetype_scores_target_venue_short_squeeze() -> None:
    scored = apply_archetype_model(
        pd.DataFrame(
            [
                {
                    "symbol": "STOUSDT",
                    "binance_bitget_gate_share_score": 82,
                    "target_cex_flow_score": 78,
                    "terminal_control_plane_score": 80,
                    "terminal_short_pressure_score": 82,
                    "short_account_pct": 66,
                    "terminal_pre_ignition_quality_score": 78,
                    "cex_deposit_flow_score": 64,
                    "cex_deposit_inventory_stress_score": 58,
                    "top10_holder_pct": 88,
                    "hour_return_pct": 1.0,
                    "day_return_pct": 4.0,
                    "terminal_risk_score": 5,
                }
            ]
        )
    )
    row = scored.iloc[0]

    assert row["archetype_sto_score"] >= 70
    assert row["archetype_best_match"] == "STO-style target-venue squeeze"
    assert "target-venue support" in row["archetype_match_note"]


def test_low_signal_rows_keep_neutral_archetype_label() -> None:
    row = apply_archetype_model(pd.DataFrame([{"symbol": "QUIETUSDT"}])).iloc[0]

    assert row["archetype_match_score"] < 35
    assert row["archetype_best_match"] == "No strong case-study analogue"
    assert row["archetype_reference_symbol"] == ""
    assert row["archetype_reference_date"] == ""
