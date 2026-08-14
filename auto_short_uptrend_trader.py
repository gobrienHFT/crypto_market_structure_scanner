from __future__ import annotations

import argparse
import json
import math
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from binance_futures import (
    BinanceFuturesPublic,
    BinanceHTTPError,
)
from inx_hourly_monitor import _env_value, _load_local_env, _now_label
from scan_orchestrator import run_scanner_scan
from short_account_roc import short_account_history_stats
from short_roc_position_close import (
    CloseDecision,
    ShortRocCloseConfig,
    _completed_hour_confirmation_metrics,
    _executed_quantity,
    _position_snapshot,
    evaluate_close_decision,
)
from venue_gate import (
    binance_bitget_venue_mask,
    effective_top10_holder_pct,
    holder_evidence_mask,
    holder_storage_false_positive_mask,
)
from volume_metrics import append_csv_row_schema_safe, closed_hour_volume_metrics


APP_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = APP_DIR / "auto_short_uptrend_trader_output"
TRADFI_MARKET_TYPES = {"COMMODITY", "EQUITY"}
ACTIVE_ALGO_STATUSES = {"NEW", "WORKING", "PENDING_NEW", "PARTIALLY_FILLED"}


def _env_bool(name: str, default: bool = False) -> bool:
    fallback = "1" if default else "0"
    return _env_value(name, fallback).strip().lower() in {"1", "true", "yes", "y", "on"}


def _to_float(value: Any) -> float:
    try:
        parsed = float(value)
    except Exception:
        return float("nan")
    return parsed if math.isfinite(parsed) else float("nan")


def _finite(value: Any) -> bool:
    return math.isfinite(_to_float(value))


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _now_iso() -> str:
    return _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_key() -> str:
    return _now_utc().strftime("%Y-%m-%d")


def _week_key() -> str:
    year, week, _ = _now_utc().isocalendar()
    return f"{year}-W{week:02d}"


def _fmt_decimal(value: Decimal | float | int, places: int = 12) -> str:
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    text = f"{decimal_value:.{places}f}".rstrip("0").rstrip(".")
    return text or "0"


def _fmt_money(value: Any) -> str:
    parsed = _to_float(value)
    return "n/a" if not math.isfinite(parsed) else f"${parsed:,.2f}"


def _fmt_pct(value: Any, *, signed: bool = True) -> str:
    parsed = _to_float(value)
    if not math.isfinite(parsed):
        return "n/a"
    prefix = "+" if signed and parsed > 0 else ""
    return f"{prefix}{parsed:.2f}%"


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _json_safe(value: Any) -> Any:
    if value is pd.NA:
        return None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            pass
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_json_safe(value), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _series(frame: pd.DataFrame, column: str, default: float = float("nan")) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _bool_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index, dtype=bool)
    return frame[column].map(_is_true).fillna(False).astype(bool)


def _linear_score(series: pd.Series, low: float, high: float) -> pd.Series:
    if high <= low:
        return pd.Series(0.0, index=series.index, dtype="float64")
    return ((series - low) / (high - low) * 100.0).clip(lower=0.0, upper=100.0).fillna(0.0)


def _max_series(frame: pd.DataFrame, columns: tuple[str, ...], default: float = 0.0) -> pd.Series:
    parts = [_series(frame, column) for column in columns if column in frame.columns]
    if not parts:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.concat(parts, axis=1).max(axis=1).fillna(default)


@dataclass(frozen=True)
class AutoTraderConfig:
    mode: str
    scan_mode: str
    output_dir: Path
    webhook_url: str
    base_url: str
    api_key: str
    api_secret: str
    timeout: int
    retries: int
    requests_per_second: float
    manage_interval_seconds: float
    flat_scan_interval_seconds: float
    once: bool
    leverage: int
    risk_fraction: float
    max_stress_risk_fraction: float
    daily_loss_fraction: float
    weekly_loss_fraction: float
    drawdown_halve_fraction: float
    drawdown_pause_fraction: float
    paper_equity_usdt: float
    max_notional_fraction: float
    max_depth_fraction: float
    min_short_pct: float
    min_short_roc_pp: float
    min_smoothed_short_roc_pp: float
    min_short_persistence: int
    min_funding_pct: float
    min_hour_volume_roc_pct: float
    min_daily_volume_ratio: float
    min_quote_volume_usdt: float
    min_oi_change_pct: float
    max_late_heat_score: float
    max_price_above_avwap_pct: float
    min_top10_holder_pct: float
    min_top100_holder_pct: float
    require_holder_evidence: bool
    require_bitget_evidence: bool
    require_spot_confirmation: bool
    min_spot_flow_score: float
    candidate_limit: int
    confirmation_breakout_bars: int
    min_confirmation_close_location_pct: float
    max_short_data_age_minutes: float
    max_entry_spread_pct: float
    entry_limit_slippage_pct: float
    risk_slippage_pct: float
    round_trip_fee_pct: float
    atr_period: int
    atr_stop_multiple: float
    swing_lookback_bars: int
    swing_atr_buffer: float
    min_stop_distance_pct: float
    max_stop_distance_pct: float
    risk_reduce_trigger_r: float
    risk_reduced_stop_r: float
    breakeven_trigger_r: float
    breakeven_atr_multiple: float
    breakeven_confirmation_bars: int
    breakeven_cost_buffer_pct: float
    early_proof_hours: float
    early_proof_mfe_r: float
    max_proof_hours: float
    max_proof_mfe_r: float
    absolute_proof_timeout_hours: float
    preproof_short_drop_pp: float
    cooldown_hours: float
    short_exit_trigger_pct: float
    short_exit_level_pct: float
    short_exit_peak_drawdown_pp: float
    short_exit_confirmation_readings: int
    short_exit_partial_pct: float
    short_exit_runner_readings: int
    short_exit_runner_oi_drop_pct: float
    short_exit_runner_volume_drop_pct: float
    short_exit_execution_floor_pct: float

    @property
    def live(self) -> bool:
        return self.mode == "live"


@dataclass(frozen=True)
class SymbolRules:
    tick_size: Decimal
    qty_step: Decimal
    min_qty: Decimal
    min_notional: Decimal


@dataclass(frozen=True)
class RiskPlan:
    entry_price: Decimal
    stop_price: Decimal
    quantity: Decimal
    notional_usdt: Decimal
    initial_r_per_unit: Decimal
    planned_risk_usdt: Decimal
    stress_risk_usdt: Decimal
    stop_distance_pct: float
    bid_depth_1pct_usdt: float
    rejection_reason: str = ""


def default_state() -> dict[str, Any]:
    return {
        "version": 1,
        "position": None,
        "risk_limits": {},
        "cooldowns": {},
        "last_scan_at_ms": 0,
        "last_cycle_at": "",
        "last_message": "idle",
    }


def state_path(config: AutoTraderConfig) -> Path:
    return config.output_dir / "state.json"


def load_state(config: AutoTraderConfig) -> dict[str, Any]:
    state = default_state()
    state.update(_load_json(state_path(config)))
    if not isinstance(state.get("risk_limits"), dict):
        state["risk_limits"] = {}
    if not isinstance(state.get("cooldowns"), dict):
        state["cooldowns"] = {}
    return state


def write_state(config: AutoTraderConfig, state: dict[str, Any]) -> None:
    state["last_cycle_at"] = _now_iso()
    _atomic_json_write(state_path(config), state)


def record_event(
    config: AutoTraderConfig,
    event_type: str,
    *,
    symbol: str = "",
    message: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    row = {
        "event_id": f"{_now_ms()}_{event_type}",
        "timestamp_utc": _now_iso(),
        "mode": config.mode,
        "event_type": event_type,
        "symbol": symbol.upper().strip(),
        "message": message,
        **_json_safe(details or {}),
    }
    jsonl_path = config.output_dir / "events.jsonl"
    with jsonl_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=True, default=str, sort_keys=True) + "\n")
    append_csv_row_schema_safe(config.output_dir / "events.csv", row)
    return row


def record_trade(
    config: AutoTraderConfig,
    position: dict[str, Any],
    *,
    exit_reason: str,
    exit_price: Any,
    account_equity_after: Any,
    close_source: str,
) -> None:
    entry = _to_float(position.get("entry_price"))
    exit_value = _to_float(exit_price)
    quantity = _to_float(position.get("quantity"))
    gross_pnl = (
        (exit_value - entry) * quantity
        if all(math.isfinite(value) for value in (entry, exit_value, quantity))
        else float("nan")
    )
    equity_before = _to_float(position.get("account_equity_at_entry"))
    equity_after = _to_float(account_equity_after)
    net_account_change = (
        equity_after - equity_before
        if math.isfinite(equity_before) and math.isfinite(equity_after)
        else float("nan")
    )
    row = {
        "closed_at_utc": _now_iso(),
        "opened_at_utc": position.get("opened_at_utc"),
        "mode": config.mode,
        "symbol": position.get("symbol"),
        "entry_price": entry,
        "exit_price": exit_value,
        "quantity": quantity,
        "notional_usdt": position.get("notional_usdt"),
        "initial_stop_price": position.get("initial_stop_price"),
        "initial_r_per_unit": position.get("initial_r_per_unit"),
        "planned_risk_usdt": position.get("planned_risk_usdt"),
        "maximum_favorable_price": position.get("maximum_favorable_price"),
        "maximum_favorable_r": position.get("maximum_favorable_r"),
        "gross_price_pnl_usdt": gross_pnl,
        "net_account_change_usdt": net_account_change,
        "account_equity_before": equity_before,
        "account_equity_after": equity_after,
        "exit_reason": exit_reason,
        "close_source": close_source,
        "partial_exit_completed": position.get("partial_exit_completed", False),
    }
    append_csv_row_schema_safe(config.output_dir / "trades.csv", row)


def post_discord(
    config: AutoTraderConfig,
    title: str,
    description: str,
    *,
    color: int = 0x5865F2,
) -> None:
    if not config.webhook_url:
        return
    payload = {
        "username": "Automated Short-Uptrend Trader",
        "embeds": [
            {
                "title": title[:256],
                "description": description[:3900],
                "color": int(color),
                "timestamp": _now_utc().isoformat(),
                "footer": {"text": "Automated execution. Verify risk controls and exchange orders independently."},
            }
        ],
    }
    try:
        response = requests.post(config.webhook_url, json=payload, timeout=12)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"[{_now_label()}] Discord webhook failed: {exc}", flush=True)


def score_entry_candidates(frame: pd.DataFrame, config: AutoTraderConfig) -> pd.DataFrame:
    if frame.empty or "symbol" not in frame.columns:
        return pd.DataFrame()
    rows = frame.loc[:, ~frame.columns.duplicated()].copy()
    market_type = rows.get("market_type", pd.Series("", index=rows.index)).astype(str).str.upper()
    short_pct = _series(rows, "short_account_pct")
    short_roc_pp = _series(rows, "short_account_roc_1h_pp")
    smooth_roc_pp = _series(rows, "short_account_roc_smoothed_3p_pp")
    persistence = _series(rows, "short_account_direction_persistence", 0.0).fillna(0.0)
    funding_pct = _series(rows, "carry_funding_pct")
    hour_volume_roc = _series(rows, "hour_volume_roc_1h_pct")
    daily_volume_ratio = _series(rows, "quote_volume_24h_vs_prior_30d_avg_ratio")
    quote_volume = _series(rows, "quote_volume_24h")
    oi_change = _series(rows, "oi_delta_pct")
    avwap_distance = _series(rows, "price_vs_anchored_vwap_30d_pct")
    hour_return = _series(rows, "hour_return_pct")
    day_return = _series(rows, "day_return_pct")
    trend_score = _max_series(
        rows,
        (
            "trend_confluence_score",
            "range_breakout_score",
            "breakout_pressure_score",
            "price_volume_ignition_score",
        ),
    )
    breakout = (
        _bool_series(rows, "broke_high_5d")
        | _bool_series(rows, "broke_high_20d")
        | _bool_series(rows, "broke_high_50d")
        | _bool_series(rows, "range_breakout_high")
    )
    late_heat = _max_series(
        rows,
        (
            "timing_too_late_score",
            "convexity_late_penalty",
            "no_chase_penalty_score",
            "exit_fragility_score",
            "blowoff_unwind_score",
            "crowded_short_uptrend_late_heat_score",
        ),
    )
    top10 = effective_top10_holder_pct(rows)
    top100 = _series(rows, "top100_holder_pct")
    try:
        evidence = holder_evidence_mask(rows)
    except Exception:
        evidence = pd.Series(False, index=rows.index)
    try:
        storage_false_positive = holder_storage_false_positive_mask(
            rows,
            min_whale_pct=config.min_top10_holder_pct,
        )
    except Exception:
        storage_false_positive = pd.Series(False, index=rows.index)
    try:
        venue = binance_bitget_venue_mask(rows, allow_cex_flow_targets=False)
    except Exception:
        venue = pd.Series(False, index=rows.index)
    spot_score = _max_series(
        rows,
        ("spot_flow_confluence_score", "coinbase_spot_volume_confluence_score"),
    )

    rows["_gate_crypto"] = ~market_type.isin(TRADFI_MARKET_TYPES)
    rows["_gate_short_level"] = short_pct.ge(config.min_short_pct)
    rows["_gate_short_build"] = short_roc_pp.ge(config.min_short_roc_pp) | (
        smooth_roc_pp.ge(config.min_smoothed_short_roc_pp)
        & persistence.ge(config.min_short_persistence)
    )
    rows["_gate_actual_positive_funding"] = funding_pct.gt(config.min_funding_pct)
    rows["_gate_hour_volume"] = hour_volume_roc.ge(config.min_hour_volume_roc_pct)
    rows["_gate_daily_volume"] = daily_volume_ratio.ge(config.min_daily_volume_ratio)
    rows["_gate_liquidity"] = quote_volume.ge(config.min_quote_volume_usdt)
    rows["_gate_oi"] = oi_change.ge(config.min_oi_change_pct)
    rows["_gate_uptrend"] = (
        avwap_distance.gt(0.0)
        & avwap_distance.le(config.max_price_above_avwap_pct)
        & (breakout | trend_score.ge(45.0))
        & (hour_return.gt(0.0) | day_return.gt(0.0))
    )
    rows["_gate_not_late"] = late_heat.lt(config.max_late_heat_score)
    rows["_gate_holder"] = (
        (top10.ge(config.min_top10_holder_pct) | top100.ge(config.min_top100_holder_pct))
        & (evidence if config.require_holder_evidence else True)
        & ~storage_false_positive
    )
    rows["_gate_venue"] = venue if config.require_bitget_evidence else True
    rows["_gate_spot"] = (
        spot_score.ge(config.min_spot_flow_score)
        if config.require_spot_confirmation
        else True
    )

    gate_columns = [
        "_gate_crypto",
        "_gate_short_level",
        "_gate_short_build",
        "_gate_actual_positive_funding",
        "_gate_hour_volume",
        "_gate_daily_volume",
        "_gate_liquidity",
        "_gate_oi",
        "_gate_uptrend",
        "_gate_not_late",
        "_gate_holder",
        "_gate_venue",
        "_gate_spot",
    ]
    rows["_entry_all_gates"] = pd.concat(
        [rows[column].astype(bool) for column in gate_columns],
        axis=1,
    ).all(axis=1)
    structure_score = _max_series(
        rows,
        (
            "centralized_ownership_score",
            "low_float_score",
            "float_trap_score",
            "terminal_float_score",
            "terminal_structure_edge_score",
        ),
    )
    rows["_auto_entry_score"] = (
        _linear_score(short_pct, config.min_short_pct, 75.0) * 0.16
        + _linear_score(short_roc_pp, config.min_short_roc_pp, 3.0) * 0.17
        + _linear_score(hour_volume_roc, config.min_hour_volume_roc_pct, 300.0) * 0.16
        + _linear_score(daily_volume_ratio, config.min_daily_volume_ratio, 10.0) * 0.12
        + _linear_score(oi_change, config.min_oi_change_pct, 8.0) * 0.10
        + _linear_score(funding_pct, max(0.0, config.min_funding_pct), 0.08) * 0.07
        + trend_score.clip(lower=0.0, upper=100.0) * 0.10
        + structure_score.clip(lower=0.0, upper=100.0) * 0.12
        - late_heat.clip(lower=0.0, upper=100.0) * 0.12
    ).clip(lower=0.0, upper=100.0)
    return rows.sort_values(
        ["_entry_all_gates", "_auto_entry_score", "symbol"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def _ratio_timestamp_ms(rows: list[dict[str, Any]]) -> int:
    timestamps = []
    for row in rows:
        value = _to_float(row.get("timestamp") or row.get("time"))
        if math.isfinite(value) and value > 0:
            timestamps.append(int(value))
    return max(timestamps, default=0)


def _open_interest_change(rows: list[dict[str, Any]]) -> float:
    if len(rows) < 2:
        return float("nan")
    previous = _to_float(rows[-2].get("sumOpenInterestValue") or rows[-2].get("sumOpenInterest"))
    current = _to_float(rows[-1].get("sumOpenInterestValue") or rows[-1].get("sumOpenInterest"))
    if not math.isfinite(previous) or previous <= 0 or not math.isfinite(current):
        return float("nan")
    return (current / previous - 1.0) * 100.0


def _closed_klines(rows: list[list[Any]]) -> list[list[Any]]:
    if not rows:
        return []
    now_ms = _now_ms()
    closed = [
        row
        for row in rows
        if isinstance(row, list)
        and len(row) > 6
        and _finite(row[6])
        and int(float(row[6])) < now_ms
    ]
    return closed


def _atr(rows: list[list[Any]], period: int) -> float:
    closed = _closed_klines(rows)
    if len(closed) < max(2, period + 1):
        return float("nan")
    true_ranges: list[float] = []
    sample = closed[-(period + 1) :]
    for previous, current in zip(sample, sample[1:]):
        high = _to_float(current[2])
        low = _to_float(current[3])
        previous_close = _to_float(previous[4])
        if all(math.isfinite(value) for value in (high, low, previous_close)):
            true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return sum(true_ranges) / len(true_ranges) if true_ranges else float("nan")


def _depth_metrics(depth: dict[str, Any]) -> dict[str, float]:
    bids = depth.get("bids", []) if isinstance(depth, dict) else []
    asks = depth.get("asks", []) if isinstance(depth, dict) else []
    if not bids or not asks:
        return {
            "best_bid": float("nan"),
            "best_ask": float("nan"),
            "spread_pct": float("nan"),
            "bid_depth_1pct_usdt": float("nan"),
        }
    best_bid = _to_float(bids[0][0])
    best_ask = _to_float(asks[0][0])
    spread = (
        (best_ask / best_bid - 1.0) * 100.0
        if best_bid > 0 and math.isfinite(best_ask)
        else float("nan")
    )
    floor_price = best_bid * 0.99
    bid_depth = sum(
        _to_float(price) * _to_float(quantity)
        for price, quantity, *_ in bids
        if _finite(price)
        and _finite(quantity)
        and _to_float(price) >= floor_price
    )
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_pct": spread,
        "bid_depth_1pct_usdt": bid_depth,
    }


def fetch_entry_confirmation(
    client: BinanceFuturesPublic,
    symbol: str,
    config: AutoTraderConfig,
) -> dict[str, Any]:
    ratio_rows = client.global_long_short_account_ratio(
        symbol,
        period="1h",
        limit=max(4, config.min_short_persistence + 2),
    )
    oi_rows = client.open_interest_statistics(symbol, period="1h", limit=2)
    mark_rows = client.mark_price(symbol)
    fifteen_rows = client.klines(
        symbol,
        interval="15m",
        limit=max(40, config.atr_period + config.swing_lookback_bars + 5),
    )
    hourly_rows = client.klines(symbol, interval="1h", limit=4)
    depth = client.depth(symbol, limit=100)

    short_stats = short_account_history_stats(ratio_rows, windows=(1, 3))
    current_short = _to_float(short_stats.get("short_account_current_pct"))
    short_roc_pp = _to_float(short_stats.get("short_account_roc_1h_pp"))
    smooth_roc_pp = _to_float(short_stats.get("short_account_roc_smoothed_3p_pp"))
    persistence = int(_to_float(short_stats.get("short_account_direction_persistence"))) if _finite(short_stats.get("short_account_direction_persistence")) else 0
    ratio_timestamp = _ratio_timestamp_ms(ratio_rows)
    ratio_age_minutes = (
        max(0.0, (_now_ms() - ratio_timestamp) / 60_000.0)
        if ratio_timestamp
        else float("nan")
    )

    mark = mark_rows[0] if mark_rows else {}
    mark_price = _to_float(mark.get("markPrice") or mark.get("indexPrice"))
    funding_pct = _to_float(mark.get("lastFundingRate")) * 100.0
    oi_change = _open_interest_change(oi_rows)
    hourly_volume = closed_hour_volume_metrics(hourly_rows)
    depth_stats = _depth_metrics(depth)

    closed_15m = _closed_klines(fifteen_rows)
    required = max(config.confirmation_breakout_bars + 1, config.swing_lookback_bars + 1)
    if len(closed_15m) < required:
        raise RuntimeError(f"{symbol} has insufficient completed 15m history for entry confirmation.")
    latest = closed_15m[-1]
    prior = closed_15m[-(config.confirmation_breakout_bars + 1) : -1]
    latest_high = _to_float(latest[2])
    latest_low = _to_float(latest[3])
    latest_close = _to_float(latest[4])
    prior_high = max(_to_float(row[2]) for row in prior)
    close_location = (
        (latest_close - latest_low) / (latest_high - latest_low) * 100.0
        if latest_high > latest_low
        else 50.0
    )
    swing_rows = closed_15m[-config.swing_lookback_bars :]
    swing_low = min(_to_float(row[3]) for row in swing_rows)
    atr_15m = _atr(fifteen_rows, config.atr_period)
    latest_sample_id = str(int(_to_float(latest[6]))) if _finite(latest[6]) else ""

    gates = {
        "short_level": math.isfinite(current_short) and current_short >= config.min_short_pct,
        "short_build": (
            math.isfinite(short_roc_pp)
            and short_roc_pp >= config.min_short_roc_pp
        )
        or (
            math.isfinite(smooth_roc_pp)
            and smooth_roc_pp >= config.min_smoothed_short_roc_pp
            and persistence >= config.min_short_persistence
        ),
        "short_data_fresh": math.isfinite(ratio_age_minutes)
        and ratio_age_minutes <= config.max_short_data_age_minutes,
        "funding": math.isfinite(funding_pct) and funding_pct > config.min_funding_pct,
        "oi": math.isfinite(oi_change) and oi_change >= config.min_oi_change_pct,
        "hour_volume": (
            math.isfinite(_to_float(hourly_volume.get("hour_volume_roc_1h_pct")))
            and _to_float(hourly_volume.get("hour_volume_roc_1h_pct"))
            >= config.min_hour_volume_roc_pct
        ),
        "breakout": latest_close > prior_high,
        "close_quality": close_location >= config.min_confirmation_close_location_pct,
        "price": math.isfinite(mark_price) and mark_price > 0 and mark_price >= prior_high,
        "spread": (
            math.isfinite(depth_stats["spread_pct"])
            and depth_stats["spread_pct"] <= config.max_entry_spread_pct
        ),
        "atr": math.isfinite(atr_15m) and atr_15m > 0,
    }
    return {
        "symbol": symbol,
        "confirmed": all(gates.values()),
        "gates": gates,
        "mark_price": mark_price,
        "funding_pct": funding_pct,
        "short_account_pct": current_short,
        "short_account_roc_1h_pp": short_roc_pp,
        "short_account_roc_smoothed_3p_pp": smooth_roc_pp,
        "short_account_direction_persistence": persistence,
        "short_account_sample_id": str(ratio_timestamp),
        "short_account_data_age_minutes": ratio_age_minutes,
        "open_interest_change_pct": oi_change,
        "hour_volume_roc_1h_pct": hourly_volume.get("hour_volume_roc_1h_pct"),
        "latest_15m_close": latest_close,
        "latest_15m_low": latest_low,
        "latest_15m_close_location_pct": close_location,
        "latest_15m_sample_id": latest_sample_id,
        "activation_price": prior_high,
        "swing_low": swing_low,
        "atr_15m": atr_15m,
        **depth_stats,
    }


def symbol_rules(client: BinanceFuturesPublic, symbol: str) -> SymbolRules:
    exchange_info = client.exchange_info()
    symbol_info = next(
        (
            item
            for item in exchange_info.get("symbols", [])
            if str(item.get("symbol") or "").upper() == symbol.upper()
        ),
        None,
    )
    if not symbol_info:
        raise RuntimeError(f"{symbol} is missing from Binance futures exchange info.")
    filters = {
        str(item.get("filterType") or "").upper(): item
        for item in symbol_info.get("filters", [])
        if isinstance(item, dict)
    }
    price_filter = filters.get("PRICE_FILTER", {})
    lot_filter = filters.get("MARKET_LOT_SIZE") or filters.get("LOT_SIZE", {})
    notional_filter = filters.get("MIN_NOTIONAL", {})
    try:
        tick_size = Decimal(str(price_filter.get("tickSize") or "0"))
        qty_step = Decimal(str(lot_filter.get("stepSize") or "0"))
        min_qty = Decimal(str(lot_filter.get("minQty") or "0"))
        min_notional = Decimal(
            str(notional_filter.get("notional") or notional_filter.get("minNotional") or "5")
        )
    except InvalidOperation as exc:
        raise RuntimeError(f"{symbol} returned invalid exchange filters.") from exc
    if tick_size <= 0 or qty_step <= 0:
        raise RuntimeError(f"{symbol} returned incomplete tick or quantity filters.")
    return SymbolRules(tick_size, qty_step, min_qty, min_notional)


def _round_step(value: Decimal, step: Decimal, *, up: bool = False) -> Decimal:
    rounding = ROUND_UP if up else ROUND_DOWN
    return (value / step).to_integral_value(rounding=rounding) * step


def build_risk_plan(
    *,
    equity_usdt: float,
    entry_price: float,
    atr_15m: float,
    swing_low: float,
    bid_depth_1pct_usdt: float,
    rules: SymbolRules,
    config: AutoTraderConfig,
    risk_fraction: float | None = None,
) -> RiskPlan:
    equity = Decimal(str(equity_usdt))
    entry = Decimal(str(entry_price))
    atr = Decimal(str(atr_15m))
    swing = Decimal(str(swing_low))
    selected_risk_fraction = config.risk_fraction if risk_fraction is None else float(risk_fraction)
    rejection = ""
    if equity <= 0 or entry <= 0 or atr <= 0 or swing <= 0:
        rejection = "equity, entry, ATR, or swing-low input is invalid"
        return RiskPlan(entry, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), float("nan"), bid_depth_1pct_usdt, rejection)

    structural_stop = swing - atr * Decimal(str(config.swing_atr_buffer))
    volatility_stop = entry - atr * Decimal(str(config.atr_stop_multiple))
    minimum_distance_stop = entry * (Decimal("1") - Decimal(str(config.min_stop_distance_pct)))
    raw_stop = min(structural_stop, volatility_stop, minimum_distance_stop)
    stop = _round_step(raw_stop, rules.tick_size)
    if stop <= 0 or stop >= entry:
        rejection = "calculated protective stop is invalid"
        return RiskPlan(entry, stop, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), float("nan"), bid_depth_1pct_usdt, rejection)

    initial_r = entry - stop
    stop_distance_pct = float(initial_r / entry)
    if stop_distance_pct > config.max_stop_distance_pct:
        rejection = (
            f"required stop distance {stop_distance_pct * 100.0:.2f}% exceeds "
            f"{config.max_stop_distance_pct * 100.0:.2f}%"
        )
        return RiskPlan(entry, stop, Decimal("0"), Decimal("0"), initial_r, Decimal("0"), Decimal("0"), stop_distance_pct * 100.0, bid_depth_1pct_usdt, rejection)

    cost_buffer = entry * Decimal(str(config.risk_slippage_pct + config.round_trip_fee_pct))
    planned_budget = equity * Decimal(str(selected_risk_fraction))
    stress_budget = equity * Decimal(str(config.max_stress_risk_fraction))
    qty_by_planned = planned_budget / (initial_r + cost_buffer)
    qty_by_stress = stress_budget / (initial_r * Decimal("2") + cost_buffer)
    max_notional = equity * Decimal(str(config.max_notional_fraction))
    qty_by_notional = max_notional / entry
    quantity_limits = [qty_by_planned, qty_by_stress, qty_by_notional]
    if math.isfinite(bid_depth_1pct_usdt) and bid_depth_1pct_usdt > 0:
        depth_notional = Decimal(str(bid_depth_1pct_usdt * config.max_depth_fraction))
        quantity_limits.append(depth_notional / entry)
    quantity = _round_step(min(quantity_limits), rules.qty_step)
    notional = quantity * entry
    planned_risk = quantity * (initial_r + cost_buffer)
    stress_risk = quantity * (initial_r * Decimal("2") + cost_buffer)
    if quantity < rules.min_qty:
        rejection = (
            f"risk-sized quantity {_fmt_decimal(quantity)} is below Binance minimum "
            f"{_fmt_decimal(rules.min_qty)}"
        )
    elif notional < rules.min_notional:
        rejection = (
            f"risk-sized notional {_fmt_decimal(notional, 4)} is below Binance minimum "
            f"{_fmt_decimal(rules.min_notional, 4)}"
        )
    return RiskPlan(
        entry_price=entry,
        stop_price=stop,
        quantity=quantity,
        notional_usdt=notional,
        initial_r_per_unit=initial_r,
        planned_risk_usdt=planned_risk,
        stress_risk_usdt=stress_risk,
        stop_distance_pct=stop_distance_pct * 100.0,
        bid_depth_1pct_usdt=bid_depth_1pct_usdt,
        rejection_reason=rejection,
    )


def account_equity_usdt(client: BinanceFuturesPublic) -> float:
    account = client.account_information_v3()
    for key in ("totalWalletBalance", "totalMarginBalance", "availableBalance"):
        value = _to_float(account.get(key))
        if math.isfinite(value) and value > 0:
            return value
    for asset in account.get("assets", []):
        if str(asset.get("asset") or "").upper() != "USDT":
            continue
        for key in ("walletBalance", "marginBalance", "availableBalance"):
            value = _to_float(asset.get(key))
            if math.isfinite(value) and value > 0:
                return value
    raise RuntimeError("Binance did not return usable USDT futures equity.")


def _open_positions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if isinstance(row, dict)
        and math.isfinite(_to_float(row.get("positionAmt")))
        and abs(_to_float(row.get("positionAmt"))) > 0
    ]


def _long_position(rows: list[dict[str, Any]], symbol: str) -> dict[str, Any]:
    matches = [
        row
        for row in _open_positions(rows)
        if str(row.get("symbol") or "").upper() == symbol.upper()
        and _to_float(row.get("positionAmt")) > 0
    ]
    return matches[0] if len(matches) == 1 else {}


def _hedge_mode(rows: list[dict[str, Any]]) -> bool:
    return any(
        str(row.get("positionSide") or "").upper() in {"LONG", "SHORT"}
        for row in rows
    )


def refresh_risk_limits(
    state: dict[str, Any],
    equity_usdt: float,
    config: AutoTraderConfig,
) -> tuple[bool, float, str]:
    limits = state.setdefault("risk_limits", {})
    today = _today_key()
    week = _week_key()
    if limits.get("day_key") != today:
        limits["day_key"] = today
        limits["day_start_equity"] = equity_usdt
    if limits.get("week_key") != week:
        limits["week_key"] = week
        limits["week_start_equity"] = equity_usdt
    high_water = max(_to_float(limits.get("high_water_equity")), equity_usdt)
    if not math.isfinite(high_water):
        high_water = equity_usdt
    limits["high_water_equity"] = high_water
    day_start = _to_float(limits.get("day_start_equity"))
    week_start = _to_float(limits.get("week_start_equity"))
    drawdown = max(0.0, 1.0 - equity_usdt / high_water) if high_water > 0 else 0.0
    day_loss = max(0.0, 1.0 - equity_usdt / day_start) if day_start > 0 else 0.0
    week_loss = max(0.0, 1.0 - equity_usdt / week_start) if week_start > 0 else 0.0
    limits.update(
        {
            "last_equity": equity_usdt,
            "drawdown_fraction": drawdown,
            "day_loss_fraction": day_loss,
            "week_loss_fraction": week_loss,
            "updated_at": _now_iso(),
        }
    )
    if drawdown >= config.drawdown_pause_fraction:
        return False, 0.0, f"drawdown {drawdown:.2%} reached pause threshold"
    if day_loss >= config.daily_loss_fraction:
        return False, 0.0, f"daily loss {day_loss:.2%} reached limit"
    if week_loss >= config.weekly_loss_fraction:
        return False, 0.0, f"weekly loss {week_loss:.2%} reached limit"
    risk_fraction = (
        config.risk_fraction / 2.0
        if drawdown >= config.drawdown_halve_fraction
        else config.risk_fraction
    )
    return True, risk_fraction, "risk limits clear"


def _binance_error_code(exc: BinanceHTTPError) -> int | None:
    if not isinstance(exc.payload, dict):
        return None
    try:
        return int(exc.payload.get("code"))
    except (TypeError, ValueError):
        return None


def _configure_symbol_for_entry(
    client: BinanceFuturesPublic,
    symbol: str,
    leverage: int,
) -> None:
    try:
        client.change_margin_type(symbol, "ISOLATED")
    except BinanceHTTPError as exc:
        if _binance_error_code(exc) != -4046:
            raise
    client.change_initial_leverage(symbol, leverage)


def _client_order_id(prefix: str) -> str:
    return f"{prefix}{int(time.time() * 1000)}"[:36]


def _active_algo_payload(payload: dict[str, Any]) -> bool:
    status = str(
        payload.get("algoStatus")
        or payload.get("status")
        or payload.get("orderStatus")
        or ""
    ).upper()
    return status in ACTIVE_ALGO_STATUSES


def _place_stop(
    client: BinanceFuturesPublic,
    *,
    symbol: str,
    trigger_price: Decimal,
    hedge_mode: bool,
) -> dict[str, Any]:
    client_algo_id = _client_order_id("csstop")
    params: dict[str, Any] = {
        "algoType": "CONDITIONAL",
        "symbol": symbol,
        "side": "SELL",
        "type": "STOP_MARKET",
        "closePosition": "true",
        "triggerPrice": _fmt_decimal(trigger_price),
        "workingType": "MARK_PRICE",
        "clientAlgoId": client_algo_id,
        "newOrderRespType": "ACK",
    }
    if hedge_mode:
        params["positionSide"] = "LONG"
    result = client.new_futures_algo_order(**params)
    algo_id = result.get("algoId")
    returned_client_id = str(result.get("clientAlgoId") or client_algo_id)
    verification = client.query_futures_algo_order(
        algo_id=algo_id,
        client_algo_id=None if algo_id is not None else returned_client_id,
    )
    if not _active_algo_payload(verification):
        raise RuntimeError(
            f"protective stop was not active after submission: {verification}"
        )
    return {
        "algo_id": algo_id,
        "client_algo_id": returned_client_id,
        "trigger_price": float(trigger_price),
        "placed_at": _now_iso(),
        "raw": _json_safe(result),
    }


def _verify_known_stop(
    client: BinanceFuturesPublic,
    stop: dict[str, Any],
) -> bool:
    algo_id = stop.get("algo_id")
    client_algo_id = str(stop.get("client_algo_id") or "")
    if algo_id in (None, "") and not client_algo_id:
        return False
    payload = client.query_futures_algo_order(
        algo_id=algo_id if algo_id not in (None, "") else None,
        client_algo_id=None if algo_id not in (None, "") else client_algo_id,
    )
    return _active_algo_payload(payload)


def _cancel_known_stop(
    client: BinanceFuturesPublic,
    stop: dict[str, Any] | None,
) -> None:
    if not stop:
        return
    algo_id = stop.get("algo_id")
    client_algo_id = str(stop.get("client_algo_id") or "")
    if algo_id in (None, "") and not client_algo_id:
        return
    try:
        client.cancel_futures_algo_order(
            algo_id=algo_id if algo_id not in (None, "") else None,
            client_algo_id=None if algo_id not in (None, "") else client_algo_id,
        )
    except BinanceHTTPError as exc:
        if _binance_error_code(exc) not in {-2011, -2013}:
            raise


def _replace_stop(
    client: BinanceFuturesPublic,
    position: dict[str, Any],
    target_price: Decimal,
    *,
    hedge_mode: bool,
) -> dict[str, Any]:
    old_stop = position.get("protective_stop") if isinstance(position.get("protective_stop"), dict) else None
    new_stop = _place_stop(
        client,
        symbol=str(position["symbol"]),
        trigger_price=target_price,
        hedge_mode=hedge_mode,
    )
    if old_stop:
        try:
            _cancel_known_stop(client, old_stop)
        except Exception as exc:
            new_stop["old_stop_cancel_warning"] = str(exc)
    return new_stop


def _entry_order_params(
    symbol: str,
    quantity: Decimal,
    limit_price: Decimal,
    *,
    hedge_mode: bool,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "symbol": symbol,
        "side": "BUY",
        "type": "LIMIT",
        "timeInForce": "IOC",
        "quantity": _fmt_decimal(quantity),
        "price": _fmt_decimal(limit_price),
        "newClientOrderId": _client_order_id("csentry"),
        "newOrderRespType": "RESULT",
    }
    if hedge_mode:
        params["positionSide"] = "LONG"
    return params


def _close_order_params(
    symbol: str,
    quantity: Decimal,
    limit_price: Decimal,
    *,
    hedge_mode: bool,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "symbol": symbol,
        "side": "SELL",
        "type": "LIMIT",
        "timeInForce": "IOC",
        "quantity": _fmt_decimal(quantity),
        "price": _fmt_decimal(limit_price),
        "newClientOrderId": _client_order_id("csexit"),
        "newOrderRespType": "RESULT",
    }
    if hedge_mode:
        params["positionSide"] = "LONG"
    else:
        params["reduceOnly"] = "true"
    return params


def _emergency_flatten(
    client: BinanceFuturesPublic,
    *,
    symbol: str,
    quantity: Decimal,
    hedge_mode: bool,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "symbol": symbol,
        "side": "SELL",
        "type": "MARKET",
        "quantity": _fmt_decimal(quantity),
        "newClientOrderId": _client_order_id("csemergency"),
        "newOrderRespType": "RESULT",
    }
    if hedge_mode:
        params["positionSide"] = "LONG"
    else:
        params["reduceOnly"] = "true"
    return client.new_futures_order(**params)


def execute_price_protected_close(
    client: BinanceFuturesPublic,
    *,
    position_row: dict[str, Any],
    close_fraction: float,
    rules: SymbolRules,
    config: AutoTraderConfig,
) -> dict[str, Any]:
    symbol = str(position_row.get("symbol") or "").upper()
    amount = abs(_to_float(position_row.get("positionAmt")))
    if not symbol or not math.isfinite(amount) or amount <= 0:
        raise RuntimeError("fresh close position is unavailable")
    fraction = min(1.0, max(0.0, float(close_fraction)))
    quantity = _round_step(Decimal(str(amount * fraction)), rules.qty_step)
    remaining = Decimal(str(amount)) - quantity
    if quantity < rules.min_qty or (remaining > 0 and remaining < rules.min_qty):
        quantity = _round_step(Decimal(str(amount)), rules.qty_step)
    depth = _depth_metrics(client.depth(symbol, limit=100))
    best_bid = _to_float(depth.get("best_bid"))
    if not math.isfinite(best_bid) or best_bid <= 0:
        raise RuntimeError("best bid unavailable for price-protected close")
    limit_price = _round_step(
        Decimal(str(best_bid))
        * (Decimal("1") - Decimal(str(config.entry_limit_slippage_pct))),
        rules.tick_size,
    )
    hedge = str(position_row.get("positionSide") or "").upper() == "LONG"
    params = _close_order_params(
        symbol,
        quantity,
        limit_price,
        hedge_mode=hedge,
    )
    result = client.new_futures_order(**params)
    response = dict(result)
    response["submitted_order_params"] = params
    return response


def _position_mark_and_pnl(position_row: dict[str, Any]) -> tuple[float, float, float]:
    amount = _to_float(position_row.get("positionAmt"))
    entry = _to_float(position_row.get("entryPrice"))
    mark = _to_float(position_row.get("markPrice"))
    unrealized = _to_float(
        position_row.get("unRealizedProfit", position_row.get("unrealizedProfit"))
    )
    if not math.isfinite(unrealized) and all(
        math.isfinite(value) for value in (amount, entry, mark)
    ):
        unrealized = (mark - entry) * amount
    return mark, unrealized, amount


def _public_position_metrics(
    client: BinanceFuturesPublic,
    symbol: str,
    config: AutoTraderConfig,
) -> dict[str, Any]:
    ratio_rows = client.global_long_short_account_ratio(symbol, period="1h", limit=12)
    hourly_rows = client.klines(symbol, interval="1h", limit=5)
    oi_rows = client.open_interest_statistics(symbol, period="1h", limit=2)
    fifteen_rows = client.klines(
        symbol,
        interval="15m",
        limit=max(40, config.atr_period + 5),
    )
    stats = short_account_history_stats(ratio_rows, windows=(1, 3, 6))
    stats["short_account_pct"] = _to_float(stats.get("short_account_current_pct"))
    timestamp = _ratio_timestamp_ms(ratio_rows)
    stats["short_account_sample_id"] = str(timestamp)
    stats.update(_completed_hour_confirmation_metrics(hourly_rows, oi_rows))
    stats["open_interest_change_pct"] = _open_interest_change(oi_rows)
    closed_15m = _closed_klines(fifteen_rows)
    latest = closed_15m[-1] if closed_15m else []
    stats.update(
        {
            "atr_15m": _atr(fifteen_rows, config.atr_period),
            "latest_15m_close": _to_float(latest[4]) if len(latest) > 4 else float("nan"),
            "latest_15m_low": _to_float(latest[3]) if len(latest) > 3 else float("nan"),
            "latest_15m_sample_id": str(int(_to_float(latest[6]))) if len(latest) > 6 and _finite(latest[6]) else "",
        }
    )
    return stats


def _short_close_config(
    config: AutoTraderConfig,
    symbol: str,
) -> ShortRocCloseConfig:
    return ShortRocCloseConfig(
        symbol=symbol,
        base_url=config.base_url,
        timeout=config.timeout,
        retries=config.retries,
        requests_per_second=config.requests_per_second,
        interval_seconds=config.manage_interval_seconds,
        output_dir=config.output_dir,
        webhook_url="",
        once=True,
        dry_run=not config.live,
        live=config.live,
        trigger_short_roc_pct=config.short_exit_trigger_pct,
        trigger_short_roc_pp=999.0,
        short_account_exit_level_pct=config.short_exit_level_pct,
        short_account_peak_drawdown_pp=config.short_exit_peak_drawdown_pp,
        oi_drop_confirmation_pct=8.0,
        volume_spike_confirmation_pct=50.0,
        confirmation_readings=config.short_exit_confirmation_readings,
        short_rebound_tolerance_pp=0.5,
        short_history_limit=12,
        partial_close_fraction=config.short_exit_partial_pct / 100.0,
        runner_confirmation_readings=config.short_exit_runner_readings,
        runner_oi_drop_pct=config.short_exit_runner_oi_drop_pct,
        runner_volume_deceleration_pct=config.short_exit_runner_volume_drop_pct,
        min_profit_usdt=0.0,
        min_profit_pct=config.short_exit_execution_floor_pct,
        execution_profit_floor_pct=config.short_exit_execution_floor_pct,
        require_breakeven_stop=True,
        block_without_breakeven_stop=True,
        breakeven_tolerance_pct=0.25,
        close_once=False,
        api_key=config.api_key,
        api_secret=config.api_secret,
    )


def thesis_failure_reason(
    position: dict[str, Any],
    metrics: dict[str, Any],
    config: AutoTraderConfig,
    *,
    now_ms: int | None = None,
) -> str:
    if str(position.get("stop_stage") or "") == "breakeven":
        return ""
    now_ms = _now_ms() if now_ms is None else int(now_ms)
    opened_ms = int(_to_float(position.get("opened_at_ms"))) if _finite(position.get("opened_at_ms")) else now_ms
    age_hours = max(0.0, (now_ms - opened_ms) / 3_600_000.0)
    mfe_r = _to_float(position.get("maximum_favorable_r"))
    short_now = _to_float(metrics.get("short_account_pct"))
    short_entry = _to_float(position.get("entry_short_account_pct"))
    short_roc_pp = _to_float(metrics.get("short_account_roc_1h_pp"))
    volume_roc = _to_float(metrics.get("hour_volume_roc_1h_pct"))
    oi_change = _to_float(metrics.get("open_interest_change_pct"))
    mark = _to_float(position.get("latest_mark_price"))
    entry = _to_float(position.get("entry_price"))
    latest_close = _to_float(metrics.get("latest_15m_close"))
    activation = _to_float(position.get("activation_price"))

    if (
        math.isfinite(short_entry)
        and math.isfinite(short_now)
        and short_entry - short_now >= config.preproof_short_drop_pp
        and (not math.isfinite(mfe_r) or mfe_r < config.max_proof_mfe_r)
    ):
        return (
            f"pre-proof short fuel fell {short_entry - short_now:.2f}pp "
            f"from the entry reading"
        )
    early_failure = (
        age_hours >= config.early_proof_hours
        and (not math.isfinite(mfe_r) or mfe_r < config.early_proof_mfe_r)
        and math.isfinite(short_roc_pp)
        and short_roc_pp <= 0
        and math.isfinite(volume_roc)
        and volume_roc <= 0
        and (
            (math.isfinite(latest_close) and math.isfinite(activation) and latest_close < activation)
            or (math.isfinite(mark) and math.isfinite(entry) and mark <= entry)
        )
    )
    if early_failure:
        return "two-hour proof window failed: no 0.5R progress, shorts and volume stopped building"
    still_valid = (
        math.isfinite(short_roc_pp)
        and short_roc_pp > 0
        and math.isfinite(oi_change)
        and oi_change > 0
        and math.isfinite(mark)
        and math.isfinite(entry)
        and mark > entry
    )
    if (
        age_hours >= config.max_proof_hours
        and (not math.isfinite(mfe_r) or mfe_r < config.max_proof_mfe_r)
        and not still_valid
    ):
        return "maximum proof window failed before reaching 0.75R"
    if (
        age_hours >= config.absolute_proof_timeout_hours
        and (not math.isfinite(mfe_r) or mfe_r < config.max_proof_mfe_r)
    ):
        return "absolute proof timeout reached without 0.75R progress"
    return ""


def stop_ratcheting_target(
    position: dict[str, Any],
    metrics: dict[str, Any],
    config: AutoTraderConfig,
) -> tuple[str, float, str]:
    entry = _to_float(position.get("entry_price"))
    initial_r = _to_float(position.get("initial_r_per_unit"))
    current_stop = _to_float(position.get("current_stop_price"))
    mark = _to_float(position.get("latest_mark_price"))
    mfe_r = _to_float(position.get("maximum_favorable_r"))
    atr = _to_float(metrics.get("atr_15m"))
    latest_close = _to_float(metrics.get("latest_15m_close"))
    current_stage = str(position.get("stop_stage") or "initial")
    if not all(math.isfinite(value) and value > 0 for value in (entry, initial_r, current_stop, mark)):
        return current_stage, current_stop, ""

    favorable_move = max(0.0, _to_float(position.get("maximum_favorable_price")) - entry)
    be_required_move = max(
        config.breakeven_trigger_r * initial_r,
        config.breakeven_atr_multiple * atr if math.isfinite(atr) else float("inf"),
    )
    be_eligible = (
        current_stage != "breakeven"
        and favorable_move >= be_required_move
        and math.isfinite(latest_close)
        and latest_close >= entry + be_required_move
    )
    sample_id = str(metrics.get("latest_15m_sample_id") or "")
    previous_sample_id = str(position.get("breakeven_last_counted_sample_id") or "")
    confirmation_count = (
        int(_to_float(position.get("breakeven_confirmation_count")))
        if _finite(position.get("breakeven_confirmation_count"))
        else 0
    )
    if be_eligible and sample_id and sample_id != previous_sample_id:
        confirmation_count += 1
        position["breakeven_confirmation_count"] = confirmation_count
        position["breakeven_last_counted_sample_id"] = sample_id
    elif not be_eligible:
        confirmation_count = 0
        position["breakeven_confirmation_count"] = 0
    if be_eligible and confirmation_count >= config.breakeven_confirmation_bars:
        target = entry * (1.0 + config.breakeven_cost_buffer_pct)
        if target < mark * (1.0 - 0.0005) and target > current_stop:
            return "breakeven", target, "1.25R/ATR proof reached; move to cost-adjusted breakeven"
    if (
        current_stage == "initial"
        and math.isfinite(mfe_r)
        and mfe_r >= config.risk_reduce_trigger_r
    ):
        target = entry - config.risk_reduced_stop_r * initial_r
        if target < mark * (1.0 - 0.0005) and target > current_stop:
            return "risk_reduced", target, "0.75R proof reached; reduce remaining downside to 0.5R"
    return current_stage, current_stop, ""


class SingleInstanceLock:
    def __init__(self, path: Path):
        self.path = path
        self.handle: Any = None

    def __enter__(self) -> "SingleInstanceLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            import msvcrt

            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
        except (ImportError, OSError) as exc:
            self.handle.close()
            self.handle = None
            raise RuntimeError("another automated short-uptrend trader appears to be running") from exc
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.handle is None:
            return
        try:
            import msvcrt

            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.handle.close()
            self.handle = None


class AutoShortUptrendTrader:
    def __init__(self, config: AutoTraderConfig):
        self.config = config
        self.client = BinanceFuturesPublic(
            base_url=config.base_url,
            timeout=config.timeout,
            requests_per_second=config.requests_per_second,
            retries=config.retries,
            api_key=config.api_key,
            api_secret=config.api_secret,
        )
        self.state = load_state(config)

    def _set_message(self, message: str) -> str:
        self.state["last_message"] = message
        write_state(self.config, self.state)
        print(f"[{_now_label()}] {message}", flush=True)
        return message

    def _equity(self) -> float:
        if self.config.live:
            return account_equity_usdt(self.client)
        paper_equity = _to_float(
            self.state.setdefault("risk_limits", {}).get("paper_equity")
        )
        return (
            paper_equity
            if math.isfinite(paper_equity) and paper_equity > 0
            else self.config.paper_equity_usdt
        )

    def _position_rows(self) -> list[dict[str, Any]]:
        if not self.config.live:
            return []
        rows = self.client.position_information_v3()
        return rows if isinstance(rows, list) else []

    def _paper_position_row(self, position: dict[str, Any], mark: float) -> dict[str, Any]:
        quantity = _to_float(position.get("quantity"))
        entry = _to_float(position.get("entry_price"))
        return {
            "symbol": position.get("symbol"),
            "positionAmt": str(quantity),
            "entryPrice": str(entry),
            "markPrice": str(mark),
            "unRealizedProfit": str((mark - entry) * quantity),
            "positionSide": "BOTH",
        }

    def _finalize_position(
        self,
        position: dict[str, Any],
        *,
        reason: str,
        exit_price: Any,
        source: str,
    ) -> None:
        if self.config.live:
            equity_after = self._equity()
        else:
            entry_value = _to_float(position.get("entry_price"))
            exit_value = _to_float(exit_price)
            quantity_value = _to_float(position.get("quantity"))
            equity_before = _to_float(position.get("account_equity_at_entry"))
            if not math.isfinite(equity_before):
                equity_before = self._equity()
            gross_pnl = (
                (exit_value - entry_value) * quantity_value
                if all(
                    math.isfinite(value)
                    for value in (entry_value, exit_value, quantity_value)
                )
                else 0.0
            )
            estimated_fees = (
                entry_value
                * quantity_value
                * self.config.round_trip_fee_pct
                if all(
                    math.isfinite(value)
                    for value in (entry_value, quantity_value)
                )
                else 0.0
            )
            equity_after = equity_before + gross_pnl - estimated_fees
            self.state.setdefault("risk_limits", {})["paper_equity"] = equity_after
        if self.config.live:
            try:
                _cancel_known_stop(self.client, position.get("protective_stop"))
            except Exception as exc:
                record_event(
                    self.config,
                    "stop_cleanup_warning",
                    symbol=str(position.get("symbol") or ""),
                    message=str(exc),
                )
        record_trade(
            self.config,
            position,
            exit_reason=reason,
            exit_price=exit_price,
            account_equity_after=equity_after,
            close_source=source,
        )
        symbol = str(position.get("symbol") or "").upper()
        self.state.setdefault("cooldowns", {})[symbol] = _now_ms() + int(
            self.config.cooldown_hours * 3_600_000
        )
        self.state["position"] = None
        refresh_risk_limits(self.state, equity_after, self.config)
        record_event(
            self.config,
            "position_closed",
            symbol=symbol,
            message=reason,
            details={
                "exit_price": exit_price,
                "equity_after": equity_after,
                "source": source,
            },
        )
        post_discord(
            self.config,
            f"{symbol} position closed",
            f"Reason: {reason}\nExit: {exit_price}\nEquity: {_fmt_money(equity_after)}\nSource: {source}",
            color=0xED4245,
        )
        self._set_message(f"{symbol} closed: {reason}")

    def _enter_paper(
        self,
        row: pd.Series,
        confirmation: dict[str, Any],
        plan: RiskPlan,
        equity: float,
    ) -> None:
        position = self._position_state(
            row=row,
            confirmation=confirmation,
            plan=plan,
            equity=equity,
            actual_entry=float(plan.entry_price),
            actual_quantity=float(plan.quantity),
            protective_stop={
                "algo_id": "paper",
                "client_algo_id": "paper",
                "trigger_price": float(plan.stop_price),
                "placed_at": _now_iso(),
            },
        )
        self.state["position"] = position
        record_event(
            self.config,
            "paper_entry",
            symbol=position["symbol"],
            message="Paper entry opened and protected by simulated initial stop.",
            details=position,
        )
        post_discord(
            self.config,
            f"PAPER {position['symbol']} entered",
            self._entry_description(position, row, confirmation),
            color=0x57F287,
        )
        self._set_message(
            f"PAPER {position['symbol']} entered at {position['entry_price']}; "
            f"stop {position['initial_stop_price']}; risk {_fmt_money(position['planned_risk_usdt'])}"
        )

    def _position_state(
        self,
        *,
        row: pd.Series,
        confirmation: dict[str, Any],
        plan: RiskPlan,
        equity: float,
        actual_entry: float,
        actual_quantity: float,
        protective_stop: dict[str, Any] | None,
    ) -> dict[str, Any]:
        initial_stop = float(plan.stop_price)
        initial_r = actual_entry - initial_stop
        return {
            "status": "open",
            "mode": self.config.mode,
            "symbol": str(row.get("symbol") or "").upper(),
            "opened_at_utc": _now_iso(),
            "opened_at_ms": _now_ms(),
            "entry_price": actual_entry,
            "quantity": actual_quantity,
            "notional_usdt": actual_entry * actual_quantity,
            "account_equity_at_entry": equity,
            "initial_stop_price": initial_stop,
            "current_stop_price": initial_stop,
            "initial_r_per_unit": initial_r,
            "planned_risk_usdt": float(plan.planned_risk_usdt),
            "stress_risk_usdt": float(plan.stress_risk_usdt),
            "stop_distance_pct": initial_r / actual_entry * 100.0,
            "stop_stage": "initial",
            "protective_stop": protective_stop,
            "activation_price": confirmation.get("activation_price"),
            "entry_short_account_pct": confirmation.get("short_account_pct"),
            "entry_short_account_roc_1h_pp": confirmation.get("short_account_roc_1h_pp"),
            "entry_funding_pct": confirmation.get("funding_pct"),
            "entry_oi_change_pct": confirmation.get("open_interest_change_pct"),
            "entry_hour_volume_roc_pct": confirmation.get("hour_volume_roc_1h_pct"),
            "entry_daily_volume_ratio": row.get("quote_volume_24h_vs_prior_30d_avg_ratio"),
            "entry_candidate_score": row.get("_auto_entry_score"),
            "maximum_favorable_price": actual_entry,
            "maximum_favorable_r": 0.0,
            "latest_mark_price": actual_entry,
            "short_exit_state": {
                "status": "open",
                "symbol": str(row.get("symbol") or "").upper(),
                "position_side": "LONG",
                "entry_price": actual_entry,
            },
            "partial_exit_completed": False,
            "entry_snapshot": {
                "candidate": _json_safe(row.to_dict()),
                "confirmation": _json_safe(confirmation),
            },
        }

    def _entry_description(
        self,
        position: dict[str, Any],
        row: pd.Series,
        confirmation: dict[str, Any],
    ) -> str:
        return (
            f"/{position['symbol']} LONG\n"
            f"Entry {position['entry_price']:.10g} | initial stop {position['initial_stop_price']:.10g}\n"
            f"Quantity {position['quantity']:.10g} | notional {_fmt_money(position['notional_usdt'])}\n"
            f"Planned risk {_fmt_money(position['planned_risk_usdt'])} | "
            f"stress risk {_fmt_money(position['stress_risk_usdt'])}\n"
            f"Short accounts {_fmt_pct(confirmation.get('short_account_pct'), signed=False)} | "
            f"1h build {_fmt_pct(confirmation.get('short_account_roc_1h_pp'))}pp\n"
            f"Funding {_fmt_pct(confirmation.get('funding_pct'))} | "
            f"OI {_fmt_pct(confirmation.get('open_interest_change_pct'))} | "
            f"1h volume ROC {_fmt_pct(confirmation.get('hour_volume_roc_1h_pct'))}\n"
            f"24h/prior-30D volume {float(_to_float(row.get('quote_volume_24h_vs_prior_30d_avg_ratio'))):.2f}x | "
            f"candidate score {_to_float(row.get('_auto_entry_score')):.1f}/100"
        )

    def _enter_live(
        self,
        row: pd.Series,
        confirmation: dict[str, Any],
        plan: RiskPlan,
        equity: float,
        all_position_rows: list[dict[str, Any]],
    ) -> None:
        symbol = str(row.get("symbol") or "").upper()
        hedge = _hedge_mode(all_position_rows)
        rules = symbol_rules(self.client, symbol)
        _configure_symbol_for_entry(self.client, symbol, self.config.leverage)
        limit_price = _round_step(
            plan.entry_price
            * (Decimal("1") + Decimal(str(self.config.entry_limit_slippage_pct))),
            rules.tick_size,
            up=True,
        )
        entering_state = self._position_state(
            row=row,
            confirmation=confirmation,
            plan=plan,
            equity=equity,
            actual_entry=float(plan.entry_price),
            actual_quantity=float(plan.quantity),
            protective_stop=None,
        )
        entering_state["status"] = "entering"
        self.state["position"] = entering_state
        write_state(self.config, self.state)

        entry_result = self.client.new_futures_order(
            **_entry_order_params(
                symbol,
                plan.quantity,
                limit_price,
                hedge_mode=hedge,
            )
        )
        executed = _to_float(entry_result.get("executedQty"))
        if not math.isfinite(executed) or executed <= 0:
            self.state["position"] = None
            record_event(
                self.config,
                "entry_not_filled",
                symbol=symbol,
                message="Price-protected IOC entry did not fill.",
                details={"entry_result": entry_result},
            )
            self._set_message(f"{symbol} entry IOC did not fill; no position opened")
            return

        fresh_rows = self.client.position_information_v3(symbol)
        fresh_position = _long_position(fresh_rows, symbol)
        if not fresh_position:
            self.state["position"] = None
            raise RuntimeError(f"{symbol} entry reported a fill but no long position was found.")
        actual_entry = _to_float(fresh_position.get("entryPrice"))
        actual_quantity = abs(_to_float(fresh_position.get("positionAmt")))
        if not all(
            math.isfinite(value) and value > 0
            for value in (actual_entry, actual_quantity)
        ):
            raise RuntimeError(f"{symbol} returned invalid position details after entry.")
        actual_stress = actual_quantity * (
            2.0 * (actual_entry - float(plan.stop_price))
            + actual_entry * (self.config.risk_slippage_pct + self.config.round_trip_fee_pct)
        )
        if actual_stress > equity * self.config.max_stress_risk_fraction * 1.02:
            emergency = _emergency_flatten(
                self.client,
                symbol=symbol,
                quantity=Decimal(str(actual_quantity)),
                hedge_mode=hedge,
            )
            emergency_rows = self.client.position_information_v3(symbol)
            emergency_position = _long_position(emergency_rows, symbol)
            if emergency_position:
                entering_state.update(
                    {
                        "status": "entering",
                        "entry_price": actual_entry,
                        "quantity": actual_quantity,
                        "latest_mark_price": _to_float(emergency_position.get("markPrice")),
                        "entry_risk_violation": True,
                    }
                )
                self.state["position"] = entering_state
            else:
                self.state["position"] = None
            write_state(self.config, self.state)
            record_event(
                self.config,
                "entry_emergency_flatten",
                symbol=symbol,
                message="Actual fill exceeded the stress-risk ceiling.",
                details={"actual_stress": actual_stress, "order": emergency},
            )
            raise RuntimeError(
                f"{symbol} actual fill stress risk exceeded the hard ceiling and was flattened."
            )

        try:
            protective_stop = _place_stop(
                self.client,
                symbol=symbol,
                trigger_price=plan.stop_price,
                hedge_mode=hedge,
            )
        except Exception as stop_exc:
            emergency_result: dict[str, Any] | None = None
            emergency_error = ""
            try:
                emergency_result = _emergency_flatten(
                    self.client,
                    symbol=symbol,
                    quantity=Decimal(str(actual_quantity)),
                    hedge_mode=hedge,
                )
            except Exception as emergency_exc:
                emergency_error = str(emergency_exc)
            emergency_rows = self.client.position_information_v3(symbol)
            emergency_position = _long_position(emergency_rows, symbol)
            if emergency_position:
                entering_state.update(
                    {
                        "status": "entering",
                        "entry_price": actual_entry,
                        "quantity": abs(_to_float(emergency_position.get("positionAmt"))),
                        "latest_mark_price": _to_float(emergency_position.get("markPrice")),
                        "protective_stop_error": str(stop_exc),
                        "emergency_flatten_error": emergency_error,
                    }
                )
                self.state["position"] = entering_state
            else:
                self.state["position"] = None
            write_state(self.config, self.state)
            record_event(
                self.config,
                "protective_stop_failure",
                symbol=symbol,
                message=str(stop_exc),
                details={
                    "emergency_order": emergency_result,
                    "emergency_error": emergency_error,
                    "position_still_open": bool(emergency_position),
                },
            )
            raise RuntimeError(
                f"{symbol} protective stop failed; emergency flatten "
                f"{'did not fully close the position' if emergency_position else 'closed the position'}: "
                f"{stop_exc}"
            ) from stop_exc

        position = self._position_state(
            row=row,
            confirmation=confirmation,
            plan=plan,
            equity=equity,
            actual_entry=actual_entry,
            actual_quantity=actual_quantity,
            protective_stop=protective_stop,
        )
        position["entry_order"] = _json_safe(entry_result)
        self.state["position"] = position
        record_event(
            self.config,
            "live_entry_protected",
            symbol=symbol,
            message="Live IOC entry filled and exchange-native stop verified.",
            details=position,
        )
        post_discord(
            self.config,
            f"LIVE {symbol} entered and protected",
            self._entry_description(position, row, confirmation),
            color=0x57F287,
        )
        self._set_message(
            f"LIVE {symbol} entered at {actual_entry:.10g}; verified stop "
            f"{float(plan.stop_price):.10g}; planned risk {_fmt_money(position['planned_risk_usdt'])}"
        )

    def _scan_and_maybe_enter(self) -> str:
        now_ms = _now_ms()
        last_scan = int(_to_float(self.state.get("last_scan_at_ms"))) if _finite(self.state.get("last_scan_at_ms")) else 0
        if last_scan and now_ms - last_scan < self.config.flat_scan_interval_seconds * 1000:
            wait_seconds = int(
                self.config.flat_scan_interval_seconds - (now_ms - last_scan) / 1000
            )
            return self._set_message(f"flat; next Deep entry scan in {max(0, wait_seconds)}s")

        live_rows = self._position_rows()
        open_positions = _open_positions(live_rows)
        if open_positions:
            symbols = ", ".join(str(row.get("symbol") or "") for row in open_positions)
            return self._set_message(
                f"entry blocked: account already has open position(s): {symbols}"
            )
        if self.config.live:
            resting_orders = self.client.open_futures_orders()
            resting_algos = self.client.open_futures_algo_orders()
            if resting_orders or resting_algos:
                return self._set_message(
                    "entry blocked: account has pre-existing futures orders; "
                    "clear or reconcile them before autonomous entry"
                )
        equity = self._equity()
        allowed, risk_fraction, limit_reason = refresh_risk_limits(
            self.state,
            equity,
            self.config,
        )
        if not allowed:
            record_event(
                self.config,
                "risk_limit_block",
                message=limit_reason,
                details={"equity": equity},
            )
            return self._set_message(f"entry blocked by risk limits: {limit_reason}")

        self.state["last_scan_at_ms"] = now_ms
        write_state(self.config, self.state)
        result = run_scanner_scan(
            self.config.scan_mode,
            refresh_nonce=now_ms,
            write_discord_cache=True,
        )
        scored = score_entry_candidates(result.all_rows, self.config)
        config_snapshot = asdict(self.config)
        config_snapshot.update(
            {
                "api_key": "configured" if self.config.api_key else "missing",
                "api_secret": "configured" if self.config.api_secret else "missing",
                "webhook_url": "configured" if self.config.webhook_url else "missing",
            }
        )
        config_path = self.config.output_dir / "config_snapshot.json"
        _atomic_json_write(config_path, config_snapshot)
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        scored.head(250).to_csv(
            self.config.output_dir / "candidate_audit_latest.csv",
            index=False,
        )
        candidates = scored[scored["_entry_all_gates"]].head(self.config.candidate_limit)
        if candidates.empty:
            gate_counts = {
                column: int(scored[column].fillna(False).astype(bool).sum())
                for column in scored.columns
                if column.startswith("_gate_")
            }
            record_event(
                self.config,
                "no_candidate",
                message="No Deep-scan row passed every automated entry gate.",
                details={"scan_source": result.source, **gate_counts},
            )
            return self._set_message(
                f"Deep scan complete: no row passed all entry gates ({len(scored)} scanned rows)"
            )

        cooldowns = self.state.setdefault("cooldowns", {})
        for _, row in candidates.iterrows():
            symbol = str(row.get("symbol") or "").upper()
            cooldown_until = int(_to_float(cooldowns.get(symbol))) if _finite(cooldowns.get(symbol)) else 0
            if cooldown_until > now_ms:
                continue
            try:
                confirmation = fetch_entry_confirmation(self.client, symbol, self.config)
            except Exception as exc:
                record_event(
                    self.config,
                    "confirmation_error",
                    symbol=symbol,
                    message=str(exc),
                )
                continue
            if not confirmation["confirmed"]:
                failed = [
                    key for key, passed in confirmation["gates"].items() if not passed
                ]
                record_event(
                    self.config,
                    "confirmation_rejected",
                    symbol=symbol,
                    message="Fresh entry confirmation failed: " + ", ".join(failed),
                    details=confirmation,
                )
                continue
            rules = symbol_rules(self.client, symbol)
            plan = build_risk_plan(
                equity_usdt=equity,
                entry_price=confirmation["best_ask"],
                atr_15m=confirmation["atr_15m"],
                swing_low=confirmation["swing_low"],
                bid_depth_1pct_usdt=confirmation["bid_depth_1pct_usdt"],
                rules=rules,
                config=self.config,
                risk_fraction=risk_fraction,
            )
            if plan.rejection_reason:
                record_event(
                    self.config,
                    "risk_plan_rejected",
                    symbol=symbol,
                    message=plan.rejection_reason,
                    details=asdict(plan),
                )
                continue
            if self.config.live:
                self._enter_live(
                    row,
                    confirmation,
                    plan,
                    equity,
                    live_rows,
                )
            else:
                self._enter_paper(row, confirmation, plan, equity)
            return self.state.get("last_message", "entry processed")
        return self._set_message(
            f"{len(candidates)} Deep candidate(s) found, but none passed fresh confirmation/risk checks"
        )

    def _sync_exit_state(
        self,
        position: dict[str, Any],
        decision_row: dict[str, Any],
        *,
        partial_executed_qty: float = 0.0,
    ) -> None:
        snapshot = _position_snapshot(CloseDecision(False, "", decision_row))
        if partial_executed_qty > 0:
            snapshot.update(
                {
                    "partial_exit_completed": True,
                    "partial_exit_completed_at": _now_iso(),
                    "partial_exit_sample_id": decision_row.get("short_account_sample_id"),
                    "partial_exit_executed_qty": partial_executed_qty,
                    "partial_exit_fraction": decision_row.get("partial_exit_fraction"),
                    "runner_active": True,
                    "runner_confirmation_count": 0,
                    "runner_last_counted_sample_id": decision_row.get("short_account_sample_id"),
                    "exit_signal_stage": "runner_active_wait_exhaustion",
                }
            )
            position["partial_exit_completed"] = True
        position["short_exit_state"] = snapshot

    def _manage_position(self) -> str:
        position = self.state.get("position")
        if not isinstance(position, dict):
            self.state["position"] = None
            return self._set_message("flat")
        symbol = str(position.get("symbol") or "").upper()
        if not symbol:
            self.state["position"] = None
            return self._set_message("invalid persisted position cleared")

        live_rows = self._position_rows()
        if self.config.live:
            fresh_position = _long_position(live_rows, symbol)
            if not fresh_position:
                exit_price = position.get("latest_mark_price") or position.get("current_stop_price")
                self._finalize_position(
                    position,
                    reason="position no longer open; exchange stop or external close detected",
                    exit_price=exit_price,
                    source="exchange_or_external",
                )
                return self.state.get("last_message", "position closed")
            hedge = str(fresh_position.get("positionSide") or "").upper() == "LONG"
            stop = position.get("protective_stop")
            if not isinstance(stop, dict) or not _verify_known_stop(self.client, stop):
                target = Decimal(str(position.get("current_stop_price")))
                replacement = _place_stop(
                    self.client,
                    symbol=symbol,
                    trigger_price=target,
                    hedge_mode=hedge,
                )
                position["protective_stop"] = replacement
                record_event(
                    self.config,
                    "protective_stop_restored",
                    symbol=symbol,
                    message="Missing/inactive bot stop was replaced and verified.",
                    details=replacement,
                )
        else:
            mark_rows = self.client.mark_price(symbol)
            mark = _to_float(
                (mark_rows[0] if mark_rows else {}).get("markPrice")
            )
            if not math.isfinite(mark) or mark <= 0:
                raise RuntimeError(f"{symbol} paper mark price unavailable.")
            fresh_position = self._paper_position_row(position, mark)
            hedge = False

        mark, unrealized, amount = _position_mark_and_pnl(fresh_position)
        entry = _to_float(position.get("entry_price"))
        initial_r = _to_float(position.get("initial_r_per_unit"))
        position["latest_mark_price"] = mark
        position["latest_unrealized_pnl"] = unrealized
        previous_mfe = max(entry, _to_float(position.get("maximum_favorable_price")))
        maximum_price = max(previous_mfe, mark)
        position["maximum_favorable_price"] = maximum_price
        position["maximum_favorable_r"] = (
            (maximum_price - entry) / initial_r
            if initial_r > 0
            else float("nan")
        )
        if not self.config.live and mark <= _to_float(position.get("current_stop_price")):
            self._finalize_position(
                position,
                reason=f"simulated exchange stop triggered at {position.get('current_stop_price')}",
                exit_price=position.get("current_stop_price"),
                source="paper_stop",
            )
            return self.state.get("last_message", "paper stop")

        metrics = _public_position_metrics(self.client, symbol, self.config)
        new_stage, target_stop, ratchet_reason = stop_ratcheting_target(
            position,
            metrics,
            self.config,
        )
        if ratchet_reason and target_stop > _to_float(position.get("current_stop_price")):
            rules = symbol_rules(self.client, symbol)
            rounded_target = _round_step(
                Decimal(str(target_stop)),
                rules.tick_size,
                up=True,
            )
            if self.config.live:
                replacement = _replace_stop(
                    self.client,
                    position,
                    rounded_target,
                    hedge_mode=hedge,
                )
            else:
                replacement = {
                    "algo_id": "paper",
                    "client_algo_id": "paper",
                    "trigger_price": float(rounded_target),
                    "placed_at": _now_iso(),
                }
            position["protective_stop"] = replacement
            position["current_stop_price"] = float(rounded_target)
            position["stop_stage"] = new_stage
            record_event(
                self.config,
                "stop_ratcheted",
                symbol=symbol,
                message=ratchet_reason,
                details={
                    "stop_stage": new_stage,
                    "new_stop": float(rounded_target),
                    "mark": mark,
                    "mfe_r": position.get("maximum_favorable_r"),
                },
            )
            post_discord(
                self.config,
                f"{symbol} stop moved: {new_stage}",
                f"{ratchet_reason}\nMark {mark:.10g} | new stop {float(rounded_target):.10g} | "
                f"MFE {position.get('maximum_favorable_r'):.2f}R",
                color=0xFEE75C,
            )

        failure_reason = thesis_failure_reason(position, metrics, self.config)
        if failure_reason:
            if self.config.live:
                rules = symbol_rules(self.client, symbol)
                order = execute_price_protected_close(
                    self.client,
                    position_row=fresh_position,
                    close_fraction=1.0,
                    rules=rules,
                    config=self.config,
                )
                record_event(
                    self.config,
                    "thesis_failure_exit_order",
                    symbol=symbol,
                    message=failure_reason,
                    details={"order": order},
                )
                refreshed = self.client.position_information_v3(symbol)
                if not _long_position(refreshed, symbol):
                    exit_price = _to_float(order.get("avgPrice"))
                    if not math.isfinite(exit_price) or exit_price <= 0:
                        exit_price = mark
                    self._finalize_position(
                        position,
                        reason=failure_reason,
                        exit_price=exit_price,
                        source="thesis_failure_bot",
                    )
                    return self.state.get("last_message", "thesis exit")
            else:
                self._finalize_position(
                    position,
                    reason=failure_reason,
                    exit_price=mark,
                    source="paper_thesis_failure",
                )
                return self.state.get("last_message", "paper thesis exit")

        stop_order_view = {
            "type": "STOP_MARKET",
            "side": "SELL",
            "triggerPrice": position.get("current_stop_price"),
        }
        close_config = _short_close_config(self.config, symbol)
        decision = evaluate_close_decision(
            symbol=symbol,
            position=fresh_position,
            short_metrics=metrics,
            config=close_config,
            open_orders=[stop_order_view],
            signal_state=position.get("short_exit_state") or {},
        )
        self._sync_exit_state(position, decision.row)
        if decision.should_close:
            fraction = _to_float(decision.row.get("close_fraction"))
            if not math.isfinite(fraction) or fraction <= 0:
                fraction = 1.0
            if self.config.live:
                rules = symbol_rules(self.client, symbol)
                order = execute_price_protected_close(
                    self.client,
                    position_row=fresh_position,
                    close_fraction=fraction,
                    rules=rules,
                    config=self.config,
                )
                executed = _executed_quantity(order)
                record_event(
                    self.config,
                    "short_roc_exit_order",
                    symbol=symbol,
                    message=decision.reason,
                    details={"close_fraction": fraction, "order": order},
                )
                refreshed = self.client.position_information_v3(symbol)
                remaining = _long_position(refreshed, symbol)
                if not remaining:
                    exit_price = _to_float(order.get("avgPrice"))
                    if not math.isfinite(exit_price) or exit_price <= 0:
                        exit_price = mark
                    self._finalize_position(
                        position,
                        reason=decision.reason,
                        exit_price=exit_price,
                        source="short_roc_bot",
                    )
                    return self.state.get("last_message", "short ROC exit")
                if executed > 0 and fraction < 1.0:
                    self._sync_exit_state(
                        position,
                        decision.row,
                        partial_executed_qty=executed,
                    )
                    position["quantity"] = abs(_to_float(remaining.get("positionAmt")))
                    post_discord(
                        self.config,
                        f"{symbol} partial short-ROC exit",
                        f"{decision.reason}\nExecuted {executed:.10g}; protected runner remains.",
                        color=0xFEE75C,
                    )
            else:
                if fraction < 1.0 and not position.get("partial_exit_completed"):
                    executed = _to_float(position.get("quantity")) * fraction
                    position["quantity"] = _to_float(position.get("quantity")) - executed
                    self._sync_exit_state(
                        position,
                        decision.row,
                        partial_executed_qty=executed,
                    )
                    record_event(
                        self.config,
                        "paper_short_roc_partial",
                        symbol=symbol,
                        message=decision.reason,
                        details={"executed_quantity": executed},
                    )
                else:
                    self._finalize_position(
                        position,
                        reason=decision.reason,
                        exit_price=mark,
                        source="paper_short_roc",
                    )
                    return self.state.get("last_message", "paper short ROC exit")

        position["last_metrics"] = _json_safe(metrics)
        self.state["position"] = position
        message = (
            f"{symbol} {position.get('stop_stage')} | mark {mark:.10g} | "
            f"unrealized {_fmt_money(unrealized)} | MFE {position.get('maximum_favorable_r'):.2f}R | "
            f"short {_fmt_pct(metrics.get('short_account_pct'), signed=False)} | "
            f"short ROC {_fmt_pct(metrics.get('short_account_roc_1h_pct'))} | "
            f"stop {position.get('current_stop_price')}"
        )
        return self._set_message(message)

    def run_cycle(self) -> str:
        self.state = load_state(self.config)
        if isinstance(self.state.get("position"), dict):
            return self._manage_position()
        return self._scan_and_maybe_enter()

    def run_forever(self) -> None:
        while True:
            try:
                self.run_cycle()
            except KeyboardInterrupt:
                print(f"[{_now_label()}] stopped by user", flush=True)
                return
            except Exception as exc:
                message = f"automated trader cycle failed closed: {exc}"
                print(f"[{_now_label()}] {message}", flush=True)
                record_event(
                    self.config,
                    "cycle_error",
                    symbol=str((self.state.get("position") or {}).get("symbol") or ""),
                    message=str(exc),
                )
                post_discord(
                    self.config,
                    "Automated trader cycle failed closed",
                    str(exc),
                    color=0xED4245,
                )
            if self.config.once:
                return
            time.sleep(max(30.0, self.config.manage_interval_seconds))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fully automated concentrated-float, crowded-short uptrend entry and "
            "position lifecycle manager."
        )
    )
    parser.add_argument("--live", action="store_true", help="Permit live orders after both live environment gates pass.")
    parser.add_argument("--once", action="store_true", help="Run one scan/management cycle and exit.")
    parser.add_argument("--scan-mode", default=_env_value("AUTO_SHORT_UPTREND_SCAN_MODE", "Deep"))
    parser.add_argument("--output-dir", default=_env_value("AUTO_SHORT_UPTREND_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)))
    parser.add_argument("--manage-interval-seconds", type=float, default=float(_env_value("AUTO_SHORT_UPTREND_MANAGE_INTERVAL_SECONDS", "60")))
    parser.add_argument("--flat-scan-interval-seconds", type=float, default=float(_env_value("AUTO_SHORT_UPTREND_FLAT_SCAN_INTERVAL_SECONDS", "900")))
    parser.add_argument("--leverage", type=int, default=int(_env_value("AUTO_SHORT_UPTREND_LEVERAGE", "2")))
    parser.add_argument("--risk-pct", type=float, default=float(_env_value("AUTO_SHORT_UPTREND_RISK_PCT", "0.25")))
    parser.add_argument("--max-stress-risk-pct", type=float, default=float(_env_value("AUTO_SHORT_UPTREND_MAX_STRESS_RISK_PCT", "0.50")))
    parser.add_argument("--paper-equity-usdt", type=float, default=float(_env_value("AUTO_SHORT_UPTREND_PAPER_EQUITY_USDT", "10000")))
    parser.add_argument("--min-short-pct", type=float, default=float(_env_value("AUTO_SHORT_UPTREND_MIN_SHORT_PCT", "60")))
    parser.add_argument("--min-short-build-pp", type=float, default=float(_env_value("AUTO_SHORT_UPTREND_MIN_SHORT_BUILD_PP", "0.5")))
    parser.add_argument("--min-hour-volume-roc-pct", type=float, default=float(_env_value("AUTO_SHORT_UPTREND_MIN_HOUR_VOLUME_ROC_PCT", "50")))
    parser.add_argument("--min-daily-volume-ratio", type=float, default=float(_env_value("AUTO_SHORT_UPTREND_MIN_DAILY_VOLUME_RATIO", "2")))
    parser.add_argument("--min-quote-volume-usdt", type=float, default=float(_env_value("AUTO_SHORT_UPTREND_MIN_QUOTE_VOLUME_USDT", "2500000")))
    parser.add_argument("--min-oi-change-pct", type=float, default=float(_env_value("AUTO_SHORT_UPTREND_MIN_OI_CHANGE_PCT", "0.5")))
    parser.add_argument("--allow-missing-holder-proof", action="store_true", help="Relax explorer-backed concentration proof. Not recommended for live use.")
    parser.add_argument("--allow-missing-bitget", action="store_true", help="Relax Binance+Bitget venue proof. Not recommended for live use.")
    parser.add_argument("--require-spot-confirmation", action="store_true", help="Require the scanner's spot-flow confluence score.")
    parser.add_argument("--candidate-limit", type=int, default=int(_env_value("AUTO_SHORT_UPTREND_CANDIDATE_LIMIT", "5")))
    parser.add_argument("--base-url", default=_env_value("BINANCE_FAPI_BASE_URL", "https://fapi.binance.com"))
    parser.add_argument("--timeout", type=int, default=int(_env_value("AUTO_SHORT_UPTREND_HTTP_TIMEOUT", "12")))
    parser.add_argument("--retries", type=int, default=int(_env_value("AUTO_SHORT_UPTREND_HTTP_RETRIES", "3")))
    parser.add_argument("--requests-per-second", type=float, default=float(_env_value("AUTO_SHORT_UPTREND_REQUESTS_PER_SECOND", "3")))
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> AutoTraderConfig:
    mode = "live" if args.live else "paper"
    if mode == "live":
        live_enabled = _env_bool("AUTO_SHORT_UPTREND_LIVE", False)
        acknowledged = (
            _env_value("AUTO_SHORT_UPTREND_LIVE_ACK", "")
            == "I_ACCEPT_LIVE_ORDERS"
        )
        if not live_enabled or not acknowledged:
            raise RuntimeError(
                "Live entry refused. Both AUTO_SHORT_UPTREND_LIVE=1 and "
                "AUTO_SHORT_UPTREND_LIVE_ACK=I_ACCEPT_LIVE_ORDERS are required."
            )
    risk_fraction = min(0.005, max(0.0001, float(args.risk_pct) / 100.0))
    stress_fraction = min(
        0.01,
        max(risk_fraction, float(args.max_stress_risk_pct) / 100.0),
    )
    return AutoTraderConfig(
        mode=mode,
        scan_mode=str(args.scan_mode or "Deep"),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        webhook_url=_env_value(
            "AUTO_SHORT_UPTREND_DISCORD_WEBHOOK_URL",
            _env_value("DISCORD_WEBHOOK_URL", ""),
        ),
        base_url=str(args.base_url),
        api_key=_env_value("BINANCE_API_KEY", _env_value("BINANCE_FUTURES_API_KEY", "")),
        api_secret=_env_value("BINANCE_API_SECRET", _env_value("BINANCE_FUTURES_API_SECRET", "")),
        timeout=max(3, int(args.timeout)),
        retries=max(1, int(args.retries)),
        requests_per_second=max(0.5, float(args.requests_per_second)),
        manage_interval_seconds=max(30.0, float(args.manage_interval_seconds)),
        flat_scan_interval_seconds=max(300.0, float(args.flat_scan_interval_seconds)),
        once=bool(args.once),
        leverage=min(3, max(1, int(args.leverage))),
        risk_fraction=risk_fraction,
        max_stress_risk_fraction=stress_fraction,
        daily_loss_fraction=0.0075,
        weekly_loss_fraction=0.02,
        drawdown_halve_fraction=0.05,
        drawdown_pause_fraction=0.08,
        paper_equity_usdt=max(100.0, float(args.paper_equity_usdt)),
        max_notional_fraction=0.25,
        max_depth_fraction=0.05,
        min_short_pct=max(50.0, float(args.min_short_pct)),
        min_short_roc_pp=max(0.0, float(args.min_short_build_pp)),
        min_smoothed_short_roc_pp=0.25,
        min_short_persistence=2,
        min_funding_pct=0.0,
        min_hour_volume_roc_pct=max(0.0, float(args.min_hour_volume_roc_pct)),
        min_daily_volume_ratio=max(1.0, float(args.min_daily_volume_ratio)),
        min_quote_volume_usdt=max(0.0, float(args.min_quote_volume_usdt)),
        min_oi_change_pct=max(0.0, float(args.min_oi_change_pct)),
        max_late_heat_score=55.0,
        max_price_above_avwap_pct=80.0,
        min_top10_holder_pct=80.0,
        min_top100_holder_pct=90.0,
        require_holder_evidence=not bool(args.allow_missing_holder_proof),
        require_bitget_evidence=not bool(args.allow_missing_bitget),
        require_spot_confirmation=bool(args.require_spot_confirmation),
        min_spot_flow_score=40.0,
        candidate_limit=max(1, min(25, int(args.candidate_limit))),
        confirmation_breakout_bars=8,
        min_confirmation_close_location_pct=65.0,
        max_short_data_age_minutes=90.0,
        max_entry_spread_pct=0.50,
        entry_limit_slippage_pct=0.0025,
        risk_slippage_pct=0.015,
        round_trip_fee_pct=0.0012,
        atr_period=14,
        atr_stop_multiple=1.5,
        swing_lookback_bars=8,
        swing_atr_buffer=0.5,
        min_stop_distance_pct=0.025,
        max_stop_distance_pct=0.12,
        risk_reduce_trigger_r=0.75,
        risk_reduced_stop_r=0.5,
        breakeven_trigger_r=1.25,
        breakeven_atr_multiple=2.0,
        breakeven_confirmation_bars=1,
        breakeven_cost_buffer_pct=0.0015,
        early_proof_hours=2.0,
        early_proof_mfe_r=0.5,
        max_proof_hours=4.0,
        max_proof_mfe_r=0.75,
        absolute_proof_timeout_hours=8.0,
        preproof_short_drop_pp=2.0,
        cooldown_hours=12.0,
        short_exit_trigger_pct=4.0,
        short_exit_level_pct=65.0,
        short_exit_peak_drawdown_pp=5.0,
        short_exit_confirmation_readings=2,
        short_exit_partial_pct=50.0,
        short_exit_runner_readings=2,
        short_exit_runner_oi_drop_pct=3.0,
        short_exit_runner_volume_drop_pct=20.0,
        short_exit_execution_floor_pct=0.25,
    )


def main(argv: list[str] | None = None) -> None:
    _load_local_env()
    config = config_from_args(parse_args(argv))
    if config.live and (not config.api_key or not config.api_secret):
        raise RuntimeError("Live mode requires Binance API key and secret in .env.")
    config.output_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"[{_now_label()}] starting automated short-uptrend trader | mode={config.mode} "
        f"scan={config.scan_mode} risk={config.risk_fraction:.2%} "
        f"stress_cap={config.max_stress_risk_fraction:.2%} leverage={config.leverage}x "
        f"short>={config.min_short_pct:.1f}% build>={config.min_short_roc_pp:.2f}pp "
        f"hour_volume>={config.min_hour_volume_roc_pct:.0f}% "
        f"daily_volume>={config.min_daily_volume_ratio:.2f}x "
        f"holder_proof={config.require_holder_evidence} "
        f"bitget={config.require_bitget_evidence} output={config.output_dir}",
        flush=True,
    )
    post_discord(
        config,
        f"Automated short-uptrend trader started ({config.mode.upper()})",
        (
            f"Risk {config.risk_fraction:.2%} per trade | stress cap "
            f"{config.max_stress_risk_fraction:.2%} | {config.leverage}x isolated\n"
            f"Strict holder proof: {config.require_holder_evidence} | "
            f"Binance+Bitget proof: {config.require_bitget_evidence}\n"
            f"Output: {config.output_dir}"
        ),
        color=0x5865F2,
    )
    with SingleInstanceLock(config.output_dir / "instance.lock"):
        AutoShortUptrendTrader(config).run_forever()


if __name__ == "__main__":
    main()
