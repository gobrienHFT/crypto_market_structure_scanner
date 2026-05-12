from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from binance_futures import BinanceFuturesPublic


APP_DIR = Path(__file__).resolve().parent
ARCHIVE_COLUMNS = [
    "alert_id",
    "symbol",
    "flagged_at_utc",
    "flagged_price",
    "convex_score",
    "reason_tags",
    "chain_concentration",
    "oi_volume_state",
    "scan_mode",
    "short_account_pct",
    "long_account_pct",
    "oi_delta_pct",
    "quote_volume_24h",
    "trade_bucket_note",
    "holder_text",
    "terminal_edge_score",
    "terminal_setup_archetype",
    "terminal_market_regime",
    "terminal_liquidity_reality",
    "terminal_evidence_summary",
    "terminal_confirmation_needed",
    "terminal_invalidation_map",
    "timing_score",
    "timing_state",
    "timing_observed_trigger",
    "timing_confirmation_needed",
    "timing_invalidation",
    "timing_too_late_score",
    "max_upside_1h_pct",
    "max_upside_4h_pct",
    "max_upside_24h_pct",
    "max_upside_7d_pct",
    "max_drawdown_pct",
    "time_to_20pct_minutes",
    "time_to_50pct_minutes",
    "time_to_2x_minutes",
    "structure_invalidated",
    "outcome_updated_at_utc",
]
HORIZONS = {"1h": 1, "4h": 4, "24h": 24, "7d": 24 * 7}


def _env_value(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def proof_archive_path() -> Path:
    return Path(_env_value("DISCORD_PROOF_ARCHIVE_PATH", str(APP_DIR / "data" / "discord_convex_alert_archive.csv")))


def archive_root_path() -> Path:
    return Path(_env_value("DISCORD_PROOF_ARCHIVE_ROOT", str(APP_DIR / "data" / "archive")))


def flags_archive_dir() -> Path:
    return archive_root_path() / "flags"


def outcomes_archive_dir() -> Path:
    return archive_root_path() / "outcomes"


def reports_archive_dir() -> Path:
    return archive_root_path() / "reports"


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _first_float(row: pd.Series | dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        parsed = _safe_float(row.get(key))
        if parsed is not None:
            return parsed
    return None


def _pct_value(value: Any) -> float | None:
    parsed = _safe_float(value)
    if parsed is None:
        return None
    if parsed != 0.0 and abs(parsed) <= 1.0:
        return parsed * 100.0
    return parsed


def _row_text(row: pd.Series | dict[str, Any], key: str) -> str:
    value = row.get(key) if hasattr(row, "get") else None
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_safe(value: Any) -> Any:
    if value is pd.NA or value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ") if value.tzinfo else value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {key: _json_safe(value) for key, value in record.items()}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(clean, ensure_ascii=True, sort_keys=True) + "\n")


def _parse_ts(value: Any) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return parsed


def _fmt_pct(value: Any) -> str:
    parsed = _pct_value(value)
    return "n/a" if parsed is None else f"{parsed:.1f}%"


def _fmt_number(value: Any) -> str:
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


def _holder_pct(holder_text: str, label: str) -> float | None:
    match = re.search(rf"{re.escape(label)}\s+([0-9]+(?:\.[0-9]+)?)%", holder_text or "", flags=re.IGNORECASE)
    return _safe_float(match.group(1)) if match else None


def _dedupe_tags(tags: Iterable[str]) -> str:
    output: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        clean = " ".join(str(tag or "").replace("\n", " ").split()).strip(" |,")
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(clean)
    return " | ".join(output[:10])


def _dedupe_tag_list(tags: Iterable[str]) -> list[str]:
    text = _dedupe_tags(tags)
    return [tag.strip() for tag in text.split("|") if tag.strip()]


def reason_tags(row: pd.Series | dict[str, Any]) -> str:
    note = _row_text(row, "trade_bucket_note")
    tags = [part.strip() for part in note.split("|") if part.strip()]
    short_pct = _pct_value(row.get("short_account_pct"))
    score = _first_float(row, "trade_bucket_score", "_discord_bucket_score")
    if score is not None and score >= 75:
        tags.insert(0, f"score {score:.0f}")
    if short_pct is not None and short_pct >= 55:
        tags.append(f"short accounts {short_pct:.1f}%")
    if _safe_float(row.get("top10_holder_pct")) is not None:
        tags.append(f"top10 holders {_safe_float(row.get('top10_holder_pct')):.1f}%")
    return _dedupe_tags(tags)


def reason_tag_list(row: pd.Series | dict[str, Any]) -> list[str]:
    note = _row_text(row, "trade_bucket_note")
    tags = [part.strip().lower().replace(" ", "_").replace("/", "_") for part in note.split("|") if part.strip()]
    short_pct = _pct_value(row.get("short_account_pct"))
    score = _first_float(row, "trade_bucket_score", "_discord_bucket_score")
    if score is not None and score >= 75:
        tags.insert(0, "high_scanner_score")
    if short_pct is not None and short_pct >= 55:
        tags.append("short_account_pressure")
    if _safe_float(row.get("top10_holder_pct")) is not None:
        tags.append("holder_concentration")
    return _dedupe_tag_list(tags)


def chain_concentration(row: pd.Series | dict[str, Any], holder_text: str = "") -> str:
    top1 = _holder_pct(holder_text, "Top1")
    top5 = _holder_pct(holder_text, "Top5")
    top10 = _holder_pct(holder_text, "Top10") or _safe_float(row.get("top10_holder_pct"))
    top100 = _holder_pct(holder_text, "Top100")
    holder_count = _safe_float(row.get("holder_count"))
    parts: list[str] = []
    if top1 is not None:
        parts.append(f"Top1 {top1:.1f}%")
    if top5 is not None:
        parts.append(f"Top5 {top5:.1f}%")
    if top10 is not None:
        parts.append(f"Top10 {top10:.1f}%")
    if top100 is not None:
        parts.append(f"Top100 {top100:.1f}%")
    if holder_count is not None:
        parts.append(f"holders {holder_count:.0f}")
    if not parts:
        owner = _safe_float(row.get("owner_holder_pct"))
        creator = _safe_float(row.get("creator_holder_pct"))
        if owner is not None:
            parts.append(f"owner {owner:.1f}%")
        if creator is not None:
            parts.append(f"creator {creator:.1f}%")
    return " | ".join(parts) if parts else "n/a"


def oi_volume_state(row: pd.Series | dict[str, Any]) -> str:
    parts = [
        f"short {_fmt_pct(row.get('short_account_pct'))}",
        f"OI change {_fmt_pct(_first_float(row, 'oi_delta_pct', 'oi_value_change_since_scan_pct'))}",
        f"24h vol {_fmt_number(row.get('quote_volume_24h'))}",
    ]
    return " | ".join(parts)


def _state_label(value: float | None, *, positive: str, negative: str, flat: str) -> str:
    if value is None:
        return "unknown"
    if value > 1.0:
        return positive
    if value < -1.0:
        return negative
    return flat


def _chain_url(row: pd.Series | dict[str, Any], holder_text: str = "") -> str:
    for key in ("chain_url", "explorer_url", "contract_url"):
        text = _row_text(row, key)
        if text:
            return text
    match = re.search(r"https?://\S+", holder_text or "")
    return match.group(0) if match else ""


def _flagged_price(row: pd.Series | dict[str, Any]) -> float | None:
    return _first_float(row, "last_price", "price", "mark_price")


def _alert_id(symbol: str, flagged_at_utc: str) -> str:
    raw = f"{symbol.upper()}|{flagged_at_utc}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _flag_jsonl_path(timestamp_utc: str) -> Path:
    parsed = _parse_ts(timestamp_utc) or pd.Timestamp.now(tz="UTC")
    return flags_archive_dir() / f"{parsed.strftime('%Y-%m-%d')}.jsonl"


def _outcome_jsonl_path(timestamp_utc: Any) -> Path:
    parsed = _parse_ts(timestamp_utc) or pd.Timestamp.now(tz="UTC")
    return outcomes_archive_dir() / f"{parsed.strftime('%Y-%m-%d')}_outcomes.jsonl"


def _flag_json_record(row: pd.Series | dict[str, Any], *, timestamp: str, scan_mode: str, holder_text: str, raw_output: str = "") -> dict[str, Any]:
    symbol = _row_text(row, "symbol").upper()
    alert_id = _alert_id(symbol, timestamp)
    top1 = _holder_pct(holder_text, "Top1")
    top5 = _holder_pct(holder_text, "Top5")
    top10 = _holder_pct(holder_text, "Top10") or _safe_float(row.get("top10_holder_pct"))
    top100 = _holder_pct(holder_text, "Top100")
    oi_change = _first_float(row, "oi_delta_pct", "oi_value_change_since_scan_pct")
    volume_change = _first_float(row, "hour_volume_multiple", "daily_quote_volume_multiple", "quote_volume_change_pct")
    return {
        "flag_id": f"{symbol}_{timestamp}",
        "alert_id": alert_id,
        "ticker": symbol,
        "symbol": symbol,
        "timestamp_utc": timestamp,
        "flagged_price": _flagged_price(row),
        "convex_score": _first_float(row, "trade_bucket_score", "_discord_bucket_score"),
        "scan_mode": str(scan_mode).lower(),
        "reason_tags": reason_tag_list(row),
        "holder_top1_pct": top1,
        "holder_top5_pct": top5,
        "holder_top10_pct": top10,
        "holder_top100_pct": top100,
        "chain_concentration": chain_concentration(row, holder_text),
        "short_account_pct": _pct_value(row.get("short_account_pct")),
        "long_account_pct": _pct_value(row.get("long_account_pct")),
        "oi_state": _state_label(oi_change, positive="rising", negative="falling", flat="flat"),
        "oi_change_pct": oi_change,
        "volume_state": _state_label(volume_change, positive="expanding", negative="contracting", flat="neutral"),
        "quote_volume_24h": _safe_float(row.get("quote_volume_24h")),
        "liquidity_risk_tags": [tag for tag in reason_tag_list(row) if "float" in tag or "liquid" in tag or "holder" in tag],
        "risk_level": _row_text(row, "risk_level") or "structural_review",
        "terminal_edge_score": _first_float(row, "terminal_edge_score"),
        "terminal_setup_archetype": _row_text(row, "terminal_setup_archetype"),
        "terminal_market_regime": _row_text(row, "terminal_market_regime"),
        "terminal_liquidity_reality": _row_text(row, "terminal_liquidity_reality"),
        "terminal_evidence_summary": _row_text(row, "terminal_evidence_summary"),
        "terminal_confirmation_needed": _row_text(row, "terminal_confirmation_needed"),
        "terminal_invalidation_map": _row_text(row, "terminal_invalidation_map"),
        "timing_score": _first_float(row, "timing_score"),
        "timing_state": _row_text(row, "timing_state"),
        "timing_observed_trigger": _row_text(row, "timing_observed_trigger"),
        "timing_confirmation_needed": _row_text(row, "timing_confirmation_needed"),
        "timing_invalidation": _row_text(row, "timing_invalidation"),
        "timing_too_late_score": _first_float(row, "timing_too_late_score"),
        "chain_url": _chain_url(row, holder_text),
        "raw_bot_output": raw_output,
        "disclaimer": "research_tooling_only",
    }


def load_archive(path: Path | None = None) -> pd.DataFrame:
    archive_path = path or proof_archive_path()
    if not archive_path.exists():
        return pd.DataFrame(columns=ARCHIVE_COLUMNS)
    try:
        frame = pd.read_csv(archive_path)
    except Exception:
        return pd.DataFrame(columns=ARCHIVE_COLUMNS)
    for column in ARCHIVE_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame.loc[:, ARCHIVE_COLUMNS].drop_duplicates(subset=["alert_id"], keep="last")


def save_archive(frame: pd.DataFrame, path: Path | None = None) -> None:
    archive_path = path or proof_archive_path()
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    output = frame.copy()
    for column in ARCHIVE_COLUMNS:
        if column not in output.columns:
            output[column] = pd.NA
    output = output.loc[:, ARCHIVE_COLUMNS].drop_duplicates(subset=["alert_id"], keep="last")
    output.to_csv(archive_path, index=False)


def archive_alerts(
    rows: pd.DataFrame,
    *,
    scan_mode: str,
    path: Path | None = None,
    flagged_at_utc: str | None = None,
) -> pd.DataFrame:
    if rows.empty:
        return load_archive(path)
    archive = load_archive(path)
    timestamp = flagged_at_utc or _now_iso()
    records: list[dict[str, Any]] = []
    for _, row in rows.iterrows():
        symbol = _row_text(row, "symbol").upper()
        price = _flagged_price(row)
        if not symbol or price is None or price <= 0:
            continue
        holder_text = _row_text(row, "_holder_text") or _row_text(row, "holder_text")
        raw_output = _row_text(row, "_raw_bot_output") or _row_text(row, "raw_bot_output")
        record = {
            "alert_id": _alert_id(symbol, timestamp),
            "symbol": symbol,
            "flagged_at_utc": timestamp,
            "flagged_price": price,
            "convex_score": _first_float(row, "trade_bucket_score", "_discord_bucket_score"),
            "reason_tags": reason_tags(row),
            "chain_concentration": chain_concentration(row, holder_text),
            "oi_volume_state": oi_volume_state(row),
            "scan_mode": scan_mode,
            "short_account_pct": _pct_value(row.get("short_account_pct")),
            "long_account_pct": _pct_value(row.get("long_account_pct")),
            "oi_delta_pct": _first_float(row, "oi_delta_pct", "oi_value_change_since_scan_pct"),
            "quote_volume_24h": _safe_float(row.get("quote_volume_24h")),
            "trade_bucket_note": _row_text(row, "trade_bucket_note"),
            "holder_text": holder_text,
            "terminal_edge_score": _first_float(row, "terminal_edge_score"),
            "terminal_setup_archetype": _row_text(row, "terminal_setup_archetype"),
            "terminal_market_regime": _row_text(row, "terminal_market_regime"),
            "terminal_liquidity_reality": _row_text(row, "terminal_liquidity_reality"),
            "terminal_evidence_summary": _row_text(row, "terminal_evidence_summary"),
            "terminal_confirmation_needed": _row_text(row, "terminal_confirmation_needed"),
            "terminal_invalidation_map": _row_text(row, "terminal_invalidation_map"),
            "timing_score": _first_float(row, "timing_score"),
            "timing_state": _row_text(row, "timing_state"),
            "timing_observed_trigger": _row_text(row, "timing_observed_trigger"),
            "timing_confirmation_needed": _row_text(row, "timing_confirmation_needed"),
            "timing_invalidation": _row_text(row, "timing_invalidation"),
            "timing_too_late_score": _first_float(row, "timing_too_late_score"),
        }
        records.append(record)
        _append_jsonl(_flag_jsonl_path(timestamp), _flag_json_record(row, timestamp=timestamp, scan_mode=scan_mode, holder_text=holder_text, raw_output=raw_output))
    if not records:
        return archive
    record_frame = pd.DataFrame(records)
    updated = record_frame if archive.empty else pd.concat([archive, record_frame], ignore_index=True)
    save_archive(updated, path)
    return load_archive(path)


def _kline_rows(
    client: BinanceFuturesPublic,
    symbol: str,
    *,
    start_ms: int,
    end_ms: int,
    interval: str = "1m",
) -> list[list[Any]]:
    rows: list[list[Any]] = []
    cursor = start_ms
    minute_ms = 60_000
    while cursor <= end_ms:
        batch = client.klines(symbol, interval=interval, limit=1500, start_time=cursor, end_time=end_ms)
        if not batch:
            break
        rows.extend(batch)
        last_open = int(batch[-1][0])
        next_cursor = last_open + minute_ms
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(batch) < 1500:
            break
    return rows


def _compute_outcome(row: pd.Series, klines: list[list[Any]], *, now: pd.Timestamp) -> dict[str, Any]:
    flagged_price = _safe_float(row.get("flagged_price"))
    flagged_at = _parse_ts(row.get("flagged_at_utc"))
    if flagged_price is None or flagged_price <= 0 or flagged_at is None or not klines:
        return {}

    data = pd.DataFrame(
        [
            {
                "open_time": pd.to_datetime(int(item[0]), unit="ms", utc=True),
                "high": _safe_float(item[2]),
                "low": _safe_float(item[3]),
            }
            for item in klines
        ]
    )
    data = data[data["open_time"].gt(flagged_at) & data["high"].notna() & data["low"].notna()].copy()
    if data.empty:
        return {}

    outcome: dict[str, Any] = {"outcome_updated_at_utc": pd.Timestamp.now(tz="UTC")}
    for label, hours in HORIZONS.items():
        cutoff = flagged_at + pd.Timedelta(hours=hours)
        subset = data[data["open_time"].le(min(cutoff, now))]
        if subset.empty:
            outcome[f"max_upside_{label}_pct"] = pd.NA
            continue
        max_high = float(subset["high"].max())
        outcome[f"max_upside_{label}_pct"] = (max_high / flagged_price - 1.0) * 100.0

    min_low = float(data["low"].min())
    max_drawdown = (min_low / flagged_price - 1.0) * 100.0
    outcome["max_drawdown_pct"] = max_drawdown
    for threshold, column in ((20.0, "time_to_20pct_minutes"), (50.0, "time_to_50pct_minutes"), (100.0, "time_to_2x_minutes")):
        target = flagged_price * (1.0 + threshold / 100.0)
        hits = data[data["high"].ge(target)]
        if hits.empty:
            outcome[column] = pd.NA
        else:
            hit_time = hits.iloc[0]["open_time"]
            outcome[column] = max(0.0, (hit_time - flagged_at).total_seconds() / 60.0)

    age_hours = max(0.0, (now - flagged_at).total_seconds() / 3600.0)
    hit_20 = pd.notna(outcome.get("time_to_20pct_minutes"))
    outcome["structure_invalidated"] = bool(max_drawdown <= -10.0 or (age_hours >= 24.0 and not hit_20))
    return outcome


def refresh_outcomes(
    *,
    path: Path | None = None,
    client: BinanceFuturesPublic | None = None,
    max_rows: int = 25,
    now: pd.Timestamp | None = None,
) -> pd.DataFrame:
    archive = load_archive(path)
    if archive.empty:
        return archive
    current_time = now or pd.Timestamp.now(tz="UTC")
    client = client or BinanceFuturesPublic(timeout=10, requests_per_second=4)
    archive = archive.copy()
    archive["flagged_at_utc"] = pd.to_datetime(archive["flagged_at_utc"], errors="coerce", utc=True)
    archive["outcome_updated_at_utc"] = pd.to_datetime(archive["outcome_updated_at_utc"], errors="coerce", utc=True)
    archive["flagged_price"] = pd.to_numeric(archive["flagged_price"], errors="coerce")
    archive["structure_invalidated"] = archive["structure_invalidated"].astype("object")
    eligible = archive[
        archive["flagged_at_utc"].notna()
        & archive["flagged_price"].gt(0)
        & archive["symbol"].astype(str).ne("")
    ].copy()
    if eligible.empty:
        save_archive(archive, path)
        return load_archive(path)
    eligible["_update_rank"] = eligible["outcome_updated_at_utc"].fillna(pd.Timestamp("1970-01-01", tz="UTC"))
    eligible = eligible.sort_values(["_update_rank", "flagged_at_utc"]).head(max(1, int(max_rows)))

    for index, row in eligible.iterrows():
        flagged_at = row["flagged_at_utc"]
        if pd.isna(flagged_at):
            continue
        end_time = min(flagged_at + pd.Timedelta(days=7), current_time)
        if end_time <= flagged_at:
            continue
        start_ms = int(flagged_at.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)
        try:
            klines = _kline_rows(client, str(row["symbol"]).upper(), start_ms=start_ms, end_ms=end_ms)
            outcome = _compute_outcome(row, klines, now=current_time)
        except Exception:
            continue
        for key, value in outcome.items():
            archive.loc[index, key] = value
        if outcome:
            outcome_record = {
                "flag_id": f"{str(row['symbol']).upper()}_{row['flagged_at_utc'].strftime('%Y-%m-%dT%H:%M:%SZ')}",
                "alert_id": row.get("alert_id"),
                "ticker": str(row["symbol"]).upper(),
                "timestamp_utc": row["flagged_at_utc"],
                "flagged_price": row.get("flagged_price"),
                "calculated_at_utc": pd.Timestamp.now(tz="UTC"),
                "volume_oi_confirmed": bool(
                    (_safe_float(row.get("oi_delta_pct")) or 0.0) > 0.0
                    and (_safe_float(row.get("quote_volume_24h")) or 0.0) > 0.0
                ),
                "structure_confirmed": pd.notna(outcome.get("time_to_20pct_minutes")),
            }
            outcome_record.update(outcome)
            _append_jsonl(_outcome_jsonl_path(row["flagged_at_utc"]), outcome_record)
    save_archive(archive, path)
    return load_archive(path)


def _hit_rate(frame: pd.DataFrame, column: str) -> str:
    if frame.empty or column not in frame.columns:
        return "n/a"
    hits = pd.to_numeric(frame[column], errors="coerce").notna()
    return f"{hits.mean() * 100:.1f}%"


def _symbol_for_extreme(frame: pd.DataFrame, column: str, *, ascending: bool = False) -> str:
    if frame.empty or column not in frame.columns:
        return "n/a"
    values = pd.to_numeric(frame[column], errors="coerce")
    valid = frame[values.notna()].copy()
    if valid.empty:
        return "n/a"
    values = pd.to_numeric(valid[column], errors="coerce")
    idx = values.idxmin() if ascending else values.idxmax()
    row = valid.loc[idx]
    value = _safe_float(row.get(column))
    return f"{row.get('symbol', 'UNKNOWN')} ({value:.1f}%)" if value is not None else str(row.get("symbol", "UNKNOWN"))


def weekly_scoreboard_text(path: Path | None = None, *, now: pd.Timestamp | None = None) -> str:
    archive = load_archive(path)
    if archive.empty:
        return "No archived scanner flags yet."
    current_time = now or pd.Timestamp.now(tz="UTC")
    archive["flagged_at_utc"] = pd.to_datetime(archive["flagged_at_utc"], errors="coerce", utc=True)
    recent = archive[archive["flagged_at_utc"].ge(current_time - pd.Timedelta(days=7))].copy()
    if recent.empty:
        return "No archived scanner flags in the last 7 days."
    drawdowns = pd.to_numeric(recent["max_drawdown_pct"], errors="coerce")
    median_adverse = drawdowns.median()
    invalidated = recent["structure_invalidated"].astype(str).str.lower().isin({"true", "1", "yes"}).mean() * 100
    lines = [
        "Proof scoreboard - trailing 7 days",
        f"Total archived flags: {len(recent)}",
        f"Hit rate to +20%: {_hit_rate(recent, 'time_to_20pct_minutes')}",
        f"Hit rate to +50%: {_hit_rate(recent, 'time_to_50pct_minutes')}",
        f"Hit rate to 2x: {_hit_rate(recent, 'time_to_2x_minutes')}",
        f"Median adverse excursion: {median_adverse:.1f}%" if pd.notna(median_adverse) else "Median adverse excursion: n/a",
        f"Invalidated structure rate: {invalidated:.1f}%",
        f"Best outlier: {_symbol_for_extreme(recent, 'max_upside_7d_pct')}",
        f"Worst failed flag: {_symbol_for_extreme(recent, 'max_drawdown_pct', ascending=True)}",
        "Research tooling only. Structural-risk screen, not trade instruction.",
    ]
    return "\n".join(lines)


def write_weekly_report(path: Path | None = None, *, now: pd.Timestamp | None = None) -> tuple[Path | None, Path | None]:
    archive = load_archive(path)
    if archive.empty:
        return None, None
    current_time = now or pd.Timestamp.now(tz="UTC")
    archive["flagged_at_utc"] = pd.to_datetime(archive["flagged_at_utc"], errors="coerce", utc=True)
    recent = archive[archive["flagged_at_utc"].ge(current_time - pd.Timedelta(days=7))].copy()
    if recent.empty:
        return None, None
    iso = current_time.isocalendar()
    stem = f"weekly_{iso.year}-W{int(iso.week):02d}"
    report_dir = reports_archive_dir()
    report_dir.mkdir(parents=True, exist_ok=True)
    csv_path = report_dir / f"{stem}.csv"
    md_path = report_dir / f"{stem}.md"
    recent.to_csv(csv_path, index=False)
    scoreboard = weekly_scoreboard_text(path, now=current_time)
    top = recent.copy()
    top["max_upside_7d_pct"] = pd.to_numeric(top["max_upside_7d_pct"], errors="coerce")
    top = top.sort_values(["max_upside_7d_pct", "convex_score"], ascending=[False, False]).head(20)
    rows = ["| Symbol | Score | Max upside 7d | Max drawdown | Tags |", "|---|---:|---:|---:|---|"]
    for _, row in top.iterrows():
        rows.append(
            f"| {row.get('symbol', '')} | {_fmt_number(row.get('convex_score'))} | "
            f"{_fmt_pct(row.get('max_upside_7d_pct'))} | {_fmt_pct(row.get('max_drawdown_pct'))} | "
            f"{str(row.get('reason_tags', '')).replace('|', ',')} |"
        )
    md_path.write_text(
        "# Weekly proof report\n\n"
        f"Generated: {_now_iso()}\n\n"
        "Research tooling only. Structural-risk screen, not trade instruction.\n\n"
        "```text\n"
        f"{scoreboard}\n"
        "```\n\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )
    return md_path, csv_path
