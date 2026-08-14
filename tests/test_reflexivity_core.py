from __future__ import annotations

from datetime import datetime, timezone

from crypto_market_structure.reflexivity import (
    FUNDING_SEMANTICS,
    MetricObservation,
    ReflexivityState,
    assess_reflexivity,
    assessment_to_row,
    observation_from_row,
)


def _base_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
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
    row.update(overrides)
    return row


def test_funding_semantics_are_explicit_and_not_called_backwardation() -> None:
    assert FUNDING_SEMANTICS["positive"] == "positive funding means longs pay shorts"
    assert FUNDING_SEMANTICS["negative"] == "negative funding means shorts pay longs"
    assert "backwardation" not in FUNDING_SEMANTICS["research_use"]


def test_observation_keeps_event_receipt_source_units_and_missingness() -> None:
    observation = observation_from_row(
        {"symbol": "TESTUSDT", "scanned_at_utc": "2026-01-02T10:00:00Z"},
        observation_id="test-observation",
    )
    metric = observation.metric("short_account_pct")

    assert observation.event_time_basis == "snapshot_time"
    assert metric.status(as_of=observation.received_at) == "missing"
    assert metric.units == "percent of accounts"
    assert metric.provenance == "row missing:short_account_pct"
    assert observation.validation(as_of=observation.received_at)["missing"]


def test_primary_fixture_is_active_and_explains_account_count() -> None:
    observation = observation_from_row(_base_row(), observation_id="active")
    assessment = assess_reflexivity(observation, as_of=observation.received_at)

    assert assessment.state in {ReflexivityState.ACTIVE_REFLEXIVITY, ReflexivityState.ACCELERATING}
    assert assessment.market_trigger is True
    assert assessment.gates["short_crowding"] is True
    assert assessment.components["short_account_crowding_acceleration"].definition.find("not short dollar notional") >= 0
    assert any("account count" in line for line in assessment.explanation)


def test_short_rollover_and_level_drop_mark_exhaustion_not_a_normal_active_state() -> None:
    observation = observation_from_row(
        _base_row(
            short_account_pct=61.0,
            short_account_roc_1h_pp=-3.0,
            short_account_change_3p_pp=-4.0,
            short_account_change_4p_pp=-5.0,
            short_account_peak_drawdown_pp=-7.0,
            oi_delta_pct=-1.2,
            oi_acceleration_1h_pct=-0.8,
            oi_change_3p_pct=-3.5,
            oi_build_persistence=0,
            price_change_24h_pct=48.0,
            price_vs_anchored_vwap_30d_pct=52.0,
            hour_upper_wick_pct=60.0,
            hour_close_location_pct=42.0,
        ),
        observation_id="exhaustion",
    )
    assessment = assess_reflexivity(observation, as_of=observation.received_at)

    assert assessment.state == ReflexivityState.EXHAUSTION_RISK
    assert assessment.market_trigger is False
    assert "short-account ROC <= -4pp" in " ".join(assessment.invalidation)


def test_stale_metrics_are_not_promoted_to_structural_proof() -> None:
    observation = observation_from_row(_base_row(), observation_id="stale")
    as_of = datetime(2026, 1, 3, 12, 0, tzinfo=timezone.utc)
    assessment = assess_reflexivity(observation, as_of=as_of)

    assert observation.metric("short_account_pct").status(as_of=as_of) == "stale"
    assert assessment.data_quality_pct == 0.0
    assert assessment.state == ReflexivityState.DISCOVERY
    assert assessment.gates["holder_proof"] is True


def test_metric_with_missing_provenance_is_invalid_even_with_a_value() -> None:
    metric = MetricObservation(
        name="short_account_pct",
        value=70.0,
        event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        received_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        source="source",
        venue="venue",
        units="percent",
        provenance="",
    )

    assert metric.status(as_of=metric.received_at) == "invalid"


def test_structured_evidence_keeps_wallet_venue_and_flow_provenance() -> None:
    observation = observation_from_row(
        _base_row(
            provenance="fixture:observation",
            wallet_classifications=[
                {
                    "address": "0xwhale",
                    "category": "unidentified_whale",
                    "confidence": "medium",
                    "confidence_score": 72,
                    "pct_total_supply": 24.0,
                    "evidence_source": "label registry",
                }
            ],
            venue_observations=[
                {
                    "venue": "Bitget",
                    "market_type": "perpetual",
                    "available": True,
                    "volume_share_pct": 3.0,
                    "source": "venue snapshot",
                    "provenance": "fixture:venue:bitget",
                }
            ],
            supply_flows=[
                {
                    "target_exchange": "Binance",
                    "token_amount": 1000,
                    "notional_usd": 1000,
                    "sender_category": "treasury",
                    "sender_confidence": "high",
                    "transfer_to_float_pct": 0.2,
                    "source": "labelled transfer",
                    "provenance": "fixture:flow:binance",
                }
            ],
        ),
        observation_id="structured",
    )

    assert observation.ownership is not None
    assert observation.ownership.raw_top10_pct == 88.0
    assert observation.wallet_classifications[0].category == "unidentified_whale"
    assert observation.wallet_classifications[0].provenance == "fixture:observation:wallet_classifications[0]"
    assert observation.venue_observations[0].provenance == "fixture:venue:bitget"
    assert observation.supply_flows[0].target_exchange == "Binance"
    assert observation.metric("short_account_pct").status(as_of=observation.received_at) == "observed"


def test_funding_regime_reports_direction_without_market_label_shortcuts() -> None:
    positive = assess_reflexivity(
        observation_from_row(_base_row(funding_rate_pct=0.12), observation_id="positive-funding"),
    )
    negative = assess_reflexivity(
        observation_from_row(_base_row(funding_rate_pct=-0.12), observation_id="negative-funding"),
    )

    assert positive.funding_regime == "extreme_positive_longs_pay_shorts"
    assert negative.funding_regime == "extreme_negative_shorts_pay_longs"
    assert "backwardation" not in positive.funding_read


def test_fresh_large_cex_flow_vetoes_market_trigger_and_stays_explainable() -> None:
    observation = observation_from_row(
        _base_row(
            cex_deposit_24h_transfer_to_float_pct=1.2,
            cex_deposit_24h_notional_to_spot_volume_pct=30.0,
            cex_deposit_24h_notional_to_visible_liquidity_pct=80.0,
        ),
        observation_id="flow-veto",
    )
    assessment = assess_reflexivity(observation, as_of=observation.received_at)

    assert assessment.gates["supply_flow_clear"] is False
    assert assessment.market_trigger is False
    assert assessment.components["cex_supply_risk"].status == "observed"
    assert "CEX flow/float 1.20%" in assessment.components["cex_supply_risk"].evidence
    projection = assessment_to_row(assessment)
    assert projection["reflexivity_component_scores"]["cex_supply_risk"] is not None
    assert projection["reflexivity_component_status"]["cex_supply_risk"] == "observed"


def test_state_model_exposes_building_discovery_and_invalidated_paths() -> None:
    building = assess_reflexivity(
        observation_from_row(
            _base_row(
                short_account_roc_1h_pp=0.0,
                short_account_change_3p_pp=0.0,
                short_account_direction_persistence=0,
                hour_volume_roc_pct=80.0,
                hour_volume_multiple=2.0,
            ),
            observation_id="building",
        )
    )
    discovery = assess_reflexivity(
        observation_from_row(_base_row(short_account_pct=50.0), observation_id="discovery")
    )
    invalidated = assess_reflexivity(
        observation_from_row(
            _base_row(
                price_change_24h_pct=-10.0,
                price_vs_anchored_vwap_30d_pct=-8.0,
                broke_low_20d=True,
            ),
            observation_id="invalidated",
        )
    )

    assert building.state == ReflexivityState.BUILDING
    assert discovery.state == ReflexivityState.DISCOVERY
    assert invalidated.state == ReflexivityState.INVALIDATED
