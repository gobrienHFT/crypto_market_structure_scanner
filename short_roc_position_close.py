from __future__ import annotations

import argparse
import csv
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from binance_futures import BinanceAuthenticationError, BinanceFuturesPublic, BinanceHTTPError
from discord_flag_formatter import DISCORD_FOOTER
from inx_hourly_monitor import (
    _env_value,
    _format_number,
    _format_pct,
    _format_pp,
    _load_local_env,
    _now_label,
    _oi_metrics,
    _short_metrics,
)
from volume_metrics import append_csv_row_schema_safe, closed_hour_volume_metrics


APP_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = APP_DIR / "short_roc_close_output"


@dataclass(frozen=True)
class ShortRocCloseConfig:
    symbol: str
    base_url: str
    timeout: int
    retries: int
    requests_per_second: float
    interval_seconds: float
    output_dir: Path
    webhook_url: str
    once: bool
    dry_run: bool
    live: bool
    trigger_short_roc_pct: float
    trigger_short_roc_pp: float
    short_account_exit_level_pct: float
    short_account_peak_drawdown_pp: float
    oi_drop_confirmation_pct: float
    volume_spike_confirmation_pct: float
    confirmation_readings: int
    short_rebound_tolerance_pp: float
    min_profit_usdt: float
    min_profit_pct: float
    execution_profit_floor_pct: float
    require_breakeven_stop: bool
    block_without_breakeven_stop: bool
    breakeven_tolerance_pct: float
    close_once: bool
    api_key: str
    api_secret: str


@dataclass(frozen=True)
class CloseDecision:
    should_close: bool
    reason: str
    row: dict[str, Any]
    order_params: dict[str, Any] | None = None


def _to_float(value: Any) -> float:
    try:
        parsed = float(value)
    except Exception:
        return float("nan")
    return parsed if math.isfinite(parsed) else float("nan")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _base_asset(symbol: Any) -> str:
    clean = str(symbol or "").upper().strip()
    return clean[:-4] if clean.endswith("USDT") else clean


def _output_prefix(symbol: Any) -> str:
    base = _base_asset(symbol) or "symbol"
    return "".join(char.lower() if char.isalnum() else "_" for char in base).strip("_") or "symbol"


def _position_state_path(config: ShortRocCloseConfig) -> Path:
    prefix = "auto" if config.symbol.upper().strip() in {"AUTO", "*", ""} else _output_prefix(config.symbol)
    return config.output_dir / f"{prefix}_position_state.json"


def _load_position_state(config: ShortRocCloseConfig) -> dict[str, Any]:
    path = _position_state_path(config)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_position_state(state: dict[str, Any], config: ShortRocCloseConfig) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    path = _position_state_path(config)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    temporary_path.replace(path)


def _position_snapshot(decision: CloseDecision) -> dict[str, Any]:
    row = decision.row
    amount = _to_float(row.get("position_amt"))
    side = str(row.get("position_side") or "").upper()
    symbol = str(row.get("symbol") or "").upper().strip()
    if not symbol or side not in {"LONG", "SHORT"} or not math.isfinite(amount) or amount == 0:
        return {}
    return {
        "status": "open",
        "symbol": symbol,
        "position_side": side,
        "position_amt": amount,
        "entry_price": row.get("entry_price"),
        "mark_price": row.get("mark_price"),
        "unrealized_profit": row.get("unrealized_profit"),
        "profit_pct": row.get("profit_pct"),
        "realized_carry_pnl": row.get("realized_carry_pnl"),
        "short_account_pct": row.get("short_account_pct"),
        "short_account_roc_1h_pct": row.get("short_account_roc_1h_pct"),
        "short_account_sample_id": row.get("short_account_sample_id"),
        "short_account_peak_pct": row.get("short_account_peak_pct"),
        "short_account_drawdown_from_peak_pp": row.get("short_account_drawdown_from_peak_pp"),
        "short_unwind_armed": row.get("short_unwind_armed"),
        "short_unwind_armed_at": row.get("short_unwind_armed_at"),
        "short_unwind_armed_sample_id": row.get("short_unwind_armed_sample_id"),
        "short_unwind_armed_short_pct": row.get("short_unwind_armed_short_pct"),
        "short_unwind_confirmation_count": row.get("short_unwind_confirmation_count"),
        "short_unwind_last_counted_sample_id": row.get("short_unwind_last_counted_sample_id"),
        "exit_signal_stage": row.get("exit_signal_stage"),
        "hour_volume_roc_1h_pct": row.get("hour_volume_roc_1h_pct"),
        "last_seen_at": row.get("scanned_at") or _now_utc().strftime("%Y-%m-%d %H:%M:%S UTC"),
    }


def _position_data_available(decision: CloseDecision, errors: list[str]) -> bool:
    if decision.reason == "position data unavailable; will retry":
        return False
    return not any(str(error).lower().startswith("position information:") for error in errors)


def _detect_external_close(
    previous_state: dict[str, Any],
    decision: CloseDecision,
    errors: list[str],
) -> dict[str, Any] | None:
    if previous_state.get("status") != "open" or not _position_data_available(decision, errors):
        return None

    previous_symbol = str(previous_state.get("symbol") or "").upper()
    previous_side = str(previous_state.get("position_side") or "").upper()
    current = _position_snapshot(decision)
    if current:
        if current["symbol"] == previous_symbol and current["position_side"] == previous_side:
            return None
        transition = "position reversed" if current["symbol"] == previous_symbol else "position replaced by another symbol"
    else:
        visible_symbols = {
            symbol.strip().upper()
            for symbol in str(decision.row.get("open_position_symbols") or "").split(",")
            if symbol.strip()
        }
        if previous_symbol in visible_symbols:
            return None
        transition = "position no longer open"

    return {
        **previous_state,
        "status": "closed",
        "close_source": "manual_or_external",
        "close_transition": transition,
        "detected_closed_at": _now_utc().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "replacement_symbol": current.get("symbol", ""),
        "replacement_side": current.get("position_side", ""),
    }


def _nonzero_position(rows: list[dict[str, Any]], symbol: str) -> dict[str, Any]:
    symbol = symbol.upper()
    for row in rows:
        if str(row.get("symbol", "")).upper() != symbol:
            continue
        if abs(_to_float(row.get("positionAmt"))) > 0:
            return row
    return {}


def _nonzero_positions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if abs(_to_float(row.get("positionAmt"))) > 0]


def _empty_decision(symbol: str, reason: str, config: ShortRocCloseConfig, *, positions: list[dict[str, Any]] | None = None) -> CloseDecision:
    symbols = ",".join(str(row.get("symbol", "")).upper() for row in (positions or []) if row.get("symbol"))
    return CloseDecision(
        False,
        reason,
        {
            "scanned_at": _now_utc().strftime("%Y-%m-%d %H:%M:%S UTC"),
            "symbol": symbol.upper(),
            "position_side": "FLAT",
            "position_amt": float("nan"),
            "entry_price": float("nan"),
            "mark_price": float("nan"),
            "unrealized_profit": float("nan"),
            "profit_pct": float("nan"),
            "short_account_previous_1h_pct": float("nan"),
            "short_account_pct": float("nan"),
            "short_account_roc_1h_pp": float("nan"),
            "short_account_roc_1h_pct": float("nan"),
            "short_account_direction": "",
            "trigger_short_roc_pct": config.trigger_short_roc_pct,
            "trigger_short_roc_pp": config.trigger_short_roc_pp,
            "short_account_exit_level_pct": config.short_account_exit_level_pct,
            "short_account_peak_drawdown_pp": config.short_account_peak_drawdown_pp,
            "oi_drop_confirmation_pct": config.oi_drop_confirmation_pct,
            "volume_spike_confirmation_pct": config.volume_spike_confirmation_pct,
            "confirmation_readings": config.confirmation_readings,
            "short_rebound_tolerance_pp": config.short_rebound_tolerance_pp,
            "short_unwind_armed": False,
            "short_unwind_confirmation_count": 0,
            "exit_signal_stage": "flat",
            "min_profit_usdt": config.min_profit_usdt,
            "min_profit_pct": config.min_profit_pct,
            "execution_profit_floor_pct": config.execution_profit_floor_pct,
            "require_breakeven_stop": bool(config.require_breakeven_stop),
            "block_without_breakeven_stop": bool(config.block_without_breakeven_stop),
            "breakeven_stop_found": False,
            "breakeven_tolerance_pct": config.breakeven_tolerance_pct,
            "live_enabled": bool(config.live),
            "open_position_symbols": symbols,
        },
    )


def _profit_pct(position: dict[str, Any]) -> float:
    amount = _to_float(position.get("positionAmt"))
    entry = _to_float(position.get("entryPrice"))
    mark = _to_float(position.get("markPrice"))
    if not math.isfinite(amount) or not math.isfinite(entry) or not math.isfinite(mark) or entry <= 0 or amount == 0:
        return float("nan")
    if amount > 0:
        return (mark / entry - 1.0) * 100.0
    return (entry / mark - 1.0) * 100.0 if mark > 0 else float("nan")


def _position_side(position: dict[str, Any]) -> str:
    amount = _to_float(position.get("positionAmt"))
    if amount > 0:
        return "LONG"
    if amount < 0:
        return "SHORT"
    return "FLAT"


def _close_order_params(symbol: str, position: dict[str, Any]) -> dict[str, Any]:
    amount = _to_float(position.get("positionAmt"))
    side = "SELL" if amount > 0 else "BUY"
    quantity = format(abs(amount), "f").rstrip("0").rstrip(".")
    params: dict[str, Any] = {
        "symbol": symbol.upper(),
        "side": side,
        "type": "MARKET",
        "quantity": quantity,
    }
    position_side = str(position.get("positionSide") or "BOTH").upper()
    if position_side and position_side != "BOTH":
        params["positionSide"] = position_side
    else:
        params["reduceOnly"] = "true"
    return params


def _is_true(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _has_breakeven_stop(position: dict[str, Any], open_orders: list[dict[str, Any]], tolerance_pct: float) -> bool:
    amount = _to_float(position.get("positionAmt"))
    entry = _to_float(position.get("entryPrice"))
    if not math.isfinite(amount) or amount == 0 or not math.isfinite(entry) or entry <= 0:
        return False

    close_side = "SELL" if amount > 0 else "BUY"
    tolerance = abs(float(tolerance_pct)) / 100.0
    min_long_stop = entry * (1.0 - tolerance)
    max_short_stop = entry * (1.0 + tolerance)
    allowed_types = {"STOP", "STOP_MARKET", "TRAILING_STOP_MARKET"}

    for order in open_orders:
        order_type = str(order.get("type") or order.get("algoType") or order.get("strategyType") or "").upper()
        if order_type not in allowed_types and "STOP" not in order_type:
            continue
        if str(order.get("side") or "").upper() != close_side:
            continue
        stop_price = _to_float(order.get("stopPrice") or order.get("triggerPrice") or order.get("activatePrice"))
        if not math.isfinite(stop_price) or stop_price <= 0:
            continue
        if amount > 0 and stop_price >= min_long_stop:
            return True
        if amount < 0 and stop_price <= max_short_stop:
            return True
    return False


def _volume_metrics(
    ticker: dict[str, Any] | None,
    daily_klines: list[list[Any]],
    *,
    now_ms: int | None = None,
) -> dict[str, Any]:
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    ticker = ticker or {}
    completed_rows = []
    for row in daily_klines:
        if not isinstance(row, list) or len(row) <= 7:
            continue
        close_time = _to_float(row[6])
        quote_volume = _to_float(row[7])
        if math.isfinite(close_time) and close_time < now_ms and math.isfinite(quote_volume) and quote_volume >= 0:
            completed_rows.append((int(close_time), quote_volume))
    sample = sorted(completed_rows, key=lambda item: item[0])[-30:]
    prior_total = sum(item[1] for item in sample) if sample else float("nan")
    prior_average = prior_total / len(sample) if sample else float("nan")
    volume_24h = _to_float(ticker.get("quoteVolume"))
    ratio = (
        volume_24h / prior_average
        if math.isfinite(volume_24h) and math.isfinite(prior_average) and prior_average > 0
        else float("nan")
    )
    return {
        "quote_volume_24h_usdt": volume_24h,
        "quote_volume_prior_30d_total_usdt": prior_total,
        "quote_volume_prior_30d_daily_avg_usdt": prior_average,
        "quote_volume_prior_30d_days": len(sample),
        "quote_volume_24h_vs_prior_30d_avg_ratio": ratio,
    }


def _realized_carry_metrics(
    rows: list[dict[str, Any]],
    *,
    symbol: str,
    position_start_ms: Any,
) -> dict[str, Any]:
    wanted_symbol = str(symbol or "").upper()
    start_ms = _to_float(position_start_ms)
    funding_rows: list[dict[str, Any]] = []
    assets: set[str] = set()
    total = 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("symbol") or "").upper() != wanted_symbol:
            continue
        if str(row.get("incomeType") or "").upper() != "FUNDING_FEE":
            continue
        row_time = _to_float(row.get("time"))
        if math.isfinite(start_ms) and start_ms > 0 and math.isfinite(row_time) and row_time < start_ms:
            continue
        income = _to_float(row.get("income"))
        if not math.isfinite(income):
            continue
        total += income
        funding_rows.append(row)
        asset = str(row.get("asset") or "").upper().strip()
        if asset:
            assets.add(asset)
    return {
        "realized_carry_pnl": total,
        "realized_carry_asset": "/".join(sorted(assets)) or "USDT",
        "realized_carry_event_count": len(funding_rows),
        "realized_carry_since_ms": int(start_ms) if math.isfinite(start_ms) and start_ms > 0 else 0,
    }


def _latest_metric_timestamp(rows: list[dict[str, Any]]) -> int:
    timestamps = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        parsed = _to_float(row.get("timestamp") or row.get("time"))
        if math.isfinite(parsed) and parsed > 0:
            timestamps.append(int(parsed))
    return max(timestamps, default=0)


def _completed_hour_confirmation_metrics(
    hourly_klines: list[list[Any]],
    open_interest_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        **closed_hour_volume_metrics(hourly_klines, bars_per_hour=1),
        **_oi_metrics(open_interest_rows),
        "hour_candle_open": float("nan"),
        "hour_candle_high": float("nan"),
        "hour_candle_low": float("nan"),
        "hour_candle_close": float("nan"),
        "hour_previous_high": float("nan"),
        "hour_previous_low": float("nan"),
        "hour_prior_2h_swing_high": float("nan"),
        "hour_prior_2h_swing_low": float("nan"),
        "hour_red_candle": False,
        "hour_green_candle": False,
        "hour_bearish_breakdown": False,
        "hour_bullish_breakout": False,
        "hour_price_stopped_making_highs": False,
        "hour_price_stopped_making_lows": False,
    }
    closed_rows = hourly_klines[:-1] if hourly_klines else []
    if len(closed_rows) < 3:
        return metrics

    prior_two = closed_rows[-3:-1]
    latest = closed_rows[-1]
    if any(not isinstance(row, list) or len(row) < 7 for row in [*prior_two, latest]):
        return metrics

    latest_open = _to_float(latest[1])
    latest_high = _to_float(latest[2])
    latest_low = _to_float(latest[3])
    latest_close = _to_float(latest[4])
    previous_high = _to_float(prior_two[-1][2])
    previous_low = _to_float(prior_two[-1][3])
    prior_highs = [_to_float(row[2]) for row in prior_two]
    prior_lows = [_to_float(row[3]) for row in prior_two]
    valid_prices = all(
        math.isfinite(value)
        for value in [latest_open, latest_high, latest_low, latest_close, previous_high, previous_low, *prior_highs, *prior_lows]
    )
    if not valid_prices:
        return metrics

    prior_swing_high = max(prior_highs)
    prior_swing_low = min(prior_lows)
    metrics.update(
        {
            "hour_candle_open": latest_open,
            "hour_candle_high": latest_high,
            "hour_candle_low": latest_low,
            "hour_candle_close": latest_close,
            "hour_previous_high": previous_high,
            "hour_previous_low": previous_low,
            "hour_prior_2h_swing_high": prior_swing_high,
            "hour_prior_2h_swing_low": prior_swing_low,
            "hour_red_candle": latest_close < latest_open,
            "hour_green_candle": latest_close > latest_open,
            "hour_bearish_breakdown": latest_close < prior_swing_low,
            "hour_bullish_breakout": latest_close > prior_swing_high,
            "hour_price_stopped_making_highs": latest_high <= previous_high,
            "hour_price_stopped_making_lows": latest_low >= previous_low,
        }
    )
    return metrics


def _state_matches_position(
    state: dict[str, Any],
    *,
    symbol: str,
    side: str,
    entry_price: float,
) -> bool:
    if state.get("status") != "open":
        return False
    if str(state.get("symbol") or "").upper() != symbol.upper():
        return False
    if str(state.get("position_side") or "").upper() != side.upper():
        return False
    state_entry = _to_float(state.get("entry_price"))
    if math.isfinite(state_entry) and math.isfinite(entry_price):
        return math.isclose(state_entry, entry_price, rel_tol=1e-8, abs_tol=1e-12)
    return True


def evaluate_close_decision(
    *,
    symbol: str,
    position: dict[str, Any],
    short_metrics: dict[str, Any],
    config: ShortRocCloseConfig,
    open_orders: list[dict[str, Any]] | None = None,
    signal_state: dict[str, Any] | None = None,
    scanned_at: datetime | None = None,
) -> CloseDecision:
    scanned_at = scanned_at or _now_utc()
    amount = _to_float(position.get("positionAmt"))
    unrealized = _to_float(position.get("unRealizedProfit"))
    if not math.isfinite(unrealized):
        unrealized = _to_float(position.get("unrealizedProfit"))
    profit_pct = _profit_pct(position)
    roc_pct = _to_float(short_metrics.get("short_account_roc_1h_pct"))
    roc_pp = _to_float(short_metrics.get("short_account_roc_1h_pp"))
    current_short = _to_float(short_metrics.get("short_account_pct"))
    previous_short = _to_float(short_metrics.get("short_account_previous_1h_pct"))
    position_side = _position_side(position)
    entry_price = _to_float(position.get("entryPrice"))
    breakeven_stop_found = _has_breakeven_stop(position, open_orders or [], config.breakeven_tolerance_pct)

    previous_state = signal_state or {}
    state_matches = _state_matches_position(
        previous_state,
        symbol=symbol,
        side=position_side,
        entry_price=entry_price,
    )
    previous_peak = _to_float(previous_state.get("short_account_peak_pct")) if state_matches else float("nan")
    peak_candidates = [value for value in (previous_peak, previous_short, current_short) if math.isfinite(value)]
    short_peak = max(peak_candidates) if peak_candidates else float("nan")
    short_peak_drawdown = short_peak - current_short if math.isfinite(short_peak) and math.isfinite(current_short) else float("nan")

    sample_id = str(short_metrics.get("short_account_sample_id") or short_metrics.get("short_account_timestamp") or "").strip()
    pct_trigger = math.isfinite(roc_pct) and roc_pct <= -abs(config.trigger_short_roc_pct)
    pp_trigger = math.isfinite(roc_pp) and roc_pp <= -abs(config.trigger_short_roc_pp)
    unwind_trigger = pct_trigger or pp_trigger

    armed = bool(previous_state.get("short_unwind_armed")) if state_matches else False
    armed_at = str(previous_state.get("short_unwind_armed_at") or "") if armed else ""
    armed_sample_id = str(previous_state.get("short_unwind_armed_sample_id") or "") if armed else ""
    armed_short = _to_float(previous_state.get("short_unwind_armed_short_pct")) if armed else float("nan")
    confirmation_count = int(_to_float(previous_state.get("short_unwind_confirmation_count"))) if state_matches and math.isfinite(_to_float(previous_state.get("short_unwind_confirmation_count"))) else 0
    last_counted_sample_id = str(previous_state.get("short_unwind_last_counted_sample_id") or "") if state_matches else ""
    new_hourly_sample = bool(sample_id and sample_id != last_counted_sample_id)

    if unwind_trigger:
        if not armed:
            armed = True
            armed_at = scanned_at.strftime("%Y-%m-%d %H:%M:%S UTC")
            armed_sample_id = sample_id
            armed_short = current_short
            confirmation_count = 1
            last_counted_sample_id = sample_id
        elif new_hourly_sample:
            rebound_limit = armed_short + abs(config.short_rebound_tolerance_pp) if math.isfinite(armed_short) else float("nan")
            if math.isfinite(current_short) and math.isfinite(rebound_limit) and current_short > rebound_limit:
                armed_at = scanned_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                armed_sample_id = sample_id
                armed_short = current_short
                confirmation_count = 1
            else:
                confirmation_count = max(1, confirmation_count) + 1
                if math.isfinite(current_short):
                    armed_short = min(armed_short, current_short) if math.isfinite(armed_short) else current_short
            last_counted_sample_id = sample_id
    elif armed and new_hourly_sample:
        rebound_limit = armed_short + abs(config.short_rebound_tolerance_pp) if math.isfinite(armed_short) else float("nan")
        if math.isfinite(current_short) and math.isfinite(rebound_limit) and current_short <= rebound_limit:
            confirmation_count = max(1, confirmation_count) + 1
            last_counted_sample_id = sample_id
        else:
            armed = False
            armed_at = ""
            armed_sample_id = ""
            armed_short = float("nan")
            confirmation_count = 0
            last_counted_sample_id = sample_id

    level_condition = math.isfinite(current_short) and current_short <= config.short_account_exit_level_pct
    peak_condition = math.isfinite(short_peak_drawdown) and short_peak_drawdown >= config.short_account_peak_drawdown_pp
    structure_condition = level_condition or peak_condition

    oi_change_pct = _to_float(short_metrics.get("open_interest_change_pct"))
    volume_roc_pct = _to_float(short_metrics.get("hour_volume_roc_1h_pct"))
    if position_side == "SHORT":
        price_confirmation = bool(short_metrics.get("hour_bullish_breakout"))
        price_stalled = bool(short_metrics.get("hour_price_stopped_making_lows"))
        volume_reversal_candle = bool(short_metrics.get("hour_green_candle"))
        price_confirmation_label = "1h bullish breakout"
    else:
        price_confirmation = bool(short_metrics.get("hour_bearish_breakdown"))
        price_stalled = bool(short_metrics.get("hour_price_stopped_making_highs"))
        volume_reversal_candle = bool(short_metrics.get("hour_red_candle"))
        price_confirmation_label = "1h bearish breakdown"
    oi_confirmation = (
        math.isfinite(oi_change_pct)
        and oi_change_pct <= -abs(config.oi_drop_confirmation_pct)
        and price_stalled
    )
    volume_confirmation = (
        math.isfinite(volume_roc_pct)
        and volume_roc_pct >= abs(config.volume_spike_confirmation_pct)
        and volume_reversal_candle
    )
    market_confirmations = []
    if price_confirmation:
        market_confirmations.append(price_confirmation_label)
    if oi_confirmation:
        market_confirmations.append("OI flush + stalled price")
    if volume_confirmation:
        market_confirmations.append("high-volume reversal candle")
    market_confirmation = bool(market_confirmations)
    reading_confirmation = confirmation_count >= max(1, config.confirmation_readings)
    confirmation_condition = market_confirmation or reading_confirmation

    if not armed:
        signal_stage = "unarmed"
    elif not structure_condition:
        signal_stage = "armed_wait_structure"
    elif not confirmation_condition:
        signal_stage = "armed_wait_confirmation"
    else:
        signal_stage = "confirmed"

    row: dict[str, Any] = {
        "scanned_at": scanned_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "symbol": symbol.upper(),
        "position_side": position_side,
        "position_amt": amount,
        "entry_price": entry_price,
        "mark_price": _to_float(position.get("markPrice")),
        "unrealized_profit": unrealized,
        "profit_pct": profit_pct,
        "short_account_previous_1h_pct": previous_short,
        "short_account_pct": current_short,
        "short_account_roc_1h_pp": roc_pp,
        "short_account_roc_1h_pct": roc_pct,
        "short_account_direction": short_metrics.get("short_account_direction") or "",
        "trigger_short_roc_pct": config.trigger_short_roc_pct,
        "trigger_short_roc_pp": config.trigger_short_roc_pp,
        "short_account_exit_level_pct": config.short_account_exit_level_pct,
        "short_account_peak_drawdown_pp": config.short_account_peak_drawdown_pp,
        "oi_drop_confirmation_pct": config.oi_drop_confirmation_pct,
        "volume_spike_confirmation_pct": config.volume_spike_confirmation_pct,
        "confirmation_readings": config.confirmation_readings,
        "short_rebound_tolerance_pp": config.short_rebound_tolerance_pp,
        "short_account_sample_id": sample_id,
        "short_account_peak_pct": short_peak,
        "short_account_drawdown_from_peak_pp": short_peak_drawdown,
        "short_unwind_triggered_this_sample": unwind_trigger,
        "short_unwind_armed": armed,
        "short_unwind_armed_at": armed_at,
        "short_unwind_armed_sample_id": armed_sample_id,
        "short_unwind_armed_short_pct": armed_short,
        "short_unwind_confirmation_count": confirmation_count,
        "short_unwind_last_counted_sample_id": last_counted_sample_id,
        "short_structure_level_met": level_condition,
        "short_structure_peak_met": peak_condition,
        "short_structure_met": structure_condition,
        "exit_price_confirmation": price_confirmation,
        "exit_oi_confirmation": oi_confirmation,
        "exit_volume_confirmation": volume_confirmation,
        "exit_market_confirmation": market_confirmation,
        "exit_market_confirmation_reasons": ", ".join(market_confirmations),
        "exit_reading_confirmation": reading_confirmation,
        "exit_confirmation_met": confirmation_condition,
        "exit_signal_stage": signal_stage,
        "min_profit_usdt": config.min_profit_usdt,
        "min_profit_pct": config.min_profit_pct,
        "execution_profit_floor_pct": config.execution_profit_floor_pct,
        "require_breakeven_stop": bool(config.require_breakeven_stop),
        "block_without_breakeven_stop": bool(config.block_without_breakeven_stop),
        "breakeven_stop_found": bool(breakeven_stop_found),
        "breakeven_tolerance_pct": config.breakeven_tolerance_pct,
        "live_enabled": bool(config.live),
    }
    for key, value in short_metrics.items():
        if key not in row:
            row[key] = value

    if not math.isfinite(amount) or amount == 0:
        return CloseDecision(False, "no open position", row)
    if not math.isfinite(unrealized) or unrealized < config.min_profit_usdt:
        return CloseDecision(False, "profit guard not met", row)
    if not math.isfinite(profit_pct) or profit_pct < config.min_profit_pct:
        return CloseDecision(False, "profit percent guard not met", row)
    if config.block_without_breakeven_stop and not breakeven_stop_found:
        return CloseDecision(False, "breakeven stop guard not met", row)

    if not armed:
        return CloseDecision(False, "short unwind not armed", row)
    if not structure_condition:
        return CloseDecision(False, "short unwind armed; squeeze-fuel depletion threshold not met", row)
    if not confirmation_condition:
        return CloseDecision(False, "short unwind armed; waiting for market confirmation or a second distinct hourly reading", row)

    reason_parts = []
    if pct_trigger:
        reason_parts.append(f"short ROC {_format_pct(roc_pct)} <= -{abs(config.trigger_short_roc_pct):.2f}%")
    if pp_trigger:
        reason_parts.append(f"short delta {_format_pp(roc_pp)} <= -{abs(config.trigger_short_roc_pp):.2f}pp")
    if level_condition:
        reason_parts.append(f"short accounts {_format_pct(current_short, signed=False)} <= {config.short_account_exit_level_pct:.2f}%")
    if peak_condition:
        reason_parts.append(f"shorts {_format_pp(-short_peak_drawdown)} from observed peak")
    if market_confirmation:
        reason_parts.append("confirmation: " + ", ".join(market_confirmations))
    elif reading_confirmation:
        reason_parts.append(f"confirmation: {confirmation_count} distinct hourly readings")
    return CloseDecision(True, "; ".join(reason_parts), row, _close_order_params(symbol, position))


def fetch_decision(
    client: BinanceFuturesPublic,
    config: ShortRocCloseConfig,
    signal_state: dict[str, Any] | None = None,
) -> tuple[CloseDecision, list[str]]:
    symbol = config.symbol.upper().strip()
    errors: list[str] = []
    auto_symbol = symbol in {"AUTO", "*", ""}

    try:
        positions = client.position_information_v3(None if auto_symbol else symbol)
    except (BinanceAuthenticationError, BinanceHTTPError, requests.RequestException, RuntimeError, ValueError) as exc:
        errors.append(f"position information: {exc}")
        return _empty_decision(symbol or "AUTO", "position data unavailable; will retry", config), errors

    if auto_symbol:
        open_positions = _nonzero_positions(positions if isinstance(positions, list) else [])
        if len(open_positions) != 1:
            reason = "no open position" if not open_positions else f"auto mode found multiple open positions ({len(open_positions)})"
            return _empty_decision("AUTO", reason, config, positions=open_positions), errors
        position = open_positions[0]
        symbol = str(position.get("symbol", "")).upper().strip()
        if not symbol:
            return _empty_decision("AUTO", "auto mode found open position without symbol", config, positions=open_positions), errors
    else:
        position = _nonzero_position(positions if isinstance(positions, list) else [], symbol)

    try:
        ratio_rows = client.global_long_short_account_ratio(symbol, period="1h", limit=2)
    except (BinanceHTTPError, requests.RequestException, RuntimeError, ValueError) as exc:
        errors.append(f"short account ratio: {exc}")
        ratio_rows = []

    try:
        ticker_rows = client.ticker_24hr(symbol)
        ticker = ticker_rows[0] if isinstance(ticker_rows, list) and ticker_rows else {}
    except (AttributeError, BinanceHTTPError, requests.RequestException, RuntimeError, ValueError) as exc:
        errors.append(f"24h volume: {exc}")
        ticker = {}
    try:
        daily_klines = client.klines_1d(symbol, limit=31)
    except (AttributeError, BinanceHTTPError, requests.RequestException, RuntimeError, ValueError) as exc:
        errors.append(f"30d volume: {exc}")
        daily_klines = []
    try:
        hourly_klines = client.klines(symbol, interval="1h", limit=5) if hasattr(client, "klines") else []
    except (BinanceHTTPError, requests.RequestException, RuntimeError, ValueError) as exc:
        errors.append(f"1h volume ROC: {exc}")
        hourly_klines = []
    try:
        open_interest_rows = (
            client.open_interest_statistics(symbol, period="1h", limit=2)
            if hasattr(client, "open_interest_statistics")
            else []
        )
    except (BinanceHTTPError, requests.RequestException, RuntimeError, ValueError) as exc:
        errors.append(f"1h open interest: {exc}")
        open_interest_rows = []

    position_start_ms = _to_float(position.get("updateTime"))
    try:
        if not math.isfinite(position_start_ms) or position_start_ms <= 0:
            raise ValueError("position updateTime unavailable")
        funding_income_rows = client.income_history(
            symbol=symbol,
            start_time=int(position_start_ms),
            income_type="FUNDING_FEE",
            limit=1000,
        )
        carry_metrics = _realized_carry_metrics(
            funding_income_rows if isinstance(funding_income_rows, list) else [],
            symbol=symbol,
            position_start_ms=position_start_ms,
        )
    except (AttributeError, BinanceAuthenticationError, BinanceHTTPError, requests.RequestException, RuntimeError, ValueError) as exc:
        errors.append(f"realized carry: {exc}")
        carry_metrics = {
            "realized_carry_pnl": float("nan"),
            "realized_carry_asset": "",
            "realized_carry_event_count": 0,
            "realized_carry_since_ms": int(position_start_ms) if math.isfinite(position_start_ms) and position_start_ms > 0 else 0,
        }

    try:
        open_orders = client.open_futures_orders(symbol) if config.require_breakeven_stop or config.block_without_breakeven_stop else []
    except (BinanceAuthenticationError, BinanceHTTPError, requests.RequestException, RuntimeError, ValueError) as exc:
        errors.append(f"open orders: {exc}")
        open_orders = []
    try:
        algo_orders = client.open_futures_algo_orders(symbol) if config.require_breakeven_stop or config.block_without_breakeven_stop else []
    except (AttributeError, BinanceAuthenticationError, BinanceHTTPError, requests.RequestException, RuntimeError, ValueError) as exc:
        errors.append(f"open algo orders: {exc}")
        algo_orders = []

    metrics = _short_metrics(ratio_rows if isinstance(ratio_rows, list) else [])
    latest_short_timestamp = _latest_metric_timestamp(ratio_rows if isinstance(ratio_rows, list) else [])
    if latest_short_timestamp:
        metrics["short_account_timestamp_ms"] = latest_short_timestamp
        metrics["short_account_sample_id"] = str(latest_short_timestamp)
    metrics.update(
        _completed_hour_confirmation_metrics(
            hourly_klines if isinstance(hourly_klines, list) else [],
            open_interest_rows if isinstance(open_interest_rows, list) else [],
        )
    )
    if isinstance(algo_orders, list):
        open_orders = list(open_orders if isinstance(open_orders, list) else []) + algo_orders
    decision = evaluate_close_decision(
        symbol=symbol,
        position=position,
        short_metrics=metrics,
        config=config,
        open_orders=open_orders if isinstance(open_orders, list) else [],
        signal_state=signal_state,
    )
    decision.row["market_price"] = _to_float(ticker.get("lastPrice"))
    decision.row.update(_volume_metrics(ticker, daily_klines))
    decision.row.update(carry_metrics)
    if errors and decision.reason == "no open position" and not position:
        decision.row["data_warning"] = " | ".join(errors[:3])
    return decision, errors


def maybe_close_position(client: BinanceFuturesPublic, decision: CloseDecision, config: ShortRocCloseConfig) -> dict[str, Any] | None:
    if not decision.should_close or not decision.order_params:
        return None
    live_env = _env_value("SHORT_ROC_CLOSE_LIVE", "0").strip().lower() in {"1", "true", "yes", "y"}
    if not config.live or config.dry_run or not live_env:
        return {"dry_run": True, "order_params": decision.order_params}

    symbol = str(decision.row.get("symbol") or "").upper().strip()
    try:
        fresh_rows = client.position_information_v3(symbol)
        fresh_position = _nonzero_position(fresh_rows if isinstance(fresh_rows, list) else [], symbol)
        if not fresh_position:
            return _execution_block("fresh revalidation found no open position")

        original_amount = _to_float(decision.row.get("position_amt"))
        fresh_amount = _to_float(fresh_position.get("positionAmt"))
        if not math.isfinite(fresh_amount) or fresh_amount == 0:
            return _execution_block("fresh position amount is unavailable or flat")
        if math.isfinite(original_amount) and original_amount != 0 and (original_amount > 0) != (fresh_amount > 0):
            return _execution_block("position side changed after the close signal")

        fresh_unrealized = _to_float(fresh_position.get("unRealizedProfit"))
        if not math.isfinite(fresh_unrealized):
            fresh_unrealized = _to_float(fresh_position.get("unrealizedProfit"))
        fresh_profit_pct = _profit_pct(fresh_position)
        required_profit_usdt = max(0.0, float(config.min_profit_usdt))
        required_profit_pct = max(0.0, float(config.min_profit_pct), float(config.execution_profit_floor_pct))
        decision.row.update(
            {
                "execution_revalidated_at": _now_utc().strftime("%Y-%m-%d %H:%M:%S UTC"),
                "execution_revalidated_position_amt": fresh_amount,
                "execution_revalidated_mark_price": _to_float(fresh_position.get("markPrice")),
                "execution_revalidated_unrealized_profit": fresh_unrealized,
                "execution_revalidated_profit_pct": fresh_profit_pct,
                "execution_required_profit_usdt": required_profit_usdt,
                "execution_required_profit_pct": required_profit_pct,
            }
        )
        if not math.isfinite(fresh_unrealized) or fresh_unrealized <= required_profit_usdt:
            return _execution_block(
                f"fresh unrealized PnL {_format_number(fresh_unrealized)} is not above ${required_profit_usdt:.2f}"
            )
        if not math.isfinite(fresh_profit_pct) or fresh_profit_pct < required_profit_pct:
            return _execution_block(
                f"fresh profit {_format_pct(fresh_profit_pct)} is below protected floor {required_profit_pct:.2f}%"
            )

        depth = client.depth(symbol, limit=5)
        bids = depth.get("bids", []) if isinstance(depth, dict) else []
        asks = depth.get("asks", []) if isinstance(depth, dict) else []
        if not bids or not asks:
            return _execution_block("live order book unavailable for price-protected close")
        best_bid_text = str(bids[0][0])
        best_ask_text = str(asks[0][0])
        best_bid = _to_float(best_bid_text)
        best_ask = _to_float(best_ask_text)
        entry_price = _to_float(fresh_position.get("entryPrice"))
        if not all(math.isfinite(value) and value > 0 for value in (best_bid, best_ask, entry_price)):
            return _execution_block("live best bid/ask or entry price is invalid")

        protected_price_text = best_bid_text if fresh_amount > 0 else best_ask_text
        protected_price = best_bid if fresh_amount > 0 else best_ask
        executable_profit_pct = (
            (protected_price / entry_price - 1.0) * 100.0
            if fresh_amount > 0
            else (entry_price / protected_price - 1.0) * 100.0
        )
        executable_gross_pnl = (
            (protected_price - entry_price) * abs(fresh_amount)
            if fresh_amount > 0
            else (entry_price - protected_price) * abs(fresh_amount)
        )
        realized_carry = _to_float(decision.row.get("realized_carry_pnl"))
        carry_for_guard = realized_carry if math.isfinite(realized_carry) else 0.0
        executable_pnl_after_carry = executable_gross_pnl + carry_for_guard
        decision.row.update(
            {
                "execution_best_bid": best_bid,
                "execution_best_ask": best_ask,
                "execution_protected_price": protected_price,
                "execution_executable_profit_pct": executable_profit_pct,
                "execution_executable_gross_pnl": executable_gross_pnl,
                "execution_pnl_after_realized_carry": executable_pnl_after_carry,
            }
        )
        if executable_profit_pct < required_profit_pct:
            return _execution_block(
                f"best executable profit {_format_pct(executable_profit_pct)} is below protected floor {required_profit_pct:.2f}%"
            )
        if executable_pnl_after_carry <= required_profit_usdt:
            return _execution_block(
                f"price-protected PnL after realized carry {_format_number(executable_pnl_after_carry)} is not above ${required_profit_usdt:.2f}"
            )

        order_params = _close_order_params(symbol, fresh_position)
        order_params.update(
            {
                "type": "LIMIT",
                "timeInForce": "IOC",
                "price": protected_price_text,
                "newOrderRespType": "RESULT",
            }
        )
        order_result = client.new_futures_order(**order_params)
        result = dict(order_result) if isinstance(order_result, dict) else {"raw_result": order_result}
        result["safety_revalidated"] = True
        result["submitted_order_params"] = order_params
        return result
    except (BinanceAuthenticationError, BinanceHTTPError, requests.RequestException, RuntimeError, TypeError, ValueError) as exc:
        return _execution_block(f"execution revalidation failed: {exc}")


def _execution_block(reason: str) -> dict[str, Any]:
    return {
        "safety_blocked": True,
        "status": "BLOCKED",
        "reason": str(reason),
    }


def _executed_quantity(order_result: dict[str, Any] | None) -> float:
    if not order_result or order_result.get("dry_run") or order_result.get("safety_blocked"):
        return 0.0
    value = _to_float(order_result.get("executedQty"))
    if math.isfinite(value) and value > 0:
        return value
    return 1.0 if str(order_result.get("status") or "").upper() == "FILLED" else 0.0


def _order_fully_filled(order_result: dict[str, Any] | None) -> bool:
    return bool(
        order_result
        and not order_result.get("dry_run")
        and not order_result.get("safety_blocked")
        and str(order_result.get("status") or "").upper() == "FILLED"
    )


def build_discord_payload(decision: CloseDecision, errors: list[str], order_result: dict[str, Any] | None = None) -> dict[str, Any]:
    row = decision.row
    symbol = str(row.get("symbol", "")).upper()
    base = _base_asset(symbol) or symbol
    action = (
        "EXECUTION BLOCKED"
        if order_result and order_result.get("safety_blocked")
        else "CLOSE TRIGGER"
        if decision.should_close
        else "ARMED / WAIT"
        if row.get("short_unwind_armed")
        else "monitor"
    )
    order_text = ""
    if order_result:
        order_label = "BLOCKED " if order_result.get("safety_blocked") else "DRY RUN " if order_result.get("dry_run") else "LIVE "
        order_text = "\nOrder: " + order_label + json.dumps(order_result, default=str)[:700]
    warning_text = ""
    if errors:
        warning_text = "\nWarnings: " + " | ".join(str(error)[:160] for error in errors[:3])
    decision_text = str(order_result.get("reason")) if order_result and order_result.get("safety_blocked") else decision.reason
    description = (
        f"{base} short-ROC position close monitor\n"
        f"Source: Binance Futures public + signed account data | Detected: {_now_label()}\n"
        f"Rule: arm at short ROC <= -{_format_number(row.get('trigger_short_roc_pct'))}% | "
        f"fuel depleted at shorts <= {_format_pct(row.get('short_account_exit_level_pct'), signed=False)} "
        f"or {_format_number(row.get('short_account_peak_drawdown_pp'))}pp below peak.\n"
        f"Confirm with hourly price/OI/volume structure or "
        f"{int(_to_float(row.get('confirmation_readings'))) if math.isfinite(_to_float(row.get('confirmation_readings'))) else 0} distinct hourly short samples.\n\n"
        f"Market price: ${_format_number(row.get('market_price'))}\n"
        f"/{symbol} | {row.get('position_side')} amt {_format_number(row.get('position_amt'))} | "
        f"entry {_format_number(row.get('entry_price'))} | mark {_format_number(row.get('mark_price'))}\n"
        f"Unrealized PnL ${_format_number(row.get('unrealized_profit'))} / {_format_pct(row.get('profit_pct'))} | "
        f"guard >= ${_format_number(row.get('min_profit_usdt'))} and {_format_pct(row.get('min_profit_pct'))}\n"
        f"Execution floor: {_format_pct(row.get('execution_profit_floor_pct'), signed=False)} | "
        f"fresh PnL ${_format_number(row.get('execution_revalidated_unrealized_profit'))} / "
        f"{_format_pct(row.get('execution_revalidated_profit_pct'))} | protected executable {_format_pct(row.get('execution_executable_profit_pct'))}\n"
        f"Realized Carry PnL ${_format_number(row.get('realized_carry_pnl'))} "
        f"{row.get('realized_carry_asset') or ''} | funding events {int(_to_float(row.get('realized_carry_event_count'))) if math.isfinite(_to_float(row.get('realized_carry_event_count'))) else 0}\n"
        f"BE stop check: {'hard block' if row.get('block_without_breakeven_stop') else 'warning' if row.get('require_breakeven_stop') else 'off'} | "
        f"found={row.get('breakeven_stop_found')} | tolerance {_format_pct(row.get('breakeven_tolerance_pct'))}\n"
        f"short {_format_pct(row.get('short_account_previous_1h_pct'), signed=False)} -> "
        f"{_format_pct(row.get('short_account_pct'), signed=False)} | "
        f"delta {_format_pp(row.get('short_account_roc_1h_pp'))} / {_format_pct(row.get('short_account_roc_1h_pct'))} | "
        f"{row.get('short_account_direction') or 'n/a'}\n"
        f"Exit state: {row.get('exit_signal_stage') or 'n/a'} | armed={bool(row.get('short_unwind_armed'))} | "
        f"hourly reads {int(_to_float(row.get('short_unwind_confirmation_count'))) if math.isfinite(_to_float(row.get('short_unwind_confirmation_count'))) else 0}/"
        f"{int(_to_float(row.get('confirmation_readings'))) if math.isfinite(_to_float(row.get('confirmation_readings'))) else 0}\n"
        f"Short peak {_format_pct(row.get('short_account_peak_pct'), signed=False)} | "
        f"drawdown {_format_pp(-_to_float(row.get('short_account_drawdown_from_peak_pp')))} | "
        f"level={bool(row.get('short_structure_level_met'))} peak={bool(row.get('short_structure_peak_met'))}\n"
        f"Confirmations: price={bool(row.get('exit_price_confirmation'))} | "
        f"OI={bool(row.get('exit_oi_confirmation'))} ({_format_pct(row.get('open_interest_change_pct'))}) | "
        f"volume={bool(row.get('exit_volume_confirmation'))} | "
        f"{row.get('exit_market_confirmation_reasons') or 'none'}\n"
        f"Volume: 24h ${_format_number(row.get('quote_volume_24h_usdt'))} | "
        f"prior 30D ${_format_number(row.get('quote_volume_prior_30d_total_usdt'))} "
        f"({int(_to_float(row.get('quote_volume_prior_30d_days'))) if math.isfinite(_to_float(row.get('quote_volume_prior_30d_days'))) else 0} closed days)\n"
        f"Prior daily avg ${_format_number(row.get('quote_volume_prior_30d_daily_avg_usdt'))} | "
        f"24h / prior avg {_format_number(row.get('quote_volume_24h_vs_prior_30d_avg_ratio'), suffix='x')}\n"
        f"1H quote volume ${_format_number(row.get('hour_quote_volume'))} | previous ${_format_number(row.get('hour_quote_volume_previous_1h'))} | "
        f"1H volume ROC {_format_pct(row.get('hour_volume_roc_1h_pct'))}\n"
        f"Decision: {action} | {decision_text}"
        f"{order_text}{warning_text}"
    )
    return {
        "username": f"{base} Short ROC Close",
        "embeds": [
            {
                "title": f"{symbol} short-ROC close monitor",
                "description": description[:3900],
                "color": 0xEF4444 if decision.should_close else 0xF59E0B if row.get("short_unwind_armed") else 0x64748B,
                "footer": {"text": DISCORD_FOOTER},
            }
        ],
    }


def build_external_close_payload(close_event: dict[str, Any]) -> dict[str, Any]:
    symbol = str(close_event.get("symbol") or "UNKNOWN").upper()
    base = _base_asset(symbol) or symbol
    replacement = ""
    if close_event.get("replacement_symbol"):
        replacement = (
            f"\nCurrent position: /{close_event.get('replacement_symbol')} "
            f"{close_event.get('replacement_side') or 'UNKNOWN'}"
        )
    description = (
        f"{base} manual/external position close detected\n"
        f"Source: signed Binance Futures account data | Detected: {close_event.get('detected_closed_at') or _now_label()}\n"
        "The position was open on the prior successful check and is no longer open. "
        "This detects a close made manually, by another bot, by a stop, or by another exchange client.\n\n"
        f"/{symbol} | previously {close_event.get('position_side') or 'UNKNOWN'} "
        f"amt {_format_number(close_event.get('position_amt'))}\n"
        f"Entry {_format_number(close_event.get('entry_price'))} | "
        f"last mark {_format_number(close_event.get('mark_price'))}\n"
        f"Last Unrealized PnL ${_format_number(close_event.get('unrealized_profit'))} / "
        f"{_format_pct(close_event.get('profit_pct'))}\n"
        f"Last Realized Carry PnL ${_format_number(close_event.get('realized_carry_pnl'))}\n"
        f"Last short accounts {_format_pct(close_event.get('short_account_pct'), signed=False)} | "
        f"1h ROC {_format_pct(close_event.get('short_account_roc_1h_pct'))}\n"
        f"Last 1H volume ROC {_format_pct(close_event.get('hour_volume_roc_1h_pct'))}\n"
        f"Last seen: {close_event.get('last_seen_at') or 'n/a'} | "
        f"Transition: {close_event.get('close_transition') or 'position no longer open'}"
        f"{replacement}"
    )
    last_profit = _to_float(close_event.get("unrealized_profit"))
    color = 0x22C55E if math.isfinite(last_profit) and last_profit >= 0 else 0xEF4444
    return {
        "username": f"{base} Position Close",
        "embeds": [
            {
                "title": f"{symbol} CLOSE DETECTED",
                "description": description[:3900],
                "color": color,
                "footer": {"text": DISCORD_FOOTER},
            }
        ],
    }


def _post_payload(payload: dict[str, Any], config: ShortRocCloseConfig) -> None:
    if config.dry_run:
        print("DRY RUN webhook payload:")
        print(json.dumps(payload, indent=2, default=str))
        return
    if not config.webhook_url:
        raise RuntimeError("SHORT_ROC_CLOSE_DISCORD_WEBHOOK_URL or DISCORD_WEBHOOK_URL is not set.")
    response = requests.post(config.webhook_url, json=payload, timeout=15)
    if response.status_code >= 300:
        raise RuntimeError(f"Discord webhook HTTP {response.status_code}: {response.text[:250]}")


def _post_webhook(decision: CloseDecision, errors: list[str], order_result: dict[str, Any] | None, config: ShortRocCloseConfig) -> None:
    _post_payload(build_discord_payload(decision, errors, order_result), config)


def _write_outputs(decision: CloseDecision, errors: list[str], order_result: dict[str, Any] | None, config: ShortRocCloseConfig) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    prefix = _output_prefix(decision.row.get("symbol") or config.symbol)
    row = dict(decision.row)
    row["should_close"] = decision.should_close
    row["decision_reason"] = decision.reason
    row["order_result"] = json.dumps(order_result or {}, default=str)
    row["errors"] = " | ".join(errors)

    latest_path = config.output_dir / f"{prefix}_short_roc_close_latest.csv"
    history_path = config.output_dir / f"{prefix}_short_roc_close_history.csv"
    fieldnames = list(row.keys())
    with latest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)
    append_csv_row_schema_safe(history_path, row)


def _order_status(order_result: dict[str, Any] | None) -> str:
    if not order_result:
        return ""
    if order_result.get("dry_run"):
        return "DRY_RUN"
    if order_result.get("safety_blocked"):
        return "BLOCKED"
    status = str(order_result.get("status") or "").upper().strip()
    return status or "SENT"


def _write_closed_trade_ledger(decision: CloseDecision, order_result: dict[str, Any] | None, config: ShortRocCloseConfig) -> None:
    if not decision.should_close or not order_result or _executed_quantity(order_result) <= 0:
        return
    config.output_dir.mkdir(parents=True, exist_ok=True)
    prefix = _output_prefix(decision.row.get("symbol") or config.symbol)
    path = config.output_dir / f"{prefix}_closed_trades.csv"
    row = dict(decision.row)
    params = order_result.get("submitted_order_params") or decision.order_params or {}
    row.update(
        {
            "closed_at": _now_utc().strftime("%Y-%m-%d %H:%M:%S UTC"),
            "decision_reason": decision.reason,
            "order_status": _order_status(order_result),
            "order_id": order_result.get("orderId", ""),
            "client_order_id": order_result.get("clientOrderId", order_result.get("clientOrderId", "")),
            "close_side": params.get("side", ""),
            "close_quantity": params.get("quantity", ""),
            "dry_run": bool(order_result.get("dry_run")),
            "avg_price": order_result.get("avgPrice", ""),
            "executed_qty": order_result.get("executedQty", ""),
            "cum_quote": order_result.get("cumQuote", ""),
            "raw_order_result": json.dumps(order_result, default=str),
        }
    )
    fieldnames = list(row.keys())
    file_exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def _write_external_close_ledger(close_event: dict[str, Any], config: ShortRocCloseConfig) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    prefix = _output_prefix(close_event.get("symbol") or config.symbol)
    path = config.output_dir / f"{prefix}_external_closes.csv"
    fieldnames = list(close_event.keys())
    file_exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(close_event)


def run_once(config: ShortRocCloseConfig) -> tuple[CloseDecision, list[str], dict[str, Any] | None]:
    client = BinanceFuturesPublic(
        base_url=config.base_url,
        timeout=config.timeout,
        requests_per_second=config.requests_per_second,
        retries=config.retries,
        api_key=config.api_key,
        api_secret=config.api_secret,
    )
    previous_state = _load_position_state(config)
    decision, errors = fetch_decision(client, config, signal_state=previous_state)
    external_close = _detect_external_close(previous_state, decision, errors)
    current_snapshot = _position_snapshot(decision)
    order_result = maybe_close_position(client, decision, config)
    _write_outputs(decision, errors, order_result, config)
    _write_closed_trade_ledger(decision, order_result, config)
    detected_symbol = str(decision.row.get("symbol") or config.symbol).upper()
    print(
        f"[{_now_label()}] {config.symbol.upper()} close-monitor symbol={detected_symbol} "
        f"should_close={decision.should_close} "
        f"reason={decision.reason} unrealized_pnl={_format_number(decision.row.get('unrealized_profit'))} "
        f"realized_carry_pnl={_format_number(decision.row.get('realized_carry_pnl'))} "
        f"short={_format_pct(decision.row.get('short_account_previous_1h_pct'), signed=False)}"
        f"->{_format_pct(decision.row.get('short_account_pct'), signed=False)} "
        f"short_roc={_format_pct(decision.row.get('short_account_roc_1h_pct'))} "
        f"stage={decision.row.get('exit_signal_stage') or 'n/a'} "
        f"armed={bool(decision.row.get('short_unwind_armed'))} "
        f"short_peak={_format_pct(decision.row.get('short_account_peak_pct'), signed=False)} "
        f"peak_drawdown={_format_pp(-_to_float(decision.row.get('short_account_drawdown_from_peak_pp')))} "
        f"confirm_reads={decision.row.get('short_unwind_confirmation_count', 0)}/{config.confirmation_readings} "
        f"market_confirm={bool(decision.row.get('exit_market_confirmation'))} "
        f"oi_roc={_format_pct(decision.row.get('open_interest_change_pct'))} "
        f"vol24=${_format_number(decision.row.get('quote_volume_24h_usdt'))} "
        f"vol30avg=${_format_number(decision.row.get('quote_volume_prior_30d_daily_avg_usdt'))} "
        f"vol_ratio={_format_number(decision.row.get('quote_volume_24h_vs_prior_30d_avg_ratio'), suffix='x')} "
        f"vol_roc_1h={_format_pct(decision.row.get('hour_volume_roc_1h_pct'))} "
        f"execution={_order_status(order_result) or 'NONE'} "
        f"live={config.live}",
        flush=True,
    )
    if external_close:
        _post_payload(build_external_close_payload(external_close), config)
        _write_external_close_ledger(external_close, config)
        print(
            f"[{_now_label()}] {external_close.get('symbol')} CLOSE DETECTED "
            f"source=manual_or_external transition={external_close.get('close_transition')}",
            flush=True,
        )

    if _position_data_available(decision, errors):
        if _order_fully_filled(order_result):
            closed_state = {
                **(current_snapshot or previous_state),
                "status": "closed",
                "close_source": "bot",
                "detected_closed_at": _now_utc().strftime("%Y-%m-%d %H:%M:%S UTC"),
            }
            _write_position_state(closed_state, config)
        elif current_snapshot:
            _write_position_state(current_snapshot, config)
        elif external_close or decision.reason == "no open position":
            _write_position_state(
                external_close
                or {
                    "status": "flat",
                    "symbol": str(decision.row.get("symbol") or config.symbol).upper(),
                    "last_checked_at": _now_utc().strftime("%Y-%m-%d %H:%M:%S UTC"),
                },
                config,
            )

    _post_webhook(decision, errors, order_result, config)
    return decision, errors, order_result


def run_forever(config: ShortRocCloseConfig) -> None:
    while True:
        try:
            _, _, order_result = run_once(config)
        except KeyboardInterrupt:
            print(f"[{_now_label()}] stopped by user", flush=True)
            return
        except Exception as exc:
            print(f"[{_now_label()}] {config.symbol.upper()} close monitor cycle failed: {exc}", flush=True)
            order_result = None
        if config.close_once and _order_fully_filled(order_result):
            print(f"[{_now_label()}] live close order sent; close-once enabled, stopping monitor", flush=True)
            return
        if config.once:
            return
        time.sleep(max(30.0, float(config.interval_seconds)))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Close a profitable Binance futures position when short-account ROC rolls over.")
    parser.add_argument("--once", action="store_true", help="Run one scan and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Print webhook payload and never place an order.")
    parser.add_argument("--live", action="store_true", help="Allow live close orders, also requires SHORT_ROC_CLOSE_LIVE=1.")
    parser.add_argument("--symbol", default=_env_value("SHORT_ROC_CLOSE_SYMBOL", "LABUSDT"), help="Symbol to monitor.")
    parser.add_argument("--trigger-short-roc-pct", type=float, default=float(_env_value("SHORT_ROC_CLOSE_TRIGGER_PCT", "4.0")), help="Arm the exit when 1h short-account ROC falls by at least this relative percent.")
    parser.add_argument("--trigger-short-roc-pp", type=float, default=float(_env_value("SHORT_ROC_CLOSE_TRIGGER_PP", "999")), help="Alternative arming threshold in short-account percentage points; 999 effectively disables it.")
    parser.add_argument("--short-exit-level-pct", type=float, default=float(_env_value("SHORT_ROC_CLOSE_SHORT_LEVEL_PCT", "65")), help="Require short accounts at or below this level, unless the peak-drawdown condition is met.")
    parser.add_argument("--short-peak-drawdown-pp", type=float, default=float(_env_value("SHORT_ROC_CLOSE_PEAK_DRAWDOWN_PP", "5")), help="Require short accounts to be this many percentage points below their observed position peak, unless the absolute level condition is met.")
    parser.add_argument("--oi-drop-confirmation-pct", type=float, default=float(_env_value("SHORT_ROC_CLOSE_OI_DROP_CONFIRMATION_PCT", "8")), help="Confirm an exit when hourly OI falls by at least this percent and price stops making directional extremes.")
    parser.add_argument("--volume-spike-confirmation-pct", type=float, default=float(_env_value("SHORT_ROC_CLOSE_VOLUME_CONFIRMATION_PCT", "50")), help="Confirm an exit on a reversal candle when completed 1h quote-volume ROC reaches this percent.")
    parser.add_argument("--confirmation-readings", type=int, default=int(_env_value("SHORT_ROC_CLOSE_CONFIRMATION_READINGS", "2")), help="Distinct hourly short-account samples that can confirm an armed unwind when no market confirmation is present.")
    parser.add_argument("--short-rebound-tolerance-pp", type=float, default=float(_env_value("SHORT_ROC_CLOSE_REBOUND_TOLERANCE_PP", "0.5")), help="Maximum short-account rebound from the armed level while waiting for another hourly confirmation.")
    parser.add_argument("--min-profit-usdt", type=float, default=float(_env_value("SHORT_ROC_CLOSE_MIN_PROFIT_USDT", "0")), help="Minimum unrealized profit in USDT before close can trigger.")
    parser.add_argument("--min-profit-pct", type=float, default=float(_env_value("SHORT_ROC_CLOSE_MIN_PROFIT_PCT", "0")), help="Minimum position profit percent before close can trigger.")
    parser.add_argument("--execution-profit-floor-pct", type=float, default=float(_env_value("SHORT_ROC_CLOSE_EXECUTION_PROFIT_FLOOR_PCT", "0.25")), help="Hard minimum executable gross profit percent required immediately before a protected close order.")
    parser.add_argument("--require-breakeven-stop", action="store_true", help="Check and report whether a stop order near breakeven exists before closing.")
    parser.add_argument("--block-without-breakeven-stop", action="store_true", help="Hard-block closes when the breakeven stop check is not found.")
    parser.add_argument("--breakeven-tolerance-pct", type=float, default=float(_env_value("SHORT_ROC_CLOSE_BREAKEVEN_TOLERANCE_PCT", "1.0")), help="Allowed distance below long entry or above short entry for the breakeven stop check.")
    parser.add_argument("--no-close-once", action="store_true", help="Keep running after a live close order is sent.")
    parser.add_argument("--interval-seconds", type=float, default=float(_env_value("SHORT_ROC_CLOSE_INTERVAL_SECONDS", "300")), help="Seconds between checks.")
    parser.add_argument("--requests-per-second", type=float, default=float(_env_value("SHORT_ROC_CLOSE_REQUESTS_PER_SECOND", "2")), help="Binance request pace.")
    parser.add_argument("--timeout", type=int, default=int(_env_value("SHORT_ROC_CLOSE_HTTP_TIMEOUT", "12")), help="HTTP timeout in seconds.")
    parser.add_argument("--retries", type=int, default=int(_env_value("SHORT_ROC_CLOSE_HTTP_RETRIES", "3")), help="HTTP retry attempts.")
    parser.add_argument("--base-url", default=_env_value("BINANCE_FAPI_BASE_URL", "https://fapi.binance.com"), help="Binance futures API base URL.")
    parser.add_argument("--output-dir", default=_env_value("SHORT_ROC_CLOSE_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)), help="Directory for local CSV snapshots.")
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> ShortRocCloseConfig:
    return ShortRocCloseConfig(
        symbol=str(args.symbol).upper().strip(),
        base_url=str(args.base_url),
        timeout=int(args.timeout),
        retries=int(args.retries),
        requests_per_second=float(args.requests_per_second),
        interval_seconds=float(args.interval_seconds),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        webhook_url=_env_value("SHORT_ROC_CLOSE_DISCORD_WEBHOOK_URL", _env_value("DISCORD_WEBHOOK_URL", "")),
        once=bool(args.once),
        dry_run=bool(args.dry_run),
        live=bool(args.live),
        trigger_short_roc_pct=abs(float(args.trigger_short_roc_pct)),
        trigger_short_roc_pp=abs(float(args.trigger_short_roc_pp)),
        short_account_exit_level_pct=float(args.short_exit_level_pct),
        short_account_peak_drawdown_pp=abs(float(args.short_peak_drawdown_pp)),
        oi_drop_confirmation_pct=abs(float(args.oi_drop_confirmation_pct)),
        volume_spike_confirmation_pct=abs(float(args.volume_spike_confirmation_pct)),
        confirmation_readings=max(1, int(args.confirmation_readings)),
        short_rebound_tolerance_pp=abs(float(args.short_rebound_tolerance_pp)),
        min_profit_usdt=float(args.min_profit_usdt),
        min_profit_pct=float(args.min_profit_pct),
        execution_profit_floor_pct=max(0.0, float(args.execution_profit_floor_pct)),
        require_breakeven_stop=bool(args.require_breakeven_stop),
        block_without_breakeven_stop=bool(args.block_without_breakeven_stop),
        breakeven_tolerance_pct=abs(float(args.breakeven_tolerance_pct)),
        close_once=not bool(args.no_close_once),
        api_key=_env_value("BINANCE_API_KEY", _env_value("BINANCE_FUTURES_API_KEY", "")),
        api_secret=_env_value("BINANCE_API_SECRET", _env_value("BINANCE_FUTURES_API_SECRET", "")),
    )


def main(argv: list[str] | None = None) -> None:
    _load_local_env()
    config = config_from_args(parse_args(argv))
    print(
        f"[{_now_label()}] starting short-ROC close monitor | symbol={config.symbol} "
        f"interval={config.interval_seconds:.0f}s arm=-{config.trigger_short_roc_pct:.2f}% "
        f"short_level<={config.short_account_exit_level_pct:.2f}% "
        f"peak_drawdown>={config.short_account_peak_drawdown_pp:.2f}pp "
        f"confirmations={config.confirmation_readings} "
        f"execution_floor={config.execution_profit_floor_pct:.2f}% "
        f"live={config.live} output={config.output_dir}",
        flush=True,
    )
    run_forever(config)


if __name__ == "__main__":
    main()
