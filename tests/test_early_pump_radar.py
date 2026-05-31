from __future__ import annotations

import pandas as pd

from archetype_scoring import apply_archetype_model
from early_pump_radar import apply_early_pump_radar
from terminal_engine import apply_terminal_model
from timing_engine import apply_timing_model


def _score(frame: pd.DataFrame, *, min_transfer_tokens: float = 0.0) -> pd.DataFrame:
    return apply_early_pump_radar(
        apply_timing_model(apply_archetype_model(apply_terminal_model(frame))),
        min_transfer_tokens=min_transfer_tokens,
    )


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
                    "binance_perp_universe": True,
                    "token_platform": "ethereum",
                    "token_contract": "0x1111111111111111111111111111111111111111",
                    "holder_source": "Etherscan holder endpoint",
                    "top10_holder_pct": 91,
                    "top100_holder_pct": 99,
                    "centralized_ownership_score": 86,
                    "low_float_score": 82,
                    "float_trap_score": 78,
                    "fdv_to_market_cap": 8,
                    "history_days": 180,
                    "recent_max_pump_60d_pct": 8.0,
                    "recent_pump_60d_days": 60,
                    "no_large_pump_60d_flag": True,
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
    assert bool(row["early_pump_holder_evidence_gate"]) is True
    assert bool(row["early_pump_binance_bitget_gate"]) is True
    assert bool(row["early_pump_no_recent_pump_gate"]) is True
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
                    "history_days": 180,
                    "recent_max_pump_60d_pct": 8.0,
                    "recent_pump_60d_days": 60,
                    "no_large_pump_60d_flag": True,
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


def test_early_pump_radar_alert_requires_60d_no_pump_proof() -> None:
    row = _score(
        pd.DataFrame(
            [
                {
                    "symbol": "RECENTPUMPUSDT",
                    "cex_deposit_flow_score": 94,
                    "cex_deposit_flow_flag": True,
                    "cex_deposit_24h_count": 3,
                    "cex_deposit_24h_max_amount": 12_000_000,
                    "cex_deposit_24h_target_exchanges": "Binance, Bitget",
                    "binance_perp_universe": True,
                    "token_platform": "ethereum",
                    "token_contract": "0x3333333333333333333333333333333333333333",
                    "holder_source": "Etherscan holder endpoint",
                    "top10_holder_pct": 92,
                    "top100_holder_pct": 99,
                    "centralized_ownership_score": 86,
                    "low_float_score": 82,
                    "float_trap_score": 78,
                    "fdv_to_market_cap": 8,
                    "history_days": 180,
                    "recent_max_pump_60d_pct": 88.0,
                    "recent_pump_60d_days": 60,
                    "no_large_pump_60d_flag": False,
                    "short_account_pct": 64,
                    "short_dominance_score": 80,
                    "short_account_build_score": 74,
                    "pre_pump_precision_score": 76,
                    "hour_return_pct": 0.6,
                    "day_return_pct": 2.0,
                    "binance_volume_share_pct": 6.0,
                    "bitget_volume_share_pct": 2.4,
                }
            ]
        )
    ).iloc[0]

    assert bool(row["early_pump_no_recent_pump_gate"]) is False
    assert bool(row["early_pump_alert_flag"]) is False
    assert row["early_pump_state"] == "Dormancy unproven"
    assert "60D no-pump proof" in row["early_pump_next_check"]


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


def test_early_pump_radar_does_not_alert_on_top100_only_control() -> None:
    row = apply_early_pump_radar(
        pd.DataFrame(
            [
                {
                    "symbol": "TOP100ONLYUSDT",
                    "cex_deposit_flow_score": 95,
                    "cex_deposit_flow_flag": True,
                    "cex_deposit_24h_count": 2,
                    "cex_deposit_24h_max_amount": 2_000_000,
                    "cex_deposit_24h_target_exchanges": "Binance, Bitget",
                    "token_platform": "ethereum",
                    "token_contract": "0x2222222222222222222222222222222222222222",
                    "holder_source": "Etherscan holder endpoint",
                    "top10_holder_pct": 55,
                    "top100_holder_pct": 99,
                    "short_account_pct": 64,
                    "low_float_score": 82,
                    "bitget_volume_share_pct": 2.4,
                }
            ]
        )
    ).iloc[0]

    assert bool(row["early_pump_whale_gate"]) is False
    assert bool(row["early_pump_alert_flag"]) is False


def test_early_pump_state_names_missing_holder_gate_before_watch_state() -> None:
    row = apply_early_pump_radar(
        pd.DataFrame(
            [
                {
                    "symbol": "TOP100FLOWUSDT",
                    "cex_deposit_flow_score": 95,
                    "cex_deposit_flow_flag": True,
                    "cex_deposit_24h_count": 2,
                    "cex_deposit_24h_max_amount": 2_000_000,
                    "cex_deposit_24h_target_exchanges": "Binance, Bitget",
                    "binance_perp_universe": True,
                    "token_platform": "ethereum",
                    "token_contract": "0x2222222222222222222222222222222222222222",
                    "holder_source": "Etherscan holder endpoint",
                    "top10_holder_pct": 55,
                    "top100_holder_pct": 99,
                    "history_days": 180,
                    "recent_max_pump_60d_pct": 8.0,
                    "recent_pump_60d_days": 60,
                    "no_large_pump_60d_flag": True,
                    "short_account_pct": 64,
                    "low_float_score": 82,
                    "bitget_volume_share_pct": 2.4,
                }
            ]
        )
    ).iloc[0]

    assert bool(row["early_pump_confirmed_target_flow"]) is True
    assert bool(row["early_pump_whale_gate"]) is False
    assert row["early_pump_state"] == "Holder gate unproven"
    assert bool(row["early_pump_alert_flag"]) is False


def test_early_pump_state_names_missing_binance_bitget_gate_before_flow_watch() -> None:
    row = apply_early_pump_radar(
        pd.DataFrame(
            [
                {
                    "symbol": "FLOWNOVENUEUSDT",
                    "cex_deposit_flow_score": 95,
                    "cex_deposit_flow_flag": True,
                    "cex_deposit_24h_count": 2,
                    "cex_deposit_24h_max_amount": 2_000_000,
                    "cex_deposit_24h_target_exchanges": "Binance, Bitget",
                    "token_platform": "ethereum",
                    "token_contract": "0x4444444444444444444444444444444444444444",
                    "holder_source": "Etherscan holder endpoint",
                    "top10_holder_pct": 92,
                    "top100_holder_pct": 99,
                    "history_days": 180,
                    "recent_max_pump_60d_pct": 8.0,
                    "recent_pump_60d_days": 60,
                    "no_large_pump_60d_flag": True,
                    "short_account_pct": 64,
                    "low_float_score": 82,
                }
            ]
        )
    ).iloc[0]

    assert bool(row["early_pump_confirmed_target_flow"]) is True
    assert bool(row["early_pump_whale_gate"]) is True
    assert bool(row["early_pump_binance_bitget_gate"]) is False
    assert row["early_pump_state"] == "Venue gate unproven"
    assert bool(row["early_pump_alert_flag"]) is False


def test_early_pump_radar_target_flow_respects_transfer_floor() -> None:
    scored = _score(
        pd.DataFrame(
            [
                {
                    "symbol": "SMALLFLOWUSDT",
                    "cex_deposit_flow_score": 90,
                    "cex_deposit_flow_flag": True,
                    "cex_deposit_24h_count": 1,
                    "cex_deposit_24h_max_amount": 9_999,
                    "cex_deposit_24h_target_exchanges": "Binance",
                    "top100_holder_pct": 99,
                    "short_account_pct": 60,
                    "low_float_score": 80,
                }
            ]
        ),
        min_transfer_tokens=10_000,
    )
    row = scored.iloc[0]

    assert bool(row["early_pump_confirmed_target_flow"]) is False
    assert "Binance below transfer floor" in row["early_pump_note"]
    assert "target CEX flow" not in row["early_pump_primary_signal"]


def test_early_pump_short_gate_requires_squeeze_fuel_not_short_pct_alone() -> None:
    base = {
        "cex_deposit_flow_score": 90,
        "cex_deposit_flow_flag": True,
        "cex_deposit_24h_count": 2,
        "cex_deposit_24h_max_amount": 2_000_000,
        "cex_deposit_24h_target_exchanges": "Binance, Bitget",
        "binance_perp_universe": True,
        "bitget_volume_share_pct": 2.4,
        "token_platform": "ethereum",
        "token_contract": "0x5555555555555555555555555555555555555555",
        "holder_source": "Etherscan holder endpoint",
        "holder_count": 6_000,
        "top10_holder_pct": 92.0,
        "top100_holder_pct": 99.0,
        "centralized_ownership_score": 86.0,
        "low_float_score": 82.0,
        "float_trap_score": 78.0,
        "fdv_to_market_cap": 8.0,
        "history_days": 180,
        "recent_max_pump_60d_pct": 6.0,
        "recent_pump_60d_days": 60,
        "no_large_pump_60d_flag": True,
        "short_account_pct": 72.0,
        "short_dominance_score": 80.0,
        "short_squeeze_score": 95.0,
        "hour_return_pct": 1.2,
        "day_return_pct": 3.0,
    }
    scored = apply_early_pump_radar(
        pd.DataFrame(
            [
                {**base, "symbol": "SHORTONLYUSDT"},
                {
                    **base,
                    "symbol": "FUELUSDT",
                    "short_account_build_score": 52.0,
                    "oi_delta_pct": 4.0,
                },
            ]
        ),
        min_transfer_tokens=20_000,
    ).set_index("symbol")

    assert scored.loc["SHORTONLYUSDT", "early_pump_short_squeeze_score"] >= 55.0
    assert scored.loc["SHORTONLYUSDT", "early_pump_squeeze_fuel_score"] < 40.0
    assert not bool(scored.loc["SHORTONLYUSDT", "early_pump_short_gate"])
    assert not bool(scored.loc["SHORTONLYUSDT", "early_pump_alert_flag"])
    assert scored.loc["SHORTONLYUSDT", "early_pump_state"] == "Squeeze fuel unproven"
    assert "short crowd plus squeeze fuel" in scored.loc["SHORTONLYUSDT", "early_pump_next_check"]

    assert scored.loc["FUELUSDT", "early_pump_squeeze_fuel_score"] >= 40.0
    assert bool(scored.loc["FUELUSDT", "early_pump_short_gate"])
    assert bool(scored.loc["FUELUSDT", "early_pump_alert_flag"])
