from __future__ import annotations

import math
import re
from typing import Any, Mapping

import pandas as pd

from venue_gate import binance_bitget_venue_mask, holder_concentration_mask, holder_evidence_mask


TARGET_CEX_RE = re.compile(r"\b(?:binance|bitget|gate(?:\.io|io)?)\b", flags=re.IGNORECASE)

PRE_ACTIVITY_RADAR_COLUMNS = [
    "pre_activity_pump_score",
    "pre_activity_control_score",
    "pre_activity_float_score",
    "pre_activity_behavior_score",
    "pre_activity_short_fuse_score",
    "pre_activity_quiet_score",
    "pre_activity_venue_score",
    "pre_activity_thin_book_score",
    "pre_activity_preignition_score",
    "pre_activity_heat_score",
    "pre_activity_confirmed_target_flow",
    "pre_activity_holder_evidence_gate",
    "pre_activity_whale_gate",
    "pre_activity_binance_bitget_gate",
    "pre_activity_structure_gate",
    "pre_activity_behavior_gate",
    "pre_activity_quiet_gate",
    "pre_activity_alert_flag",
    "pre_activity_state",
    "pre_activity_primary_signal",
    "pre_activity_next_check",
    "pre_activity_note",
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


def _raw_num(frame: pd.DataFrame, column: str, default: float = float("nan")) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _pct_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(float("nan"), index=frame.index, dtype="float64")
    values = frame[column].map(_safe_float).astype("float64")
    return values.mask((values != 0.0) & (values.abs() <= 1.0), values * 100.0)


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


def _score_log(series: pd.Series, low: float, high: float, *, invert: bool = False) -> pd.Series:
    if high <= low:
        return pd.Series(0.0, index=series.index, dtype="float64")
    numeric = pd.to_numeric(series, errors="coerce").where(lambda values: values > 0)
    low_log = math.log10(max(low, 1e-12))
    high_log = math.log10(max(high, low + 1e-12))
    scored = ((numeric.map(math.log10) - low_log) / (high_log - low_log) * 100.0).clip(lower=0.0, upper=100.0)
    if invert:
        scored = 100.0 - scored
    return scored.fillna(0.0).clip(lower=0.0, upper=100.0)


def _max_num(frame: pd.DataFrame, *columns: str, default: float = 0.0) -> pd.Series:
    parts = [_num(frame, column, default=float("nan")) for column in columns if column in frame.columns]
    if not parts:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.concat(parts, axis=1).max(axis=1).fillna(default).astype("float64")


def _row_float(row: Mapping[str, Any] | pd.Series, *columns: str) -> float | None:
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
    behavior = _row_float(row, "pre_activity_behavior_score") or 0.0
    if _row_bool(row, "pre_activity_confirmed_target_flow") and behavior >= 35.0:
        return f"target CEX flow {behavior:.0f}/100"
    candidates = {
        "holder control": _row_float(row, "pre_activity_control_score") or 0.0,
        "low-float/FDV gap": _row_float(row, "pre_activity_float_score") or 0.0,
        "behavioural CEX/venue tell": behavior,
        "short-fuse perp positioning": _row_float(row, "pre_activity_short_fuse_score") or 0.0,
        "quiet tape": _row_float(row, "pre_activity_quiet_score") or 0.0,
        "thin visible book": _row_float(row, "pre_activity_thin_book_score") or 0.0,
    }
    label, score = max(candidates.items(), key=lambda item: item[1])
    return f"{label} {score:.0f}/100" if score >= 35.0 else "evidence still thin"


def _state(row: Mapping[str, Any] | pd.Series) -> str:
    score = _row_float(row, "pre_activity_pump_score") or 0.0
    heat = _row_float(row, "pre_activity_heat_score") or 0.0
    quiet = _row_bool(row, "pre_activity_quiet_gate")
    behavior = _row_bool(row, "pre_activity_behavior_gate")
    structure = _row_bool(row, "pre_activity_structure_gate")
    flow = _row_bool(row, "pre_activity_confirmed_target_flow")
    venue = _row_bool(row, "pre_activity_binance_bitget_gate")
    if heat >= 70.0 or not quiet:
        return "Already active / chase risk"
    if score >= 76.0 and flow and structure and venue:
        return "Stealth inventory setup"
    if score >= 68.0 and behavior and structure and venue:
        return "Silent squeeze fuse"
    if score >= 60.0 and structure:
        return "Control-plane watch"
    return "No latent edge"


def _next_check(row: Mapping[str, Any] | pd.Series) -> str:
    if not _row_bool(row, "pre_activity_quiet_gate"):
        return "wait for heat to reset; the setup is no longer pre-activity"
    missing: list[str] = []
    if not _row_bool(row, "pre_activity_whale_gate"):
        missing.append("top10 whale-control evidence")
    if not _row_bool(row, "pre_activity_binance_bitget_gate"):
        missing.append("Binance+Bitget trading evidence")
    if not _row_bool(row, "pre_activity_structure_gate"):
        missing.append("low-float/FDV structure")
    if not _row_bool(row, "pre_activity_behavior_gate"):
        missing.append("target CEX flow or venue-inventory tell")
    if not _row_bool(row, "pre_activity_confirmed_target_flow"):
        missing.append("fresh labelled Binance/Bitget/Gate transfer")
    if missing:
        return "verify " + ", ".join(missing[:3]) + " before treating this as live"
    return "watch for absorption, OI expansion, and first volume lift while price remains below chase heat"


def _note(row: Mapping[str, Any] | pd.Series, *, min_transfer_tokens: float = 0.0) -> str:
    score = _row_float(row, "pre_activity_pump_score") or 0.0
    quiet = _row_float(row, "pre_activity_quiet_score") or 0.0
    heat = _row_float(row, "pre_activity_heat_score") or 0.0
    target_text = _target_cex_text(row)
    target_note = target_text if _row_bool(row, "pre_activity_confirmed_target_flow") else "no confirmed target CEX"
    max_amount = _row_float(row, "cex_deposit_24h_max_amount")
    if (
        target_text
        and not _row_bool(row, "pre_activity_confirmed_target_flow")
        and min_transfer_tokens > 0.0
        and max_amount is not None
        and max_amount < min_transfer_tokens
    ):
        target_note = f"{target_text} below transfer floor"
    parts = [
        f"latent {score:.0f}/100",
        _clean_text(row.get("pre_activity_state") if hasattr(row, "get") else ""),
        _clean_text(row.get("pre_activity_primary_signal") if hasattr(row, "get") else ""),
        f"quiet {quiet:.0f}/100",
        f"heat {heat:.0f}/100",
        target_note,
    ]
    return " | ".join(part for part in parts if part)


def apply_pre_activity_radar(frame: pd.DataFrame, *, min_transfer_tokens: float = 0.0) -> pd.DataFrame:
    """Score latent abnormal-market-structure setups before obvious activity.

    The model is intentionally different from an ignition score: it rewards
    controlled float, insider/holder concentration proxies, target-CEX inventory
    tells, short-fuse perp positioning, and thin visible liquidity, while
    penalizing rows that already have breakout/volume/return heat.
    """
    if frame.empty:
        output = frame.copy()
        for column in PRE_ACTIVITY_RADAR_COLUMNS:
            output[column] = pd.NA
        return output

    output = frame.loc[:, ~frame.columns.duplicated()].copy()
    index = output.index
    transfer_floor = max(0.0, _safe_float(min_transfer_tokens) or 0.0)

    top10 = _pct_series(output, "top10_holder_pct").fillna(0.0)
    top100 = _pct_series(output, "top100_holder_pct").fillna(0.0)
    owner_team = (_pct_series(output, "owner_holder_pct").fillna(0.0) + _pct_series(output, "creator_holder_pct").fillna(0.0)).clip(
        lower=0.0,
        upper=100.0,
    )
    holder_count = _raw_num(output, "holder_count")
    fdv_to_mcap = _raw_num(output, "fdv_to_market_cap")
    circulating = _raw_num(output, "circulating_supply_pct")
    short_pct = _pct_series(output, "short_account_pct").fillna(_num(output, "short_account_pct"))

    control_score = _clip(
        pd.concat(
            [
                _score_linear(top10, 45.0, 92.0),
                _score_linear(top100, 78.0, 99.5),
                _score_linear(owner_team, 4.0, 35.0),
                _score_log(holder_count, 4_000.0, 120_000.0, invert=True),
                _num(output, "holder_concentration_score"),
                _num(output, "centralized_ownership_score"),
                _num(output, "crime_owner_circle_score"),
                _num(output, "terminal_control_plane_score"),
                _num(output, "crime_supply_control_score"),
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
                _score_log(fdv_to_mcap, 1.6, 18.0),
                _score_linear(_num(output, "locked_supply_pct"), 15.0, 88.0),
                _score_linear(circulating, 4.0, 38.0, invert=True),
            ],
            axis=1,
        ).max(axis=1)
    )

    targets = _text(output, "cex_deposit_24h_target_exchanges")
    target_flow = (
        (_boolish(output.get("cex_deposit_flow_flag"), index=index) | _num(output, "cex_deposit_flow_score").gt(0.0))
        & _num(output, "cex_deposit_24h_count").gt(0.0)
        & _num(output, "cex_deposit_24h_max_amount").ge(transfer_floor)
        & targets.str.contains(TARGET_CEX_RE, regex=True)
    )
    raw_behavior_score = _clip(
        pd.concat(
            [
                _num(output, "cex_deposit_flow_score"),
                _num(output, "cex_deposit_inventory_stress_score"),
                _num(output, "terminal_exchange_flow_score"),
                _num(output, "target_cex_flow_score"),
                _num(output, "inventory_transfer_risk_score"),
                _num(output, "inventory_sponsor_mismatch_score"),
                _score_log(_num(output, "cex_deposit_24h_max_amount"), 10_000.0, 10_000_000.0),
                _score_log(_num(output, "cex_deposit_24h_token_amount"), 20_000.0, 25_000_000.0),
            ],
            axis=1,
        ).max(axis=1)
    )
    behavior_score = _clip(raw_behavior_score.where(target_flow, raw_behavior_score * 0.68))

    short_fuse_score = _clip(
        pd.concat(
            [
                _score_linear(short_pct, 49.0, 72.0),
                _num(output, "short_dominance_score"),
                _num(output, "short_account_build_score"),
                _num(output, "terminal_short_pressure_score"),
                _num(output, "early_pump_short_squeeze_score"),
                _score_linear(_num(output, "short_account_change_max_pp"), 0.25, 5.0),
                _score_linear(_num(output, "oi_to_24h_volume_pct"), 2.0, 22.0),
                _score_linear(_num(output, "oi_to_market_cap_pct"), 2.0, 35.0),
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
                _score_linear(_num(output, "binance_bitget_gate_share_pct"), 6.0, 55.0),
                _score_linear(_num(output, "binance_volume_share_pct"), 4.0, 50.0),
                _score_linear(_num(output, "bitget_volume_share_pct"), 0.1, 12.0),
                _score_linear(_num(output, "gate_volume_share_pct"), 0.1, 12.0),
                target_flow.astype(float) * 100.0,
            ],
            axis=1,
        ).max(axis=1)
    )
    thin_book_score = _clip(
        pd.concat(
            [
                _score_log(_raw_num(output, "ask_depth_1pct_usdt"), 20_000.0, 2_500_000.0, invert=True),
                _score_linear(_raw_num(output, "ask_depth_to_24h_volume_pct"), 0.02, 0.85, invert=True),
                _score_linear(_raw_num(output, "coinbase_depth_to_perp_volume_pct"), 0.02, 0.75, invert=True),
                _num(output, "crime_microstructure_score"),
                _num(output, "terminal_liquidity_score"),
            ],
            axis=1,
        ).max(axis=1)
    )
    preignition_score = _clip(
        pd.concat(
            [
                _num(output, "pre_pump_precision_score"),
                _num(output, "dormant_short_fuse_score"),
                _num(output, "pre_pump_compression_score"),
                _num(output, "silent_oi_accumulation_score"),
                _num(output, "terminal_pre_ignition_quality_score"),
                _num(output, "timing_inventory_response_score"),
                _num(output, "early_pump_timing_score"),
            ],
            axis=1,
        ).max(axis=1)
    )

    high_breaks = (
        _boolish(output.get("broke_high_5d"), index=index).astype(float)
        + _boolish(output.get("broke_high_20d"), index=index).astype(float)
        + _boolish(output.get("broke_high_90d"), index=index).astype(float)
        + _boolish(output.get("broke_high_180d"), index=index).astype(float)
    ).clip(upper=1.0) * 100.0
    activity_heat = _clip(
        pd.concat(
            [
                _score_linear(_raw_num(output, "day_return_pct").abs(), 7.0, 35.0),
                _score_linear(_raw_num(output, "price_change_24h_pct").abs(), 7.0, 35.0),
                _score_linear(_raw_num(output, "hour_return_pct").abs(), 2.0, 12.0),
                _score_linear(_raw_num(output, "range_24h_pct"), 8.0, 35.0),
                _score_log(_raw_num(output, "daily_quote_volume_multiple"), 1.4, 8.0),
                _score_log(_raw_num(output, "hour_volume_multiple"), 1.4, 8.0),
                _score_log(_raw_num(output, "hour_trade_count_multiple"), 1.4, 8.0),
                _num(output, "cmc_mover_score") * 0.85,
                _num(output, "timing_too_late_score"),
                _num(output, "convexity_late_penalty"),
                _num(output, "crime_exhaustion_score") * 0.75,
                high_breaks,
            ],
            axis=1,
        ).max(axis=1).fillna(0.0)
    )
    quiet_score = _clip(
        (100.0 - activity_heat) * 0.68
        + preignition_score * 0.20
        + _num(output, "low_volatility_coil_score") * 0.12
    )

    major_excluded = _boolish(output.get("crime_excluded_major"), index=index)
    holder_evidence_gate = holder_evidence_mask(output)
    whale_gate = holder_concentration_mask(output, min_whale_pct=90.0, require_holder_evidence=True)
    venue_pair_gate = binance_bitget_venue_mask(output, allow_cex_flow_targets=False)
    structure_gate = whale_gate & ((float_score >= 45.0) | (thin_book_score >= 55.0))
    behavior_gate = target_flow | behavior_score.ge(58.0) | ((venue_score >= 55.0) & (short_fuse_score >= 52.0))
    quiet_gate = quiet_score.ge(50.0) & activity_heat.lt(62.0)

    raw_score = (
        control_score * 0.18
        + float_score * 0.16
        + behavior_score * 0.18
        + short_fuse_score * 0.13
        + quiet_score * 0.15
        + venue_score * 0.08
        + thin_book_score * 0.07
        + preignition_score * 0.05
        + target_flow.astype(float) * 4.0
        + structure_gate.astype(float) * 3.0
        + behavior_gate.astype(float) * 2.0
        - (activity_heat - 55.0).clip(lower=0.0) * 0.32
    )
    score = raw_score.where(~major_excluded, other=0.0).clip(lower=0.0, upper=100.0)

    output["pre_activity_pump_score"] = score
    output["pre_activity_control_score"] = control_score
    output["pre_activity_float_score"] = float_score
    output["pre_activity_behavior_score"] = behavior_score
    output["pre_activity_short_fuse_score"] = short_fuse_score
    output["pre_activity_quiet_score"] = quiet_score
    output["pre_activity_venue_score"] = venue_score
    output["pre_activity_thin_book_score"] = thin_book_score
    output["pre_activity_preignition_score"] = preignition_score
    output["pre_activity_heat_score"] = activity_heat
    output["pre_activity_confirmed_target_flow"] = target_flow
    output["pre_activity_holder_evidence_gate"] = holder_evidence_gate
    output["pre_activity_whale_gate"] = whale_gate
    output["pre_activity_binance_bitget_gate"] = venue_pair_gate
    output["pre_activity_structure_gate"] = structure_gate & (~major_excluded)
    output["pre_activity_behavior_gate"] = behavior_gate & (~major_excluded)
    output["pre_activity_quiet_gate"] = quiet_gate & (~major_excluded)
    output["pre_activity_alert_flag"] = (
        score.ge(62.0)
        & structure_gate
        & behavior_gate
        & quiet_gate
        & venue_pair_gate
        & short_fuse_score.ge(50.0)
        & (~major_excluded)
    )
    output["pre_activity_state"] = output.apply(_state, axis=1)
    output["pre_activity_primary_signal"] = output.apply(_primary_signal, axis=1)
    output["pre_activity_next_check"] = output.apply(_next_check, axis=1)
    output["pre_activity_note"] = output.apply(lambda row: _note(row, min_transfer_tokens=transfer_floor), axis=1)
    return output
