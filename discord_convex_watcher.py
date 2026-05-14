from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from discord_flag_formatter import (
    DISCORD_EMBED_DESCRIPTION_LIMIT,
    DISCORD_FOOTER,
    DISCORD_PRODUCT_IDENTITY,
    build_discord_flag_card,
    join_discord_flag_cards,
)
from holder_composition import fetch_holder_composition, format_holder_composition_for_discord
from proof_engine import archive_alerts, refresh_outcomes
from terminal_engine import apply_terminal_model
from timing_engine import apply_timing_model


APP_DIR = Path(__file__).resolve().parent
STATE_COLUMNS = ["symbol", "active", "last_seen_at", "last_alerted_at", "last_score", "last_note"]


def _load_local_env() -> None:
    env_path = APP_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


def _env_value(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    try:
        parsed = int(str(_env_value(name, str(default))).strip())
    except Exception:
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    return parsed


def _env_float(name: str, default: float, *, minimum: float | None = None) -> float:
    try:
        parsed = float(str(_env_value(name, str(default))).strip())
    except Exception:
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    return parsed


def _env_bool(name: str, default: bool = False) -> bool:
    fallback = "1" if default else "0"
    return _env_value(name, fallback).strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str, default: str = "") -> list[str]:
    raw = _env_value(name, default)
    return [chunk.strip() for chunk in raw.split(",") if chunk.strip()]


def _now() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state_path() -> Path:
    return Path(_env_value("DISCORD_WATCHER_STATE_PATH", str(APP_DIR / "data" / "discord_convex_watcher_state.csv")))


def _load_state() -> pd.DataFrame:
    path = _state_path()
    if not path.exists():
        return pd.DataFrame(columns=STATE_COLUMNS)
    try:
        state = pd.read_csv(path)
    except Exception:
        return pd.DataFrame(columns=STATE_COLUMNS)
    for column in STATE_COLUMNS:
        if column not in state.columns:
            state[column] = pd.NA
    state = state.loc[:, STATE_COLUMNS].copy()
    state["symbol"] = state["symbol"].astype(str).str.upper().str.strip()
    state["active"] = state["active"].fillna(False).astype(bool)
    state["last_seen_at"] = pd.to_datetime(state["last_seen_at"], errors="coerce", utc=True)
    state["last_alerted_at"] = pd.to_datetime(state["last_alerted_at"], errors="coerce", utc=True)
    state["last_score"] = pd.to_numeric(state["last_score"], errors="coerce")
    return state[state["symbol"].ne("")].drop_duplicates(subset=["symbol"], keep="last")


def _save_state(state: pd.DataFrame) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    output = state.loc[:, STATE_COLUMNS].copy()
    output["last_seen_at"] = pd.to_datetime(output["last_seen_at"], errors="coerce", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    output["last_alerted_at"] = pd.to_datetime(output["last_alerted_at"], errors="coerce", utc=True).dt.strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    output.to_csv(path, index=False)


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _boolish_series(series: Any, *, index: pd.Index | None = None) -> pd.Series:
    if not isinstance(series, pd.Series):
        if series is None and index is not None:
            series = pd.Series(False, index=index)
        else:
            series = pd.Series(series if series is not None else [])
            if index is not None and len(series) == len(index):
                series.index = index
    return series.fillna(False).astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y", "on"})


def _holder_contract_hints_path() -> Path:
    return Path(_env_value("DISCORD_HOLDER_CONTRACTS_FILE", str(APP_DIR / "data" / "discord_holder_contracts.csv")))


def _holder_composition_text(row: pd.Series) -> str:
    if not _env_bool("DISCORD_HOLDER_COMPOSITION_ENABLED", True):
        return ""
    try:
        composition = fetch_holder_composition(
            row.to_dict(),
            hints_path=_holder_contract_hints_path(),
            timeout=_env_int("DISCORD_HOLDER_COMPOSITION_TIMEOUT_SECONDS", 12, minimum=3),
            max_holders=_env_int("DISCORD_HOLDER_COMPOSITION_MAX_HOLDERS", 100, minimum=10),
        )
    except Exception as exc:
        return f"Holder composition unavailable: {exc}"
    if composition.error == "no contract hint" and not _env_bool("DISCORD_HOLDER_COMPOSITION_SHOW_MISSING", False):
        return ""
    return format_holder_composition_for_discord(
        composition,
        include_top_holders=_env_int("DISCORD_HOLDER_COMPOSITION_TOP_HOLDERS", 0, minimum=0),
        max_chars=_env_int("DISCORD_HOLDER_COMPOSITION_MAX_CHARS", 520, minimum=200),
    )


def _candidate_line(row: pd.Series) -> str:
    holder_text = _holder_composition_text(row)
    return build_discord_flag_card(row, holder_text=holder_text)


def _ensure_alert_scores(frame: pd.DataFrame) -> pd.DataFrame:
    scored = frame.copy()
    if "terminal_edge_score" not in scored.columns:
        scored = apply_terminal_model(scored)
    if "timing_score" not in scored.columns or "timing_state" not in scored.columns:
        scored = apply_timing_model(scored)
    return scored


def _candidate_cards_and_archive_rows(candidates: pd.DataFrame) -> tuple[list[str], pd.DataFrame]:
    candidates = _ensure_alert_scores(candidates)
    cards: list[str] = []
    archive_rows: list[dict[str, Any]] = []
    for _, row in candidates.iterrows():
        holder_text = _holder_composition_text(row)
        card = build_discord_flag_card(row, holder_text=holder_text)
        cards.append(card)
        record = row.to_dict()
        record["_holder_text"] = holder_text
        record["_raw_bot_output"] = card
        archive_rows.append(record)
    return cards, pd.DataFrame(archive_rows)


def _select_alert_candidates(all_df: pd.DataFrame, *, alert_source: str, top_n: int) -> pd.DataFrame:
    if all_df.empty:
        return all_df.copy()
    scored = _ensure_alert_scores(all_df)
    source = alert_source.strip().lower().replace("-", "_")

    if source in {"convex", "legacy_convex"}:
        candidates = scored[scored.get("trade_bucket", pd.Series("", index=scored.index)).astype(str).eq("Convex Long")].copy()
        if candidates.empty and "trade_bucket_score" in scored.columns:
            candidates = scored.sort_values(["trade_bucket_score", "symbol"], ascending=[False, True]).head(top_n).copy()
        return candidates.head(top_n)

    if source == "terminal":
        min_terminal = _env_float("DISCORD_WATCHER_MIN_TERMINAL_SCORE", 65.0, minimum=0.0)
        candidates = scored[pd.to_numeric(scored.get("terminal_edge_score"), errors="coerce").fillna(0.0) >= min_terminal].copy()
        return candidates.sort_values(["terminal_edge_score", "symbol"], ascending=[False, True]).head(top_n)

    if source == "timing":
        min_timing = _env_float("DISCORD_WATCHER_MIN_TIMING_SCORE", 58.0, minimum=0.0)
        excluded_states = {state.lower() for state in _env_csv("DISCORD_WATCHER_EXCLUDE_TIMING_STATES", "Extended / fragile,Dead / invalidating,No timing edge")}
        candidates = scored[pd.to_numeric(scored.get("timing_score"), errors="coerce").fillna(0.0) >= min_timing].copy()
        state_text = candidates.get("timing_state", pd.Series("", index=candidates.index)).astype(str).str.lower()
        candidates = candidates[~state_text.isin(excluded_states)]
        return candidates.sort_values(["timing_score", "terminal_edge_score", "symbol"], ascending=[False, False, True]).head(top_n)

    if source in {"cex_flow", "cexflow", "cex_deposit_flow"}:
        min_flow = _env_float("DISCORD_WATCHER_MIN_CEX_FLOW_SCORE", 35.0, minimum=0.0)
        flow_score = pd.to_numeric(
            scored.get("cex_deposit_flow_score", pd.Series(0.0, index=scored.index)),
            errors="coerce",
        ).fillna(0.0)
        flow_flag = _boolish_series(scored.get("cex_deposit_flow_flag", pd.Series(False, index=scored.index)), index=scored.index)
        candidates = scored[flow_flag | flow_score.ge(min_flow)].copy()
        if candidates.empty:
            return candidates
        candidates["watcher_alert_score"] = flow_score.loc[candidates.index]
        candidates["_cex_total_pct"] = pd.to_numeric(
            candidates.get("cex_deposit_24h_total_pct_supply", pd.Series(0.0, index=candidates.index)),
            errors="coerce",
        ).fillna(0.0)
        candidates["_cex_count"] = pd.to_numeric(
            candidates.get("cex_deposit_24h_count", pd.Series(0.0, index=candidates.index)),
            errors="coerce",
        ).fillna(0.0)
        return candidates.sort_values(
            ["watcher_alert_score", "_cex_total_pct", "_cex_count", "symbol"],
            ascending=[False, False, False, True],
        ).head(top_n)

    min_terminal = _env_float("DISCORD_WATCHER_MIN_TERMINAL_SCORE", 60.0, minimum=0.0)
    min_timing = _env_float("DISCORD_WATCHER_MIN_TIMING_SCORE", 55.0, minimum=0.0)
    allowed_states = {state.lower() for state in _env_csv("DISCORD_WATCHER_ALLOWED_TIMING_STATES", "Coiling,Triggering,Confirmed")}
    terminal_ok = pd.to_numeric(scored.get("terminal_edge_score"), errors="coerce").fillna(0.0) >= min_terminal
    timing_ok = pd.to_numeric(scored.get("timing_score"), errors="coerce").fillna(0.0) >= min_timing
    state_text = scored.get("timing_state", pd.Series("", index=scored.index)).astype(str).str.lower()
    state_ok = state_text.isin(allowed_states)
    candidates = scored[terminal_ok & timing_ok & state_ok].copy()
    candidates["watcher_alert_score"] = (
        pd.to_numeric(candidates.get("terminal_edge_score"), errors="coerce").fillna(0.0) * 0.52
        + pd.to_numeric(candidates.get("timing_score"), errors="coerce").fillna(0.0) * 0.48
    )
    return candidates.sort_values(
        ["watcher_alert_score", "timing_score", "terminal_edge_score", "symbol"],
        ascending=[False, False, False, True],
    ).head(top_n)


def _scan_alert_candidates(scan_mode: str, *, alert_source: str, top_n: int) -> pd.DataFrame:
    os.environ["CRYPTO_SCANNER_IMPORT_ONLY"] = "1"
    print(f"{_iso_now()} starting {scan_mode} scan...")
    import app as scanner_app

    scan_fn = getattr(scanner_app.run_scan, "__wrapped__", scanner_app.run_scan)
    _, all_df = scan_fn(int(time.time()), scan_mode)
    scanner_app._write_latest_convex_longs_cache(all_df, scan_mode=scan_mode)
    if alert_source.strip().lower().replace("-", "_") in {"convex", "legacy_convex"}:
        candidates = scanner_app._discord_convex_candidates(all_df).copy().head(top_n)
    else:
        candidates = _select_alert_candidates(all_df, alert_source=alert_source, top_n=top_n)
    if candidates.empty:
        return candidates
    candidates.insert(0, "scanned_at_utc", _iso_now())
    candidates.insert(1, "scan_mode", scan_mode)
    candidates.insert(2, "watcher_alert_source", alert_source)
    return candidates


def _eligible_new_candidates(candidates: pd.DataFrame, state: pd.DataFrame, *, realert_hours: float) -> pd.DataFrame:
    if candidates.empty:
        return candidates
    previous_active = set(state[state["active"]]["symbol"].astype(str).str.upper())
    last_alerted = dict(zip(state["symbol"], state["last_alerted_at"]))
    cutoff = _now() - pd.Timedelta(hours=realert_hours)
    eligible_indices: list[Any] = []
    for index, row in candidates.iterrows():
        symbol = str(row.get("symbol", "")).upper().strip()
        if not symbol:
            continue
        alerted_at = last_alerted.get(symbol)
        can_realert = pd.isna(alerted_at) or alerted_at <= cutoff
        if symbol not in previous_active and can_realert:
            eligible_indices.append(index)
    return candidates.loc[eligible_indices].copy()


def _update_state(state: pd.DataFrame, candidates: pd.DataFrame, alerted: pd.DataFrame) -> pd.DataFrame:
    now = _now()
    current_symbols = {str(symbol).upper().strip() for symbol in candidates.get("symbol", pd.Series(dtype="object")).tolist()}
    alerted_symbols = {str(symbol).upper().strip() for symbol in alerted.get("symbol", pd.Series(dtype="object")).tolist()}
    if state.empty:
        state = pd.DataFrame(columns=STATE_COLUMNS)
    state = state.copy()
    state["active"] = state["symbol"].isin(current_symbols)
    by_symbol = {str(row.get("symbol", "")).upper().strip(): row for _, row in candidates.iterrows()}

    new_rows: list[dict[str, Any]] = []
    existing_symbols = set(state["symbol"].astype(str).str.upper())
    for symbol, row in by_symbol.items():
        score = (
            _safe_float(row.get("watcher_alert_score"))
            or _safe_float(row.get("cex_deposit_flow_score"))
            or _safe_float(row.get("timing_score"))
            or _safe_float(row.get("terminal_edge_score"))
            or _safe_float(row.get("trade_bucket_score"))
        )
        note = str(row.get("cex_deposit_flow_note", "")).strip()[:300]
        if not note:
            note = str(row.get("trade_bucket_note", "")).strip()[:300]
        if not note:
            note = str(row.get("timing_state", "") or row.get("terminal_setup_archetype", "")).strip()[:300]
        if symbol in existing_symbols:
            state.loc[state["symbol"] == symbol, ["active", "last_seen_at", "last_score", "last_note"]] = [
                True,
                now,
                score,
                note,
            ]
        else:
            new_rows.append(
                {
                    "symbol": symbol,
                    "active": True,
                    "last_seen_at": now,
                    "last_alerted_at": pd.NaT,
                    "last_score": score,
                    "last_note": note,
                }
            )

    if new_rows and state.empty:
        state = pd.DataFrame(new_rows, columns=STATE_COLUMNS)
    elif new_rows:
        state = pd.concat([state, pd.DataFrame(new_rows, columns=STATE_COLUMNS)], ignore_index=True)

    for symbol in alerted_symbols:
        state.loc[state["symbol"] == symbol, "last_alerted_at"] = now
    return state.drop_duplicates(subset=["symbol"], keep="last")


def _post_webhook(candidates: pd.DataFrame, *, scan_mode: str, alert_source: str, dry_run: bool) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()
    webhook_url = _env_value("DISCORD_WEBHOOK_URL")
    if not webhook_url and not dry_run:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not set.")

    lines, archive_rows = _candidate_cards_and_archive_rows(candidates)
    card_budget = DISCORD_EMBED_DESCRIPTION_LIMIT - len(DISCORD_PRODUCT_IDENTITY) - 2
    description = f"{DISCORD_PRODUCT_IDENTITY}\n\n{join_discord_flag_cards(lines, max_chars=card_budget)}"
    payload = {
        "username": "Convex Scanner",
        "embeds": [
            {
                "title": f"New market-structure candidate ({len(candidates)})",
                "description": description,
                "color": 0x22C55E,
                "fields": [
                    {"name": "Scan mode", "value": scan_mode, "inline": True},
                    {"name": "Alert source", "value": alert_source, "inline": True},
                    {"name": "Detected", "value": _iso_now(), "inline": True},
                ],
                "footer": {"text": DISCORD_FOOTER},
            }
        ],
    }
    if dry_run:
        print("DRY RUN webhook payload:")
        print(payload)
        return archive_rows
    response = requests.post(webhook_url, json=payload, timeout=15)
    if response.status_code >= 300:
        raise RuntimeError(f"Discord webhook HTTP {response.status_code}: {response.text[:250]}")
    return archive_rows


def run_once(*, scan_mode: str, top_n: int, realert_hours: float, dry_run: bool, alert_source: str) -> tuple[int, int]:
    state = _load_state()
    candidates = _scan_alert_candidates(scan_mode, alert_source=alert_source, top_n=top_n).head(top_n).copy()
    new_candidates = _eligible_new_candidates(candidates, state, realert_hours=realert_hours)
    archived_rows = pd.DataFrame()
    if not new_candidates.empty:
        archived_rows = _post_webhook(new_candidates, scan_mode=scan_mode, alert_source=alert_source, dry_run=dry_run)
    if dry_run:
        return len(candidates), len(new_candidates)
    if not archived_rows.empty:
        archive_alerts(archived_rows, scan_mode=scan_mode)
    if _env_bool("DISCORD_PROOF_REFRESH_ENABLED", True):
        refresh_outcomes(max_rows=_env_int("DISCORD_PROOF_REFRESH_MAX_ROWS", 12, minimum=1))
    updated_state = _update_state(state, candidates, new_candidates if not dry_run else pd.DataFrame())
    _save_state(updated_state)
    return len(candidates), len(new_candidates)


def main() -> None:
    _load_local_env()
    parser = argparse.ArgumentParser(description="Automatically scan market-structure candidates and post new names to Discord.")
    parser.add_argument("--once", action="store_true", help="Run one scan then exit.")
    parser.add_argument("--dry-run", action="store_true", help="Print webhook payload without posting.")
    args = parser.parse_args()

    scan_mode = _env_value("DISCORD_WATCHER_SCAN_MODE", "Deep")
    alert_source = _env_value("DISCORD_WATCHER_ALERT_SOURCE", "terminal_timing")
    interval_seconds = _env_int("DISCORD_WATCHER_SCAN_INTERVAL_SECONDS", 180, minimum=30)
    top_n = _env_int("DISCORD_WATCHER_TOP_N", 25, minimum=1)
    realert_hours = _env_float("DISCORD_WATCHER_REALERT_HOURS", 12.0, minimum=0.0)
    retry_seconds = _env_int("DISCORD_WATCHER_ERROR_RETRY_SECONDS", 60, minimum=15)
    dry_run = args.dry_run or _env_value("DISCORD_WATCHER_DRY_RUN", "0").strip().lower() in {"1", "true", "yes", "on"}

    print(
        f"Convex watcher started: mode={scan_mode}, alert_source={alert_source}, interval={interval_seconds}s, top_n={top_n}, "
        f"realert_hours={realert_hours}, dry_run={dry_run}."
    )
    while True:
        try:
            total, alerted = run_once(scan_mode=scan_mode, top_n=top_n, realert_hours=realert_hours, dry_run=dry_run, alert_source=alert_source)
            print(f"{_iso_now()} scan complete: {total} market-structure candidates, {alerted} new alerts.")
        except Exception as exc:
            print(f"{_iso_now()} watcher error: {exc}. Retrying in {retry_seconds}s.")
            time.sleep(retry_seconds)
            if args.once:
                raise
        if args.once:
            return
        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
