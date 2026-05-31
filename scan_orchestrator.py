from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from venue_gate import apply_thesis_alert_gate


_MISSING = object()


@dataclass(frozen=True)
class ScanResult:
    scan_mode: str
    source: str
    candidates: pd.DataFrame
    all_rows: pd.DataFrame


def _utc_scan_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _num_series(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").fillna(default).astype("float64")


def _score_linear(series: pd.Series, low: float, high: float) -> pd.Series:
    if high <= low:
        return pd.Series(0.0, index=series.index, dtype="float64")
    return ((series - low) / (high - low) * 100.0).clip(lower=0.0, upper=100.0)


def _max_series(frame: pd.DataFrame, *columns: str, default: float = 0.0) -> pd.Series:
    parts = [_num_series(frame, column, default=float("nan")) for column in columns if column in frame.columns]
    if not parts:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.concat(parts, axis=1).max(axis=1).fillna(default).astype("float64")


def apply_core_setup_gate(frame: pd.DataFrame, *, min_short_pct: float = 50.0) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    output = frame.loc[:, ~frame.columns.duplicated()].copy()
    short_pct = _num_series(output, "short_account_pct")
    float_component = pd.concat(
        [
            _num_series(output, "low_float_score"),
            _num_series(output, "float_trap_score"),
            _num_series(output, "terminal_float_score"),
            _num_series(output, "terminal_hidden_float_reflexivity_score"),
            _score_linear(_num_series(output, "fdv_to_market_cap"), 1.8, 12.0),
            _score_linear(_num_series(output, "locked_supply_pct"), 15.0, 85.0),
        ],
        axis=1,
    ).max(axis=1)
    structure_component = _max_series(
        output,
        "terminal_pre_ignition_quality_score",
        "timing_score",
        "dormant_short_fuse_score",
        "pre_pump_precision_score",
        "rave_lab_setup_score",
        "accumulation_absorption_score",
    )
    late_risk = pd.concat(
        [
            _num_series(output, "timing_too_late_score"),
            _num_series(output, "convexity_late_penalty"),
            _num_series(output, "no_chase_penalty_score"),
            _num_series(output, "exit_fragility_score") * 0.7,
        ],
        axis=1,
    ).max(axis=1)
    not_late = (100.0 - late_risk).clip(lower=0.0, upper=100.0)
    float_pass = float_component.ge(55.0) | _num_series(output, "fdv_to_market_cap").ge(4.0) | _num_series(output, "locked_supply_pct").ge(45.0)
    core_mask = short_pct.ge(float(min_short_pct or 0.0)) & float_pass & structure_component.ge(35.0) & not_late.ge(45.0)
    return output[core_mask.fillna(False)].copy()


def select_convex_long_candidates(
    frame: pd.DataFrame,
    *,
    min_score: float = 0.0,
    allow_cex_flow_targets: bool = False,
) -> pd.DataFrame:
    if frame.empty or "trade_bucket" not in frame.columns:
        return pd.DataFrame()
    source = frame.loc[:, ~frame.columns.duplicated()].copy()
    source["_discord_bucket_score"] = pd.to_numeric(source.get("trade_bucket_score"), errors="coerce").fillna(0.0)
    candidates = source[
        source["trade_bucket"].astype(str).eq("Convex Long")
        & source["_discord_bucket_score"].ge(float(min_score or 0.0))
    ].copy()
    if candidates.empty:
        return candidates
    candidates = apply_thesis_alert_gate(candidates, allow_cex_flow_targets=allow_cex_flow_targets)
    candidates = apply_core_setup_gate(candidates)
    if candidates.empty:
        return candidates
    return candidates.sort_values(["_discord_bucket_score", "symbol"], ascending=[False, True])


def run_scanner_scan(
    scan_mode: str = "Deep",
    *,
    refresh_nonce: int | None = None,
    write_discord_cache: bool = True,
    cex_min_transfer_tokens: float | None = None,
    cex_lookback_hours: int | None = None,
) -> ScanResult:
    mode = str(scan_mode or "Deep").strip() or "Deep"
    started_at = _utc_scan_stamp()
    os.environ["CRYPTO_SCANNER_IMPORT_ONLY"] = "1"
    import app as scanner_app

    env_overrides: dict[str, str] = {}
    attr_overrides: dict[str, float | int] = {}
    if cex_min_transfer_tokens is not None:
        min_transfer = max(0.0, float(cex_min_transfer_tokens))
        env_overrides["CEX_DEPOSIT_FLOW_MIN_TRANSFER_TOKENS"] = str(min_transfer)
        attr_overrides["CEX_DEPOSIT_FLOW_MIN_TRANSFER_TOKENS"] = min_transfer
    if cex_lookback_hours is not None:
        lookback = max(1, int(cex_lookback_hours))
        env_overrides["CEX_DEPOSIT_FLOW_LOOKBACK_HOURS"] = str(lookback)
        attr_overrides["CEX_DEPOSIT_FLOW_LOOKBACK_HOURS"] = lookback

    old_env = {key: os.environ.get(key) for key in env_overrides}
    old_attrs = {key: getattr(scanner_app, key, _MISSING) for key in attr_overrides}
    try:
        for key, value in env_overrides.items():
            os.environ[key] = value
        for key, value in attr_overrides.items():
            if hasattr(scanner_app, key):
                setattr(scanner_app, key, value)

        scan_fn = getattr(scanner_app.run_scan, "__wrapped__", scanner_app.run_scan)
        _, all_df = scan_fn(int(time.time()) if refresh_nonce is None else int(refresh_nonce), mode)
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for key, value in old_attrs.items():
            if value is not _MISSING:
                setattr(scanner_app, key, value)

    if all_df.empty:
        return ScanResult(mode, f"fresh {mode} scan returned no rows at {started_at}", pd.DataFrame(), all_df.copy())

    frame = all_df.loc[:, ~all_df.columns.duplicated()].copy()
    if "scanned_at_utc" not in frame.columns:
        frame.insert(0, "scanned_at_utc", started_at)
    if "scan_mode" not in frame.columns:
        frame.insert(1, "scan_mode", mode)
    if "binance_perp_universe" not in frame.columns:
        frame["binance_perp_universe"] = True
    if write_discord_cache:
        try:
            scanner_app._write_latest_convex_longs_cache(frame, scan_mode=mode)
        except Exception:
            pass

    min_score = float(getattr(scanner_app, "DISCORD_CONVEX_ALERT_MIN_SCORE", 0.0) or 0.0)
    candidates = select_convex_long_candidates(frame, min_score=min_score, allow_cex_flow_targets=False)
    threshold_note = ""
    if cex_min_transfer_tokens is not None:
        threshold_note = f" | CEX min transfer {float(cex_min_transfer_tokens):g} tokens"
    return ScanResult(mode, f"fresh {mode} scan at {started_at}{threshold_note}", candidates, frame)


def run_fresh_scan_frame(
    scan_mode: str = "Deep",
    *,
    cex_min_transfer_tokens: float | None = None,
    cex_lookback_hours: int | None = None,
) -> tuple[pd.DataFrame, str]:
    try:
        result = run_scanner_scan(
            scan_mode,
            write_discord_cache=True,
            cex_min_transfer_tokens=cex_min_transfer_tokens,
            cex_lookback_hours=cex_lookback_hours,
        )
    except Exception as exc:
        return pd.DataFrame(), f"fresh scan unavailable: {exc}"
    if result.all_rows.empty:
        return pd.DataFrame(), result.source
    return result.all_rows, result.source
