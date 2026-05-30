from __future__ import annotations

import os
import re

import pandas as pd


BINANCE_RE = re.compile(r"\bbinance\b", re.IGNORECASE)
BITGET_RE = re.compile(r"\bbitget\b", re.IGNORECASE)


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


def binance_bitget_venue_gate_enabled() -> bool:
    return _env_bool("DISCORD_REQUIRE_BITGET_OR_GATE", True)


def binance_bitget_min_share_pct() -> float:
    return _env_float("DISCORD_VENUE_GATE_MIN_SHARE_PCT", 0.0, minimum=0.0)


def binance_bitget_venue_mask(frame: pd.DataFrame, *, allow_cex_flow_targets: bool = True) -> pd.Series:
    if frame.empty:
        return pd.Series(False, index=frame.index)

    min_share = binance_bitget_min_share_pct()
    symbols = _text_column(frame, "symbol").str.strip().ne("")
    binance_share = _numeric_column(frame, "binance_volume_share_pct").gt(min_share)
    bitget_share = _numeric_column(frame, "bitget_volume_share_pct").gt(min_share)
    top_venue = _text_column(frame, "top_venue")

    has_binance = symbols | binance_share | top_venue.str.contains(BINANCE_RE, na=False)
    has_bitget = bitget_share | top_venue.str.contains(BITGET_RE, na=False)
    return (has_binance & has_bitget).fillna(False)


def apply_binance_bitget_venue_gate(frame: pd.DataFrame, *, allow_cex_flow_targets: bool = True) -> pd.DataFrame:
    if frame.empty or not binance_bitget_venue_gate_enabled():
        return frame.copy()
    return frame[binance_bitget_venue_mask(frame, allow_cex_flow_targets=allow_cex_flow_targets)].copy()


def binance_bitget_venue_header(*, allow_cex_flow_targets: bool = False) -> str:
    if not binance_bitget_venue_gate_enabled():
        return "Venue gate: disabled"
    min_share = binance_bitget_min_share_pct()
    share_text = "any visible Bitget share" if min_share <= 0 else f"Bitget >{min_share:.2f}% share"
    flow_text = "; transfer targets are supporting evidence only" if allow_cex_flow_targets else ""
    return f"Venue gate: Binance perp + Bitget trading evidence required ({share_text}); Gate optional{flow_text}"


# Backward-compatible names for older imports. Their behavior now follows the
# stricter thesis gate: Gate no longer substitutes for Bitget.
def bitget_gate_venue_gate_enabled() -> bool:
    return binance_bitget_venue_gate_enabled()


def bitget_gate_min_share_pct() -> float:
    return binance_bitget_min_share_pct()


def bitget_gate_venue_mask(frame: pd.DataFrame, *, allow_cex_flow_targets: bool = True) -> pd.Series:
    return binance_bitget_venue_mask(frame, allow_cex_flow_targets=allow_cex_flow_targets)


def apply_bitget_gate_venue_gate(frame: pd.DataFrame, *, allow_cex_flow_targets: bool = True) -> pd.DataFrame:
    return apply_binance_bitget_venue_gate(frame, allow_cex_flow_targets=allow_cex_flow_targets)


def bitget_gate_venue_header(*, allow_cex_flow_targets: bool = False) -> str:
    return binance_bitget_venue_header(allow_cex_flow_targets=allow_cex_flow_targets)
