from __future__ import annotations

from pathlib import Path

from binance_futures import BinanceHTTPError
from short_roc_position_close import (
    ShortRocCloseConfig,
    _completed_hour_confirmation_metrics,
    _detect_external_close,
    _load_position_state,
    _position_snapshot,
    _write_position_state,
    _write_closed_trade_ledger,
    _volume_metrics,
    _realized_carry_metrics,
    build_discord_payload,
    build_external_close_payload,
    evaluate_close_decision,
    fetch_decision,
    maybe_close_position,
)


def _config(**overrides):
    values = {
        "symbol": "LABUSDT",
        "base_url": "https://fapi.binance.com",
        "timeout": 12,
        "retries": 1,
        "requests_per_second": 10.0,
        "interval_seconds": 300.0,
        "output_dir": Path("."),
        "webhook_url": "",
        "once": True,
        "dry_run": False,
        "live": False,
        "trigger_short_roc_pct": 4.0,
        "trigger_short_roc_pp": 999.0,
        "short_account_exit_level_pct": 65.0,
        "short_account_peak_drawdown_pp": 5.0,
        "oi_drop_confirmation_pct": 8.0,
        "volume_spike_confirmation_pct": 50.0,
        "confirmation_readings": 2,
        "short_rebound_tolerance_pp": 0.5,
        "short_history_limit": 12,
        "partial_close_fraction": 1.0,
        "runner_confirmation_readings": 2,
        "runner_oi_drop_pct": 3.0,
        "runner_volume_deceleration_pct": 20.0,
        "min_profit_usdt": 0.0,
        "min_profit_pct": 0.0,
        "execution_profit_floor_pct": 0.25,
        "require_breakeven_stop": False,
        "block_without_breakeven_stop": False,
        "breakeven_tolerance_pct": 0.25,
        "close_once": True,
        "api_key": "",
        "api_secret": "",
    }
    values.update(overrides)
    return ShortRocCloseConfig(**values)


def _long_position(**overrides):
    row = {
        "symbol": "LABUSDT",
        "positionAmt": "100",
        "entryPrice": "4.00",
        "markPrice": "5.00",
        "unRealizedProfit": "100",
        "positionSide": "BOTH",
        "updateTime": "1000",
    }
    row.update(overrides)
    return row


def _metrics(**overrides):
    row = {
        "short_account_previous_1h_pct": 70.0,
        "short_account_pct": 64.0,
        "short_account_roc_1h_pp": -6.0,
        "short_account_roc_1h_pct": -8.5714285714,
        "short_account_direction": "cover",
        "short_account_sample_id": "2",
        "hour_bearish_breakdown": True,
        "hour_price_stopped_making_highs": True,
        "hour_red_candle": True,
        "hour_volume_roc_1h_pct": 60.0,
        "open_interest_change_pct": -10.0,
    }
    row.update(overrides)
    return row


def _unconfirmed_metrics(**overrides):
    row = _metrics(
        hour_bearish_breakdown=False,
        hour_bullish_breakout=False,
        hour_price_stopped_making_highs=False,
        hour_price_stopped_making_lows=False,
        hour_red_candle=False,
        hour_green_candle=False,
        hour_volume_roc_1h_pct=0.0,
        open_interest_change_pct=0.0,
    )
    row.update(overrides)
    return row


class _AutoClient:
    def __init__(self, positions):
        self.positions = positions
        self.ratio_symbol = ""
        self.orders_symbol = ""

    def position_information_v3(self, symbol=None):
        assert symbol is None
        return self.positions

    def global_long_short_account_ratio(self, symbol, period="1h", limit=2):
        self.ratio_symbol = symbol
        return [
            {"timestamp": 1, "shortAccount": "0.70"},
            {"timestamp": 2, "shortAccount": "0.64"},
        ]

    def ticker_24hr(self, symbol=None):
        return [{"symbol": symbol, "quoteVolume": "45000000"}]

    def klines_1d(self, symbol, limit=31):
        return [
            [index, "0", "0", "0", "0", "0", index + 1, "10000000"]
            for index in range(30)
        ]

    def klines(self, symbol, interval="1h", limit=5):
        return [
            [0, "5.0", "5.2", "4.8", "5.0", "0", 1, "100"],
            [1, "5.0", "5.1", "4.7", "4.9", "0", 2, "100"],
            [2, "4.9", "4.9", "4.5", "4.6", "0", 3, "200"],
            [3, "4.6", "4.8", "4.5", "4.7", "0", 4, "50"],
        ]

    def open_interest_statistics(self, symbol, period="1h", limit=2):
        return [
            {"timestamp": 1, "sumOpenInterest": "100", "sumOpenInterestValue": "500"},
            {"timestamp": 2, "sumOpenInterest": "90", "sumOpenInterestValue": "414"},
        ]

    def income_history(self, **kwargs):
        income_type = kwargs.get("income_type")
        return [
            {
                "symbol": kwargs.get("symbol"),
                "incomeType": income_type,
                "income": "1.25" if income_type == "FUNDING_FEE" else "-0.05",
                "asset": "USDT",
                "time": 2000,
            }
        ]

    def open_futures_orders(self, symbol):
        self.orders_symbol = symbol
        return [
            {
                "symbol": symbol,
                "side": "SELL",
                "type": "STOP_MARKET",
                "stopPrice": "4.00",
                "closePosition": "true",
            }
        ]

    def open_futures_algo_orders(self, symbol):
        return []


class _UnavailablePositionClient:
    def position_information_v3(self, symbol=None):
        raise BinanceHTTPError(400, {"code": -1021, "msg": "Timestamp ahead"}, "/fapi/v3/positionRisk")


class _LiveExecutionClient:
    def __init__(self, position, *, best_bid="5.00", best_ask="5.01", order_result=None):
        self.position = position
        self.best_bid = best_bid
        self.best_ask = best_ask
        self.order_result = order_result or {
            "status": "FILLED",
            "orderId": 123,
            "executedQty": str(abs(float(position.get("positionAmt", 0)))),
            "avgPrice": best_bid if float(position.get("positionAmt", 0)) > 0 else best_ask,
        }
        self.submitted = None

    def position_information_v3(self, symbol=None):
        return [self.position]

    def depth(self, symbol, limit=5):
        return {"bids": [[self.best_bid, "1000"]], "asks": [[self.best_ask, "1000"]]}

    def exchange_info(self):
        return {
            "symbols": [
                {
                    "symbol": str(self.position.get("symbol") or "LABUSDT"),
                    "filters": [
                        {
                            "filterType": "LOT_SIZE",
                            "stepSize": "0.1",
                            "minQty": "0.1",
                        },
                        {
                            "filterType": "MARKET_LOT_SIZE",
                            "stepSize": "1",
                            "minQty": "1",
                        }
                    ],
                }
            ]
        }

    def new_futures_order(self, **params):
        self.submitted = params
        return self.order_result


def test_profitable_position_closes_when_short_roc_rolls_over() -> None:
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(),
        config=_config(min_profit_usdt=10, min_profit_pct=1),
    )

    assert decision.should_close is True
    assert "short ROC" in decision.reason
    assert decision.order_params == {
        "symbol": "LABUSDT",
        "side": "SELL",
        "type": "MARKET",
        "quantity": "100",
        "reduceOnly": "true",
    }


def test_first_confirmed_unwind_reduces_half_and_retains_runner() -> None:
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(short_account_sample_id="hour-1"),
        config=_config(partial_close_fraction=0.5),
    )

    assert decision.should_close is True
    assert decision.row["exit_action"] == "partial_reduce"
    assert decision.row["close_fraction"] == 0.5
    assert decision.order_params["quantity"] == "50"
    assert "retain protected runner" in decision.reason


def test_gradual_five_point_peak_drawdown_arms_without_single_hour_shock() -> None:
    config = _config(partial_close_fraction=0.5, confirmation_readings=2)
    state = {
        "status": "open",
        "symbol": "LABUSDT",
        "position_side": "LONG",
        "entry_price": 4.0,
        "short_account_peak_pct": 80.0,
    }
    first = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_unconfirmed_metrics(
            short_account_previous_1h_pct=76.0,
            short_account_pct=75.0,
            short_account_roc_1h_pp=-1.0,
            short_account_roc_1h_pct=-1.3158,
            short_account_sample_id="hour-1",
        ),
        config=config,
        signal_state=state,
    )
    second = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_unconfirmed_metrics(
            short_account_previous_1h_pct=75.0,
            short_account_pct=74.8,
            short_account_roc_1h_pp=-0.2,
            short_account_roc_1h_pct=-0.2667,
            short_account_sample_id="hour-2",
        ),
        config=config,
        signal_state=_position_snapshot(first),
    )

    assert first.should_close is False
    assert first.row["short_unwind_peak_drawdown_triggered"] is True
    assert first.row["short_unwind_confirmation_count"] == 1
    assert second.should_close is True
    assert second.row["short_unwind_confirmation_count"] == 2
    assert second.row["exit_action"] == "partial_reduce"


def test_runner_waits_for_two_distinct_joint_exhaustion_samples() -> None:
    config = _config(
        partial_close_fraction=0.5,
        runner_confirmation_readings=2,
        runner_oi_drop_pct=3.0,
        runner_volume_deceleration_pct=20.0,
    )
    initial = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(short_account_sample_id="hour-1"),
        config=config,
    )
    runner_state = _position_snapshot(initial)
    runner_state.update(
        {
            "partial_exit_completed": True,
            "partial_exit_completed_at": "2026-07-23 10:00:00 UTC",
            "partial_exit_sample_id": "hour-1",
            "partial_exit_executed_qty": 50.0,
            "runner_active": True,
            "runner_confirmation_count": 0,
            "runner_last_counted_sample_id": "hour-1",
        }
    )
    first = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(positionAmt="50", unRealizedProfit="50"),
        short_metrics=_unconfirmed_metrics(
            short_account_sample_id="hour-2",
            hour_price_stopped_making_highs=True,
            open_interest_change_pct=-4.0,
            hour_volume_roc_1h_pct=-25.0,
        ),
        config=config,
        signal_state=runner_state,
    )
    second = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(positionAmt="50", unRealizedProfit="50"),
        short_metrics=_unconfirmed_metrics(
            short_account_sample_id="hour-3",
            hour_price_stopped_making_highs=True,
            open_interest_change_pct=-4.0,
            hour_volume_roc_1h_pct=-25.0,
        ),
        config=config,
        signal_state=_position_snapshot(first),
    )

    assert first.should_close is False
    assert first.row["runner_confirmation_count"] == 1
    assert first.row["exit_signal_stage"] == "runner_active_wait_exhaustion"
    assert second.should_close is True
    assert second.row["runner_confirmation_count"] == 2
    assert second.row["exit_action"] == "close_runner"
    assert second.order_params["quantity"] == "50"


def test_runner_holds_when_oi_remains_elevated_despite_short_unwind() -> None:
    config = _config(partial_close_fraction=0.5)
    state = {
        "status": "open",
        "symbol": "LABUSDT",
        "position_side": "LONG",
        "entry_price": 4.0,
        "short_account_peak_pct": 72.0,
        "partial_exit_completed": True,
        "partial_exit_sample_id": "hour-1",
        "partial_exit_executed_qty": 50.0,
        "runner_active": True,
        "runner_last_counted_sample_id": "hour-1",
    }
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(positionAmt="50", unRealizedProfit="50"),
        short_metrics=_unconfirmed_metrics(
            short_account_sample_id="hour-2",
            hour_price_stopped_making_highs=True,
            open_interest_change_pct=5.0,
            hour_volume_roc_1h_pct=-25.0,
        ),
        config=config,
        signal_state=state,
    )

    assert decision.should_close is False
    assert decision.row["runner_active"] is True
    assert decision.row["runner_oi_decline"] is False
    assert decision.row["runner_confirmation_count"] == 0


def test_bank_style_minus_3_point_6_percent_short_move_no_longer_arms_or_closes() -> None:
    decision = evaluate_close_decision(
        symbol="BANKUSDT",
        position=_long_position(symbol="BANKUSDT"),
        short_metrics=_metrics(
            short_account_previous_1h_pct=70.06,
            short_account_pct=67.54,
            short_account_roc_1h_pp=-2.52,
            short_account_roc_1h_pct=-3.5969,
            short_account_sample_id="bank-hour",
        ),
        config=_config(symbol="BANKUSDT"),
    )

    assert decision.should_close is False
    assert decision.row["short_unwind_armed"] is False
    assert decision.reason == "short unwind not armed"


def test_short_unwind_arms_but_cannot_close_before_fuel_depletion() -> None:
    decision = evaluate_close_decision(
        symbol="BANKUSDT",
        position=_long_position(symbol="BANKUSDT"),
        short_metrics=_metrics(
            short_account_previous_1h_pct=70.0,
            short_account_pct=67.0,
            short_account_roc_1h_pp=-3.0,
            short_account_roc_1h_pct=-4.2857,
            short_account_sample_id="hour-1",
        ),
        config=_config(symbol="BANKUSDT"),
    )

    assert decision.should_close is False
    assert decision.row["short_unwind_armed"] is True
    assert decision.row["short_structure_met"] is False
    assert decision.row["exit_signal_stage"] == "armed_wait_structure"


def test_same_hourly_short_sample_cannot_count_as_two_confirmations() -> None:
    config = _config()
    first = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_unconfirmed_metrics(short_account_sample_id="hour-1"),
        config=config,
    )
    repeated = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_unconfirmed_metrics(short_account_sample_id="hour-1"),
        config=config,
        signal_state=_position_snapshot(first),
    )

    assert first.should_close is False
    assert repeated.should_close is False
    assert repeated.row["short_unwind_confirmation_count"] == 1
    assert repeated.row["exit_signal_stage"] == "armed_wait_confirmation"


def test_second_distinct_hourly_sample_confirms_persistent_unwind() -> None:
    config = _config()
    first = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_unconfirmed_metrics(short_account_sample_id="hour-1"),
        config=config,
    )
    second = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_unconfirmed_metrics(
            short_account_previous_1h_pct=64.0,
            short_account_pct=63.8,
            short_account_roc_1h_pp=-0.2,
            short_account_roc_1h_pct=-0.3125,
            short_account_sample_id="hour-2",
        ),
        config=config,
        signal_state=_position_snapshot(first),
    )

    assert second.should_close is True
    assert second.row["short_unwind_confirmation_count"] == 2
    assert second.row["exit_reading_confirmation"] is True
    assert "2 distinct hourly readings" in second.reason


def test_short_rebound_beyond_tolerance_disarms_waiting_signal() -> None:
    config = _config()
    first = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_unconfirmed_metrics(short_account_sample_id="hour-1"),
        config=config,
    )
    rebound = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_unconfirmed_metrics(
            short_account_previous_1h_pct=64.0,
            short_account_pct=65.6,
            short_account_roc_1h_pp=1.6,
            short_account_roc_1h_pct=2.5,
            short_account_sample_id="hour-2",
        ),
        config=config,
        signal_state=_position_snapshot(first),
    )

    assert rebound.should_close is False
    assert rebound.row["short_unwind_armed"] is False
    assert rebound.row["short_unwind_confirmation_count"] == 0


def test_missing_short_ratio_sample_preserves_armed_state_without_counting_it() -> None:
    config = _config()
    first = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_unconfirmed_metrics(short_account_sample_id="hour-1"),
        config=config,
    )
    unavailable = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_unconfirmed_metrics(
            short_account_previous_1h_pct=float("nan"),
            short_account_pct=float("nan"),
            short_account_roc_1h_pp=float("nan"),
            short_account_roc_1h_pct=float("nan"),
            short_account_sample_id="",
        ),
        config=config,
        signal_state=_position_snapshot(first),
    )

    assert unavailable.should_close is False
    assert unavailable.row["short_unwind_armed"] is True
    assert unavailable.row["short_unwind_confirmation_count"] == 1
    assert unavailable.row["short_unwind_last_counted_sample_id"] == "hour-1"


def test_peak_drawdown_can_deplete_fuel_while_shorts_remain_above_65_percent() -> None:
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(
            short_account_previous_1h_pct=72.0,
            short_account_pct=66.5,
            short_account_roc_1h_pp=-5.5,
            short_account_roc_1h_pct=-7.6389,
        ),
        config=_config(),
    )

    assert decision.should_close is True
    assert decision.row["short_structure_level_met"] is False
    assert decision.row["short_structure_peak_met"] is True


def test_oi_flush_with_stalled_highs_confirms_an_armed_exit() -> None:
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_unconfirmed_metrics(
            hour_price_stopped_making_highs=True,
            open_interest_change_pct=-8.1,
        ),
        config=_config(),
    )

    assert decision.should_close is True
    assert decision.row["exit_oi_confirmation"] is True


def test_high_volume_red_hour_confirms_an_armed_exit() -> None:
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_unconfirmed_metrics(
            hour_red_candle=True,
            hour_volume_roc_1h_pct=50.0,
        ),
        config=_config(),
    )

    assert decision.should_close is True
    assert decision.row["exit_volume_confirmation"] is True


def test_completed_hour_metrics_detect_breakdown_volume_and_oi_flush() -> None:
    metrics = _completed_hour_confirmation_metrics(
        [
            [0, "5.0", "5.2", "4.8", "5.0", "0", 1, "100"],
            [1, "5.0", "5.1", "4.7", "4.9", "0", 2, "100"],
            [2, "4.9", "4.9", "4.5", "4.6", "0", 3, "200"],
            [3, "4.6", "4.8", "4.5", "4.7", "0", 4, "50"],
        ],
        [
            {"timestamp": 1, "sumOpenInterest": "100", "sumOpenInterestValue": "500"},
            {"timestamp": 2, "sumOpenInterest": "90", "sumOpenInterestValue": "414"},
        ],
    )

    assert metrics["hour_bearish_breakdown"] is True
    assert metrics["hour_red_candle"] is True
    assert metrics["hour_price_stopped_making_highs"] is True
    assert metrics["hour_volume_roc_1h_pct"] == 100.0
    assert round(metrics["open_interest_change_pct"], 6) == -10.0


def test_position_api_error_is_not_reported_as_no_open_position() -> None:
    decision, errors = fetch_decision(_UnavailablePositionClient(), _config(symbol="AUTO"))

    assert decision.should_close is False
    assert decision.reason == "position data unavailable; will retry"
    assert decision.row["symbol"] == "AUTO"
    assert errors and "-1021" in errors[0]


def test_close_is_blocked_until_profit_guard_is_met() -> None:
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(unRealizedProfit="-1", markPrice="3.99"),
        short_metrics=_metrics(),
        config=_config(),
    )

    assert decision.should_close is False
    assert decision.reason == "profit guard not met"


def test_roc_just_inside_arm_threshold_does_not_close() -> None:
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(
            short_account_previous_1h_pct=66.0,
            short_account_pct=63.3666,
            short_account_roc_1h_pct=-3.99,
            short_account_roc_1h_pp=-2.6334,
        ),
        config=_config(),
    )

    assert decision.should_close is False
    assert decision.reason == "short unwind not armed"


def test_breakeven_stop_check_warns_but_does_not_block_when_missing() -> None:
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(),
        config=_config(require_breakeven_stop=True),
        open_orders=[],
    )

    assert decision.should_close is True
    assert decision.row["breakeven_stop_found"] is False


def test_hard_block_without_breakeven_stop_still_blocks_when_requested() -> None:
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(),
        config=_config(require_breakeven_stop=True, block_without_breakeven_stop=True),
        open_orders=[],
    )

    assert decision.should_close is False
    assert decision.reason == "breakeven stop guard not met"


def test_required_breakeven_stop_allows_close_when_found() -> None:
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(),
        config=_config(require_breakeven_stop=True),
        open_orders=[
            {
                "symbol": "LABUSDT",
                "side": "SELL",
                "type": "STOP_MARKET",
                "stopPrice": "4.00",
                "closePosition": "true",
            }
        ],
    )

    assert decision.should_close is True
    assert decision.row["breakeven_stop_found"] is True


def test_algo_stop_order_can_satisfy_breakeven_check() -> None:
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(),
        config=_config(require_breakeven_stop=True),
        open_orders=[
            {
                "symbol": "LABUSDT",
                "side": "SELL",
                "algoType": "CONDITIONAL",
                "type": "STOP_MARKET",
                "triggerPrice": "3.99",
            }
        ],
    )

    assert decision.should_close is True
    assert decision.row["breakeven_stop_found"] is True


def test_dry_run_order_result_requires_explicit_live_gate() -> None:
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(),
        config=_config(),
    )

    result = maybe_close_position(object(), decision, _config(live=False))

    assert result is not None
    assert result["dry_run"] is True
    assert result["order_params"]["side"] == "SELL"


def test_live_close_is_blocked_when_fresh_position_has_moved_to_a_loss(monkeypatch) -> None:
    monkeypatch.setenv("SHORT_ROC_CLOSE_LIVE", "1")
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(),
        config=_config(live=True),
    )
    client = _LiveExecutionClient(
        _long_position(markPrice="3.99", unRealizedProfit="-1"),
        best_bid="3.99",
        best_ask="4.00",
    )

    result = maybe_close_position(client, decision, _config(live=True))

    assert result["safety_blocked"] is True
    assert "fresh unrealized PnL" in result["reason"]
    assert client.submitted is None


def test_live_close_is_blocked_when_best_bid_is_below_profit_floor(monkeypatch) -> None:
    monkeypatch.setenv("SHORT_ROC_CLOSE_LIVE", "1")
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(),
        config=_config(live=True),
    )
    client = _LiveExecutionClient(
        _long_position(markPrice="4.10", unRealizedProfit="10"),
        best_bid="4.005",
        best_ask="4.01",
    )

    result = maybe_close_position(client, decision, _config(live=True))

    assert result["safety_blocked"] is True
    assert "best executable profit" in result["reason"]
    assert client.submitted is None


def test_live_close_uses_price_protected_ioc_reduce_only_order(monkeypatch) -> None:
    monkeypatch.setenv("SHORT_ROC_CLOSE_LIVE", "1")
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(),
        config=_config(live=True),
    )
    client = _LiveExecutionClient(_long_position(), best_bid="5.00", best_ask="5.01")

    result = maybe_close_position(client, decision, _config(live=True))

    assert result["status"] == "FILLED"
    assert result["safety_revalidated"] is True
    assert client.submitted == {
        "symbol": "LABUSDT",
        "side": "SELL",
        "type": "LIMIT",
        "quantity": "100",
        "reduceOnly": "true",
        "timeInForce": "IOC",
        "price": "5.00",
        "newOrderRespType": "RESULT",
    }


def test_live_partial_close_rounds_to_limit_step_and_leaves_runner(monkeypatch) -> None:
    monkeypatch.setenv("SHORT_ROC_CLOSE_LIVE", "1")
    config = _config(live=True, partial_close_fraction=0.5)
    position = _long_position(positionAmt="101")
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=position,
        short_metrics=_metrics(),
        config=config,
    )
    client = _LiveExecutionClient(
        position,
        best_bid="5.00",
        best_ask="5.01",
        order_result={
            "status": "FILLED",
            "orderId": 456,
            "executedQty": "50.5",
            "avgPrice": "5.00",
        },
    )

    result = maybe_close_position(client, decision, config)

    assert result["status"] == "FILLED"
    assert result["exit_action"] == "partial_reduce"
    assert result["close_fraction"] == 0.5
    assert client.submitted["quantity"] == "50.5"
    assert client.submitted["reduceOnly"] == "true"


def test_live_short_close_uses_ask_as_max_buy_price(monkeypatch) -> None:
    monkeypatch.setenv("SHORT_ROC_CLOSE_LIVE", "1")
    short_position = _long_position(
        positionAmt="-100",
        entryPrice="5.00",
        markPrice="4.00",
        unRealizedProfit="100",
    )
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=short_position,
        short_metrics=_metrics(hour_bearish_breakdown=False, hour_bullish_breakout=True),
        config=_config(live=True),
    )
    client = _LiveExecutionClient(short_position, best_bid="3.99", best_ask="4.00")

    result = maybe_close_position(client, decision, _config(live=True))

    assert result["status"] == "FILLED"
    assert client.submitted["side"] == "BUY"
    assert client.submitted["price"] == "4.00"
    assert client.submitted["type"] == "LIMIT"


def test_payload_reports_decision_and_thresholds() -> None:
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(),
        config=_config(),
    )

    payload = build_discord_payload(decision, [], {"dry_run": True, "order_params": decision.order_params})
    description = payload["embeds"][0]["description"]

    assert payload["username"] == "LAB Short ROC Close"
    assert "LAB short-ROC position close monitor" in description
    assert "Unrealized PnL $100 / +25.00%" in description
    assert "Decision: CLOSE TRIGGER" in description
    assert "DRY RUN" in description


def test_payload_reports_execution_safety_block_reason() -> None:
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(),
        config=_config(),
    )

    payload = build_discord_payload(
        decision,
        [],
        {"safety_blocked": True, "status": "BLOCKED", "reason": "fresh position moved to a loss"},
    )
    description = payload["embeds"][0]["description"]

    assert "Decision: EXECUTION BLOCKED | fresh position moved to a loss" in description


def test_volume_metrics_compare_rolling_24h_with_prior_closed_days() -> None:
    rows = [
        [index, "0", "0", "0", "0", "0", index + 1, str((index + 1) * 1000)]
        for index in range(32)
    ]
    rows.append([33, "0", "0", "0", "0", "0", 10_000, "999999999"])

    metrics = _volume_metrics({"quoteVolume": "49500"}, rows, now_ms=1000)

    assert metrics["quote_volume_prior_30d_days"] == 30
    assert metrics["quote_volume_prior_30d_total_usdt"] == sum(range(3, 33)) * 1000
    assert metrics["quote_volume_prior_30d_daily_avg_usdt"] == 17_500
    assert round(metrics["quote_volume_24h_vs_prior_30d_avg_ratio"], 6) == round(49_500 / 17_500, 6)


def test_payload_reports_volume_context() -> None:
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(),
        config=_config(),
    )
    decision.row.update(
        {
            "quote_volume_24h_usdt": 45_000_000,
            "quote_volume_prior_30d_total_usdt": 300_000_000,
            "quote_volume_prior_30d_daily_avg_usdt": 10_000_000,
            "quote_volume_prior_30d_days": 30,
            "quote_volume_24h_vs_prior_30d_avg_ratio": 4.5,
        }
    )

    description = build_discord_payload(decision, [])["embeds"][0]["description"]

    assert "Volume: 24h $45.00M | prior 30D $300.00M (30 closed days)" in description
    assert "Prior daily avg $10.00M | 24h / prior avg 4.5x" in description


def test_payload_reports_market_price_without_an_open_position() -> None:
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position={},
        short_metrics=_metrics(),
        config=_config(),
    )
    decision.row["market_price"] = 5.125

    description = build_discord_payload(decision, [])["embeds"][0]["description"]

    assert decision.reason == "no open position"
    assert "Market price: $5.125" in description


def test_realized_carry_metrics_net_funding_and_trading_fees_for_current_position() -> None:
    metrics = _realized_carry_metrics(
        [
            {"symbol": "LABUSDT", "incomeType": "FUNDING_FEE", "income": "99", "asset": "USDT", "time": 999},
            {"symbol": "LABUSDT", "incomeType": "FUNDING_FEE", "income": "1.25", "asset": "USDT", "time": 1000},
            {"symbol": "LABUSDT", "incomeType": "FUNDING_FEE", "income": "-0.25", "asset": "USDT", "time": 2000},
            {"symbol": "OTHERUSDT", "incomeType": "FUNDING_FEE", "income": "50", "asset": "USDT", "time": 2000},
            {"symbol": "LABUSDT", "incomeType": "COMMISSION", "income": "-0.10", "asset": "USDT", "time": 2000},
            {"symbol": "LABUSDT", "incomeType": "COMMISSION", "income": "-9", "asset": "USDT", "time": 999},
            {"symbol": "LABUSDT", "incomeType": "REALIZED_PNL", "income": "50", "asset": "USDT", "time": 2000},
        ],
        symbol="LABUSDT",
        position_start_ms=1000,
    )

    assert metrics["realized_carry_pnl"] == 0.9
    assert metrics["realized_funding_pnl"] == 1.0
    assert metrics["realized_trading_fee_pnl"] == -0.1
    assert metrics["realized_carry_asset"] == "USDT"
    assert metrics["realized_carry_event_count"] == 2
    assert metrics["realized_trading_fee_event_count"] == 1


def test_realized_carry_includes_entry_commission_rounded_to_opening_second() -> None:
    metrics = _realized_carry_metrics(
        [
            {
                "symbol": "LABUSDT",
                "incomeType": "COMMISSION",
                "income": "-0.63",
                "asset": "USDT",
                "time": 1000,
            }
        ],
        symbol="LABUSDT",
        position_start_ms=1519,
    )

    assert metrics["realized_carry_pnl"] == -0.63
    assert metrics["realized_trading_fee_pnl"] == -0.63
    assert metrics["realized_carry_since_ms"] == 1000


def test_position_snapshot_preserves_realized_carry_start() -> None:
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(),
        config=_config(),
    )
    decision.row["realized_carry_since_ms"] = 1234000

    assert _position_snapshot(decision)["realized_carry_since_ms"] == 1234000


def test_payload_labels_realized_carry_pnl() -> None:
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(),
        config=_config(),
    )
    decision.row.update(
        {
            "realized_carry_pnl": 1.25,
            "realized_funding_pnl": 1.50,
            "realized_trading_fee_pnl": -0.25,
            "realized_carry_asset": "USDT",
            "realized_carry_event_count": 2,
            "realized_trading_fee_event_count": 1,
        }
    )

    description = build_discord_payload(decision, [])["embeds"][0]["description"]

    assert "Unrealized PnL $100 / +25.00%" in description
    assert (
        "Realized Carry PnL $1.25 USDT | funding $1.5 | trading fees $-0.25 | "
        "events 2 funding / 1 fee"
    ) in description


def test_triggered_close_appends_closed_trade_ledger(tmp_path: Path) -> None:
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(),
        config=_config(output_dir=tmp_path),
    )
    order_result = {
        "orderId": 12345,
        "status": "FILLED",
        "avgPrice": "5.00",
        "executedQty": "100",
        "cumQuote": "500",
    }

    _write_closed_trade_ledger(decision, order_result, _config(output_dir=tmp_path))

    ledger_path = tmp_path / "lab_closed_trades.csv"
    text = ledger_path.read_text(encoding="utf-8")

    assert "order_status" in text
    assert "FILLED" in text
    assert "12345" in text
    assert "SELL" in text
    assert "short ROC" in text


def test_blocked_or_unfilled_order_does_not_write_closed_trade_ledger(tmp_path: Path) -> None:
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(),
        config=_config(output_dir=tmp_path),
    )

    _write_closed_trade_ledger(
        decision,
        {"safety_blocked": True, "status": "BLOCKED", "reason": "fresh loss"},
        _config(output_dir=tmp_path),
    )
    _write_closed_trade_ledger(
        decision,
        {"status": "EXPIRED", "executedQty": "0"},
        _config(output_dir=tmp_path),
    )

    assert not (tmp_path / "lab_closed_trades.csv").exists()


def test_auto_symbol_uses_single_open_position() -> None:
    client = _AutoClient([_long_position()])

    decision, errors = fetch_decision(client, _config(symbol="AUTO", require_breakeven_stop=True))

    assert errors == []
    assert client.ratio_symbol == "LABUSDT"
    assert client.orders_symbol == "LABUSDT"
    assert decision.row["symbol"] == "LABUSDT"
    assert decision.should_close is True


def test_auto_symbol_refuses_multiple_open_positions() -> None:
    client = _AutoClient([_long_position(), _long_position(symbol="EVAAUSDT")])

    decision, errors = fetch_decision(client, _config(symbol="AUTO", require_breakeven_stop=True))

    assert errors == []
    assert decision.should_close is False
    assert decision.reason == "auto mode found multiple open positions (2)"
    assert "LABUSDT" in decision.row["open_position_symbols"]
    assert "EVAAUSDT" in decision.row["open_position_symbols"]


def test_position_state_round_trip(tmp_path: Path) -> None:
    config = _config(output_dir=tmp_path, symbol="AUTO")
    state = {"status": "open", "symbol": "LABUSDT", "position_side": "LONG", "position_amt": 100.0}

    _write_position_state(state, config)

    assert _load_position_state(config) == state
    assert (tmp_path / "auto_position_state.json").exists()


def test_detects_manual_or_external_close_after_open_position_disappears() -> None:
    open_decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(),
        config=_config(),
    )
    previous_state = _position_snapshot(open_decision)
    flat_decision = evaluate_close_decision(
        symbol="LABUSDT",
        position={},
        short_metrics=_metrics(),
        config=_config(),
    )

    event = _detect_external_close(previous_state, flat_decision, [])

    assert event is not None
    assert event["symbol"] == "LABUSDT"
    assert event["close_source"] == "manual_or_external"
    assert event["close_transition"] == "position no longer open"


def test_does_not_infer_close_when_signed_position_data_failed() -> None:
    open_decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(),
        config=_config(),
    )
    previous_state = _position_snapshot(open_decision)
    unavailable = evaluate_close_decision(
        symbol="LABUSDT",
        position={},
        short_metrics=_metrics(),
        config=_config(),
    )
    unavailable = type(unavailable)(False, "position data unavailable; will retry", unavailable.row)

    assert _detect_external_close(previous_state, unavailable, ["position information: HTTP 400"]) is None


def test_auto_symbol_change_reports_previous_position_close() -> None:
    previous_decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(),
        config=_config(symbol="AUTO"),
    )
    current_decision = evaluate_close_decision(
        symbol="EVAAUSDT",
        position=_long_position(symbol="EVAAUSDT"),
        short_metrics=_metrics(),
        config=_config(symbol="AUTO"),
    )

    event = _detect_external_close(_position_snapshot(previous_decision), current_decision, [])

    assert event is not None
    assert event["symbol"] == "LABUSDT"
    assert event["replacement_symbol"] == "EVAAUSDT"
    assert event["close_transition"] == "position replaced by another symbol"


def test_external_close_payload_is_explicit_about_detection_limits() -> None:
    payload = build_external_close_payload(
        {
            "symbol": "LABUSDT",
            "position_side": "LONG",
            "position_amt": 100,
            "entry_price": 4,
            "mark_price": 5,
            "unrealized_profit": 100,
            "profit_pct": 25,
            "realized_carry_pnl": 1.25,
            "realized_funding_pnl": 1.50,
            "realized_trading_fee_pnl": -0.25,
            "realized_carry_asset": "USDT",
            "short_account_pct": 68,
            "short_account_roc_1h_pct": -3,
            "last_seen_at": "2026-07-16 10:00:00 UTC",
            "detected_closed_at": "2026-07-16 10:05:00 UTC",
            "close_transition": "position no longer open",
        }
    )
    description = payload["embeds"][0]["description"]

    assert payload["embeds"][0]["title"] == "LABUSDT CLOSE DETECTED"
    assert "manual/external position close detected" in description
    assert "another bot, by a stop, or by another exchange client" in description
    assert "Last Unrealized PnL $100 / +25.00%" in description
    assert "Last Realized Carry PnL $1.25 USDT | funding $1.5 | trading fees $-0.25" in description
