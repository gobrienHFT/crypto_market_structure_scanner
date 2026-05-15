from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from terminal_engine import _bool, _clip, _first_float, _fmt_pct, _num, _pct_value, _safe_float


TIMING_SCORE_COLUMNS = [
    "timing_score",
    "timing_trigger_score",
    "timing_reclaim_score",
    "timing_flow_score",
    "timing_early_score",
    "timing_too_late_score",
    "timing_state",
    "timing_observed_trigger",
    "timing_confirmation_needed",
    "timing_invalidation",
    "timing_failure_condition",
    "timing_hold_condition",
    "timing_liquidity_warning",
]


def _score_linear(series: pd.Series, low: float, high: float, *, invert: bool = False) -> pd.Series:
    if high <= low:
        score = pd.Series(0.0, index=series.index)
    else:
        score = ((series - low) / (high - low) * 100.0).clip(lower=0.0, upper=100.0)
    return 100.0 - score if invert else score


def _score_band(series: pd.Series, low: float, sweet_low: float, sweet_high: float, high: float) -> pd.Series:
    left = _score_linear(series, low, sweet_low)
    right = _score_linear(series, sweet_high, high, invert=True)
    score = pd.Series(100.0, index=series.index, dtype="float64")
    score = score.where(series >= sweet_low, left)
    score = score.where(series <= sweet_high, right)
    return score.clip(lower=0.0, upper=100.0)


def _row_bool(row: Mapping[str, Any] | pd.Series, key: str) -> bool:
    value = row.get(key) if hasattr(row, "get") else False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    try:
        if value is None or pd.isna(value):
            return False
    except Exception:
        pass
    return bool(value)


def infer_timing_state(row: Mapping[str, Any] | pd.Series) -> str:
    score = _first_float(row, "timing_score") or 0.0
    trigger = _first_float(row, "timing_trigger_score") or 0.0
    too_late = _first_float(row, "timing_too_late_score") or 0.0
    terminal = _first_float(row, "terminal_edge_score") or 0.0
    oi = _first_float(row, "oi_delta_pct") or 0.0
    close_loc = _first_float(row, "hour_close_location_pct")
    wick = _first_float(row, "hour_upper_wick_pct") or 0.0
    vol_x = _first_float(row, "hour_volume_multiple", "daily_quote_volume_multiple") or 0.0

    if too_late >= 72.0 or (wick >= 38.0 and close_loc is not None and close_loc <= 42.0):
        return "Extended / fragile"
    if oi <= -1.0 and vol_x < 1.0 and close_loc is not None and close_loc < 35.0:
        return "Dead / invalidating"
    if score >= 72.0 and trigger >= 65.0:
        return "Confirmed"
    if score >= 58.0 and trigger >= 48.0:
        return "Triggering"
    if terminal >= 58.0 and trigger < 45.0:
        return "Coiling"
    if terminal >= 45.0:
        return "Dormant watch"
    return "No timing edge"


def infer_observed_trigger(row: Mapping[str, Any] | pd.Series) -> str:
    triggers: list[str] = []
    accumulation = _first_float(row, "accumulation_absorption_score", "accumulation_cvd_proxy_score") or 0.0
    if accumulation >= 60.0 or _row_bool(row, "accumulation_absorption_flag"):
        triggers.append("aggressive taker demand absorbed with muted price response")
    if (_first_float(row, "oi_delta_pct") or 0.0) >= 1.0:
        triggers.append("OI expanding")
    if (_first_float(row, "hour_volume_multiple", "daily_quote_volume_multiple") or 0.0) >= 1.25:
        triggers.append("volume lifting from baseline")
    if (_first_float(row, "hour_trade_count_multiple") or 0.0) >= 1.20:
        triggers.append("trade count rising")
    close_loc = _first_float(row, "hour_close_location_pct")
    if close_loc is not None and close_loc >= 60.0:
        triggers.append("close quality constructive")
    short_pct = _pct_value(_first_float(row, "short_account_pct"))
    if short_pct is not None and short_pct >= 50.0:
        triggers.append(f"short accounts {_fmt_pct(short_pct)}")
    return ", ".join(triggers[:5]) if triggers else "no live trigger confirmed yet"


def infer_timing_confirmation(row: Mapping[str, Any] | pd.Series) -> str:
    needs: list[str] = []
    accumulation = _first_float(row, "accumulation_absorption_score", "accumulation_cvd_proxy_score") or 0.0
    if (_first_float(row, "oi_delta_pct") or 0.0) < 1.0:
        needs.append("OI expansion")
    if (_first_float(row, "hour_volume_multiple", "daily_quote_volume_multiple") or 0.0) < 1.25:
        if accumulation >= 60.0 or _row_bool(row, "accumulation_absorption_flag"):
            needs.append("continued absorption/volume confirmation")
        else:
            needs.append("volume lift")
    if (_first_float(row, "hour_trade_count_multiple") or 0.0) < 1.15:
        needs.append("trade-count lift")
    close_loc = _first_float(row, "hour_close_location_pct")
    if close_loc is None or close_loc < 60.0:
        needs.append("stronger close location")
    if (_pct_value(_first_float(row, "short_account_pct")) or 0.0) < 50.0:
        needs.append("short-account majority")
    return ", ".join(needs[:5]) if needs else "OI, volume, trade count, close quality, and positioning are aligned"


def infer_timing_invalidation(row: Mapping[str, Any] | pd.Series) -> str:
    if infer_timing_state(row) == "Extended / fragile":
        return "upper wick persists, OI fades, and volume fails to support the move"
    if (_pct_value(_first_float(row, "short_account_pct")) or 0.0) >= 50.0:
        return "short pressure unwinds while OI contracts and reclaim levels fail"
    return "OI contracts, volume fades, and price fails to reclaim the local range"


def infer_failure_condition(row: Mapping[str, Any] | pd.Series) -> str:
    return "mark as failed if OI contracts, close quality weakens, and volume decays across the next scan window"


def infer_hold_condition(row: Mapping[str, Any] | pd.Series) -> str:
    accumulation = _first_float(row, "accumulation_absorption_score", "accumulation_cvd_proxy_score") or 0.0
    if accumulation >= 60.0 or _row_bool(row, "accumulation_absorption_flag"):
        return "structure remains relevant while absorption persists, OI does not flush, and price avoids chase extension"
    if infer_timing_state(row) in {"Confirmed", "Triggering"}:
        return "structure remains relevant while OI/volume expand and closes keep reclaiming local highs"
    return "structure remains watchable only if OI/volume begin confirming without a chase candle"


def infer_timing_liquidity_warning(row: Mapping[str, Any] | pd.Series) -> str:
    accumulation = _first_float(row, "accumulation_absorption_score", "accumulation_cvd_proxy_score") or 0.0
    if accumulation >= 60.0 or _row_bool(row, "accumulation_absorption_flag"):
        return "accumulation-like absorption can release into gaps if liquidity thins; verify visible depth"
    top100 = _first_float(row, "top100_holder_pct")
    ask_depth = _first_float(row, "ask_depth_1pct_usdt")
    spread = _first_float(row, "coinbase_bid_ask_spread_pct")
    if top100 is not None and top100 >= 95.0:
        return "top 100 holders control most observed supply; exits can gap"
    if ask_depth is not None and ask_depth < 75_000:
        return "visible ask depth is thin; slippage can expand quickly"
    if spread is not None and spread > 1.0:
        return "visible spread is wide; execution quality may degrade"
    return "liquidity must still be checked against intended size"


def apply_timing_model(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        output = frame.copy()
        for column in TIMING_SCORE_COLUMNS:
            if column not in output.columns:
                output[column] = pd.NA
        return output

    output = frame.copy()
    hour_return = _num(output, "hour_return_pct")
    day_return = _num(output, "day_return_pct")
    if "day_return_pct" not in output.columns and "price_change_24h_pct" in output.columns:
        day_return = _num(output, "price_change_24h_pct")
    oi = _num(output, "oi_delta_pct")
    close_loc = _num(output, "hour_close_location_pct", 50.0)
    wick = _num(output, "hour_upper_wick_pct")
    hour_vol = _num(output, "hour_volume_multiple")
    daily_vol = _num(output, "daily_quote_volume_multiple")
    volume_signal = pd.concat([hour_vol, daily_vol], axis=1).max(axis=1)
    trade_count = _num(output, "hour_trade_count_multiple")
    short_pct = _num(output, "short_account_pct")
    dist_5d = _num(output, "distance_to_high_5d_pct", 25.0)
    dist_20d = _num(output, "distance_to_high_20d_pct", 35.0)
    terminal = _num(output, "terminal_edge_score")
    ask_depth_to_vol = _num(output, "ask_depth_to_24h_volume_pct", 0.15)
    range_event_score = _num(output, "range_breakout_score")
    accumulation = _num(output, "accumulation_absorption_score")

    trigger_score = _clip(
        _score_linear(oi, 0.25, 5.0) * 0.28
        + _score_band(hour_return, -2.0, 0.2, 7.5, 18.0) * 0.18
        + _score_linear(close_loc, 52.0, 90.0) * 0.17
        + _score_linear(volume_signal, 1.05, 4.0) * 0.17
        + _score_linear(trade_count, 1.05, 3.0) * 0.14
        + range_event_score * 0.06
        + accumulation * 0.10
    )
    reclaim_score = _clip(
        _score_linear(dist_5d.abs(), 0.0, 12.0, invert=True) * 0.55
        + _score_linear(dist_20d.abs(), 0.0, 20.0, invert=True) * 0.25
        + _score_linear(close_loc, 55.0, 88.0) * 0.20
    )
    flow_score = _clip(
        _score_linear(short_pct, 48.0, 68.0) * 0.36
        + _score_linear(oi, 0.25, 6.0) * 0.28
        + _score_linear(volume_signal, 1.0, 5.0) * 0.20
        + _score_linear(trade_count, 1.0, 3.5) * 0.16
        + accumulation * 0.12
    )
    too_late = _clip(
        _score_linear(hour_return, 10.0, 32.0) * 0.26
        + _score_linear(day_return, 35.0, 160.0) * 0.24
        + _score_linear(wick, 18.0, 55.0) * 0.24
        + _num(output, "convexity_late_penalty") * 0.20
        + _num(output, "no_chase_penalty_score") * 0.10
    )
    early_score = _clip(
        100.0
        - too_late * 0.55
        + _score_band(hour_return.abs(), 0.0, 0.4, 6.0, 18.0) * 0.18
        + _score_band(daily_vol, 0.75, 1.05, 3.0, 9.0) * 0.14
        + _score_linear(ask_depth_to_vol, 0.02, 0.20) * 0.13
        + accumulation * 0.08
    )
    timing_score = _clip(
        terminal * 0.22
        + trigger_score * 0.25
        + reclaim_score * 0.18
        + flow_score * 0.15
        + early_score * 0.15
        + _num(output, "terminal_liquidity_score", 50.0) * 0.05
        + accumulation * 0.08
        - too_late * 0.12
        + _bool(output, "setup_ready_flag").astype(float) * 6.0
        + _bool(output, "clean_convex_setup_flag").astype(float) * 4.0
    )

    output["timing_score"] = timing_score
    output["timing_trigger_score"] = trigger_score
    output["timing_reclaim_score"] = reclaim_score
    output["timing_flow_score"] = flow_score
    output["timing_early_score"] = early_score
    output["timing_too_late_score"] = too_late
    output["timing_state"] = output.apply(infer_timing_state, axis=1)
    output["timing_observed_trigger"] = output.apply(infer_observed_trigger, axis=1)
    output["timing_confirmation_needed"] = output.apply(infer_timing_confirmation, axis=1)
    output["timing_invalidation"] = output.apply(infer_timing_invalidation, axis=1)
    output["timing_failure_condition"] = output.apply(infer_failure_condition, axis=1)
    output["timing_hold_condition"] = output.apply(infer_hold_condition, axis=1)
    output["timing_liquidity_warning"] = output.apply(infer_timing_liquidity_warning, axis=1)
    return output


def build_timing_card(row: Mapping[str, Any] | pd.Series) -> str:
    symbol = str(row.get("symbol", "UNKNOWN")).upper() if hasattr(row, "get") else "UNKNOWN"
    score = _safe_float(row.get("timing_score") if hasattr(row, "get") else None)
    state = str(row.get("timing_state", "No timing edge")) if hasattr(row, "get") else "No timing edge"
    return "\n".join(
        [
            f"/{symbol}",
            "",
            f"Timing Score: {score:.0f}/100" if score is not None else "Timing Score: n/a",
            f"State: {state}",
            f"Observed trigger: {row.get('timing_observed_trigger', 'pending')}",
            f"Confirmation needed: {row.get('timing_confirmation_needed', 'pending')}",
            f"Invalidation: {row.get('timing_invalidation', 'pending')}",
            f"Failure condition: {row.get('timing_failure_condition', 'pending')}",
            f"Structure remains relevant while: {row.get('timing_hold_condition', 'pending')}",
            f"Liquidity warning: {row.get('timing_liquidity_warning', 'check liquidity')}",
            "Research constraint: entries, sizing, stops, and execution are your own responsibility",
        ]
    )
