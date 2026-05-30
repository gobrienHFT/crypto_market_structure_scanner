from __future__ import annotations

import os
import re

import pandas as pd

from holder_composition import clean_contract_address, normalize_chain


BINANCE_RE = re.compile(r"\bbinance\b", re.IGNORECASE)
BITGET_RE = re.compile(r"\bbitget\b", re.IGNORECASE)
THESIS_HOLDER_EVIDENCE_CHAINS = {"ethereum", "bsc", "arbitrum"}
THESIS_HOLDER_EVIDENCE_CHAIN_LABEL = "ETH/BNB/ARB"


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


def _pct_column(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(float("nan"), index=frame.index, dtype="float64")
    values = (
        frame[column]
        .astype("object")
        .map(lambda value: str(value).replace(",", "").replace("%", "").strip())
        .replace({"": None, "nan": None, "None": None, "<NA>": None})
    )
    parsed = pd.to_numeric(values, errors="coerce").astype("float64")
    return parsed.mask((parsed != 0.0) & (parsed.abs() <= 1.0), parsed * 100.0)


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


def holder_evidence_mask(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(False, index=frame.index)

    source_columns = [column for column in ("holder_source", "holder_data_source") if column in frame.columns]
    if source_columns:
        source_mask = pd.concat([_text_column(frame, column).str.strip().ne("") for column in source_columns], axis=1).any(axis=1)
    else:
        source_mask = pd.Series(False, index=frame.index)
    holder_count = _numeric_column(frame, "holder_count").gt(0.0)

    def row_has_chain(row: pd.Series) -> bool:
        for column in ("token_platform", "chain", "token_chain"):
            value = row.get(column)
            text = "" if value is None else str(value).strip()
            if text and text.lower() not in {"nan", "none", "null", "<na>"}:
                return normalize_chain(text) in THESIS_HOLDER_EVIDENCE_CHAINS
        return False

    def row_contract(row: pd.Series) -> str:
        for column in ("token_contract", "contract_address", "contract"):
            value = row.get(column)
            try:
                if value is None or pd.isna(value):
                    continue
            except (TypeError, ValueError):
                pass
            contract = clean_contract_address(value)
            if contract:
                return contract
        return ""

    chain_mask = frame.apply(row_has_chain, axis=1).astype(bool)
    contract_mask = frame.apply(lambda row: bool(row_contract(row)), axis=1).astype(bool)
    return (chain_mask & contract_mask & (source_mask | holder_count)).fillna(False)


def holder_concentration_mask(
    frame: pd.DataFrame,
    *,
    min_whale_pct: float = 90.0,
    require_holder_evidence: bool = True,
) -> pd.Series:
    if frame.empty:
        return pd.Series(False, index=frame.index)
    top10 = _pct_column(frame, "top10_holder_pct").fillna(0.0)
    top100 = _pct_column(frame, "top100_holder_pct").fillna(0.0)
    whale_pct = pd.concat([top10, top100], axis=1).max(axis=1).fillna(0.0)
    gate = whale_pct.ge(max(0.0, float(min_whale_pct)))
    if require_holder_evidence:
        gate = gate & holder_evidence_mask(frame)
    return gate.fillna(False)


def apply_thesis_alert_gate(
    frame: pd.DataFrame,
    *,
    min_whale_pct: float = 90.0,
    require_holder_evidence: bool = True,
    require_venue: bool = True,
    allow_cex_flow_targets: bool = False,
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    gated = frame[holder_concentration_mask(frame, min_whale_pct=min_whale_pct, require_holder_evidence=require_holder_evidence)].copy()
    if gated.empty or not require_venue:
        return gated
    return apply_binance_bitget_venue_gate(gated, allow_cex_flow_targets=allow_cex_flow_targets)


def thesis_alert_header(
    *,
    min_whale_pct: float = 90.0,
    require_holder_evidence: bool = True,
    require_venue: bool = True,
    allow_cex_flow_targets: bool = False,
) -> str:
    holder = f"Holder gate: observed top-holder concentration >= {float(min_whale_pct):.1f}%"
    if require_holder_evidence:
        holder = f"{holder} with {THESIS_HOLDER_EVIDENCE_CHAIN_LABEL} chain+contract source/count evidence"
    else:
        holder = f"{holder}; holder evidence diagnostic relaxed"
    if not require_venue:
        return f"{holder} | Venue gate: disabled"
    return f"{holder} | {binance_bitget_venue_header(allow_cex_flow_targets=allow_cex_flow_targets)}"


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
