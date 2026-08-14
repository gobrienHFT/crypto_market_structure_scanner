from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pandas as pd
import pytest

from auto_short_uptrend_trader import (
    SymbolRules,
    build_risk_plan,
    config_from_args,
    parse_args,
    score_entry_candidates,
    stop_ratcheting_target,
    thesis_failure_reason,
)


def _config(**changes):
    config = config_from_args(parse_args(["--once"]))
    return replace(config, **changes)


def _candidate(symbol: str = "PLAYUSDT") -> dict[str, object]:
    return {
        "symbol": symbol,
        "market_type": "COIN",
        "binance_perp_universe": True,
        "bitget_volume_share_pct": 2.0,
        "token_platform": "ethereum",
        "token_contract": "0x" + "1" * 40,
        "holder_source": "Etherscan holder endpoint",
        "holder_count": 500,
        "top10_holder_pct": 85.0,
        "top100_holder_pct": 96.0,
        "short_account_pct": 66.0,
        "short_account_roc_1h_pp": 0.8,
        "short_account_roc_smoothed_3p_pp": 0.6,
        "short_account_direction_persistence": 3,
        "carry_funding_pct": 0.02,
        "predicted_funding_pct": 0.03,
        "hour_volume_roc_1h_pct": 125.0,
        "quote_volume_24h_vs_prior_30d_avg_ratio": 3.5,
        "quote_volume_24h": 20_000_000,
        "oi_delta_pct": 2.5,
        "price_vs_anchored_vwap_30d_pct": 12.0,
        "hour_return_pct": 3.0,
        "day_return_pct": 18.0,
        "trend_confluence_score": 72.0,
        "broke_high_5d": True,
        "timing_too_late_score": 20.0,
        "convexity_late_penalty": 15.0,
        "centralized_ownership_score": 82.0,
        "low_float_score": 76.0,
    }


def test_candidate_requires_every_strict_entry_gate() -> None:
    scored = score_entry_candidates(
        pd.DataFrame([_candidate(), {**_candidate("WEAKUSDT"), "short_account_pct": 55.0}]),
        _config(),
    )

    passing = scored[scored["_entry_all_gates"]]

    assert passing["symbol"].tolist() == ["PLAYUSDT"]
    assert bool(passing.iloc[0]["_gate_holder"]) is True
    assert bool(passing.iloc[0]["_gate_venue"]) is True


def test_historical_short_build_does_not_replace_current_build() -> None:
    row = {
        **_candidate(),
        "short_account_roc_1h_pp": -0.1,
        "short_account_roc_smoothed_3p_pp": -0.05,
        "short_account_direction_persistence": 1,
        "short_account_change_max_pp": 8.0,
    }

    scored = score_entry_candidates(pd.DataFrame([row]), _config())

    assert bool(scored.iloc[0]["_gate_short_build"]) is False
    assert bool(scored.iloc[0]["_entry_all_gates"]) is False


def test_predicted_funding_does_not_replace_current_funding() -> None:
    row = {
        **_candidate(),
        "carry_funding_pct": -0.01,
        "predicted_funding_pct": 0.08,
    }

    scored = score_entry_candidates(pd.DataFrame([row]), _config())

    assert bool(scored.iloc[0]["_gate_actual_positive_funding"]) is False
    assert bool(scored.iloc[0]["_entry_all_gates"]) is False


def test_risk_plan_respects_planned_and_stress_bankroll_caps() -> None:
    config = _config(
        risk_fraction=0.0025,
        max_stress_risk_fraction=0.005,
        max_depth_fraction=1.0,
        max_notional_fraction=1.0,
    )
    rules = SymbolRules(
        tick_size=Decimal("0.001"),
        qty_step=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        min_notional=Decimal("5"),
    )

    plan = build_risk_plan(
        equity_usdt=10_000,
        entry_price=1.0,
        atr_15m=0.04,
        swing_low=0.94,
        bid_depth_1pct_usdt=1_000_000,
        rules=rules,
        config=config,
    )

    assert plan.rejection_reason == ""
    assert plan.stop_price == Decimal("0.920")
    assert float(plan.planned_risk_usdt) <= 25.0
    assert float(plan.stress_risk_usdt) <= 50.0
    assert plan.stop_distance_pct == 8.0


def test_stop_ratcheting_reduces_risk_then_moves_to_cost_breakeven() -> None:
    config = _config()
    risk_reduction_position = {
        "entry_price": 1.0,
        "initial_r_per_unit": 0.08,
        "current_stop_price": 0.92,
        "latest_mark_price": 1.065,
        "maximum_favorable_price": 1.061,
        "maximum_favorable_r": 0.7625,
        "stop_stage": "initial",
    }

    stage, target, _ = stop_ratcheting_target(
        risk_reduction_position,
        {
            "atr_15m": 0.04,
            "latest_15m_close": 1.04,
            "latest_15m_sample_id": "1",
        },
        config,
    )

    assert stage == "risk_reduced"
    assert target == 0.96

    breakeven_position = {
        **risk_reduction_position,
        "current_stop_price": 0.96,
        "latest_mark_price": 1.11,
        "maximum_favorable_price": 1.105,
        "maximum_favorable_r": 1.3125,
        "stop_stage": "risk_reduced",
    }
    stage, target, _ = stop_ratcheting_target(
        breakeven_position,
        {
            "atr_15m": 0.04,
            "latest_15m_close": 1.105,
            "latest_15m_sample_id": "2",
        },
        config,
    )

    assert stage == "breakeven"
    assert target == 1.0015
    assert breakeven_position["breakeven_confirmation_count"] == 1


def test_two_hour_failure_to_launch_requires_joint_thesis_decay() -> None:
    config = _config()
    opened_ms = 1_000_000
    position = {
        "opened_at_ms": opened_ms,
        "entry_price": 1.0,
        "activation_price": 1.01,
        "entry_short_account_pct": 66.0,
        "latest_mark_price": 0.995,
        "maximum_favorable_r": 0.3,
        "stop_stage": "initial",
    }
    metrics = {
        "short_account_pct": 65.5,
        "short_account_roc_1h_pp": -0.2,
        "hour_volume_roc_1h_pct": -15.0,
        "open_interest_change_pct": -1.0,
        "latest_15m_close": 1.0,
    }

    reason = thesis_failure_reason(
        position,
        metrics,
        config,
        now_ms=opened_ms + int(2.1 * 3_600_000),
    )

    assert "two-hour proof window failed" in reason


def test_failure_to_launch_does_not_exit_while_short_and_oi_build() -> None:
    config = _config()
    opened_ms = 1_000_000
    position = {
        "opened_at_ms": opened_ms,
        "entry_price": 1.0,
        "activation_price": 0.99,
        "entry_short_account_pct": 66.0,
        "latest_mark_price": 1.01,
        "maximum_favorable_r": 0.4,
        "stop_stage": "initial",
    }
    metrics = {
        "short_account_pct": 66.5,
        "short_account_roc_1h_pp": 0.3,
        "hour_volume_roc_1h_pct": 20.0,
        "open_interest_change_pct": 1.0,
        "latest_15m_close": 1.01,
    }

    reason = thesis_failure_reason(
        position,
        metrics,
        config,
        now_ms=opened_ms + int(4.1 * 3_600_000),
    )

    assert reason == ""


def test_live_mode_requires_both_explicit_execution_gates(monkeypatch) -> None:
    monkeypatch.delenv("AUTO_SHORT_UPTREND_LIVE", raising=False)
    monkeypatch.delenv("AUTO_SHORT_UPTREND_LIVE_ACK", raising=False)

    with pytest.raises(RuntimeError, match="Live entry refused"):
        config_from_args(parse_args(["--live", "--once"]))
