from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from crypto_market_structure.reporting import project_reflexivity_assessments


def test_reporting_projection_is_ui_independent_and_preserves_canonical_evidence() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "TESTUSDT",
                "event_time_utc": "2026-01-02T10:00:00Z",
                "received_at_utc": "2026-01-02T10:01:00Z",
                "source": "fixture source",
                "venue": "Binance Futures; Bitget",
                "binance_venue_presence": True,
                "bitget_volume_share_pct": 3.0,
                "tradable_float_pct": 18.0,
                "top10_holder_pct": 88.0,
                "top100_holder_pct": 99.0,
                "adjusted_top10_pct": 80.0,
                "holder_evidence_level": "VERIFIED",
                "holder_storage_checked": True,
                "short_account_pct": 68.0,
                "short_account_roc_1h_pp": 1.2,
                "short_account_change_3p_pp": 2.1,
                "short_account_change_4p_pp": 2.6,
                "short_account_direction_persistence": 3,
                "short_account_peak_drawdown_pp": -0.2,
                "quote_volume_24h_vs_prior_30d_avg_ratio": 4.0,
                "hour_volume_roc_1h_pct": 180.0,
                "hour_volume_multiple": 3.0,
                "oi_delta_pct": 2.5,
                "oi_acceleration_1h_pct": 0.4,
                "oi_change_3p_pct": 4.0,
                "oi_build_persistence": 3,
                "funding_rate_pct": 0.03,
                "funding_interval_hours": 8,
                "last_price": 1.0,
                "price_change_24h_pct": 10.0,
                "hour_return_pct": 2.0,
                "price_vs_anchored_vwap_30d_pct": 12.0,
                "broke_high_5d": True,
                "broke_high_20d": True,
                "hour_close_location_pct": 78.0,
                "hour_upper_wick_pct": 10.0,
                "recent_max_pump_60d_pct": 30.0,
                "prior_observations_24h": 2,
            }
        ]
    )

    projected = project_reflexivity_assessments(
        frame,
        as_of=datetime(2026, 1, 2, 10, 2, tzinfo=timezone.utc),
    )

    assert projected.loc[0, "reflexivity_state"] in {"ACTIVE_REFLEXIVITY", "ACCELERATING"}
    assert projected.loc[0, "reflexivity_signal_version"] == "reflexivity-v1.1"
    assert projected.loc[0, "reflexivity_source"] == "fixture source"
    assert "short_account_crowding_acceleration" in projected.loc[0, "reflexivity_component_scores"]
