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
from discord_flag_formatter import DISCORD_EMBED_DESCRIPTION_LIMIT, DISCORD_FOOTER, DISCORD_PRODUCT_IDENTITY

APP_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = APP_DIR / "breakout_monitor_output"
BREAKOUT_WINDOWS = (5, 10, 20, 50, 90, 180, 1300)
MA_WINDOW = 200
KLINE_LIMIT = max(max(BREAKOUT_WINDOWS), MA_WINDOW) + 1
MAX_DISCORD_ALERT_LINES = 25


@dataclass(frozen=True)
class MonitorConfig:
    base_url: str
    timeout: int
    retries: int
    requests_per_second: float
    interval_seconds: float
    max_symbols: int
    output_dir: Path
    symbols: tuple[str, ...]
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


def _env_value(name: str, default: str) -> str:
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


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_label() -> str:
    return _now_utc().strftime("%Y-%m-%d %H:%M:%S UTC")


def _window_level(values: list[float], window: int, *, high: bool) -> float:
    if len(values) < window:
        return float("nan")
    sample = [value for value in values[-window:] if math.isfinite(value)]
    if len(sample) < window:
        return float("nan")
    return max(sample) if high else min(sample)


def _pct_distance(price: float, reference: float) -> float:
    if not math.isfinite(price) or not math.isfinite(reference) or abs(reference) < 1e-12:
        return float("nan")
    return (price / reference - 1.0) * 100.0


def _closed_daily_parts(klines: list[list[Any]]) -> tuple[list[list[Any]], list[float], list[float], list[float]]:
    if len(klines) < 2:
        return [], [], [], []

    closed = klines[:-1]
    highs = [_to_float(row[2]) for row in closed if len(row) > 4]
    lows = [_to_float(row[3]) for row in closed if len(row) > 4]
    closes = [_to_float(row[4]) for row in closed if len(row) > 4]
    return closed, highs, lows, closes


def build_monitor_row(
    *,
    futures_symbol: FuturesSymbol,
    klines: list[list[Any]],
    ticker: dict[str, Any] | None = None,
    scanned_at: datetime | None = None,
) -> dict[str, Any]:
    """Build one row of pump-risk/trend-following breakout flags from daily candles.

    Breakout levels and MA200 use closed daily candles only; live price comes from the
    latest ticker when available, falling back to the current forming daily candle.
    """
    ticker = ticker or {}
    scanned_at = scanned_at or _now_utc()
    closed, highs, lows, closes = _closed_daily_parts(klines)

    fallback_price = _to_float(klines[-1][4]) if klines and len(klines[-1]) > 4 else float("nan")
    last_price = _to_float(ticker.get("lastPrice"))
    if not math.isfinite(last_price):
        last_price = fallback_price

    row: dict[str, Any] = {
        "scanned_at": scanned_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "symbol": futures_symbol.symbol,
        "base_asset": futures_symbol.base_asset,
        "market_type": futures_symbol.underlying_type or "CRYPTO",
        "last_price": last_price,
        "quote_volume_24h": _to_float(ticker.get("quoteVolume")),
        "history_days": len(closed),
    }

    active_flags: list[str] = []
    for window in BREAKOUT_WINDOWS:
        high_level = _window_level(highs, window, high=True)
        low_level = _window_level(lows, window, high=False)
        broke_high = math.isfinite(last_price) and math.isfinite(high_level) and last_price > high_level
        broke_low = math.isfinite(last_price) and math.isfinite(low_level) and last_price < low_level
        row[f"high_{window}d"] = high_level
        row[f"low_{window}d"] = low_level
        row[f"distance_to_high_{window}d_pct"] = _pct_distance(last_price, high_level)
        row[f"distance_to_low_{window}d_pct"] = _pct_distance(last_price, low_level)
        row[f"broke_high_{window}d"] = bool(broke_high)
        row[f"broke_low_{window}d"] = bool(broke_low)
        if broke_high:
            active_flags.append(f"{window}D high breakout")
        if broke_low:
            active_flags.append(f"{window}D low breakout")

    previous_close = closes[-1] if closes else float("nan")
    if len(closes) >= MA_WINDOW:
        ma200 = float(pd.Series(closes[-MA_WINDOW:], dtype="float64").mean())
    else:
        ma200 = float("nan")

    price_above_ma = math.isfinite(last_price) and math.isfinite(ma200) and last_price > ma200
    price_below_ma = math.isfinite(last_price) and math.isfinite(ma200) and last_price < ma200
    previous_on_or_below_ma = math.isfinite(previous_close) and math.isfinite(ma200) and previous_close <= ma200
    previous_on_or_above_ma = math.isfinite(previous_close) and math.isfinite(ma200) and previous_close >= ma200
    ma_cross_above = price_above_ma and previous_on_or_below_ma
    ma_cross_below = price_below_ma and previous_on_or_above_ma

    row["previous_close"] = previous_close
    row["ma_200d"] = ma200
    row["distance_to_ma_200d_pct"] = _pct_distance(last_price, ma200)
    row["price_above_200d_ma"] = bool(price_above_ma)
    row["price_below_200d_ma"] = bool(price_below_ma)
    row["ma200_cross_above"] = bool(ma_cross_above)
    row["ma200_cross_below"] = bool(ma_cross_below)

    if ma_cross_above:
        active_flags.append("MA200 cross above")
    if ma_cross_below:
        active_flags.append("MA200 cross below")

    row["flag_count"] = len(active_flags)
    row["flags"] = " | ".join(active_flags)
    return row


def _ticker_lookup(client: BinanceFuturesPublic) -> dict[str, dict[str, Any]]:
    rows = client.ticker_24hr()
    return {str(row.get("symbol", "")).upper(): row for row in rows if row.get("symbol")}


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


def scan_breakout_universe(
    client: BinanceFuturesPublic,
    *,
    symbols: tuple[str, ...] = (),
    max_symbols: int = 0,
) -> tuple[pd.DataFrame, list[str]]:
    universe = client.perpetual_usdt_symbols()
    selected = _selected_symbols(universe, symbols=symbols, max_symbols=max_symbols)
    tickers = _ticker_lookup(client)
    scanned_at = _now_utc()

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, futures_symbol in enumerate(selected, start=1):
        try:
            klines = client.klines_1d(futures_symbol.symbol, limit=KLINE_LIMIT)
            rows.append(
                build_monitor_row(
                    futures_symbol=futures_symbol,
                    klines=klines,
                    ticker=tickers.get(futures_symbol.symbol),
                    scanned_at=scanned_at,
                )
            )
        except (BinanceHTTPError, requests.RequestException, RuntimeError, ValueError) as exc:
            errors.append(f"{futures_symbol.symbol}: {exc}")
        print(f"[{_now_label()}] scanned {index}/{len(selected)} {futures_symbol.symbol}", flush=True)

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame, errors

    sort_columns = ["flag_count", "quote_volume_24h", "symbol"]
    return frame.sort_values(sort_columns, ascending=[False, False, True]).reset_index(drop=True), errors


def _signal_columns() -> list[str]:
    columns: list[str] = []
    for window in BREAKOUT_WINDOWS:
        columns.extend([f"broke_high_{window}d", f"broke_low_{window}d"])
    columns.extend(["ma200_cross_above", "ma200_cross_below"])
    return columns


def active_signal_keys(frame: pd.DataFrame) -> set[str]:
    if frame.empty:
        return set()

    keys: set[str] = set()
    signal_columns = [column for column in _signal_columns() if column in frame.columns]
    for row in frame.to_dict("records"):
        symbol = str(row.get("symbol", "")).upper()
        if not symbol:
            continue
        for column in signal_columns:
            if bool(row.get(column)):
                keys.add(f"{symbol}:{column}")
    return keys


def flagged_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "flag_count" not in frame.columns:
        return frame.copy()
    return frame[pd.to_numeric(frame["flag_count"], errors="coerce").fillna(0) > 0].copy()


def _load_state(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if isinstance(payload, list):
        return {str(item) for item in payload}
    if isinstance(payload, dict):
        return {str(item) for item in payload.get("active_signals", [])}
    return set()


def _write_state(path: Path, active_signals: set[str]) -> None:
    path.write_text(
        json.dumps(
            {
                "updated_at": _now_label(),
                "active_signals": sorted(active_signals),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _append_alerts(path: Path, signal_keys: set[str], *, event: str) -> None:
    if not signal_keys:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp_utc", "event", "symbol", "signal"])
        if not file_exists:
            writer.writeheader()
        for key in sorted(signal_keys):
            symbol, _, signal = key.partition(":")
            writer.writerow(
                {
                    "timestamp_utc": _now_label(),
                    "event": event,
                    "symbol": symbol,
                    "signal": signal,
                }
            )


def _format_number(value: Any, suffix: str = "") -> str:
    parsed = _to_float(value)
    if not math.isfinite(parsed):
        return "n/a"
    absolute = abs(parsed)
    if absolute >= 1_000_000_000:
        return f"{parsed / 1_000_000_000:.2f}B{suffix}"
    if absolute >= 1_000_000:
        return f"{parsed / 1_000_000:.2f}M{suffix}"
    if absolute >= 1_000:
        return f"{parsed / 1_000:.2f}K{suffix}"
    if absolute >= 1:
        return f"{parsed:.4g}{suffix}"
    return f"{parsed:.6g}{suffix}"


def _format_pct(value: Any) -> str:
    parsed = _to_float(value)
    if not math.isfinite(parsed):
        return "n/a"
    return f"{parsed:+.1f}%"


def _format_int(value: Any) -> str:
    parsed = _to_float(value)
    if not math.isfinite(parsed):
        return "n/a"
    return str(int(parsed))


def _clip_text(text: Any, max_chars: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= max_chars:
        return clean
    return f"{clean[: max_chars - 3].rstrip()}..."


def _signal_label(signal: str) -> str:
    if signal.startswith("broke_high_"):
        return f"{signal.removeprefix('broke_high_').upper()} high breakout"
    if signal.startswith("broke_low_"):
        return f"{signal.removeprefix('broke_low_').upper()} low breakdown"
    if signal == "ma200_cross_above":
        return "MA200 cross above"
    if signal == "ma200_cross_below":
        return "MA200 cross below"
    return signal.replace("_", " ")


def _signals_by_symbol(signal_keys: set[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for key in sorted(signal_keys):
        symbol, _, signal = key.partition(":")
        symbol = symbol.upper().strip()
        if symbol and signal:
            grouped.setdefault(symbol, []).append(signal)
    return grouped


def alert_rows_for_signal_keys(frame: pd.DataFrame, signal_keys: set[str]) -> pd.DataFrame:
    if frame.empty or not signal_keys:
        return pd.DataFrame()

    grouped = _signals_by_symbol(signal_keys)
    rows = frame[frame["symbol"].astype(str).str.upper().isin(set(grouped))].copy()
    if rows.empty:
        return rows

    rows["_alert_signals"] = rows["symbol"].astype(str).str.upper().map(
        lambda symbol: " + ".join(_signal_label(signal) for signal in grouped.get(symbol, []))
    )
    return rows.sort_values(["flag_count", "quote_volume_24h", "symbol"], ascending=[False, False, True])


def _format_alert_line(row: pd.Series) -> str:
    symbol = str(row.get("symbol", "")).upper().strip()
    signals = _clip_text(row.get("_alert_signals") or row.get("flags", ""), 110) or "breakout"
    flags = _clip_text(row.get("flags", ""), 130)
    return (
        f"/{symbol} | {signals} | px {_format_number(row.get('last_price'))} | "
        f"vol24 ${_format_number(row.get('quote_volume_24h'))} | hist {_format_int(row.get('history_days'))}D | "
        f"MA200 {_format_pct(row.get('distance_to_ma_200d_pct'))} | active {flags or 'n/a'}"
    )


def _description_with_alert_lines(prefix: str, lines: list[str]) -> str:
    selected: list[str] = []
    for line in lines[:MAX_DISCORD_ALERT_LINES]:
        candidate_selected = selected + [line]
        omitted = len(lines) - len(candidate_selected)
        marker = f"\n... +{omitted} more alert rows omitted; see latest CSV." if omitted else ""
        candidate = prefix + "\n".join(candidate_selected) + marker
        if len(candidate) > DISCORD_EMBED_DESCRIPTION_LIMIT:
            break
        selected.append(line)

    omitted = len(lines) - len(selected)
    description = prefix + "\n".join(selected)
    if omitted:
        marker = f"\n... +{omitted} more alert rows omitted; see latest CSV."
        while selected and len(description + marker) > DISCORD_EMBED_DESCRIPTION_LIMIT:
            selected.pop()
            omitted += 1
            marker = f"\n... +{omitted} more alert rows omitted; see latest CSV."
            description = prefix + "\n".join(selected)
        description += marker
    return description[:DISCORD_EMBED_DESCRIPTION_LIMIT]


def build_discord_payload(rows: pd.DataFrame, *, flagged_count: int | None = None) -> dict[str, Any]:
    if rows.empty:
        return {}
    lines = [_format_alert_line(row) for _, row in rows.iterrows()]
    snapshot_text = f" | Active flagged snapshot: {flagged_count}" if flagged_count is not None else ""
    prefix = (
        f"{DISCORD_PRODUCT_IDENTITY}\n\n"
        f"Breakout/MA200 monitor\n"
        f"New alert symbols: {len(rows)}{snapshot_text} | Windows: {', '.join(f'{window}D' for window in BREAKOUT_WINDOWS)} | "
        f"Detected: {_now_label()}\n"
        f"Discord shows state-diff alerts only; console/CSV can contain the broader flagged snapshot.\n\n"
    )
    description = _description_with_alert_lines(prefix, lines)
    return {
        "username": "Breakout Scanner",
        "embeds": [
            {
                "title": f"Breakout monitor alert ({len(rows)})",
                "description": description,
                "color": 0x38BDF8,
                "footer": {"text": DISCORD_FOOTER},
            }
        ],
    }


def _post_webhook(rows: pd.DataFrame, config: MonitorConfig, *, flagged_count: int | None = None) -> None:
    if rows.empty:
        return
    payload = build_discord_payload(rows, flagged_count=flagged_count)
    if config.dry_run:
        print("DRY RUN webhook payload:")
        print(payload)
        return
    if not config.webhook_url:
        raise RuntimeError("BREAKOUT_MONITOR_DISCORD_WEBHOOK_URL or DISCORD_WEBHOOK_URL is not set.")
    response = requests.post(config.webhook_url, json=payload, timeout=15)
    if response.status_code >= 300:
        raise RuntimeError(f"Discord webhook HTTP {response.status_code}: {response.text[:250]}")


def _write_outputs(frame: pd.DataFrame, errors: list[str], config: MonitorConfig) -> tuple[pd.DataFrame, set[str]]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    flagged = flagged_frame(frame)

    flagged.to_csv(config.output_dir / "breakout_flags_latest.csv", index=False)
    if config.write_full_scan:
        frame.to_csv(config.output_dir / "breakout_full_scan_latest.csv", index=False)
    if errors:
        (config.output_dir / "breakout_errors_latest.txt").write_text("\n".join(errors), encoding="utf-8")
    else:
        error_path = config.output_dir / "breakout_errors_latest.txt"
        if error_path.exists():
            error_path.unlink()

    return flagged, active_signal_keys(frame)


def run_once(config: MonitorConfig) -> tuple[pd.DataFrame, list[str], set[str]]:
    client = BinanceFuturesPublic(
        base_url=config.base_url,
        timeout=config.timeout,
        requests_per_second=config.requests_per_second,
        retries=config.retries,
    )
    frame, errors = scan_breakout_universe(
        client,
        symbols=config.symbols,
        max_symbols=config.max_symbols,
    )
    flagged, active_signals = _write_outputs(frame, errors, config)
    print(
        f"[{_now_label()}] scan complete: rows={len(frame)} flagged_rows={len(flagged)} "
        f"active_signals={len(active_signals)} errors={len(errors)}",
        flush=True,
    )
    if not flagged.empty:
        preview_columns = ["symbol", "last_price", "flag_count", "flags"]
        print(flagged[preview_columns].head(25).to_string(index=False), flush=True)
    return frame, errors, active_signals


def run_forever(config: MonitorConfig) -> None:
    state_path = config.output_dir / "breakout_monitor_state.json"
    alert_path = config.output_dir / "breakout_alerts.csv"
    previous_signals = _load_state(state_path)
    first_cycle = True

    while True:
        try:
            frame, _, active_signals = run_once(config)
            new_signals = active_signals - previous_signals
            resolved_signals = previous_signals - active_signals
            if first_cycle and config.suppress_initial_alerts:
                new_signals = set()

            alert_rows = alert_rows_for_signal_keys(frame, new_signals)
            if not alert_rows.empty:
                _post_webhook(alert_rows, config, flagged_count=len(flagged_frame(frame)))
            _append_alerts(alert_path, new_signals, event="new")
            _append_alerts(alert_path, resolved_signals, event="resolved")
            _write_state(state_path, active_signals)

            if new_signals:
                print(f"[{_now_label()}] NEW signals: {', '.join(sorted(new_signals))}", flush=True)
            if resolved_signals:
                print(f"[{_now_label()}] resolved signals: {', '.join(sorted(resolved_signals))}", flush=True)

            previous_signals = active_signals
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
    parser = argparse.ArgumentParser(
        description="24/7 Binance USDT perp breakout and MA200 monitor.",
    )
    parser.add_argument("--once", action="store_true", help="Run one scan cycle and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Print webhook payload instead of posting.")
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=float(_env_value("BREAKOUT_MONITOR_INTERVAL_SECONDS", "300")),
        help="Seconds to sleep between scan cycles.",
    )
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=int(_env_value("BREAKOUT_MONITOR_MAX_SYMBOLS", "0")),
        help="Optional cap for smoke testing. 0 scans every USDT perp.",
    )
    parser.add_argument(
        "--symbols",
        default=_env_value("BREAKOUT_MONITOR_SYMBOLS", ""),
        help="Comma-separated symbols to scan, e.g. BTCUSDT,ETHUSDT. Empty scans all.",
    )
    parser.add_argument(
        "--requests-per-second",
        type=float,
        default=float(_env_value("BREAKOUT_MONITOR_REQUESTS_PER_SECOND", "2")),
        help="Public request pace for Binance.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(_env_value("BREAKOUT_MONITOR_HTTP_TIMEOUT", "12")),
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=int(_env_value("BREAKOUT_MONITOR_HTTP_RETRIES", "3")),
        help="HTTP retry attempts.",
    )
    parser.add_argument(
        "--base-url",
        default=_env_value("BINANCE_FAPI_BASE_URL", "https://fapi.binance.com"),
        help="Binance futures API base URL.",
    )
    parser.add_argument(
        "--output-dir",
        default=_env_value("BREAKOUT_MONITOR_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)),
        help="Directory for latest CSV snapshots and alert state.",
    )
    parser.add_argument(
        "--write-full-scan",
        action="store_true",
        default=_env_bool("BREAKOUT_MONITOR_WRITE_FULL_SCAN", True),
        help="Write the full latest scan CSV, not only flagged rows.",
    )
    parser.add_argument(
        "--suppress-initial-alerts",
        action="store_true",
        default=_env_bool("BREAKOUT_MONITOR_SUPPRESS_INITIAL_ALERTS", False),
        help="Do not append all currently-active signals as new alerts on first cycle.",
    )
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> MonitorConfig:
    symbols = tuple(symbol.strip().upper() for symbol in str(args.symbols).split(",") if symbol.strip())
    return MonitorConfig(
        base_url=str(args.base_url),
        timeout=int(args.timeout),
        retries=int(args.retries),
        requests_per_second=float(args.requests_per_second),
        interval_seconds=float(args.interval_seconds),
        max_symbols=int(args.max_symbols),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        symbols=symbols,
        webhook_url=_env_value("BREAKOUT_MONITOR_DISCORD_WEBHOOK_URL", _env_value("DISCORD_WEBHOOK_URL", "")),
        once=bool(args.once),
        dry_run=bool(args.dry_run),
        write_full_scan=bool(args.write_full_scan),
        suppress_initial_alerts=bool(args.suppress_initial_alerts),
    )


def main(argv: list[str] | None = None) -> None:
    _load_local_env()
    config = config_from_args(parse_args(argv))
    print(
        f"[{_now_label()}] starting breakout monitor | windows={BREAKOUT_WINDOWS} "
        f"ma={MA_WINDOW}D interval={config.interval_seconds}s output={config.output_dir}",
        flush=True,
    )
    if config.once:
        run_once(config)
    else:
        run_forever(config)


if __name__ == "__main__":
    main()
