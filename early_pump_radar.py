from __future__ import annotations

import re
from typing import Any, Mapping

import pandas as pd


TARGET_CEX_RE = re.compile(r"\b(?:binance|bitget|gate(?:\.io|io)?)\b", flags=re.IGNORECASE)

EARLY_PUMP_RADAR_COLUMNS = [
    "early_pump_radar_score",
    "early_pump_flow_score",
    "early_pump_whale_score",
    "early_pump_float_score",
    "early_pump_short_squeeze_score",
    "early_pump_timing_score",
    "early_pump_venue_score",
    "early_pump_archetype_score",
    "early_pump_not_late_score",
    "early_pump_confirmed_target_flow",
    "early_pump_whale_gate",
    "early_pump_short_gate",
    "early_pump_float_gate",
    "early_pump_venue_gate",
    "early_pump_not_late_gate",
    "early_pump_alert_flag",
    "early_pump_state",
    "early_pump_primary_signal",
    "early_pump_next_check",
    "early_pump_note",
]


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(str(value).replace(",", "").replace("%", "").strip())
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _num(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").fillna(default).astype("float64")


def _boolish(series: Any, *, index: pd.Index) -> pd.Series:
    if not isinstance(series, pd.Series):
        series = pd.Series(series if series is not None else False, index=index)
    return series.astype("object").where(pd.notna(series), False).astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y", "on"})


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype="object")
    return frame[column].fillna("").astype(str)


def _clip(series: pd.Series, lower: float = 0.0, upper: float = 100.0) -> pd.Series:
    return series.clip(lower=lower, upper=upper)


def _score_linear(series: pd.Series, low: float, high: float, *, invert: bool = False) -> pd.Series:
    if high <= low:
        scored = pd.Series(0.0, index=series.index, dtype="float64")
    else:
        scored = ((series - low) / (high - low) * 100.0).clip(lower=0.0, upper=100.0)
    return 100.0 - scored if invert else scored


def _max_num(frame: pd.DataFrame, *columns: str, default: float = 0.0) -> pd.Series:
    parts = [_num(frame, column, default=float("nan")) for column in columns if column in frame.columns]
    if not parts:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.concat(parts, axis=1).max(axis=1).fillna(default).astype("float64")


def _pct_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(float("nan"), index=frame.index, dtype="float64")
    values = frame[column].map(_safe_float).astype("float64")
    return values.mask((values != 0.0) & (values.abs() <= 1.0), values * 100.0)


def _first_float(row: Mapping[str, Any] | pd.Series, *columns: str) -> float | None:
    for column in columns:
        value = row.get(column) if hasattr(row, "get") else None
        parsed = _safe_float(value)
        if parsed is not None:
            return parsed
    return None


def _row_bool(row: Mapping[str, Any] | pd.Series, column: str) -> bool:
    value = row.get(column) if hasattr(row, "get") else False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    try:
        if value is None or pd.isna(value):
            return False
    except Exception:
        pass
    return bool(value)


def _clean_text(value: Any) -> str:
    try:
        if value is None or pd.isna(value):
            return ""
    except Exception:
        pass
    text = " ".join(str(value).split()).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def _target_cex_text(row: Mapping[str, Any] | pd.Series) -> str:
    text = _clean_text(row.get("cex_deposit_24h_target_exchanges") if hasattr(row, "get") else "")
    return text if TARGET_CEX_RE.search(text) else ""


def _primary_signal(row: Mapping[str, Any] | pd.Series) -> str:
    flow_score = _first_float(row, "early_pump_flow_score") or 0.0
    if _row_bool(row, "early_pump_confirmed_target_flow") and flow_score >= 35.0:
        return f"target CEX flow {flow_score:.0f}/100"
    flow_label = "exchange-flow stress" if _target_cex_text(row) else "flow stress"
    candidates = {
        flow_label: flow_score,
        "short-squeeze fuel": _first_float(row, "early_pump_short_squeeze_score") or 0.0,
        "whale/control plane": _first_float(row, "early_pump_whale_score") or 0.0,
        "low-float pressure": _first_float(row, "early_pump_float_score") or 0.0,
        "timing": _first_float(row, "early_pump_timing_score") or 0.0,
        "case-study analogue": _first_float(row, "early_pump_archetype_score") or 0.0,
        "venue support": _first_float(row, "early_pump_venue_score") or 0.0,
    }
    label, score = max(candidates.items(), key=lambda item: item[1])
    return f"{label} {score:.0f}/100" if score >= 35.0 else "evidence still thin"


def _state(row: Mapping[str, Any] | pd.Series) -> str:
    score = _first_float(row, "early_pump_radar_score") or 0.0
    timing_late = _first_float(row, "timing_too_late_score") or 0.0
    if not _row_bool(row, "early_pump_not_late_gate") or timing_late >= 72.0:
        return "Too late / fragile"
    if (
        score >= 75.0
        and _row_bool(row, "early_pump_confirmed_target_flow")
        and _row_bool(row, "early_pump_whale_gate")
        and _row_bool(row, "early_pump_short_gate")
    ):
        return "Prime early squeeze"
    if score >= 62.0 and _row_bool(row, "early_pump_confirmed_target_flow"):
        return "Flow-first watch"
    if (
        score >= 60.0
        and _row_bool(row, "early_pump_whale_gate")
        and _row_bool(row, "early_pump_short_gate")
        and _row_bool(row, "early_pump_float_gate")
    ):
        return "Squeeze watch"
    if (
        score >= 55.0
        and _row_bool(row, "early_pump_whale_gate")
        and _row_bool(row, "early_pump_float_gate")
        and (_first_float(row, "early_pump_timing_score") or 0.0) >= 50.0
    ):
        return "Sleeper watch"
    return "No edge"


def _next_check(row: Mapping[str, Any] | pd.Series) -> str:
    missing: list[str] = []
    if not _row_bool(row, "early_pump_confirmed_target_flow"):
        missing.append("fresh labelled Binance/Bitget/Gate transfer")
    if not _row_bool(row, "early_pump_whale_gate"):
        missing.append("whale/concentration gate")
    if not _row_bool(row, "early_pump_short_gate"):
        missing.append("short-account majority")
    if not _row_bool(row, "early_pump_float_gate"):
        missing.append("low-float/FDV evidence")
    if not _row_bool(row, "early_pump_venue_gate"):
        missing.append("target venue support")
    if not _row_bool(row, "early_pump_not_late_gate"):
        return "skip unless heat resets; wait for wick/late-risk compression before re-rating"
    if missing:
        return "verify " + ", ".join(missing[:4])
    if (_first_float(row, "cex_deposit_inventory_stress_score") or 0.0) >= 55.0:
        return "check whether deposited inventory is absorbed while OI/volume expand and rejection wicks stay muted"
    return "watch for OI expansion, constructive close location, volume lift, and no chase-extension wick"


def _note(row: Mapping[str, Any] | pd.Series, *, min_transfer_tokens: float = 0.0) -> str:
    score = _first_float(row, "early_pump_radar_score") or 0.0
    target_text = _target_cex_text(row)
    targets = target_text if _row_bool(row, "early_pump_confirmed_target_flow") else "no confirmed target CEX"
    max_amount = _first_float(row, "cex_deposit_24h_max_amount")
    if (
        target_text
        and not _row_bool(row, "early_pump_confirmed_target_flow")
        and min_transfer_tokens > 0.0
        and max_amount is not None
        and max_amount < min_transfer_tokens
    ):
        targets = f"{target_text} below transfer floor"
    parts = [
        f"radar {score:.0f}/100",
        _clean_text(row.get("early_pump_state") if hasattr(row, "get") else ""),
        _clean_text(row.get("early_pump_primary_signal") if hasattr(row, "get") else ""),
        targets,
    ]
    archetype = _clean_text(row.get("archetype_best_match") if hasattr(row, "get") else "")
    if archetype and archetype != "No strong case-study analogue":
        parts.append(archetype)
    return " | ".join(part for part in parts if part)


def apply_early_pump_radar(frame: pd.DataFrame, *, min_transfer_tokens: float = 0.0) -> pd.DataFrame:
    if frame.empty:
        output = frame.copy()
        for column in EARLY_PUMP_RADAR_COLUMNS:
            output[column] = pd.NA
        return output

    output = frame.loc[:, ~frame.columns.duplicated()].copy()
    transfer_floor = max(0.0, _safe_float(min_transfer_tokens) or 0.0)
    targets = _text(output, "cex_deposit_24h_target_exchanges")
    target_flow = (
        (_boolish(output.get("cex_deposit_flow_flag"), index=output.index) | _num(output, "cex_deposit_flow_score").gt(0.0))
        & _num(output, "cex_deposit_24h_count").gt(0.0)
        & _num(output, "cex_deposit_24h_max_amount").ge(transfer_floor)
        & targets.str.contains(TARGET_CEX_RE, regex=True)
    )

    top10 = _pct_series(output, "top10_holder_pct").fillna(0.0)
    top100 = _pct_series(output, "top100_holder_pct").fillna(0.0)
    short_pct = _pct_series(output, "short_account_pct").fillna(_num(output, "short_account_pct"))

    flow_strength = _max_num(
        output,
        "cex_deposit_flow_score",
        "cex_deposit_inventory_stress_score",
        "terminal_exchange_flow_score",
        "target_cex_flow_score",
    )
    flow_score = _clip(flow_strength.where(target_flow, flow_strength * 0.58))
    whale_score = _clip(
        pd.concat(
            [
                _score_linear(top10, 55.0, 92.0),
                _score_linear(top100, 82.0, 99.5),
                _num(output, "terminal_control_plane_score"),
                _num(output, "centralized_ownership_score"),
                _score_linear(_num(output, "cluster_manipulable_supply_pct"), 8.0, 45.0),
            ],
            axis=1,
        ).max(axis=1)
    )
    float_score = _clip(
        pd.concat(
            [
                _num(output, "low_float_score"),
                _num(output, "float_trap_score"),
                _num(output, "terminal_float_score"),
                _num(output, "terminal_hidden_float_reflexivity_score"),
                _score_linear(_num(output, "fdv_to_market_cap"), 1.8, 12.0),
                _score_linear(_num(output, "locked_supply_pct"), 15.0, 85.0),
            ],
            axis=1,
        ).max(axis=1)
    )
    squeeze_score = _clip(
        pd.concat(
            [
                _score_linear(short_pct, 50.0, 72.0),
                _num(output, "terminal_short_pressure_score"),
                _num(output, "short_dominance_score"),
                _num(output, "short_account_build_score"),
                _num(output, "short_liquidation_fuel_score"),
                _num(output, "short_squeeze_score"),
                _score_linear(_num(output, "oi_delta_pct"), 0.5, 7.5),
            ],
            axis=1,
        ).max(axis=1)
    )
    timing_score = _clip(
        pd.concat(
            [
                _num(output, "timing_score"),
                _num(output, "timing_trigger_score"),
                _num(output, "timing_inventory_response_score"),
                _num(output, "terminal_pre_ignition_quality_score"),
                _num(output, "pre_pump_precision_score"),
                _num(output, "dormant_short_fuse_score"),
                _num(output, "accumulation_absorption_score"),
            ],
            axis=1,
        ).max(axis=1)
    )
    venue_score = _clip(
        pd.concat(
            [
                _num(output, "venue_support_score"),
                _num(output, "binance_bitget_gate_share_score"),
                _num(output, "target_cex_flow_score"),
                _num(output, "cex_lane_wakeup_score"),
                _score_linear(_num(output, "binance_bitget_gate_share_pct"), 8.0, 55.0),
                _score_linear(_num(output, "binance_volume_share_pct"), 5.0, 55.0),
                _score_linear(_num(output, "bitget_volume_share_pct"), 0.1, 12.0),
                _score_linear(_num(output, "gate_volume_share_pct"), 0.1, 12.0),
                target_flow.astype(float) * 100.0,
            ],
            axis=1,
        ).max(axis=1)
    )
    archetype_score = _clip(
        pd.concat(
            [
                _num(output, "archetype_match_score"),
                _num(output, "archetype_lab_score"),
                _num(output, "archetype_siren_score"),
                _num(output, "archetype_rave_score"),
                _num(output, "archetype_river_score"),
                _num(output, "archetype_sto_score"),
            ],
            axis=1,
        ).max(axis=1)
    )

    heat = pd.concat(
        [
            _num(output, "timing_too_late_score"),
            _num(output, "convexity_late_penalty"),
            _num(output, "no_chase_penalty_score"),
            _num(output, "terminal_risk_score"),
            _num(output, "exit_fragility_score") * 0.8,
            _score_linear(_num(output, "day_return_pct").abs(), 28.0, 120.0),
            _score_linear(_num(output, "hour_return_pct").abs(), 8.0, 30.0),
            _score_linear(_num(output, "hour_upper_wick_pct"), 20.0, 55.0),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    not_late = _clip(100.0 - heat)

    whale_gate = pd.concat([top10, top100], axis=1).max(axis=1).fillna(0.0).ge(90.0)
    short_gate = short_pct.ge(50.0) | squeeze_score.ge(55.0)
    float_gate = float_score.ge(55.0)
    venue_gate = venue_score.ge(45.0) | target_flow
    not_late_gate = not_late.ge(45.0)

    balanced = (
        flow_score * 0.18
        + whale_score * 0.16
        + float_score * 0.14
        + squeeze_score * 0.17
        + timing_score * 0.16
        + venue_score * 0.08
        + archetype_score * 0.07
        + not_late * 0.10
    )
    flow_led = flow_score * 0.32 + whale_score * 0.20 + squeeze_score * 0.14 + timing_score * 0.12 + venue_score * 0.12 + not_late * 0.10
    squeeze_led = squeeze_score * 0.28 + whale_score * 0.17 + float_score * 0.16 + timing_score * 0.15 + venue_score * 0.10 + archetype_score * 0.08 + not_late * 0.06
    sleeper = timing_score * 0.24 + whale_score * 0.19 + float_score * 0.18 + squeeze_score * 0.12 + venue_score * 0.10 + archetype_score * 0.08 + not_late * 0.09
    radar_score = pd.concat([balanced, flow_led, squeeze_led, sleeper], axis=1).max(axis=1)
    radar_score = _clip(
        radar_score
        + target_flow.astype(float) * 4.0
        + whale_gate.astype(float) * 3.0
        + short_gate.astype(float) * 3.0
        + venue_gate.astype(float) * 2.0
        - (~not_late_gate).astype(float) * 20.0
    )

    output["early_pump_radar_score"] = radar_score
    output["early_pump_flow_score"] = flow_score
    output["early_pump_whale_score"] = whale_score
    output["early_pump_float_score"] = float_score
    output["early_pump_short_squeeze_score"] = squeeze_score
    output["early_pump_timing_score"] = timing_score
    output["early_pump_venue_score"] = venue_score
    output["early_pump_archetype_score"] = archetype_score
    output["early_pump_not_late_score"] = not_late
    output["early_pump_confirmed_target_flow"] = target_flow
    output["early_pump_whale_gate"] = whale_gate
    output["early_pump_short_gate"] = short_gate
    output["early_pump_float_gate"] = float_gate
    output["early_pump_venue_gate"] = venue_gate
    output["early_pump_not_late_gate"] = not_late_gate
    output["early_pump_alert_flag"] = radar_score.ge(65.0) & venue_gate & not_late_gate & (target_flow | (whale_gate & short_gate & float_gate))
    output["early_pump_state"] = output.apply(_state, axis=1)
    output["early_pump_primary_signal"] = output.apply(_primary_signal, axis=1)
    output["early_pump_next_check"] = output.apply(_next_check, axis=1)
    output["early_pump_note"] = output.apply(lambda row: _note(row, min_transfer_tokens=transfer_floor), axis=1)
    return output
