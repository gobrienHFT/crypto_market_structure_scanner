from __future__ import annotations

from datetime import datetime, timezone

import pytest

from crypto_market_structure.event_study import (
    EventStudyDefinition,
    build_events,
    evaluate_event,
    build_token_history_baseline_events,
    build_unconditional_baseline_events,
    run_event_study,
)
from crypto_market_structure.reflexivity import SIGNAL_VERSION, assess_reflexivity, observation_from_row


def _row(symbol: str, timestamp: str, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "symbol": symbol,
        "event_time_utc": timestamp,
        "received_at_utc": timestamp,
        "source": "fixture",
        "venue": "Binance Futures",
        "binance_venue_presence": True,
        "bitget_volume_share_pct": 3.0,
        "tradable_float_pct": 20.0,
        "top10_holder_pct": 88.0,
        "top100_holder_pct": 98.0,
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
        "hour_close_location_pct": 75.0,
        "hour_upper_wick_pct": 10.0,
        "recent_max_pump_60d_pct": 30.0,
        "prior_observations_24h": 2,
    }
    row.update(overrides)
    return row


def test_events_freeze_current_evidence_and_dedupe_same_symbol() -> None:
    rows = [
        _row("XUSDT", "2026-01-01T10:00:00Z"),
        _row("XUSDT", "2026-01-01T18:00:00Z", short_account_pct=75.0),
    ]
    observations = [observation_from_row(row, observation_id=f"obs-{index}") for index, row in enumerate(rows)]
    assessments = [assess_reflexivity(observation, as_of=observation.received_at) for observation in observations]
    definition = EventStudyDefinition(signal_version=SIGNAL_VERSION, dedupe_hours=24)
    events = build_events(observations, assessments, definition)

    assert len(events) == 1
    assert events[0].event_time.isoformat() == "2026-01-01T10:00:00+00:00"
    assert events[0].evidence_snapshot["short_account_pct"] == 68.0
    assert "return_1h_pct" not in events[0].evidence_snapshot


def test_event_outcomes_report_mfe_mae_and_missing_long_horizon() -> None:
    observation = observation_from_row(_row("XUSDT", "2026-01-01T10:00:00Z"), observation_id="obs")
    assessment = assess_reflexivity(observation, as_of=observation.received_at)
    definition = EventStudyDefinition(signal_version=SIGNAL_VERSION, horizons_hours=(1, 4, 24))
    event = build_events([observation], [assessment], definition)[0]
    bars = [
        {"event_time": "2026-01-01T10:00:00Z", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
        {"event_time": "2026-01-01T11:00:00Z", "open": 1.0, "high": 1.2, "low": 0.95, "close": 1.1},
        {"event_time": "2026-01-01T14:00:00Z", "open": 1.1, "high": 1.4, "low": 1.05, "close": 1.3},
    ]
    outcome = evaluate_event(event, bars, definition)

    assert outcome["return_1h_pct"] == pytest.approx(10.0)
    assert outcome["mfe_1h_pct"] == pytest.approx(20.0)
    assert outcome["mae_1h_pct"] == pytest.approx(-5.0)
    assert outcome["return_4h_pct"] == pytest.approx(30.0)
    assert outcome["return_24h_pct"] is None
    assert outcome["invalidation_1h_hit"] is False


def test_event_study_reports_coverage_and_chronological_holdout() -> None:
    rows = [
        _row("XUSDT", "2026-01-01T10:00:00Z"),
        _row("YUSDT", "2026-01-05T10:00:00Z"),
    ]
    observations = [observation_from_row(row, observation_id=f"obs-{index}") for index, row in enumerate(rows)]
    assessments = [assess_reflexivity(observation, as_of=observation.received_at) for observation in observations]
    definition = EventStudyDefinition(
        signal_version=SIGNAL_VERSION,
        horizons_hours=(1,),
        holdout_start=datetime(2026, 1, 4, tzinfo=timezone.utc),
        bootstrap_samples=50,
    )
    events = build_events(observations, assessments, definition)
    report = run_event_study(
        events,
        {
            "XUSDT": [
                {"event_time": "2026-01-01T10:00:00Z", "close": 1.0, "high": 1.0, "low": 1.0},
                {"event_time": "2026-01-01T11:00:00Z", "close": 1.1, "high": 1.2, "low": 0.9},
            ],
            "YUSDT": [
                {"event_time": "2026-01-05T10:00:00Z", "close": 2.0, "high": 2.0, "low": 2.0}
            ],
        },
        definition,
    )

    assert report["event_count"] == 2
    assert report["development_summary"]["event_count"] == 1
    assert report["holdout_summary"]["event_count"] == 1
    assert report["summary"]["horizons"]["1"]["coverage_pct"] == 50.0


def test_event_study_tracks_profit_thresholds_short_unwind_and_benchmark_excess() -> None:
    observation = observation_from_row(_row("XUSDT", "2026-01-01T10:00:00Z"), observation_id="fuel-event")
    assessment = assess_reflexivity(observation, as_of=observation.received_at)
    definition = EventStudyDefinition(
        signal_version=SIGNAL_VERSION,
        horizons_hours=(1, 4),
        threshold_return_pct=20.0,
        profit_thresholds_pct=(10.0, 25.0, 50.0),
        short_unwind_level_pct=65.0,
        bootstrap_samples=25,
        bootstrap_method="block",
        bootstrap_block_size=2,
    )
    event = build_events([observation], [assessment], definition)[0]
    price_path = [
        {"event_time": "2026-01-01T10:00:00Z", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
        {"event_time": "2026-01-01T11:00:00Z", "open": 1.0, "high": 1.12, "low": 0.98, "close": 1.10},
        {"event_time": "2026-01-01T12:00:00Z", "open": 1.10, "high": 1.25, "low": 1.05, "close": 1.20},
        {"event_time": "2026-01-01T14:00:00Z", "open": 1.20, "high": 1.55, "low": 1.10, "close": 1.30},
    ]
    fuel_path = [
        {"event_time": "2026-01-01T10:00:00Z", "short_account_pct": 68.0, "short_account_roc_1h_pp": 1.2},
        {"event_time": "2026-01-01T12:00:00Z", "short_account_pct": 64.0, "short_account_roc_1h_pp": -3.0},
    ]
    benchmark_path = [
        {"event_time": "2026-01-01T10:00:00Z", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
        {"event_time": "2026-01-01T11:00:00Z", "open": 100.0, "high": 101.0, "low": 99.0, "close": 101.0},
        {"event_time": "2026-01-01T14:00:00Z", "open": 101.0, "high": 102.0, "low": 100.0, "close": 102.0},
    ]

    outcome = evaluate_event(event, price_path, definition, fuel_bars=fuel_path)
    report = run_event_study(
        [event],
        {"XUSDT": price_path},
        definition,
        fuel_paths={"XUSDT": fuel_path},
        benchmark_paths={"BTCUSDT": benchmark_path},
        benchmark_symbol="BTCUSDT",
    )

    assert outcome["time_to_plus_10_minutes"] == 60.0
    assert outcome["time_to_plus_25_minutes"] == 120.0
    assert outcome["time_to_plus_50_minutes"] == 240.0
    assert outcome["time_to_short_unwind_minutes"] == 120.0
    assert outcome["peak_return_before_short_unwind_pct"] == pytest.approx(25.0)
    assert outcome["fuel_observation_count"] == 2
    assert outcome["fuel_coverage_status"] == "observed"
    assert report["event_study_version"] == "event-study-v1.1"
    assert report["benchmark_symbol"] == "BTCUSDT"
    assert report["summary"]["horizons"]["1"]["median_excess_return_pct"] == pytest.approx(9.0)
    assert report["summary"]["horizons"]["1"]["bootstrap_method"] == "block"
    assert report["summary"]["time_to_short_unwind_median_minutes"] == 120.0
    assert report["summary"]["fuel_coverage_pct"] == 100.0


def test_unconditional_and_token_history_baselines_are_explicitly_separate() -> None:
    active_row = _row("XUSDT", "2026-01-02T10:00:00Z")
    historical_row = _row(
        "XUSDT",
        "2026-01-01T10:00:00Z",
        short_account_pct=45.0,
        short_account_roc_1h_pp=-0.5,
        short_account_change_3p_pp=-1.0,
        short_account_change_4p_pp=-1.2,
        short_account_direction_persistence=0,
        quote_volume_24h_vs_prior_30d_avg_ratio=0.8,
        hour_volume_roc_1h_pct=-10.0,
        hour_volume_multiple=0.8,
        oi_delta_pct=-0.3,
        oi_acceleration_1h_pct=-0.1,
        oi_change_3p_pct=-0.5,
        oi_build_persistence=0,
        funding_rate_pct=-0.01,
        price_change_24h_pct=-1.0,
        hour_return_pct=-0.2,
        price_vs_anchored_vwap_30d_pct=-1.0,
        broke_high_5d=False,
        broke_high_20d=False,
    )
    observations = [
        observation_from_row(active_row, observation_id="active"),
        observation_from_row(historical_row, observation_id="historical"),
    ]
    assessments = [assess_reflexivity(item, as_of=item.received_at) for item in observations]
    definition = EventStudyDefinition(signal_version=SIGNAL_VERSION)

    unconditional = build_unconditional_baseline_events(observations, assessments, definition)
    token_history = build_token_history_baseline_events(observations, assessments, definition)

    assert len(unconditional) == 2
    assert {event.state for event in unconditional} == {"UNCONDITIONAL_UNIVERSE"}
    assert len(token_history) == 1
    assert token_history[0].symbol == "XUSDT"
    assert token_history[0].state == "TOKEN_HISTORICAL_BASELINE"
