from __future__ import annotations

import pandas as pd
import pytest

from squeeze_radar import (
    attach_squeeze_history_features,
    oi_history_stats,
    score_squeeze_radar,
    select_squeeze_candidates,
)


def _rave_lab_candidate(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "symbol": "LABUSDT",
        "market_type": "COIN",
        "short_account_pct": 68.0,
        "short_account_roc_1h_pp": 1.20,
        "short_account_change_3p_pp": 2.10,
        "short_account_change_6p_pp": 2.80,
        "short_account_roc_smoothed_3p_pp": 0.80,
        "short_account_direction_persistence": 3,
        "short_account_peak_drawdown_pp": -0.20,
        "carry_funding_pct": 0.0300,
        "hour_volume_roc_1h_pct": 180.0,
        "hour_volume_multiple": 3.0,
        "quote_volume_24h_vs_prior_30d_avg_ratio": 4.0,
        "oi_delta_pct": 2.5,
        "oi_change_3p_pct": 4.0,
        "oi_change_6p_pct": 5.0,
        "oi_build_persistence": 3,
        "day_return_pct": 10.0,
        "hour_return_pct": 2.0,
        "price_vs_anchored_vwap_30d_pct": 12.0,
        "hour_close_location_pct": 78.0,
        "hour_upper_wick_pct": 10.0,
        "recent_max_pump_60d_pct": 30.0,
        "broke_high_5d": True,
        "broke_high_20d": True,
        "broke_low_20d": False,
        "top10_holder_pct": 88.0,
        "top100_holder_pct": 99.0,
        "adjusted_top_10_pct": 81.0,
        "controlled_float_squeeze_score": 80.0,
        "low_float_score": 75.0,
        "centralized_ownership_score": 80.0,
        "ravedao_archetype_score": 82.0,
        "rave_lab_setup_score": 85.0,
        "pre_pump_precision_score": 75.0,
        "bitget_volume_share_pct": 2.0,
        "target_cex_volume_share_pct": 6.0,
        "protocol_storage_score": 10.0,
        "cex_storage_supply_pct": 5.0,
        "holder_table_not_global_supply": False,
        "wrapped_representation_warning": False,
        "structural_evidence_level": "VERIFIED",
        "structural_evidence_age_days": 2.0,
        "structural_storage_checked": True,
        "crowd_top_position_divergence_pct": -8.0,
        "crowd_top_account_divergence_pct": -5.0,
        "taker_buy_sell_ratio": 1.08,
    }
    row.update(overrides)
    return row


def test_candidate_selector_is_bounded_excludes_tradfi_and_keeps_forced_symbol() -> None:
    ticker = pd.DataFrame(
        [
            {
                "symbol": f"C{index}USDT",
                "market_type": "COIN",
                "quoteVolume": 1_000_000 + index,
                "priceChangePercent": float(index),
                "highPrice": 1.10,
                "lowPrice": 1.00,
                "count": 1_000 + index,
            }
            for index in range(8)
        ]
        + [
            {
                "symbol": "MSFTUSDT",
                "market_type": "EQUITY",
                "quoteVolume": 1_000_000_000,
                "priceChangePercent": 20.0,
                "highPrice": 450.0,
                "lowPrice": 400.0,
                "count": 1_000_000,
            },
            {
                "symbol": "ZHIPUUSDT",
                "market_type": "HK_EQUITY",
                "quoteVolume": 900_000_000,
                "priceChangePercent": 18.0,
                "highPrice": 12.0,
                "lowPrice": 10.0,
                "count": 900_000,
            },
        ]
    )

    selected = select_squeeze_candidates(
        ticker,
        forced_symbols={"C0USDT"},
        max_symbols=4,
    )

    assert len(selected) == 4
    assert "C0USDT" in set(selected["symbol"])
    assert "MSFTUSDT" not in set(selected["symbol"])
    assert "ZHIPUUSDT" not in set(selected["symbol"])
    assert bool(selected.loc[selected["symbol"] == "C0USDT", "candidate_forced"].iloc[0])


def test_candidate_selector_prefers_live_short_account_probe_over_stale_seed() -> None:
    ticker = pd.DataFrame(
        [
            {
                "symbol": "LOWUSDT",
                "market_type": "COIN",
                "quoteVolume": 10_000_000,
                "priceChangePercent": 4.0,
                "highPrice": 1.10,
                "lowPrice": 1.00,
                "count": 10_000,
                "live_short_account_pct": 54.0,
            },
            {
                "symbol": "HIGHUSDT",
                "market_type": "COIN",
                "quoteVolume": 10_000_000,
                "priceChangePercent": 4.0,
                "highPrice": 1.10,
                "lowPrice": 1.00,
                "count": 10_000,
                "live_short_account_pct": 72.0,
            },
        ]
    )
    selected = select_squeeze_candidates(
        ticker,
        seed_frames=[pd.DataFrame([{"symbol": "LOWUSDT", "short_account_pct": 75.0}])],
        max_symbols=1,
    )

    assert selected.iloc[0]["symbol"] == "HIGHUSDT"
    assert float(selected.iloc[0]["candidate_short_account_pct"]) == 72.0


def test_primary_profile_identifies_rave_lab_style_reflexive_setup() -> None:
    scored = score_squeeze_radar(pd.DataFrame([_rave_lab_candidate()]), profile="Primary")
    row = scored.iloc[0]

    assert row["squeeze_stage"] == "REFLEXIVE"
    assert bool(row["squeeze_actionable"])
    assert bool(row["squeeze_high_conviction"])
    assert bool(row["squeeze_holder_gate"])
    assert bool(row["squeeze_venue_gate"])
    assert row["squeeze_evidence_tier"] == "FULL"
    assert float(row["squeeze_score"]) >= 60.0


def test_historical_max_short_build_cannot_replace_current_build() -> None:
    candidate = _rave_lab_candidate(
        short_account_roc_1h_pp=-0.20,
        short_account_roc_smoothed_3p_pp=-0.10,
        short_account_direction_persistence=0,
        short_account_change_max_pp=8.0,
        short_account_change_max_pct=20.0,
    )
    row = score_squeeze_radar(pd.DataFrame([candidate]), profile="Primary").iloc[0]

    assert not bool(row["squeeze_build_gate"])
    assert not bool(row["squeeze_actionable"])
    assert "shorts not building now" in row["squeeze_gate_failures"]


def test_late_heat_is_a_hard_veto_even_when_every_fuel_metric_is_strong() -> None:
    candidate = _rave_lab_candidate(
        day_return_pct=82.0,
        hour_return_pct=22.0,
        price_vs_anchored_vwap_30d_pct=95.0,
        hour_upper_wick_pct=68.0,
        hour_close_location_pct=31.0,
    )
    row = score_squeeze_radar(pd.DataFrame([candidate]), profile="Primary").iloc[0]

    assert row["squeeze_stage"] == "LATE"
    assert bool(row["squeeze_late_veto"])
    assert not bool(row["squeeze_actionable"])
    assert "late/exhausted" in row["squeeze_gate_failures"]


def test_holder_storage_false_positive_cannot_be_full_evidence() -> None:
    candidate = _rave_lab_candidate(protocol_storage_score=90.0)
    row = score_squeeze_radar(pd.DataFrame([candidate]), profile="Primary").iloc[0]

    assert not bool(row["squeeze_holder_gate"])
    assert row["squeeze_evidence_tier"] == "VENUE"
    assert not bool(row["squeeze_high_conviction"])


def test_structure_can_arm_before_volume_ignition_without_becoming_actionable() -> None:
    candidate = _rave_lab_candidate(
        hour_volume_roc_1h_pct=-20.0,
        hour_volume_multiple=0.8,
        quote_volume_24h_vs_prior_30d_avg_ratio=1.10,
    )
    row = score_squeeze_radar(pd.DataFrame([candidate]), profile="Primary").iloc[0]

    assert row["squeeze_stage"] == "ARMED"
    assert not bool(row["squeeze_volume_gate"])
    assert not bool(row["squeeze_actionable"])


def test_fuel_score_falls_when_current_short_share_is_far_below_its_recent_peak() -> None:
    near_peak = score_squeeze_radar(
        pd.DataFrame([_rave_lab_candidate(short_account_peak_drawdown_pp=-0.10)]),
        profile="Primary",
    ).iloc[0]
    depleted = score_squeeze_radar(
        pd.DataFrame([_rave_lab_candidate(short_account_peak_drawdown_pp=-5.00)]),
        profile="Primary",
    ).iloc[0]

    assert float(near_peak["squeeze_fuel_remaining_score"]) > float(
        depleted["squeeze_fuel_remaining_score"]
    )


def test_proxy_structure_can_rank_but_cannot_be_entry_ready() -> None:
    row = score_squeeze_radar(
        pd.DataFrame([_rave_lab_candidate(structural_evidence_level="PROXY")]),
        profile="Primary",
    ).iloc[0]

    assert row["squeeze_stage"] == "REFLEXIVE"
    assert bool(row["squeeze_market_trigger"])
    assert not bool(row["squeeze_structural_evidence_fresh"])
    assert not bool(row["squeeze_entry_ready"])
    assert not bool(row["squeeze_actionable"])
    assert row["squeeze_evidence_tier"] == "PROXY ONLY"
    assert "proxy-only" in row["squeeze_gate_failures"]


def test_stale_verified_structure_is_not_entry_ready() -> None:
    row = score_squeeze_radar(
        pd.DataFrame([_rave_lab_candidate(structural_evidence_age_days=31.0)]),
        profile="Primary",
    ).iloc[0]

    assert not bool(row["squeeze_structural_evidence_fresh"])
    assert not bool(row["squeeze_entry_ready"])
    assert row["squeeze_evidence_tier"] == "VERIFIED / STALE"


def test_verified_holder_measure_without_storage_controls_is_not_entry_ready() -> None:
    row = score_squeeze_radar(
        pd.DataFrame([_rave_lab_candidate(structural_storage_checked=False)]),
        profile="Primary",
    ).iloc[0]

    assert bool(row["squeeze_structural_evidence_fresh"])
    assert not bool(row["squeeze_holder_gate"])
    assert not bool(row["squeeze_entry_ready"])
    assert "storage/representation controls" in row["squeeze_gate_failures"]


def test_crowd_already_long_is_a_false_positive_veto_when_diagnostics_exist() -> None:
    row = score_squeeze_radar(
        pd.DataFrame(
            [
                _rave_lab_candidate(
                    crowd_top_position_divergence_pct=6.0,
                    crowd_top_account_divergence_pct=7.0,
                )
            ]
        ),
        profile="Primary",
    ).iloc[0]

    assert not bool(row["squeeze_crowd_fuel_gate"])
    assert not bool(row["squeeze_market_trigger"])
    assert not bool(row["squeeze_actionable"])
    assert "crowd/top-trader divergence unfavorable" in row["squeeze_gate_failures"]


def test_market_trigger_requires_both_holder_and_venue_proof() -> None:
    row = score_squeeze_radar(
        pd.DataFrame([_rave_lab_candidate(bitget_volume_share_pct=0.0)]),
        profile="Primary",
    ).iloc[0]

    assert bool(row["squeeze_market_trigger"])
    assert not bool(row["squeeze_structural_evidence_gate"])
    assert not bool(row["squeeze_entry_ready"])


def test_gate_venue_support_counts_as_venue_evidence() -> None:
    row = score_squeeze_radar(
        pd.DataFrame([_rave_lab_candidate(bitget_volume_share_pct=0.0, gate_volume_share_pct=1.5)]),
        profile="Primary",
    ).iloc[0]

    assert bool(row["squeeze_venue_gate"])
    assert bool(row["squeeze_entry_ready"])


def test_stale_market_snapshot_is_neutralized_until_refreshed() -> None:
    stale_timestamp = pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=91)
    row = score_squeeze_radar(
        pd.DataFrame([_rave_lab_candidate(scanned_at_utc=stale_timestamp.isoformat())]),
        profile="Primary",
    ).iloc[0]

    assert bool(row["squeeze_snapshot_stale"])
    assert row["squeeze_stage"] == "STALE"
    assert not bool(row["squeeze_market_trigger"])
    assert not bool(row["squeeze_entry_ready"])
    assert "refresh required" in row["squeeze_gate_failures"]


def test_oi_history_stats_measure_multi_hour_build_and_persistence() -> None:
    rows = [
        {"timestamp": 1_000 + index * 3_600_000, "sumOpenInterestValue": 100.0 + index}
        for index in range(7)
    ]

    stats = oi_history_stats(list(reversed(rows)))

    assert stats["oi_history_points"] == 7
    assert round(float(stats["oi_change_3p_pct"]), 4) == round((106.0 / 103.0 - 1.0) * 100.0, 4)
    assert round(float(stats["oi_change_6p_pct"]), 4) == 6.0
    assert stats["oi_build_persistence"] == 6
    assert float(stats["oi_peak_drawdown_pct"]) == 0.0
    expected_current_growth = (106.0 / 105.0 - 1.0) * 100.0
    expected_previous_growth = (105.0 / 104.0 - 1.0) * 100.0
    assert float(stats["oi_acceleration_1h_pct"]) == pytest.approx(
        expected_current_growth - expected_previous_growth
    )


def test_primary_profile_does_not_promote_one_noisy_short_print() -> None:
    candidate = _rave_lab_candidate(
        short_account_change_3p_pp=-0.60,
        short_account_change_6p_pp=-0.80,
        short_account_direction_persistence=1,
    )
    row = score_squeeze_radar(pd.DataFrame([candidate]), profile="Primary").iloc[0]

    assert not bool(row["squeeze_short_confirmation_gate"])
    assert not bool(row["squeeze_build_gate"])
    assert not bool(row["squeeze_actionable"])


def test_scan_history_labels_repeated_structure_without_mutating_current_values() -> None:
    current_time = pd.Timestamp("2026-08-12T12:00:00Z")
    current = pd.DataFrame(
        [
            {
                "symbol": "LABUSDT",
                "scanned_at_utc": current_time.isoformat(),
                "short_account_roc_1h_pp": 0.8,
                "oi_delta_pct": 1.2,
                "day_return_pct": 4.0,
            }
        ]
    )
    history = pd.DataFrame(
        [
            {
                "symbol": "LABUSDT",
                "scanned_at_utc": (current_time - pd.Timedelta(hours=hours)).isoformat(),
                "short_account_roc_1h_pp": 0.5,
                "oi_delta_pct": 0.8,
                "day_return_pct": 2.0,
                "squeeze_stage": "ARMED",
                "squeeze_score": 61.0,
                "squeeze_market_trigger": False,
                "squeeze_entry_ready": False,
            }
            for hours in (1, 3)
        ]
    )

    enriched = attach_squeeze_history_features(current, history)
    row = enriched.iloc[0]

    assert int(row["radar_prior_observations"]) == 2
    assert row["radar_confirmation_label"] == "REPEATED"
    assert float(row["radar_short_build_consistency_24h"]) == 100.0
    assert float(row["short_account_roc_1h_pp"]) == 0.8
