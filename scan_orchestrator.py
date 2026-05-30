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
