from __future__ import annotations

from pathlib import Path

from short_roc_position_close import (
    ShortRocCloseConfig,
    _write_closed_trade_ledger,
    build_discord_payload,
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
        "trigger_short_roc_pct": 2.5,
        "trigger_short_roc_pp": 1.0,
        "min_profit_usdt": 0.0,
        "min_profit_pct": 0.0,
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
    }
    row.update(overrides)
    return row


def _metrics(**overrides):
    row = {
        "short_account_previous_1h_pct": 70.0,
        "short_account_pct": 67.9,
        "short_account_roc_1h_pp": -2.1,
        "short_account_roc_1h_pct": -3.0,
        "short_account_direction": "cover",
    }
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
            {"timestamp": 2, "shortAccount": "0.679"},
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


def test_close_is_blocked_until_profit_guard_is_met() -> None:
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(unRealizedProfit="-1", markPrice="3.99"),
        short_metrics=_metrics(),
        config=_config(),
    )

    assert decision.should_close is False
    assert decision.reason == "profit guard not met"


def test_exact_threshold_does_not_close_until_more_than_threshold() -> None:
    decision = evaluate_close_decision(
        symbol="LABUSDT",
        position=_long_position(),
        short_metrics=_metrics(short_account_roc_1h_pct=-2.5, short_account_roc_1h_pp=-1.0),
        config=_config(),
    )

    assert decision.should_close is False
    assert decision.reason == "short ROC has not rolled over enough"


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
    assert "Decision: CLOSE TRIGGER" in description
    assert "DRY RUN" in description


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
