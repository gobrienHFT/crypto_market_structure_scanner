from __future__ import annotations

from typing import Any, Mapping

import pandas as pd


ARCHETYPE_SCORE_COLUMNS = [
    "archetype_rave_score",
    "archetype_lab_score",
    "archetype_siren_score",
    "archetype_river_score",
    "archetype_sto_score",
    "archetype_match_score",
    "archetype_best_match",
    "archetype_match_note",
]


ARCHETYPE_LABELS = {
    "archetype_rave_score": "RAVE-style cap-table reflexivity",
    "archetype_lab_score": "LAB-style venue-inventory stress",
    "archetype_siren_score": "SIREN-style short-fuse compression",
    "archetype_river_score": "RIVER-style runway breakout",
    "archetype_sto_score": "STO-style target-venue squeeze",
}


def _num(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").fillna(default).astype("float64")


def _clip(series: pd.Series, lower: float = 0.0, upper: float = 100.0) -> pd.Series:
    return series.clip(lower=lower, upper=upper)


def _score_linear(series: pd.Series, low: float, high: float, *, invert: bool = False) -> pd.Series:
    if high <= low:
        scored = pd.Series(0.0, index=series.index, dtype="float64")
    else:
        scored = ((series - low) / (high - low) * 100.0).clip(lower=0.0, upper=100.0)
    return 100.0 - scored if invert else scored


def _score_band(series: pd.Series, low: float, sweet_low: float, sweet_high: float, high: float) -> pd.Series:
    left = _score_linear(series, low, sweet_low)
    right = _score_linear(series, sweet_high, high, invert=True)
    scored = pd.Series(100.0, index=series.index, dtype="float64")
    scored = scored.where(series >= sweet_low, left)
    scored = scored.where(series <= sweet_high, right)
    return scored.clip(lower=0.0, upper=100.0)


def _max_num(frame: pd.DataFrame, *columns: str, default: float = 0.0) -> pd.Series:
    if not columns:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.concat([_num(frame, column, default) for column in columns], axis=1).max(axis=1).fillna(default)


def _bool_score(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0.0, index=frame.index, dtype="float64")
    return frame[column].fillna(False).astype(bool).astype(float) * 100.0


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _best_match(row: Mapping[str, Any] | pd.Series) -> str:
    scores = {label: _safe_float(row.get(label)) or 0.0 for label in ARCHETYPE_LABELS}
    best_key, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score < 35.0:
        return "No strong case-study analogue"
    return ARCHETYPE_LABELS[best_key]


def _top_score(row: Mapping[str, Any] | pd.Series) -> float:
    values = [_safe_float(row.get(column)) or 0.0 for column in ARCHETYPE_LABELS]
    return max(values) if values else 0.0


def _archetype_note(row: Mapping[str, Any] | pd.Series) -> str:
    label = str(row.get("archetype_best_match", "") or _best_match(row))
    score = _safe_float(row.get("archetype_match_score")) or _top_score(row)
    if label == "RAVE-style cap-table reflexivity":
        detail = "cap-table concentration, opaque/hidden-float markers, and ATH/runway asymmetry"
    elif label == "LAB-style venue-inventory stress":
        detail = "controlled float, concentration-gated CEX flow, and venue-inventory pressure"
    elif label == "SIREN-style short-fuse compression":
        detail = "short crowding, low-vol compression, and pre-ignition quality before chase extension"
    elif label == "RIVER-style runway breakout":
        detail = "runway, venue support, constructive range pressure, and not-too-late ignition"
    elif label == "STO-style target-venue squeeze":
        detail = "target-venue support, whale/control pressure, short crowding, and early timing before chase extension"
    else:
        detail = "no single reference pattern dominates; use the component scores"
    return f"{label} {score:.0f}/100; {detail}"


def apply_archetype_model(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        output = frame.copy()
        for column in ARCHETYPE_SCORE_COLUMNS:
            output[column] = pd.NA
        return output

    output = frame.copy()
    top10 = _max_num(output, "top10_holder_pct", "raw_top_10_pct", "adjusted_top_10_pct")
    top100 = _max_num(output, "top100_holder_pct", "raw_top_100_pct")
    control_plane = _max_num(
        output,
        "terminal_control_plane_score",
        "centralized_ownership_score",
        "low_float_score",
        "float_trap_score",
    )
    hidden_float = _max_num(
        output,
        "terminal_hidden_float_reflexivity_score",
        "terminal_opaque_supply_score",
        "opaque_supply_score",
    )
    cex_flow = _max_num(output, "cex_deposit_flow_score", "terminal_exchange_flow_score", "target_cex_flow_score")
    inventory_stress = _num(output, "cex_deposit_inventory_stress_score")
    distribution = _max_num(output, "terminal_distribution_pressure_score", "inventory_transfer_risk_score")
    pre_ignition = _max_num(output, "terminal_pre_ignition_quality_score", "pre_pump_precision_score", "dormant_short_fuse_score")
    short_pressure = _max_num(output, "terminal_short_pressure_score", "short_dominance_score", "pre_pump_short_fuse_score")
    runway = _max_num(output, "terminal_runway_score", "convexity_runway_score", "ath_runway_confluence_score")
    venue = _max_num(output, "venue_support_score", "binance_bitget_gate_share_score", "mm_sponsor_confluence_score")
    target_venue = _max_num(
        output,
        "binance_bitget_gate_share_score",
        "target_cex_flow_score",
        "cex_lane_wakeup_score",
        "venue_support_score",
    )
    ignition = _max_num(output, "terminal_ignition_score", "ignition_score_v2", "price_volume_ignition_score")
    late_risk = _max_num(output, "terminal_risk_score", "convexity_late_penalty", "no_chase_penalty_score")

    ath_multiple = _num(output, "ath_multiple")
    hour_return_abs = _num(output, "hour_return_pct").abs()
    day_return_abs = _num(output, "day_return_pct").abs()
    short_pct = _num(output, "short_account_pct")
    oi_delta = _num(output, "oi_delta_pct")
    close_loc = _num(output, "hour_close_location_pct", 50.0)
    volume_signal = _max_num(output, "hour_volume_multiple", "daily_quote_volume_multiple")
    range_breakout = _max_num(output, "range_breakout_score")

    quiet_not_chased = _clip(
        _score_band(hour_return_abs, 0.0, 0.1, 5.0, 18.0) * 0.45
        + _score_band(day_return_abs, 0.0, 0.5, 18.0, 80.0) * 0.35
        + _score_linear(late_risk, 20.0, 70.0, invert=True) * 0.20
    )

    output["archetype_rave_score"] = _clip(
        _score_linear(top100, 95.0, 99.7) * 0.16
        + _score_linear(top10, 70.0, 95.0) * 0.14
        + hidden_float * 0.18
        + control_plane * 0.14
        + _score_linear(ath_multiple, 15.0, 80.0) * 0.14
        + _max_num(output, "ravedao_archetype_score", "master_score") * 0.10
        + distribution * 0.08
        + _score_linear(_num(output, "fdv_to_market_cap"), 2.0, 12.0) * 0.06
    )
    output["archetype_lab_score"] = _clip(
        control_plane * 0.22
        + cex_flow * 0.19
        + inventory_stress * 0.21
        + distribution * 0.17
        + venue * 0.09
        + _score_linear(top10, 70.0, 95.0) * 0.06
        + _bool_score(output, "bitget_rank_1_inventory_dominance") * 0.03
        + _bool_score(output, "cex_deposit_flow_flag") * 0.03
    )
    output["archetype_siren_score"] = _clip(
        pre_ignition * 0.24
        + short_pressure * 0.20
        + _score_linear(short_pct, 48.0, 70.0) * 0.12
        + _score_linear(oi_delta, 0.25, 6.0) * 0.10
        + _max_num(output, "low_volatility_coil_score", "pre_pump_compression_score") * 0.12
        + quiet_not_chased * 0.10
        + control_plane * 0.08
        - late_risk * 0.14
    )
    output["archetype_river_score"] = _clip(
        runway * 0.24
        + range_breakout * 0.18
        + venue * 0.16
        + ignition * 0.12
        + _score_linear(close_loc, 55.0, 88.0) * 0.08
        + _score_linear(volume_signal, 1.05, 4.0) * 0.08
        + _score_linear(ath_multiple, 8.0, 35.0) * 0.06
        + _max_num(output, "terminal_edge_score", "trade_bucket_score") * 0.08
        - late_risk * 0.10
    )
    output["archetype_sto_score"] = _clip(
        target_venue * 0.18
        + control_plane * 0.16
        + short_pressure * 0.18
        + _score_linear(short_pct, 50.0, 72.0) * 0.10
        + pre_ignition * 0.14
        + cex_flow * 0.10
        + inventory_stress * 0.07
        + quiet_not_chased * 0.09
        + _score_linear(top10, 70.0, 94.0) * 0.06
        - late_risk * 0.12
    )

    score_frame = output[list(ARCHETYPE_LABELS)].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    output["archetype_match_score"] = score_frame.max(axis=1)
    output["archetype_best_match"] = output.apply(_best_match, axis=1)
    output["archetype_match_note"] = output.apply(_archetype_note, axis=1)
    return output
