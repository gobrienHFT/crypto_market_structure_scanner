from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pandas as pd


TERMINAL_SCORE_COLUMNS = [
    "terminal_edge_score",
    "terminal_regime_score",
    "terminal_liquidity_score",
    "terminal_float_score",
    "terminal_short_pressure_score",
    "terminal_ignition_score",
    "terminal_runway_score",
    "terminal_risk_score",
    "terminal_market_regime",
    "terminal_liquidity_reality",
    "terminal_setup_archetype",
    "terminal_evidence_summary",
    "terminal_confirmation_needed",
    "terminal_invalidation_map",
    "terminal_case_study_key",
]


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _num(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").fillna(default).astype("float64")


def _bool(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame[column].fillna(False).astype(bool)


def _clip(series: pd.Series, lower: float = 0.0, upper: float = 100.0) -> pd.Series:
    return series.clip(lower=lower, upper=upper)


def _pct_value(value: Any) -> float | None:
    parsed = _safe_float(value)
    if parsed is None:
        return None
    if parsed != 0.0 and abs(parsed) <= 1.0:
        return parsed * 100.0
    return parsed


def _fmt_pct(value: Any) -> str:
    parsed = _pct_value(value)
    return "n/a" if parsed is None else f"{parsed:.1f}%"


def _fmt_num(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "n/a"
    if abs(parsed) >= 1_000_000_000:
        return f"{parsed / 1_000_000_000:.2f}B"
    if abs(parsed) >= 1_000_000:
        return f"{parsed / 1_000_000:.2f}M"
    if abs(parsed) >= 1_000:
        return f"{parsed / 1_000:.2f}K"
    return f"{parsed:.2f}"


def _first_text(row: Mapping[str, Any] | pd.Series, *keys: str) -> str:
    for key in keys:
        value = row.get(key) if hasattr(row, "get") else None
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except Exception:
            pass
        text = str(value).strip()
        if text and text.lower() not in {"nan", "none", "null"}:
            return text
    return ""


def _first_float(row: Mapping[str, Any] | pd.Series, *keys: str) -> float | None:
    for key in keys:
        value = row.get(key) if hasattr(row, "get") else None
        parsed = _safe_float(value)
        if parsed is not None:
            return parsed
    return None


def _row_bool(row: Mapping[str, Any] | pd.Series, key: str) -> bool:
    value = row.get(key) if hasattr(row, "get") else None
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value) if not pd.isna(value) else False


def infer_market_regime(row: Mapping[str, Any] | pd.Series) -> str:
    btc_1h = _first_float(row, "btc_return_1h_pct", "btc_1h_pct", "btc_hour_return_pct")
    btc_24h = _first_float(row, "btc_return_24h_pct", "btc_24h_pct", "btc_day_return_pct")
    corr = _first_float(row, "corr_to_btc_6m")
    if btc_1h is None and btc_24h is None:
        if corr is not None and corr < 0.25:
            return "idiosyncratic tape"
        return "regime data pending"
    if (btc_1h or 0.0) <= -1.5 and (btc_24h or 0.0) <= -3.0:
        return "hostile beta tape"
    if (btc_1h or 0.0) >= 1.0 and (btc_24h or 0.0) >= 2.0:
        return "risk-on beta tape"
    if abs(btc_1h or 0.0) < 0.75 and abs(btc_24h or 0.0) < 2.0:
        return "calm beta tape"
    return "mixed beta tape"


def infer_liquidity_reality(row: Mapping[str, Any] | pd.Series) -> str:
    ask_depth = _first_float(row, "ask_depth_1pct_usdt")
    ask_depth_to_vol = _first_float(row, "ask_depth_to_24h_volume_pct")
    spread = _first_float(row, "coinbase_bid_ask_spread_pct")
    quote_volume = _first_float(row, "quote_volume_24h")
    top100 = _first_float(row, "top100_holder_pct")
    if top100 is not None and top100 >= 95:
        return "cap-table supply; exits can gap"
    if ask_depth is not None and ask_depth < 75_000:
        return "thin visible ask depth"
    if ask_depth_to_vol is not None and ask_depth_to_vol < 0.05:
        return "book depth tiny versus turnover"
    if spread is not None and spread > 1.0:
        return "wide visible spread"
    if quote_volume is not None and quote_volume >= 50_000_000:
        return "high turnover; still verify exit depth"
    return "liquidity check required"


def infer_setup_archetype(row: Mapping[str, Any] | pd.Series) -> str:
    if _row_bool(row, "pre_pump_precision_flag"):
        return "pre-ignition compression"
    if _row_bool(row, "dormant_short_fuse_flag"):
        return "low-vol short-fuse"
    if _row_bool(row, "rave_lab_extreme_flag"):
        return "controlled-float reflexivity"
    if _row_bool(row, "forced_buying_setup_flag"):
        return "forced-flow pressure"
    if _row_bool(row, "clean_convex_setup_flag"):
        return "clean market-structure candidate"
    if _row_bool(row, "convexity_chase_risk_flag") or _row_bool(row, "convexity_too_late_flag"):
        return "late-stage heat"
    return "watchlist structure"


def terminal_evidence_summary(row: Mapping[str, Any] | pd.Series) -> str:
    parts: list[str] = []
    score = _first_float(row, "terminal_edge_score", "trade_bucket_score", "convexity_entry_score")
    if score is not None:
        parts.append(f"terminal {score:.0f}/100")
    short_pct = _pct_value(_first_float(row, "short_account_pct"))
    if short_pct is not None:
        parts.append(f"short accounts {_fmt_pct(short_pct)}")
    oi = _first_float(row, "oi_delta_pct", "oi_value_change_since_scan_pct")
    if oi is not None:
        parts.append(f"OI change {_fmt_pct(oi)}")
    vol_x = _first_float(row, "daily_quote_volume_multiple", "hour_volume_multiple")
    if vol_x is not None and vol_x > 0:
        parts.append(f"volume {vol_x:.2f}x")
    top10 = _first_float(row, "top10_holder_pct")
    if top10 is not None:
        parts.append(f"top10 holders {_fmt_pct(top10)}")
    ath = _first_float(row, "ath_multiple")
    if ath is not None:
        parts.append(f"{ath:.1f}x ATH runway")
    if not parts:
        parts.append("market-structure evidence pending")
    return " | ".join(parts[:7])


def terminal_confirmation_needed(row: Mapping[str, Any] | pd.Series) -> str:
    needs: list[str] = []
    oi = _first_float(row, "oi_delta_pct", "oi_value_change_since_scan_pct")
    vol_x = _first_float(row, "daily_quote_volume_multiple", "hour_volume_multiple")
    close_loc = _first_float(row, "hour_close_location_pct")
    short_pct = _pct_value(_first_float(row, "short_account_pct"))
    if oi is None or oi < 1.0:
        needs.append("OI expansion")
    if vol_x is None or vol_x < 1.3:
        needs.append("volume confirmation")
    if close_loc is None or close_loc < 65.0:
        needs.append("strong close quality")
    if short_pct is None or short_pct < 50.0:
        needs.append("short crowd confirmation")
    return ", ".join(needs[:4]) if needs else "structure already has OI, volume, close-quality, and positioning confirmation"


def terminal_invalidation_map(row: Mapping[str, Any] | pd.Series) -> str:
    archetype = infer_setup_archetype(row)
    if archetype == "late-stage heat":
        return "OI flush, upper-wick continuation, and volume decay"
    if "short" in archetype or (_pct_value(_first_float(row, "short_account_pct")) or 0.0) >= 50.0:
        return "short pressure unwinds, OI contracts, reclaim fails, and volume fades"
    return "OI contracts, liquidity thins further, price fails reclaim, and volume fades"


def apply_terminal_model(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        output = frame.copy()
        for column in TERMINAL_SCORE_COLUMNS:
            if column not in output.columns:
                output[column] = pd.NA
        return output

    output = frame.copy()
    float_score = _clip(
        _num(output, "centralized_ownership_score") * 0.32
        + _num(output, "low_float_score") * 0.28
        + _num(output, "float_trap_score") * 0.20
        + _num(output, "valuation_trap_score") * 0.12
        + _num(output, "rave_lab_setup_score") * 0.08
    )
    short_score = _clip(
        _num(output, "short_dominance_score") * 0.32
        + _num(output, "short_account_build_score") * 0.25
        + _num(output, "short_liquidation_fuel_score") * 0.20
        + _num(output, "short_crowding_score") * 0.13
        + _num(output, "forced_buying_setup_score") * 0.10
    )
    ignition_score = _clip(
        _num(output, "price_volume_ignition_score") * 0.28
        + _num(output, "convexity_preignition_score") * 0.22
        + _num(output, "trend_confluence_score") * 0.18
        + _num(output, "spot_flow_confluence_score") * 0.16
        + _num(output, "perp_squeeze_confluence_score") * 0.16
    )
    liquidity_score = _clip(
        100.0
        - _num(output, "exit_fragility_score") * 0.28
        - _num(output, "no_chase_penalty_score") * 0.22
        - _num(output, "mm_withdrawal_risk_score") * 0.18
        - _num(output, "ask_depth_withdrawal_score") * 0.16
        + _num(output, "target_cex_flow_score") * 0.16
    )
    runway_score = _clip(
        _num(output, "convexity_runway_score") * 0.34
        + _num(output, "ath_runway_confluence_score") * 0.26
        + _num(output, "rave_lab_convex_fuel_score") * 0.20
        + _num(output, "clean_convex_setup_score") * 0.20
    )
    late_risk = _clip(
        _num(output, "convexity_late_penalty") * 0.35
        + _num(output, "rave_lab_late_penalty_score") * 0.25
        + _num(output, "exit_fragility_score") * 0.25
        + _num(output, "no_chase_penalty_score") * 0.15
    )
    regime_score = _clip(
        50.0
        + _num(output, "convexity_confluence_score") * 0.15
        + _num(output, "silent_oi_accumulation_score") * 0.12
        - _num(output, "crime_largecap_penalty_score") * 0.16
    )
    edge = _clip(
        float_score * 0.22
        + short_score * 0.20
        + ignition_score * 0.18
        + runway_score * 0.16
        + regime_score * 0.10
        + liquidity_score * 0.09
        - late_risk * 0.10
        + _bool(output, "pre_pump_precision_flag").astype(float) * 12.0
        + _bool(output, "dormant_short_fuse_flag").astype(float) * 8.0
        + _bool(output, "convexity_prime_flag").astype(float) * 6.0
    )

    output["terminal_float_score"] = float_score
    output["terminal_short_pressure_score"] = short_score
    output["terminal_ignition_score"] = ignition_score
    output["terminal_liquidity_score"] = liquidity_score
    output["terminal_runway_score"] = runway_score
    output["terminal_risk_score"] = late_risk
    output["terminal_regime_score"] = regime_score
    output["terminal_edge_score"] = edge
    output["terminal_market_regime"] = output.apply(infer_market_regime, axis=1)
    output["terminal_liquidity_reality"] = output.apply(infer_liquidity_reality, axis=1)
    output["terminal_setup_archetype"] = output.apply(infer_setup_archetype, axis=1)
    output["terminal_evidence_summary"] = output.apply(terminal_evidence_summary, axis=1)
    output["terminal_confirmation_needed"] = output.apply(terminal_confirmation_needed, axis=1)
    output["terminal_invalidation_map"] = output.apply(terminal_invalidation_map, axis=1)
    output["terminal_case_study_key"] = output.apply(
        lambda row: f"{str(row.get('symbol', '')).upper()}_{pd.Timestamp.utcnow().strftime('%Y-%m-%d')}",
        axis=1,
    )
    return output


def build_setup_dossier(row: Mapping[str, Any] | pd.Series) -> str:
    symbol = str(row.get("symbol", "UNKNOWN")).upper() if hasattr(row, "get") else "UNKNOWN"
    lines = [
        f"# {symbol} Market-Structure Dossier",
        "",
        "Research tooling only. This is not trade instruction.",
        "",
        f"- Terminal score: {_fmt_num(_first_float(row, 'terminal_edge_score'))}/100",
        f"- Archetype: {_first_text(row, 'terminal_setup_archetype') or infer_setup_archetype(row)}",
        f"- Regime: {_first_text(row, 'terminal_market_regime') or infer_market_regime(row)}",
        f"- Liquidity reality: {_first_text(row, 'terminal_liquidity_reality') or infer_liquidity_reality(row)}",
        f"- Evidence: {_first_text(row, 'terminal_evidence_summary') or terminal_evidence_summary(row)}",
        f"- Confirmation needed: {_first_text(row, 'terminal_confirmation_needed') or terminal_confirmation_needed(row)}",
        f"- Invalidation map: {_first_text(row, 'terminal_invalidation_map') or terminal_invalidation_map(row)}",
        "",
        "## Key Metrics",
        "",
        f"- Price: {_fmt_num(_first_float(row, 'last_price'))}",
        f"- Short accounts: {_fmt_pct(_first_float(row, 'short_account_pct'))}",
        f"- Long accounts: {_fmt_pct(_first_float(row, 'long_account_pct'))}",
        f"- OI change: {_fmt_pct(_first_float(row, 'oi_delta_pct', 'oi_value_change_since_scan_pct'))}",
        f"- 24h quote volume: {_fmt_num(_first_float(row, 'quote_volume_24h'))}",
        f"- Top10 holder proxy: {_fmt_pct(_first_float(row, 'top10_holder_pct'))}",
        f"- FDV/market cap: {_fmt_num(_first_float(row, 'fdv_to_market_cap'))}",
        f"- ATH runway: {_fmt_num(_first_float(row, 'ath_multiple'))}x",
        "",
        "## Research Notes",
        "",
        _first_text(row, "trade_bucket_note", "pre_pump_precision_note", "rave_lab_setup_note", "convexity_summary")
        or "No narrative note is available for this row yet.",
    ]
    return "\n".join(lines).strip() + "\n"


def write_case_study(row: Mapping[str, Any] | pd.Series, *, root: Path) -> Path:
    symbol = str(row.get("symbol", "UNKNOWN")).upper() if hasattr(row, "get") else "UNKNOWN"
    timestamp = pd.Timestamp.utcnow().strftime("%Y-%m-%d")
    path = root / "case_studies" / f"{symbol}_{timestamp}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_setup_dossier(row), encoding="utf-8")
    return path
