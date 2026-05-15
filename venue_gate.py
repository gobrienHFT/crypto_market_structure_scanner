from __future__ import annotations

import os
import re
from typing import Any

import pandas as pd


BITGET_GATE_RE = re.compile(r"\b(?:bitget|gate(?:[\s._-]*io)?)\b", re.IGNORECASE)


def _env_value(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_bool(name: str, default: bool = False) -> bool:
    fallback = "1" if default else "0"
    return _env_value(name, fallback).strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float, *, minimum: float | None = None) -> float:
    try:
        parsed = float(str(_env_value(name, str(default))).strip())
    except Exception:
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    return parsed


def _numeric_column(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame.get(column, pd.Series(0.0, index=frame.index)), errors="coerce").fillna(0.0)


def _text_column(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame.get(column, pd.Series("", index=frame.index)).fillna("").astype(str)


def _boolish_series(series: Any, *, index: pd.Index) -> pd.Series:
    if not isinstance(series, pd.Series):
        series = pd.Series(series if series is not None else False, index=index)
    return series.fillna(False).astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y", "on"})


def bitget_gate_venue_gate_enabled() -> bool:
    return _env_bool("DISCORD_REQUIRE_BITGET_OR_GATE", True)


def bitget_gate_min_share_pct() -> float:
    return _env_float("DISCORD_VENUE_GATE_MIN_SHARE_PCT", 0.0, minimum=0.0)


def bitget_gate_venue_mask(frame: pd.DataFrame, *, allow_cex_flow_targets: bool = True) -> pd.Series:
    if frame.empty:
        return pd.Series(False, index=frame.index)

    min_share = bitget_gate_min_share_pct()
    bitget_share = _numeric_column(frame, "bitget_volume_share_pct").gt(min_share)
    gate_share = _numeric_column(frame, "gate_volume_share_pct").gt(min_share)
    explicit_flag = _boolish_series(frame.get("bitget_or_gate_venue_flag"), index=frame.index)
    top_venue = _text_column(frame, "top_venue").str.contains(BITGET_GATE_RE, na=False)

    if allow_cex_flow_targets:
        cex_targets = _text_column(frame, "cex_deposit_24h_target_exchanges").str.contains(BITGET_GATE_RE, na=False)
    else:
        cex_targets = pd.Series(False, index=frame.index)

    return bitget_share | gate_share | explicit_flag | top_venue | cex_targets


def apply_bitget_gate_venue_gate(frame: pd.DataFrame, *, allow_cex_flow_targets: bool = True) -> pd.DataFrame:
    if frame.empty or not bitget_gate_venue_gate_enabled():
        return frame.copy()
    return frame[bitget_gate_venue_mask(frame, allow_cex_flow_targets=allow_cex_flow_targets)].copy()


def bitget_gate_venue_header(*, allow_cex_flow_targets: bool = False) -> str:
    if not bitget_gate_venue_gate_enabled():
        return "Venue gate: disabled"
    min_share = bitget_gate_min_share_pct()
    share_text = "any visible share" if min_share <= 0 else f">{min_share:.2f}% share"
    suffix = " or Bitget/Gate transfer target" if allow_cex_flow_targets else ""
    return f"Venue gate: Binance perp + Bitget/Gate venue support ({share_text}{suffix})"
