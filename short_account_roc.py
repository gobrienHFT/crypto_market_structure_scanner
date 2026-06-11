from __future__ import annotations

import argparse
import csv
import json
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from binance_futures import BinanceHTTPError, BinanceFuturesPublic, FuturesSymbol
from discord_flag_formatter import DISCORD_FOOTER, DISCORD_PRODUCT_IDENTITY


APP_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = APP_DIR / "short_account_roc_output"


@dataclass(frozen=True)
class ShortAccountRocConfig:
    base_url: str
    timeout: int
    retries: int
    requests_per_second: float
    interval_seconds: float
    max_symbols: int
    symbols: tuple[str, ...]
    period: str
    history_limit: int
    min_abs_pp: float
    min_abs_pct: float
    min_quote_volume: float
    top_n: int
    realert_hours: float
    output_dir: Path
    webhook_url: str
    once: bool
    dry_run: bool
    write_full_scan: bool
    suppress_initial_alerts: bool


def _load_local_env() -> None:
    env_path = APP_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env_value(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_bool(name: str, default: bool = False) -> bool:
    fallback = "1" if default else "0"
    return _env_value(name, fallback).strip().lower() in {"1", "true", "yes", "on"}


def _to_float(value: Any) -> float:
    try:
        parsed = float(value)
    except Exception:
        return float("nan")
    return parsed if math.isfinite(parsed) else float("nan")


def _share_to_pct(value: Any) -> float:
    parsed = _to_float(value)
    if not math.isfinite(parsed):
        return float("nan")
    return parsed * 100.0 if abs(parsed) <= 1.0 else parsed


def _pct_change(current: Any, previous: Any) -> float:
    current_f = _to_float(current)
    previous_f = _to_float(previous)
    if not math.isfinite(current_f) or not math.isfinite(previous_f) or abs(previous_f) < 1e-12:
        return float("nan")
    return (current_f / previous_f - 1.0) * 100.0


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_label() -> str:
    return _now_utc().strftime("%Y-%m-%d %H:%M:%S UTC")


def _row_timestamp(row: dict[str, Any]) -> int:
    for key in ("timestamp", "time"):
        value = row.get(key)
        parsed = _to_float(value)
        if math.isfinite(parsed):
            return int(parsed)
    return 0


def short_account_history_stats(rows: list[dict[str, Any]], *, windows: tuple[int, ...] = (1, 3, 6, 12, 24)) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "short_account_history_points": 0,
        "short_account_current_pct": float("nan"),
        "short_account_previous_1h_pct": float("nan"),
        "short_account_roc_1h_pct": float("nan"),
        "short_account_roc_1h_pp": float("nan"),
        "short_account_roc_1h_abs_pp": float("nan"),
        "short_account_roc_1h_direction": "",
        "short_account_change_max_pct": float("nan"),
        "short_account_change_max_pp": float("nan"),
        "short_account_change_max_window": "",
        "short_account_change_min_pct": float("nan"),
        "short_account_change_min_pp": float("nan"),
        "short_account_change_min_window": "",
    }
    sorted_rows = sorted([row for row in rows if isinstance(row, dict)], key=_row_timestamp)
    short_values = [_share_to_pct(row.get("shortAccount")) for row in sorted_rows]
    short_values = [value for value in short_values if math.isfinite(value)]
    stats["short_account_history_points"] = len(short_values)
    if not short_values:
        return stats

    current = short_values[-1]
    stats["short_account_current_pct"] = current
    pct_changes: dict[int, float] = {}
    pp_changes: dict[int, float] = {}
    for window in windows:
        pct_key = f"short_account_change_{window}p_pct"
        pp_key = f"short_account_change_{window}p_pp"
        if len(short_values) <= window:
            stats[pct_key] = float("nan")
            stats[pp_key] = float("nan")
            continue
        previous = short_values[-1 - window]
        pp_change = current - previous
        pct_delta = _pct_change(current, previous)
        stats[pct_key] = pct_delta
        stats[pp_key] = pp_change
        pct_changes[window] = pct_delta
        pp_changes[window] = pp_change
        if window == 1:
            stats["short_account_previous_1h_pct"] = previous
            stats["short_account_roc_1h_pct"] = pct_delta
            stats["short_account_roc_1h_pp"] = pp_change
            stats["short_account_roc_1h_abs_pp"] = abs(pp_change) if math.isfinite(pp_change) else float("nan")
            if math.isfinite(pp_change):
                stats["short_account_roc_1h_direction"] = "build" if pp_change > 0 else "cover" if pp_change < 0 else "flat"

    valid_pct_changes = {window: value for window, value in pct_changes.items() if math.isfinite(value)}
    valid_pp_changes = {window: value for window, value in pp_changes.items() if math.isfinite(value)}
    if valid_pct_changes:
        max_window = max(valid_pct_changes, key=valid_pct_changes.get)
        min_window = min(valid_pct_changes, key=valid_pct_changes.get)
        stats["short_account_change_max_pct"] = valid_pct_changes[max_window]
        stats["short_account_change_max_window"] = f"{max_window}p"
        stats["short_account_change_min_pct"] = valid_pct_changes[min_window]
        stats["short_account_change_min_window"] = f"{min_window}p"
    if valid_pp_changes:
        max_pp_window = max(valid_pp_changes, key=valid_pp_changes.get)
        min_pp_window = min(valid_pp_changes, key=valid_pp_changes.get)
        stats["short_account_change_max_pp"] = valid_pp_changes[max_pp_window]
        stats["short_account_change_min_pp"] = valid_pp_changes[min_pp_window]
        if not stats["short_account_change_max_window"]:
            stats["short_account_change_max_window"] = f"{max_pp_window}p"
        if not stats["short_account_change_min_window"]:
            stats["short_account_change_min_window"] = f"{min_pp_window}p"
    return stats


def build_short_account_roc_row(
    *,
    futures_symbol: FuturesSymbol,
    ratio_rows: list[dict[str, Any]],
    ticker: dict[str, Any] | None = None,
    scanned_at: datetime | None = None,
) -> dict[str, Any]:
    ticker = ticker or {}
    scanned_at = scanned_at or _now_utc()
    latest = ratio_rows[-1] if ratio_rows else {}
    stats = short_account_history_stats(ratio_rows, windows=(1,))
    return {
        "scanned_at": scanned_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "symbol": futures_symbol.symbol,
        "base_asset": futures_symbol.base_asset,
        "market_type": futures_symbol.underlying_type or "CRYPTO",
        "last_price": _to_float(ticker.get("lastPrice")),
        "quote_volume_24h": _to_float(ticker.get("quoteVolume")),
        "long_short_account_ratio": _to_float(latest.get("longShortRatio")),
        "long_account_pct": _share_to_pct(latest.get("longAccount")),
        "short_account_pct": _share_to_pct(latest.get("shortAccount")),
        "short_account_previous_1h_pct": _to_float(stats.get("short_account_previous_1h_pct")),
        "short_account_roc_1h_pct": _to_float(stats.get("short_account_roc_1h_pct")),
        "short_account_roc_1h_pp": _to_float(stats.get("short_account_roc_1h_pp")),
        "short_account_roc_1h_abs_pp": _to_float(stats.get("short_account_roc_1h_abs_pp")),
        "short_account_roc_1h_direction": str(stats.get("short_account_roc_1h_direction", "") or ""),
        "short_account_history_points": int(stats.get("short_account_history_points", 0) or 0),
    }


def _ticker_lookup(client: BinanceFuturesPublic) -> dict[str, dict[str, Any]]:
    return {str(row.get("symbol", "")).upper(): row for row in client.ticker_24hr() if row.get("symbol")}


def _selected_symbols(
    universe: list[FuturesSymbol],
    *,
    symbols: tuple[str, ...] = (),
    max_symbols: int = 0,
) -> list[FuturesSymbol]:
    requested = {symbol.upper().strip() for symbol in symbols if symbol.strip()}
    if requested:
        selected = [item for item in universe if item.symbol.upper() in requested]
    else:
        selected = list(universe)
    if max_symbols > 0:
        selected = selected[:max_symbols]
    return selected


def scan_short_account_roc(
    client: BinanceFuturesPublic,
    *,
    symbols: tuple[str, ...] = (),
    max_symbols: int = 0,
    period: str = "1h",
    history_limit: int = 2,
    min_quote_volume: float = 0.0,
) -> tuple[pd.DataFrame, list[str]]:
    universe = client.perpetual_usdt_symbols()
    tickers = _ticker_lookup(client)
    selected = _selected_symbols(universe, symbols=symbols, max_symbols=max_symbols)
    scanned_at = _now_utc()
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, futures_symbol in enumerate(selected, start=1):
        ticker = tickers.get(futures_symbol.symbol, {})
        quote_volume = _to_float(ticker.get("quoteVolume"))
        if min_quote_volume > 0 and (not math.isfinite(quote_volume) or quote_volume < min_quote_volume):
            continue
        try:
            ratio_rows = client.global_long_short_account_ratio(
                futures_symbol.symbol,
                period=period,
                limit=max(2, int(history_limit)),
            )
            rows.append(
                build_short_account_roc_row(
                    futures_symbol=futures_symbol,
                    ratio_rows=ratio_rows,
                    ticker=ticker,
                    scanned_at=scanned_at,
                )
            )
        except (BinanceHTTPError, requests.RequestException, RuntimeError, ValueError) as exc:
            errors.append(f"{futures_symbol.symbol}: {exc}")
        print(f"[{_now_label()}] scanned {index}/{len(selected)} {futures_symbol.symbol}", flush=True)

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame, errors
    frame = frame[pd.to_numeric(frame["short_account_history_points"], errors="coerce").fillna(0) >= 2].copy()
    if frame.empty:
        return frame, errors
    return frame.sort_values(["short_account_roc_1h_abs_pp", "quote_volume_24h", "symbol"], ascending=[False, False, True]).reset_index(drop=True), errors


def flagged_frame(frame: pd.DataFrame, *, min_abs_pp: float = 1.5, min_abs_pct: float = 3.0, top_n: int = 25) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    rows = frame.copy()
    pp = pd.to_numeric(rows.get("short_account_roc_1h_abs_pp"), errors="coerce").fillna(0.0)
    pct = pd.to_numeric(rows.get("short_account_roc_1h_pct"), errors="coerce").abs().fillna(0.0)
    flagged = rows[(pp >= float(min_abs_pp)) | (pct >= float(min_abs_pct))].copy()
    if flagged.empty:
        return flagged
    flagged["_short_roc_sort_abs_pct"] = pct.loc[flagged.index]
    flagged = flagged.sort_values(
        ["short_account_roc_1h_abs_pp", "_short_roc_sort_abs_pct", "quote_volume_24h", "symbol"],
        ascending=[False, False, False, True],
    ).drop(columns=["_short_roc_sort_abs_pct"], errors="ignore")
    return flagged.head(max(1, int(top_n))).copy()


def active_signal_keys(frame: pd.DataFrame, *, min_abs_pp: float = 1.5, min_abs_pct: float = 3.0) -> set[str]:
    flagged = flagged_frame(frame, min_abs_pp=min_abs_pp, min_abs_pct=min_abs_pct, top_n=max(1, len(frame)))
    keys: set[str] = set()
    for row in flagged.to_dict("records"):
        symbol = str(row.get("symbol", "")).upper().strip()
        direction = str(row.get("short_account_roc_1h_direction", "") or "move").lower()
        if symbol:
            keys.add(f"{symbol}:{direction}")
    return keys


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"active_signals": [], "last_alerted": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"active_signals": [], "last_alerted": {}}
    return payload if isinstance(payload, dict) else {"active_signals": [], "last_alerted": {}}


def _write_state(path: Path, active_signals: set[str], last_alerted: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "updated_at": _now_label(),
                "active_signals": sorted(active_signals),
                "last_alerted": last_alerted,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _new_alert_keys(active_signals: set[str], previous_signals: set[str], last_alerted: dict[str, str], *, realert_hours: float) -> set[str]:
    now = _now_utc()
    output: set[str] = set()
    for key in active_signals:
        if key not in previous_signals:
            output.add(key)
            continue
        last_at = _parse_timestamp(str(last_alerted.get(key, "")))
        if last_at is None:
            continue
        age_hours = (now - last_at).total_seconds() / 3600.0
        if age_hours >= max(0.0, float(realert_hours)):
            output.add(key)
    return output


def _append_alerts(path: Path, rows: pd.DataFrame) -> None:
    if rows.empty:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists()
    fieldnames = [
        "timestamp_utc",
        "symbol",
        "direction",
        "short_account_pct",
        "short_account_previous_1h_pct",
        "short_account_roc_1h_pp",
        "short_account_roc_1h_pct",
        "quote_volume_24h",
    ]
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for row in rows.to_dict("records"):
            writer.writerow(
                {
                    "timestamp_utc": _now_label(),
                    "symbol": str(row.get("symbol", "")).upper(),
                    "direction": row.get("short_account_roc_1h_direction", ""),
                    "short_account_pct": row.get("short_account_pct", ""),
                    "short_account_previous_1h_pct": row.get("short_account_previous_1h_pct", ""),
                    "short_account_roc_1h_pp": row.get("short_account_roc_1h_pp", ""),
                    "short_account_roc_1h_pct": row.get("short_account_roc_1h_pct", ""),
                    "quote_volume_24h": row.get("quote_volume_24h", ""),
                }
            )


def _format_number(value: Any, suffix: str = "") -> str:
    parsed = _to_float(value)
    if not math.isfinite(parsed):
        return "n/a"
    return f"{parsed:.2f}{suffix}"


def _format_alert_line(row: pd.Series) -> str:
    symbol = str(row.get("symbol", "")).upper().strip()
    direction = str(row.get("short_account_roc_1h_direction", "") or "move")
    arrow = "UP" if direction == "build" else "DOWN" if direction == "cover" else "FLAT"
    return (
        f"/{symbol} | {arrow} {direction} | short {_format_number(row.get('short_account_previous_1h_pct'), '%')} -> "
        f"{_format_number(row.get('short_account_pct'), '%')} | "
        f"delta {_format_number(row.get('short_account_roc_1h_pp'), 'pp')} / {_format_number(row.get('short_account_roc_1h_pct'), '%')} | "
        f"vol24 ${_format_number(row.get('quote_volume_24h'))}"
    )


def _post_webhook(rows: pd.DataFrame, config: ShortAccountRocConfig) -> None:
    if rows.empty:
        return
    lines = [_format_alert_line(row) for _, row in rows.iterrows()]
    description = (
        f"{DISCORD_PRODUCT_IDENTITY}\n\n"
        f"Short-account 1h ROC monitor\n"
        f"Threshold: abs delta >= {config.min_abs_pp:.2f}pp or abs relative >= {config.min_abs_pct:.2f}% | "
        f"Period: {config.period} | Detected: {_now_label()}\n\n"
        + "\n".join(lines[:25])
    )
    payload = {
        "username": "Short ROC Scanner",
        "embeds": [
            {
                "title": f"Short-account 1h ROC alert ({len(rows)})",
                "description": description[:3900],
                "color": 0xF97316,
                "footer": {"text": DISCORD_FOOTER},
            }
        ],
    }
    if config.dry_run:
        print("DRY RUN webhook payload:")
        print(payload)
        return
    if not config.webhook_url:
        raise RuntimeError("SHORT_ROC_DISCORD_WEBHOOK_URL or DISCORD_WEBHOOK_URL is not set.")
    response = requests.post(config.webhook_url, json=payload, timeout=15)
    if response.status_code >= 300:
        raise RuntimeError(f"Discord webhook HTTP {response.status_code}: {response.text[:250]}")


def _write_outputs(frame: pd.DataFrame, flagged: pd.DataFrame, errors: list[str], config: ShortAccountRocConfig) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    flagged.to_csv(config.output_dir / "short_account_roc_flags_latest.csv", index=False)
    if config.write_full_scan:
        frame.to_csv(config.output_dir / "short_account_roc_full_scan_latest.csv", index=False)
    error_path = config.output_dir / "short_account_roc_errors_latest.txt"
    if errors:
        error_path.write_text("\n".join(errors), encoding="utf-8")
    elif error_path.exists():
        error_path.unlink()


def run_once(config: ShortAccountRocConfig) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    client = BinanceFuturesPublic(
        base_url=config.base_url,
        timeout=config.timeout,
        requests_per_second=config.requests_per_second,
        retries=config.retries,
    )
    frame, errors = scan_short_account_roc(
        client,
        symbols=config.symbols,
        max_symbols=config.max_symbols,
        period=config.period,
        history_limit=config.history_limit,
        min_quote_volume=config.min_quote_volume,
    )
    flagged = flagged_frame(frame, min_abs_pp=config.min_abs_pp, min_abs_pct=config.min_abs_pct, top_n=config.top_n)
    _write_outputs(frame, flagged, errors, config)
    print(
        f"[{_now_label()}] scan complete: rows={len(frame)} flagged={len(flagged)} errors={len(errors)}",
        flush=True,
    )
    if not flagged.empty:
        print(flagged[["symbol", "short_account_pct", "short_account_roc_1h_pp", "short_account_roc_1h_pct"]].to_string(index=False), flush=True)
    return frame, flagged, errors


def run_forever(config: ShortAccountRocConfig) -> None:
    state_path = config.output_dir / "short_account_roc_state.json"
    alert_path = config.output_dir / "short_account_roc_alerts.csv"
    state = _load_state(state_path)
    previous_signals = {str(item) for item in state.get("active_signals", [])}
    last_alerted = {str(key): str(value) for key, value in dict(state.get("last_alerted", {})).items()}
    first_cycle = True

    while True:
        try:
            frame, flagged, _ = run_once(config)
            active = active_signal_keys(frame, min_abs_pp=config.min_abs_pp, min_abs_pct=config.min_abs_pct)
            alert_keys = _new_alert_keys(active, previous_signals, last_alerted, realert_hours=config.realert_hours)
            if first_cycle and config.suppress_initial_alerts:
                alert_keys = set()
            alert_rows = flagged[
                flagged.apply(
                    lambda row: f"{str(row.get('symbol', '')).upper().strip()}:{str(row.get('short_account_roc_1h_direction', '') or 'move').lower()}" in alert_keys,
                    axis=1,
                )
            ].copy()
            if not alert_rows.empty:
                _post_webhook(alert_rows, config)
                _append_alerts(alert_path, alert_rows)
                now = _now_label()
                for key in alert_keys:
                    last_alerted[key] = now
            _write_state(state_path, active, last_alerted)
            previous_signals = active
            first_cycle = False
        except KeyboardInterrupt:
            print(f"[{_now_label()}] stopped by user", flush=True)
            return
        except Exception as exc:
            print(f"[{_now_label()}] monitor cycle failed: {exc}", flush=True)
        if config.once:
            return
        time.sleep(max(5.0, float(config.interval_seconds)))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="24/7 Binance short-account 1h rate-of-change Discord monitor.")
    parser.add_argument("--once", action="store_true", help="Run one scan cycle and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Print webhook payload instead of posting.")
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=float(_env_value("SHORT_ROC_INTERVAL_SECONDS", "300")),
        help="Seconds to sleep between scan cycles.",
    )
    parser.add_argument("--max-symbols", type=int, default=int(_env_value("SHORT_ROC_MAX_SYMBOLS", "0")), help="Optional cap for smoke testing. 0 scans every USDT perp.")
    parser.add_argument("--symbols", default=_env_value("SHORT_ROC_SYMBOLS", ""), help="Comma-separated symbols to scan. Empty scans all.")
    parser.add_argument("--period", default=_env_value("SHORT_ROC_PERIOD", "1h"), help="Binance long/short account ratio period. Default 1h.")
    parser.add_argument("--history-limit", type=int, default=int(_env_value("SHORT_ROC_HISTORY_LIMIT", "2")), help="Ratio rows per symbol. 2 is enough for 1h ROC.")
    parser.add_argument("--min-abs-pp", type=float, default=float(_env_value("SHORT_ROC_MIN_ABS_PP", "1.5")), help="Alert when 1h short-account share moves by at least this many percentage points.")
    parser.add_argument("--min-abs-pct", type=float, default=float(_env_value("SHORT_ROC_MIN_ABS_PCT", "3.0")), help="Alert when 1h relative short-account change exceeds this percent.")
    parser.add_argument("--min-quote-volume", type=float, default=float(_env_value("SHORT_ROC_MIN_QUOTE_VOLUME", "0")), help="Optional 24h quote-volume floor.")
    parser.add_argument("--top-n", type=int, default=int(_env_value("SHORT_ROC_TOP_N", "25")), help="Maximum alert rows per cycle.")
    parser.add_argument("--realert-hours", type=float, default=float(_env_value("SHORT_ROC_REALERT_HOURS", "6")), help="Re-alert active signals after this many hours.")
    parser.add_argument("--requests-per-second", type=float, default=float(_env_value("SHORT_ROC_REQUESTS_PER_SECOND", "2")), help="Public request pace for Binance.")
    parser.add_argument("--timeout", type=int, default=int(_env_value("SHORT_ROC_HTTP_TIMEOUT", "12")), help="HTTP timeout in seconds.")
    parser.add_argument("--retries", type=int, default=int(_env_value("SHORT_ROC_HTTP_RETRIES", "3")), help="HTTP retry attempts.")
    parser.add_argument("--base-url", default=_env_value("BINANCE_FAPI_BASE_URL", "https://fapi.binance.com"), help="Binance futures API base URL.")
    parser.add_argument("--output-dir", default=_env_value("SHORT_ROC_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)), help="Directory for latest CSV snapshots and alert state.")
    parser.add_argument("--write-full-scan", action="store_true", default=_env_bool("SHORT_ROC_WRITE_FULL_SCAN", True), help="Write the full latest scan CSV.")
    parser.add_argument("--suppress-initial-alerts", action="store_true", default=_env_bool("SHORT_ROC_SUPPRESS_INITIAL_ALERTS", False), help="Do not alert all currently-active rows on first cycle.")
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> ShortAccountRocConfig:
    symbols = tuple(symbol.strip().upper() for symbol in str(args.symbols).split(",") if symbol.strip())
    return ShortAccountRocConfig(
        base_url=str(args.base_url),
        timeout=int(args.timeout),
        retries=int(args.retries),
        requests_per_second=float(args.requests_per_second),
        interval_seconds=float(args.interval_seconds),
        max_symbols=int(args.max_symbols),
        symbols=symbols,
        period=str(args.period),
        history_limit=max(2, int(args.history_limit)),
        min_abs_pp=max(0.0, float(args.min_abs_pp)),
        min_abs_pct=max(0.0, float(args.min_abs_pct)),
        min_quote_volume=max(0.0, float(args.min_quote_volume)),
        top_n=max(1, int(args.top_n)),
        realert_hours=max(0.0, float(args.realert_hours)),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        webhook_url=_env_value("SHORT_ROC_DISCORD_WEBHOOK_URL", _env_value("DISCORD_WEBHOOK_URL", "")),
        once=bool(args.once),
        dry_run=bool(args.dry_run),
        write_full_scan=bool(args.write_full_scan),
        suppress_initial_alerts=bool(args.suppress_initial_alerts),
    )


def main(argv: list[str] | None = None) -> None:
    _load_local_env()
    config = config_from_args(parse_args(argv))
    print(
        f"[{_now_label()}] starting short-account ROC monitor | period={config.period} "
        f"threshold={config.min_abs_pp:.2f}pp/{config.min_abs_pct:.2f}% interval={config.interval_seconds:.0f}s",
        flush=True,
    )
    if config.once:
        run_once(config)
    else:
        run_forever(config)


if __name__ == "__main__":
    main()
