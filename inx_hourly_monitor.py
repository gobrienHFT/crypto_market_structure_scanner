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

import requests

from binance_futures import BinanceHTTPError, BinanceFuturesPublic
from discord_flag_formatter import DISCORD_FOOTER


APP_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = APP_DIR / "inx_hourly_monitor_output"


@dataclass(frozen=True)
class InxHourlyConfig:
    symbol: str
    base_url: str
    timeout: int
    retries: int
    requests_per_second: float
    interval_seconds: float
    output_dir: Path
    webhook_url: str
    once: bool
    dry_run: bool


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
        parsed = _to_float(row.get(key))
        if math.isfinite(parsed):
            return int(parsed)
    return 0


def _latest_pair(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    sorted_rows = sorted([row for row in rows if isinstance(row, dict)], key=_row_timestamp)
    if not sorted_rows:
        return {}, {}
    if len(sorted_rows) == 1:
        return {}, sorted_rows[-1]
    return sorted_rows[-2], sorted_rows[-1]


def _ms_label(value: Any) -> str:
    parsed = _to_float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        return ""
    return datetime.fromtimestamp(parsed / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


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


def _format_pct(value: Any, *, signed: bool = True) -> str:
    parsed = _to_float(value)
    if not math.isfinite(parsed):
        return "n/a"
    return f"{parsed:+.2f}%" if signed else f"{parsed:.2f}%"


def _format_pp(value: Any) -> str:
    parsed = _to_float(value)
    if not math.isfinite(parsed):
        return "n/a"
    return f"{parsed:+.2f}pp"


def _short_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    previous, current = _latest_pair(rows)
    current_short = _share_to_pct(current.get("shortAccount"))
    previous_short = _share_to_pct(previous.get("shortAccount"))
    delta_pp = current_short - previous_short if math.isfinite(current_short) and math.isfinite(previous_short) else float("nan")
    direction = "build" if math.isfinite(delta_pp) and delta_pp > 0 else "cover" if math.isfinite(delta_pp) and delta_pp < 0 else "flat"
    return {
        "short_account_pct": current_short,
        "short_account_previous_1h_pct": previous_short,
        "short_account_roc_1h_pp": delta_pp,
        "short_account_roc_1h_pct": _pct_change(current_short, previous_short),
        "short_account_direction": direction,
        "short_account_points": len([row for row in rows if isinstance(row, dict)]),
        "short_account_timestamp": _ms_label(current.get("timestamp") or current.get("time")),
    }


def _oi_metrics(rows: list[dict[str, Any]], live_open_interest: dict[str, Any] | None = None) -> dict[str, Any]:
    previous, current = _latest_pair(rows)
    live_open_interest = live_open_interest or {}
    current_oi = _to_float(current.get("sumOpenInterest"))
    if not math.isfinite(current_oi):
        current_oi = _to_float(live_open_interest.get("openInterest"))
    previous_oi = _to_float(previous.get("sumOpenInterest"))
    current_value = _to_float(current.get("sumOpenInterestValue"))
    previous_value = _to_float(previous.get("sumOpenInterestValue"))
    return {
        "open_interest": current_oi,
        "open_interest_previous_1h": previous_oi,
        "open_interest_change_abs": current_oi - previous_oi if math.isfinite(current_oi) and math.isfinite(previous_oi) else float("nan"),
        "open_interest_change_pct": _pct_change(current_oi, previous_oi),
        "open_interest_value": current_value,
        "open_interest_value_previous_1h": previous_value,
        "open_interest_value_change_pct": _pct_change(current_value, previous_value),
        "live_open_interest": _to_float(live_open_interest.get("openInterest")),
        "open_interest_points": len([row for row in rows if isinstance(row, dict)]),
        "open_interest_timestamp": _ms_label(current.get("timestamp") or current.get("time")),
    }


def _last_closed_hour_volume(klines_5m: list[list[Any]], *, bars: int = 12) -> dict[str, Any]:
    if not klines_5m:
        return {
            "volume_base_60m": float("nan"),
            "volume_quote_60m": float("nan"),
            "trades_60m": float("nan"),
            "price_open_60m": float("nan"),
            "price_close_60m": float("nan"),
            "price_change_60m_pct": float("nan"),
            "high_60m": float("nan"),
            "low_60m": float("nan"),
            "volume_window": "",
            "volume_bars": 0,
        }

    closed_rows = klines_5m[:-1] if len(klines_5m) > 1 else klines_5m
    sample = closed_rows[-max(1, int(bars)) :]
    quote_volume = sum(_to_float(row[7]) for row in sample if len(row) > 7 and math.isfinite(_to_float(row[7])))
    base_volume = sum(_to_float(row[5]) for row in sample if len(row) > 5 and math.isfinite(_to_float(row[5])))
    trades = sum(_to_float(row[8]) for row in sample if len(row) > 8 and math.isfinite(_to_float(row[8])))
    opens = [_to_float(row[1]) for row in sample if len(row) > 4]
    highs = [_to_float(row[2]) for row in sample if len(row) > 4]
    lows = [_to_float(row[3]) for row in sample if len(row) > 4]
    closes = [_to_float(row[4]) for row in sample if len(row) > 4]
    open_price = opens[0] if opens else float("nan")
    close_price = closes[-1] if closes else float("nan")
    start_label = _ms_label(sample[0][0]) if sample and sample[0] else ""
    end_label = _ms_label(sample[-1][6]) if sample and len(sample[-1]) > 6 else ""
    return {
        "volume_base_60m": base_volume,
        "volume_quote_60m": quote_volume,
        "trades_60m": trades,
        "price_open_60m": open_price,
        "price_close_60m": close_price,
        "price_change_60m_pct": _pct_change(close_price, open_price),
        "high_60m": max([value for value in highs if math.isfinite(value)], default=float("nan")),
        "low_60m": min([value for value in lows if math.isfinite(value)], default=float("nan")),
        "volume_window": f"{start_label} to {end_label}".strip(),
        "volume_bars": len(sample),
    }


def build_inx_hourly_snapshot(
    *,
    symbol: str,
    ratio_rows: list[dict[str, Any]],
    open_interest_rows: list[dict[str, Any]],
    klines_5m: list[list[Any]],
    live_open_interest: dict[str, Any] | None = None,
    mark_price_rows: list[dict[str, Any]] | None = None,
    scanned_at: datetime | None = None,
) -> dict[str, Any]:
    scanned_at = scanned_at or _now_utc()
    mark_price_rows = mark_price_rows or []
    mark_price = _to_float(mark_price_rows[0].get("markPrice")) if mark_price_rows else float("nan")
    row: dict[str, Any] = {
        "scanned_at": scanned_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "symbol": symbol.upper(),
        "period": "1h",
        "source": "Binance Futures public data",
        "mark_price": mark_price,
    }
    row.update(_short_metrics(ratio_rows))
    row.update(_oi_metrics(open_interest_rows, live_open_interest))
    row.update(_last_closed_hour_volume(klines_5m))
    return row


def fetch_inx_hourly_snapshot(client: BinanceFuturesPublic, config: InxHourlyConfig) -> tuple[dict[str, Any], list[str]]:
    symbol = config.symbol.upper().strip()
    errors: list[str] = []

    def fetch(label: str, func):
        try:
            return func()
        except (BinanceHTTPError, requests.RequestException, RuntimeError, ValueError) as exc:
            errors.append(f"{label}: {exc}")
            return [] if label != "live open interest" else {}

    ratio_rows = fetch("short account ratio", lambda: client.global_long_short_account_ratio(symbol, period="1h", limit=2))
    oi_rows = fetch("open interest history", lambda: client.open_interest_statistics(symbol, period="1h", limit=2))
    live_oi = fetch("live open interest", lambda: client.open_interest(symbol))
    klines_5m = fetch("5m klines", lambda: client.klines(symbol, interval="5m", limit=13))
    mark_rows = fetch("mark price", lambda: client.mark_price(symbol))

    return (
        build_inx_hourly_snapshot(
            symbol=symbol,
            ratio_rows=ratio_rows if isinstance(ratio_rows, list) else [],
            open_interest_rows=oi_rows if isinstance(oi_rows, list) else [],
            klines_5m=klines_5m if isinstance(klines_5m, list) else [],
            live_open_interest=live_oi if isinstance(live_oi, dict) else {},
            mark_price_rows=mark_rows if isinstance(mark_rows, list) else [],
        ),
        errors,
    )


def _payload_lines(row: dict[str, Any], errors: list[str]) -> list[str]:
    symbol = str(row.get("symbol", "")).upper()
    lines = [
        (
            f"/{symbol} | short {_format_pct(row.get('short_account_previous_1h_pct'), signed=False)} -> "
            f"{_format_pct(row.get('short_account_pct'), signed=False)} | "
            f"delta {_format_pp(row.get('short_account_roc_1h_pp'))} / {_format_pct(row.get('short_account_roc_1h_pct'))} | "
            f"{row.get('short_account_direction') or 'n/a'}"
        ),
        (
            f"OI {_format_number(row.get('open_interest_previous_1h'))} -> {_format_number(row.get('open_interest'))} | "
            f"delta {_format_number(row.get('open_interest_change_abs'))} / {_format_pct(row.get('open_interest_change_pct'))} | "
            f"value ${_format_number(row.get('open_interest_value'))}"
        ),
        (
            f"60m volume {_format_number(row.get('volume_base_60m'))} {symbol.replace('USDT', '')} | "
            f"quote ${_format_number(row.get('volume_quote_60m'))} | trades {_format_number(row.get('trades_60m'))}"
        ),
        (
            f"60m px {_format_number(row.get('price_open_60m'))} -> {_format_number(row.get('price_close_60m'))} "
            f"({_format_pct(row.get('price_change_60m_pct'))}) | mark {_format_number(row.get('mark_price'))}"
        ),
    ]
    window = str(row.get("volume_window", "") or "").strip()
    if window:
        lines.append(f"Volume window: {window} | 5m bars: {row.get('volume_bars')}")
    if errors:
        lines.append("Partial data warnings: " + " | ".join(str(error)[:180] for error in errors[:3]))
    return lines


def build_discord_payload(row: dict[str, Any], errors: list[str] | None = None) -> dict[str, Any]:
    errors = errors or []
    description = (
        f"INX one-hour perp monitor\n"
        f"Source: {row.get('source') or 'Binance Futures public data'} | Detected: {_now_label()}\n"
        f"Posts every cycle; metrics are the latest 1h short-account point, 1h OI point, and last 12 closed 5m volume bars.\n\n"
        + "\n".join(_payload_lines(row, errors))
    )
    return {
        "username": "INX Hourly Scanner",
        "embeds": [
            {
                "title": f"{str(row.get('symbol', 'INXUSDT')).upper()} one-hour monitor",
                "description": description[:3900],
                "color": 0x22C55E if _to_float(row.get("short_account_roc_1h_pp")) >= 0 else 0xEF4444,
                "footer": {"text": DISCORD_FOOTER},
            }
        ],
    }


def _post_webhook(row: dict[str, Any], errors: list[str], config: InxHourlyConfig) -> None:
    payload = build_discord_payload(row, errors)
    if config.dry_run:
        print("DRY RUN webhook payload:")
        print(json.dumps(payload, indent=2))
        return
    if not config.webhook_url:
        raise RuntimeError("INX_MONITOR_DISCORD_WEBHOOK_URL or DISCORD_WEBHOOK_URL is not set.")
    response = requests.post(config.webhook_url, json=payload, timeout=15)
    if response.status_code >= 300:
        raise RuntimeError(f"Discord webhook HTTP {response.status_code}: {response.text[:250]}")


def _write_outputs(row: dict[str, Any], errors: list[str], config: InxHourlyConfig) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    latest_path = config.output_dir / "inx_hourly_latest.csv"
    history_path = config.output_dir / "inx_hourly_history.csv"
    error_path = config.output_dir / "inx_hourly_errors_latest.txt"

    fieldnames = list(row.keys())
    for path, mode in ((latest_path, "w"), (history_path, "a")):
        file_exists = path.exists()
        with path.open(mode, newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            if mode == "w" or not file_exists:
                writer.writeheader()
            writer.writerow(row)

    if errors:
        error_path.write_text("\n".join(errors), encoding="utf-8")
    elif error_path.exists():
        error_path.unlink()


def run_once(config: InxHourlyConfig) -> tuple[dict[str, Any], list[str]]:
    client = BinanceFuturesPublic(
        base_url=config.base_url,
        timeout=config.timeout,
        requests_per_second=config.requests_per_second,
        retries=config.retries,
    )
    row, errors = fetch_inx_hourly_snapshot(client, config)
    _write_outputs(row, errors, config)
    print(
        f"[{_now_label()}] {config.symbol.upper()} short={_format_pct(row.get('short_account_pct'), signed=False)} "
        f"delta={_format_pp(row.get('short_account_roc_1h_pp'))} oi={_format_number(row.get('open_interest'))} "
        f"vol60=${_format_number(row.get('volume_quote_60m'))} errors={len(errors)}",
        flush=True,
    )
    _post_webhook(row, errors, config)
    return row, errors


def run_forever(config: InxHourlyConfig) -> None:
    while True:
        try:
            run_once(config)
        except KeyboardInterrupt:
            print(f"[{_now_label()}] stopped by user", flush=True)
            return
        except Exception as exc:
            print(f"[{_now_label()}] INX monitor cycle failed: {exc}", flush=True)
        if config.once:
            return
        time.sleep(max(30.0, float(config.interval_seconds)))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="24/7 INX one-hour short/OI/volume Discord monitor.")
    parser.add_argument("--once", action="store_true", help="Run one scan and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Print webhook payload instead of posting.")
    parser.add_argument("--symbol", default=_env_value("INX_MONITOR_SYMBOL", "INXUSDT"), help="Symbol to monitor. Default INXUSDT.")
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=float(_env_value("INX_MONITOR_INTERVAL_SECONDS", "300")),
        help="Seconds between posts.",
    )
    parser.add_argument(
        "--requests-per-second",
        type=float,
        default=float(_env_value("INX_MONITOR_REQUESTS_PER_SECOND", "2")),
        help="Public request pace for Binance.",
    )
    parser.add_argument("--timeout", type=int, default=int(_env_value("INX_MONITOR_HTTP_TIMEOUT", "12")), help="HTTP timeout in seconds.")
    parser.add_argument("--retries", type=int, default=int(_env_value("INX_MONITOR_HTTP_RETRIES", "3")), help="HTTP retry attempts.")
    parser.add_argument("--base-url", default=_env_value("BINANCE_FAPI_BASE_URL", "https://fapi.binance.com"), help="Binance futures API base URL.")
    parser.add_argument("--output-dir", default=_env_value("INX_MONITOR_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)), help="Directory for local CSV snapshots.")
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> InxHourlyConfig:
    return InxHourlyConfig(
        symbol=str(args.symbol).upper().strip(),
        base_url=str(args.base_url),
        timeout=int(args.timeout),
        retries=int(args.retries),
        requests_per_second=float(args.requests_per_second),
        interval_seconds=float(args.interval_seconds),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        webhook_url=_env_value("INX_MONITOR_DISCORD_WEBHOOK_URL", _env_value("DISCORD_WEBHOOK_URL", "")),
        once=bool(args.once),
        dry_run=bool(args.dry_run),
    )


def main(argv: list[str] | None = None) -> None:
    _load_local_env()
    config = config_from_args(parse_args(argv))
    print(
        f"[{_now_label()}] starting INX hourly monitor | symbol={config.symbol} "
        f"interval={config.interval_seconds:.0f}s output={config.output_dir}",
        flush=True,
    )
    run_forever(config)


if __name__ == "__main__":
    main()
