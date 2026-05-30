import pandas as pd

from pre_activity_radar import apply_pre_activity_radar


def test_pre_activity_radar_prioritizes_quiet_controlled_cex_setup() -> None:
    rows = pd.DataFrame(
        [
            {
                "symbol": "QUIETUSDT",
                "top10_holder_pct": 88,
                "top100_holder_pct": 98.5,
                "holder_count": 8_000,
                "low_float_score": 84,
                "float_trap_score": 80,
                "fdv_to_market_cap": 12,
                "locked_supply_pct": 72,
                "cex_deposit_flow_flag": True,
                "cex_deposit_flow_score": 92,
                "cex_deposit_inventory_stress_score": 78,
                "cex_deposit_24h_count": 2,
                "cex_deposit_24h_max_amount": 250_000,
                "cex_deposit_24h_token_amount": 400_000,
                "cex_deposit_24h_target_exchanges": "Binance, Bitget",
                "inventory_transfer_risk_score": 74,
                "short_account_pct": 62,
                "short_account_change_max_pp": 1.8,
                "oi_to_24h_volume_pct": 9,
                "binance_bitget_gate_share_pct": 56,
                "ask_depth_1pct_usdt": 42_000,
                "ask_depth_to_24h_volume_pct": 0.03,
                "day_return_pct": 0.9,
                "price_change_24h_pct": 0.9,
                "hour_return_pct": 0.2,
                "range_24h_pct": 3.2,
                "daily_quote_volume_multiple": 1.05,
                "hour_volume_multiple": 0.95,
                "hour_trade_count_multiple": 1.0,
                "low_volatility_coil_score": 82,
                "pre_pump_precision_score": 78,
                "terminal_pre_ignition_quality_score": 75,
            }
        ]
    )

    row = apply_pre_activity_radar(rows).iloc[0]

    assert row["pre_activity_pump_score"] >= 70
    assert bool(row["pre_activity_alert_flag"]) is True
    assert bool(row["pre_activity_confirmed_target_flow"]) is True
    assert bool(row["pre_activity_quiet_gate"]) is True
    assert row["pre_activity_state"] == "Stealth inventory setup"
    assert "target CEX flow" in row["pre_activity_primary_signal"]


def test_pre_activity_radar_penalizes_already_active_heat() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "HOTUSDT",
                "top10_holder_pct": 90,
                "top100_holder_pct": 99,
                "low_float_score": 88,
                "cex_deposit_flow_flag": True,
                "cex_deposit_flow_score": 95,
                "cex_deposit_24h_count": 2,
                "cex_deposit_24h_target_exchanges": "Gate.io",
                "short_account_pct": 64,
                "ask_depth_1pct_usdt": 35_000,
                "ask_depth_to_24h_volume_pct": 0.02,
                "day_return_pct": 82,
                "price_change_24h_pct": 82,
                "hour_return_pct": 16,
                "range_24h_pct": 70,
                "hour_volume_multiple": 12,
                "hour_trade_count_multiple": 10,
                "cmc_mover_score": 92,
                "broke_high_20d": True,
            }
        ]
    )

    row = apply_pre_activity_radar(frame).iloc[0]

    assert row["pre_activity_heat_score"] >= 90
    assert bool(row["pre_activity_quiet_gate"]) is False
    assert bool(row["pre_activity_alert_flag"]) is False
    assert row["pre_activity_state"] == "Already active / chase risk"


def test_pre_activity_radar_target_flow_respects_transfer_floor() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "SMALLFLOWUSDT",
                "top100_holder_pct": 99,
                "low_float_score": 84,
                "cex_deposit_flow_flag": True,
                "cex_deposit_flow_score": 90,
                "cex_deposit_24h_count": 1,
                "cex_deposit_24h_max_amount": 9_999,
                "cex_deposit_24h_target_exchanges": "Binance",
                "short_account_pct": 62,
                "ask_depth_1pct_usdt": 42_000,
                "ask_depth_to_24h_volume_pct": 0.03,
                "day_return_pct": 0.9,
                "price_change_24h_pct": 0.9,
                "hour_return_pct": 0.2,
                "range_24h_pct": 3.2,
            }
        ]
    )

    row = apply_pre_activity_radar(frame, min_transfer_tokens=10_000).iloc[0]

    assert bool(row["pre_activity_confirmed_target_flow"]) is False
    assert "Binance below transfer floor" in row["pre_activity_note"]
