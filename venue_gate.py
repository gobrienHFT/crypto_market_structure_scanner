from __future__ import annotations

import os
import re

import pandas as pd

from holder_composition import clean_contract_address, normalize_chain


BINANCE_RE = re.compile(r"\bbinance\b", re.IGNORECASE)
BITGET_RE = re.compile(r"\bbitget\b", re.IGNORECASE)
THESIS_HOLDER_EVIDENCE_CHAINS = {"ethereum", "bsc", "arbitrum"}
THESIS_HOLDER_EVIDENCE_CHAIN_LABEL = "ETH/BNB/ARB"
THESIS_MIN_TOP10_HOLDER_PCT = 90.0
HOLDER_EXPLORER_SOURCE_RE = re.compile(
    r"\b(?:etherscan|bscscan|arbiscan|explorer)\b|holder\s+endpoint",
    re.IGNORECASE,
)


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
    series = frame.get(column, pd.Series("", index=frame.index)).fillna("").astype(str).str.strip()
    return series.where(~series.str.lower().isin({"nan", "none", "null", "<na>"}), "")


def _boolish_column(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    return (
        frame[column]
        .astype("object")
        .where(pd.notna(frame[column]), False)
        .astype(str)
        .str.strip()
        .str.lower()
        .isin({"1", "true", "yes", "y", "on"})
    )


def binance_bitget_venue_gate_enabled() -> bool:
    return _env_bool("DISCORD_REQUIRE_BITGET_OR_GATE", True)


def assume_symbol_universe_is_binance_perp() -> bool:
    return _env_bool("DISCORD_ASSUME_SYMBOLS_ARE_BINANCE_PERPS", False)


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
    explicit_binance_perp = (
        _boolish_column(frame, "binance_perp_universe")
        | _boolish_column(frame, "is_binance_perp")
        | _boolish_column(frame, "_ravelab_binance_perp_universe")
    )
    implicit_binance_perp = symbols if assume_symbol_universe_is_binance_perp() else pd.Series(False, index=frame.index)

    has_binance = explicit_binance_perp | implicit_binance_perp | binance_share | top_venue.str.contains(BINANCE_RE, na=False)
    has_bitget = bitget_share | top_venue.str.contains(BITGET_RE, na=False)
    return (has_binance & has_bitget).fillna(False)


def _binance_bitget_required_header(*, allow_cex_flow_targets: bool = False) -> str:
    min_share = binance_bitget_min_share_pct()
    share_text = "any visible Bitget share" if min_share <= 0 else f"Bitget >{min_share:.2f}% share"
    binance_text = "symbol-universe Binance perp marker/share" if assume_symbol_universe_is_binance_perp() else "explicit Binance perp marker/share"
    flow_text = "; transfer targets are supporting evidence only" if allow_cex_flow_targets else ""
    return f"Venue gate: Binance perp + Bitget trading evidence required ({binance_text}; {share_text}); Gate optional{flow_text}"


def apply_binance_bitget_venue_gate(frame: pd.DataFrame, *, allow_cex_flow_targets: bool = True) -> pd.DataFrame:
    if frame.empty or not binance_bitget_venue_gate_enabled():
        return frame.copy()
    return frame[binance_bitget_venue_mask(frame, allow_cex_flow_targets=allow_cex_flow_targets)].copy()


def holder_evidence_mask(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(False, index=frame.index)

    source_columns = [column for column in ("holder_source", "holder_data_source") if column in frame.columns]
    if source_columns:
        source_mask = pd.concat(
            [
                _text_column(frame, column).str.contains(HOLDER_EXPLORER_SOURCE_RE, regex=True, na=False)
                for column in source_columns
            ],
            axis=1,
        ).any(axis=1)
    else:
        source_mask = pd.Series(False, index=frame.index)

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
    snapshot_mask = (
        _numeric_column(frame, "holder_count").gt(0.0)
        | _pct_column(frame, "top10_holder_pct").notna()
        | _pct_column(frame, "top100_holder_pct").notna()
    )
    return (chain_mask & contract_mask & source_mask & snapshot_mask).fillna(False)


def holder_concentration_mask(
    frame: pd.DataFrame,
    *,
    min_whale_pct: float = 90.0,
    require_holder_evidence: bool = True,
) -> pd.Series:
    if frame.empty:
        return pd.Series(False, index=frame.index)
    top10 = _pct_column(frame, "top10_holder_pct").fillna(0.0)
    threshold = max(THESIS_MIN_TOP10_HOLDER_PCT, float(min_whale_pct))
    gate = top10.ge(threshold)
    if require_holder_evidence:
        gate = gate & holder_evidence_mask(frame)
    return gate.fillna(False)


def no_recent_pump_proof_mask(
    frame: pd.DataFrame,
    *,
    min_history_days: int = 60,
    max_recent_pump_pct: float = 35.0,
) -> pd.Series:
    if frame.empty:
        return pd.Series(False, index=frame.index)
    min_days = max(1, int(min_history_days))
    proof_days = max(1, min(60, min_days))
    history_days = _numeric_column(frame, "history_days")
    recent_pump_days = _numeric_column(frame, "recent_pump_60d_days")
    recent_pump = pd.to_numeric(frame.get("recent_max_pump_60d_pct", pd.Series(float("nan"), index=frame.index)), errors="coerce")
    no_large_flag = _boolish_column(frame, "no_large_pump_60d_flag")
    coverage = history_days.ge(min_days) | recent_pump_days.ge(proof_days)
    pump_window_ready = recent_pump_days.ge(proof_days)
    numeric_pass = recent_pump.notna() & recent_pump.lt(max(0.0, float(max_recent_pump_pct))) & pump_window_ready
    flag_pass = no_large_flag & pump_window_ready
    return (coverage & (numeric_pass | flag_pass)).fillna(False)


def apply_thesis_alert_gate(
    frame: pd.DataFrame,
    *,
    min_whale_pct: float = 90.0,
    require_holder_evidence: bool = True,
    require_venue: bool = True,
    require_no_recent_pump: bool = True,
    allow_cex_flow_targets: bool = False,
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    gated = frame[holder_concentration_mask(frame, min_whale_pct=min_whale_pct, require_holder_evidence=require_holder_evidence)].copy()
    if require_no_recent_pump and not gated.empty:
        gated = gated[no_recent_pump_proof_mask(gated)].copy()
    if gated.empty or not require_venue:
        return gated
    return gated[binance_bitget_venue_mask(gated, allow_cex_flow_targets=allow_cex_flow_targets)].copy()


def thesis_alert_header(
    *,
    min_whale_pct: float = 90.0,
    require_holder_evidence: bool = True,
    require_venue: bool = True,
    require_no_recent_pump: bool = True,
    allow_cex_flow_targets: bool = False,
) -> str:
    threshold = max(THESIS_MIN_TOP10_HOLDER_PCT, float(min_whale_pct))
    holder = f"Holder gate: observed top10 holder concentration >= {threshold:.1f}%"
    if require_holder_evidence:
        holder = f"{holder} with {THESIS_HOLDER_EVIDENCE_CHAIN_LABEL} chain+contract explorer holder-source snapshot evidence"
    else:
        holder = f"{holder}; holder evidence diagnostic relaxed"
    pump = "60D no-pump proof required" if require_no_recent_pump else "60D no-pump gate disabled"
    if not require_venue:
        return f"{holder} | {pump} | Venue gate: disabled"
    return f"{holder} | {pump} | {_binance_bitget_required_header(allow_cex_flow_targets=allow_cex_flow_targets)}"


def binance_bitget_venue_header(*, allow_cex_flow_targets: bool = False) -> str:
    if not binance_bitget_venue_gate_enabled():
        return "Venue gate: disabled"
    return _binance_bitget_required_header(allow_cex_flow_targets=allow_cex_flow_targets)


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
