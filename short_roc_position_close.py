from __future__ import annotations

import argparse
import csv
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from binance_futures import BinanceAuthenticationError, BinanceFuturesPublic, BinanceHTTPError
from discord_flag_formatter import DISCORD_FOOTER
from inx_hourly_monitor import _env_value, _format_number, _format_pct, _format_pp, _load_local_env, _now_label, _short_metrics


APP_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = APP_DIR / "short_roc_close_output"


@dataclass(frozen=True)
class ShortRocCloseConfig:
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
    live: bool
    trigger_short_roc_pct: float
    trigger_short_roc_pp: float
    min_profit_usdt: float
    min_profit_pct: float
    require_breakeven_stop: bool
    block_without_breakeven_stop: bool
    breakeven_tolerance_pct: float
    close_once: bool
    api_key: str
    api_secret: str


@dataclass(frozen=True)
class CloseDecision:
    should_close: bool
    reason: str
    row: dict[str, Any]
    order_params: dict[str, Any] | None = None


def _to_float(value: Any) -> float:
    try:
        parsed = float(value)
    except Exception:
        return float("nan")
    return parsed if math.isfinite(parsed) else float("nan")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _base_asset(symbol: Any) -> str:
    clean = str(symbol or "").upper().strip()
    return clean[:-4] if clean.endswith("USDT") else clean


def _output_prefix(symbol: Any) -> str:
    base = _base_asset(symbol) or "symbol"
    return "".join(char.lower() if char.isalnum() else "_" for char in base).strip("_") or "symbol"


def _nonzero_position(rows: list[dict[str, Any]], symbol: str) -> dict[str, Any]:
    symbol = symbol.upper()
    for row in rows:
        if str(row.get("symbol", "")).upper() != symbol:
            continue
        if abs(_to_float(row.get("positionAmt"))) > 0:
            return row
    return {}


def _nonzero_positions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if abs(_to_float(row.get("positionAmt"))) > 0]


def _empty_decision(symbol: str, reason: str, config: ShortRocCloseConfig, *, positions: list[dict[str, Any]] | None = None) -> CloseDecision:
    symbols = ",".join(str(row.get("symbol", "")).upper() for row in (positions or []) if row.get("symbol"))
    return CloseDecision(
        False,
        reason,
        {
            "scanned_at": _now_utc().strftime("%Y-%m-%d %H:%M:%S UTC"),
            "symbol": symbol.upper(),
            "position_side": "FLAT",
            "position_amt": float("nan"),
            "entry_price": float("nan"),
            "mark_price": float("nan"),
            "unrealized_profit": float("nan"),
            "profit_pct": float("nan"),
            "short_account_previous_1h_pct": float("nan"),
            "short_account_pct": float("nan"),
            "short_account_roc_1h_pp": float("nan"),
            "short_account_roc_1h_pct": float("nan"),
            "short_account_direction": "",
            "trigger_short_roc_pct": config.trigger_short_roc_pct,
            "trigger_short_roc_pp": config.trigger_short_roc_pp,
            "min_profit_usdt": config.min_profit_usdt,
            "min_profit_pct": config.min_profit_pct,
            "require_breakeven_stop": bool(config.require_breakeven_stop),
            "block_without_breakeven_stop": bool(config.block_without_breakeven_stop),
            "breakeven_stop_found": False,
            "breakeven_tolerance_pct": config.breakeven_tolerance_pct,
            "live_enabled": bool(config.live),
            "open_position_symbols": symbols,
        },
    )


def _profit_pct(position: dict[str, Any]) -> float:
    amount = _to_float(position.get("positionAmt"))
    entry = _to_float(position.get("entryPrice"))
    mark = _to_float(position.get("markPrice"))
    if not math.isfinite(amount) or not math.isfinite(entry) or not math.isfinite(mark) or entry <= 0 or amount == 0:
        return float("nan")
    if amount > 0:
        return (mark / entry - 1.0) * 100.0
    return (entry / mark - 1.0) * 100.0 if mark > 0 else float("nan")


def _position_side(position: dict[str, Any]) -> str:
    amount = _to_float(position.get("positionAmt"))
    if amount > 0:
        return "LONG"
    if amount < 0:
        return "SHORT"
    return "FLAT"


def _close_order_params(symbol: str, position: dict[str, Any]) -> dict[str, Any]:
    amount = _to_float(position.get("positionAmt"))
    side = "SELL" if amount > 0 else "BUY"
    quantity = format(abs(amount), "f").rstrip("0").rstrip(".")
    params: dict[str, Any] = {
        "symbol": symbol.upper(),
        "side": side,
        "type": "MARKET",
        "quantity": quantity,
    }
    position_side = str(position.get("positionSide") or "BOTH").upper()
    if position_side and position_side != "BOTH":
        params["positionSide"] = position_side
    else:
        params["reduceOnly"] = "true"
    return params


def _is_true(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _has_breakeven_stop(position: dict[str, Any], open_orders: list[dict[str, Any]], tolerance_pct: float) -> bool:
    amount = _to_float(position.get("positionAmt"))
    entry = _to_float(position.get("entryPrice"))
    if not math.isfinite(amount) or amount == 0 or not math.isfinite(entry) or entry <= 0:
        return False

    close_side = "SELL" if amount > 0 else "BUY"
    tolerance = abs(float(tolerance_pct)) / 100.0
    min_long_stop = entry * (1.0 - tolerance)
    max_short_stop = entry * (1.0 + tolerance)
    allowed_types = {"STOP", "STOP_MARKET", "TRAILING_STOP_MARKET"}

    for order in open_orders:
        order_type = str(order.get("type") or order.get("algoType") or order.get("strategyType") or "").upper()
        if order_type not in allowed_types and "STOP" not in order_type:
            continue
        if str(order.get("side") or "").upper() != close_side:
            continue
        stop_price = _to_float(order.get("stopPrice") or order.get("triggerPrice") or order.get("activatePrice"))
        if not math.isfinite(stop_price) or stop_price <= 0:
            continue
        if amount > 0 and stop_price >= min_long_stop:
            return True
        if amount < 0 and stop_price <= max_short_stop:
            return True
    return False


def evaluate_close_decision(
    *,
    symbol: str,
    position: dict[str, Any],
    short_metrics: dict[str, Any],
    config: ShortRocCloseConfig,
    open_orders: list[dict[str, Any]] | None = None,
    scanned_at: datetime | None = None,
) -> CloseDecision:
    scanned_at = scanned_at or _now_utc()
    amount = _to_float(position.get("positionAmt"))
    unrealized = _to_float(position.get("unRealizedProfit"))
    if not math.isfinite(unrealized):
        unrealized = _to_float(position.get("unrealizedProfit"))
    profit_pct = _profit_pct(position)
    roc_pct = _to_float(short_metrics.get("short_account_roc_1h_pct"))
    roc_pp = _to_float(short_metrics.get("short_account_roc_1h_pp"))
    current_short = _to_float(short_metrics.get("short_account_pct"))
    previous_short = _to_float(short_metrics.get("short_account_previous_1h_pct"))
    breakeven_stop_found = _has_breakeven_stop(position, open_orders or [], config.breakeven_tolerance_pct)

    row: dict[str, Any] = {
        "scanned_at": scanned_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "symbol": symbol.upper(),
        "position_side": _position_side(position),
        "position_amt": amount,
        "entry_price": _to_float(position.get("entryPrice")),
        "mark_price": _to_float(position.get("markPrice")),
        "unrealized_profit": unrealized,
        "profit_pct": profit_pct,
        "short_account_previous_1h_pct": previous_short,
        "short_account_pct": current_short,
        "short_account_roc_1h_pp": roc_pp,
        "short_account_roc_1h_pct": roc_pct,
        "short_account_direction": short_metrics.get("short_account_direction") or "",
        "trigger_short_roc_pct": config.trigger_short_roc_pct,
        "trigger_short_roc_pp": config.trigger_short_roc_pp,
        "min_profit_usdt": config.min_profit_usdt,
        "min_profit_pct": config.min_profit_pct,
        "require_breakeven_stop": bool(config.require_breakeven_stop),
        "block_without_breakeven_stop": bool(config.block_without_breakeven_stop),
        "breakeven_stop_found": bool(breakeven_stop_found),
        "breakeven_tolerance_pct": config.breakeven_tolerance_pct,
        "live_enabled": bool(config.live),
    }

    if not math.isfinite(amount) or amount == 0:
        return CloseDecision(False, "no open position", row)
    if not math.isfinite(unrealized) or unrealized < config.min_profit_usdt:
        return CloseDecision(False, "profit guard not met", row)
    if not math.isfinite(profit_pct) or profit_pct < config.min_profit_pct:
        return CloseDecision(False, "profit percent guard not met", row)
    if config.block_without_breakeven_stop and not breakeven_stop_found:
        return CloseDecision(False, "breakeven stop guard not met", row)

    pct_trigger = math.isfinite(roc_pct) and roc_pct < -abs(config.trigger_short_roc_pct)
    pp_trigger = math.isfinite(roc_pp) and roc_pp < -abs(config.trigger_short_roc_pp)
    if not pct_trigger and not pp_trigger:
        return CloseDecision(False, "short ROC has not rolled over enough", row)

    reason_parts = []
    if pct_trigger:
        reason_parts.append(f"short ROC {_format_pct(roc_pct)} < -{abs(config.trigger_short_roc_pct):.2f}%")
    if pp_trigger:
        reason_parts.append(f"short delta {_format_pp(roc_pp)} < -{abs(config.trigger_short_roc_pp):.2f}pp")
    return CloseDecision(True, "; ".join(reason_parts), row, _close_order_params(symbol, position))


def fetch_decision(client: BinanceFuturesPublic, config: ShortRocCloseConfig) -> tuple[CloseDecision, list[str]]:
    symbol = config.symbol.upper().strip()
    errors: list[str] = []
    auto_symbol = symbol in {"AUTO", "*", ""}

    try:
        positions = client.position_information_v3(None if auto_symbol else symbol)
    except (BinanceAuthenticationError, BinanceHTTPError, requests.RequestException, RuntimeError, ValueError) as exc:
        errors.append(f"position information: {exc}")
        positions = []

    if auto_symbol:
        open_positions = _nonzero_positions(positions if isinstance(positions, list) else [])
        if len(open_positions) != 1:
            reason = "no open position" if not open_positions else f"auto mode found multiple open positions ({len(open_positions)})"
            return _empty_decision("AUTO", reason, config, positions=open_positions), errors
        position = open_positions[0]
        symbol = str(position.get("symbol", "")).upper().strip()
        if not symbol:
            return _empty_decision("AUTO", "auto mode found open position without symbol", config, positions=open_positions), errors
    else:
        position = _nonzero_position(positions if isinstance(positions, list) else [], symbol)

    try:
        ratio_rows = client.global_long_short_account_ratio(symbol, period="1h", limit=2)
    except (BinanceHTTPError, requests.RequestException, RuntimeError, ValueError) as exc:
        errors.append(f"short account ratio: {exc}")
        ratio_rows = []

    try:
        open_orders = client.open_futures_orders(symbol) if config.require_breakeven_stop or config.block_without_breakeven_stop else []
    except (BinanceAuthenticationError, BinanceHTTPError, requests.RequestException, RuntimeError, ValueError) as exc:
        errors.append(f"open orders: {exc}")
        open_orders = []
    try:
        algo_orders = client.open_futures_algo_orders(symbol) if config.require_breakeven_stop or config.block_without_breakeven_stop else []
    except (AttributeError, BinanceAuthenticationError, BinanceHTTPError, requests.RequestException, RuntimeError, ValueError) as exc:
        errors.append(f"open algo orders: {exc}")
        algo_orders = []

    metrics = _short_metrics(ratio_rows if isinstance(ratio_rows, list) else [])
    if isinstance(algo_orders, list):
        open_orders = list(open_orders if isinstance(open_orders, list) else []) + algo_orders
    decision = evaluate_close_decision(
        symbol=symbol,
        position=position,
        short_metrics=metrics,
        config=config,
        open_orders=open_orders if isinstance(open_orders, list) else [],
    )
    if errors and decision.reason == "no open position" and not position:
        decision.row["data_warning"] = " | ".join(errors[:3])
    return decision, errors


def maybe_close_position(client: BinanceFuturesPublic, decision: CloseDecision, config: ShortRocCloseConfig) -> dict[str, Any] | None:
    if not decision.should_close or not decision.order_params:
        return None
    live_env = _env_value("SHORT_ROC_CLOSE_LIVE", "0").strip().lower() in {"1", "true", "yes", "y"}
    if not config.live or config.dry_run or not live_env:
        return {"dry_run": True, "order_params": decision.order_params}
    return client.new_futures_order(**decision.order_params)


def build_discord_payload(decision: CloseDecision, errors: list[str], order_result: dict[str, Any] | None = None) -> dict[str, Any]:
    row = decision.row
    symbol = str(row.get("symbol", "")).upper()
    base = _base_asset(symbol) or symbol
    action = "CLOSE TRIGGER" if decision.should_close else "monitor"
    order_text = ""
    if order_result:
        order_text = "\nOrder: " + ("DRY RUN " if order_result.get("dry_run") else "LIVE ") + json.dumps(order_result, default=str)[:700]
    warning_text = ""
    if errors:
        warning_text = "\nWarnings: " + " | ".join(str(error)[:160] for error in errors[:3])
    description = (
        f"{base} short-ROC position close monitor\n"
        f"Source: Binance Futures public + signed account data | Detected: {_now_label()}\n"
        f"Rule: close only when the position is in profit and shorts roll over past the configured threshold.\n\n"
        f"/{symbol} | {row.get('position_side')} amt {_format_number(row.get('position_amt'))} | "
        f"entry {_format_number(row.get('entry_price'))} | mark {_format_number(row.get('mark_price'))}\n"
        f"PnL ${_format_number(row.get('unrealized_profit'))} / {_format_pct(row.get('profit_pct'))} | "
        f"guard >= ${_format_number(row.get('min_profit_usdt'))} and {_format_pct(row.get('min_profit_pct'))}\n"
        f"BE stop check: {'hard block' if row.get('block_without_breakeven_stop') else 'warning' if row.get('require_breakeven_stop') else 'off'} | "
        f"found={row.get('breakeven_stop_found')} | tolerance {_format_pct(row.get('breakeven_tolerance_pct'))}\n"
        f"short {_format_pct(row.get('short_account_previous_1h_pct'), signed=False)} -> "
        f"{_format_pct(row.get('short_account_pct'), signed=False)} | "
        f"delta {_format_pp(row.get('short_account_roc_1h_pp'))} / {_format_pct(row.get('short_account_roc_1h_pct'))} | "
        f"{row.get('short_account_direction') or 'n/a'}\n"
        f"Decision: {action} | {decision.reason}"
        f"{order_text}{warning_text}"
    )
    return {
        "username": f"{base} Short ROC Close",
        "embeds": [
            {
                "title": f"{symbol} short-ROC close monitor",
                "description": description[:3900],
                "color": 0xEF4444 if decision.should_close else 0x64748B,
                "footer": {"text": DISCORD_FOOTER},
            }
        ],
    }


def _post_webhook(decision: CloseDecision, errors: list[str], order_result: dict[str, Any] | None, config: ShortRocCloseConfig) -> None:
    payload = build_discord_payload(decision, errors, order_result)
    if config.dry_run:
        print("DRY RUN webhook payload:")
        print(json.dumps(payload, indent=2, default=str))
        return
    if not config.webhook_url:
        raise RuntimeError("SHORT_ROC_CLOSE_DISCORD_WEBHOOK_URL or DISCORD_WEBHOOK_URL is not set.")
    response = requests.post(config.webhook_url, json=payload, timeout=15)
    if response.status_code >= 300:
        raise RuntimeError(f"Discord webhook HTTP {response.status_code}: {response.text[:250]}")


def _write_outputs(decision: CloseDecision, errors: list[str], order_result: dict[str, Any] | None, config: ShortRocCloseConfig) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    prefix = _output_prefix(decision.row.get("symbol") or config.symbol)
    row = dict(decision.row)
    row["should_close"] = decision.should_close
    row["decision_reason"] = decision.reason
    row["order_result"] = json.dumps(order_result or {}, default=str)
    row["errors"] = " | ".join(errors)

    latest_path = config.output_dir / f"{prefix}_short_roc_close_latest.csv"
    history_path = config.output_dir / f"{prefix}_short_roc_close_history.csv"
    fieldnames = list(row.keys())
    for path, mode in ((latest_path, "w"), (history_path, "a")):
        file_exists = path.exists()
        with path.open(mode, newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            if mode == "w" or not file_exists:
                writer.writeheader()
            writer.writerow(row)


def _order_status(order_result: dict[str, Any] | None) -> str:
    if not order_result:
        return ""
    if order_result.get("dry_run"):
        return "DRY_RUN"
    status = str(order_result.get("status") or "").upper().strip()
    return status or "SENT"


def _write_closed_trade_ledger(decision: CloseDecision, order_result: dict[str, Any] | None, config: ShortRocCloseConfig) -> None:
    if not decision.should_close or not order_result:
        return
    config.output_dir.mkdir(parents=True, exist_ok=True)
    prefix = _output_prefix(decision.row.get("symbol") or config.symbol)
    path = config.output_dir / f"{prefix}_closed_trades.csv"
    row = dict(decision.row)
    params = decision.order_params or {}
    row.update(
        {
            "closed_at": _now_utc().strftime("%Y-%m-%d %H:%M:%S UTC"),
            "decision_reason": decision.reason,
            "order_status": _order_status(order_result),
            "order_id": order_result.get("orderId", ""),
            "client_order_id": order_result.get("clientOrderId", order_result.get("clientOrderId", "")),
            "close_side": params.get("side", ""),
            "close_quantity": params.get("quantity", ""),
            "dry_run": bool(order_result.get("dry_run")),
            "avg_price": order_result.get("avgPrice", ""),
            "executed_qty": order_result.get("executedQty", ""),
            "cum_quote": order_result.get("cumQuote", ""),
            "raw_order_result": json.dumps(order_result, default=str),
        }
    )
    fieldnames = list(row.keys())
    file_exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def run_once(config: ShortRocCloseConfig) -> tuple[CloseDecision, list[str], dict[str, Any] | None]:
    client = BinanceFuturesPublic(
        base_url=config.base_url,
        timeout=config.timeout,
        requests_per_second=config.requests_per_second,
        retries=config.retries,
        api_key=config.api_key,
        api_secret=config.api_secret,
    )
    decision, errors = fetch_decision(client, config)
    order_result = maybe_close_position(client, decision, config)
    _write_outputs(decision, errors, order_result, config)
    _write_closed_trade_ledger(decision, order_result, config)
    detected_symbol = str(decision.row.get("symbol") or config.symbol).upper()
    print(
        f"[{_now_label()}] {config.symbol.upper()} close-monitor symbol={detected_symbol} "
        f"should_close={decision.should_close} "
        f"reason={decision.reason} pnl={_format_number(decision.row.get('unrealized_profit'))} "
        f"short={_format_pct(decision.row.get('short_account_previous_1h_pct'), signed=False)}"
        f"->{_format_pct(decision.row.get('short_account_pct'), signed=False)} "
        f"short_roc={_format_pct(decision.row.get('short_account_roc_1h_pct'))} live={config.live}",
        flush=True,
    )
    _post_webhook(decision, errors, order_result, config)
    return decision, errors, order_result


def run_forever(config: ShortRocCloseConfig) -> None:
    while True:
        try:
            _, _, order_result = run_once(config)
        except KeyboardInterrupt:
            print(f"[{_now_label()}] stopped by user", flush=True)
            return
        except Exception as exc:
            print(f"[{_now_label()}] {config.symbol.upper()} close monitor cycle failed: {exc}", flush=True)
            order_result = None
        if config.close_once and order_result and not order_result.get("dry_run"):
            print(f"[{_now_label()}] live close order sent; close-once enabled, stopping monitor", flush=True)
            return
        if config.once:
            return
        time.sleep(max(30.0, float(config.interval_seconds)))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Close a profitable Binance futures position when short-account ROC rolls over.")
    parser.add_argument("--once", action="store_true", help="Run one scan and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Print webhook payload and never place an order.")
    parser.add_argument("--live", action="store_true", help="Allow live close orders, also requires SHORT_ROC_CLOSE_LIVE=1.")
    parser.add_argument("--symbol", default=_env_value("SHORT_ROC_CLOSE_SYMBOL", "LABUSDT"), help="Symbol to monitor.")
    parser.add_argument("--trigger-short-roc-pct", type=float, default=float(_env_value("SHORT_ROC_CLOSE_TRIGGER_PCT", "2.5")), help="Close when 1h short-account ROC is more negative than this percent.")
    parser.add_argument("--trigger-short-roc-pp", type=float, default=float(_env_value("SHORT_ROC_CLOSE_TRIGGER_PP", "1.0")), help="Close when 1h short-account delta is more negative than this many percentage points.")
    parser.add_argument("--min-profit-usdt", type=float, default=float(_env_value("SHORT_ROC_CLOSE_MIN_PROFIT_USDT", "0")), help="Minimum unrealized profit in USDT before close can trigger.")
    parser.add_argument("--min-profit-pct", type=float, default=float(_env_value("SHORT_ROC_CLOSE_MIN_PROFIT_PCT", "0")), help="Minimum position profit percent before close can trigger.")
    parser.add_argument("--require-breakeven-stop", action="store_true", help="Check and report whether a stop order near breakeven exists before closing.")
    parser.add_argument("--block-without-breakeven-stop", action="store_true", help="Hard-block closes when the breakeven stop check is not found.")
    parser.add_argument("--breakeven-tolerance-pct", type=float, default=float(_env_value("SHORT_ROC_CLOSE_BREAKEVEN_TOLERANCE_PCT", "1.0")), help="Allowed distance below long entry or above short entry for the breakeven stop check.")
    parser.add_argument("--no-close-once", action="store_true", help="Keep running after a live close order is sent.")
    parser.add_argument("--interval-seconds", type=float, default=float(_env_value("SHORT_ROC_CLOSE_INTERVAL_SECONDS", "300")), help="Seconds between checks.")
    parser.add_argument("--requests-per-second", type=float, default=float(_env_value("SHORT_ROC_CLOSE_REQUESTS_PER_SECOND", "2")), help="Binance request pace.")
    parser.add_argument("--timeout", type=int, default=int(_env_value("SHORT_ROC_CLOSE_HTTP_TIMEOUT", "12")), help="HTTP timeout in seconds.")
    parser.add_argument("--retries", type=int, default=int(_env_value("SHORT_ROC_CLOSE_HTTP_RETRIES", "3")), help="HTTP retry attempts.")
    parser.add_argument("--base-url", default=_env_value("BINANCE_FAPI_BASE_URL", "https://fapi.binance.com"), help="Binance futures API base URL.")
    parser.add_argument("--output-dir", default=_env_value("SHORT_ROC_CLOSE_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)), help="Directory for local CSV snapshots.")
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> ShortRocCloseConfig:
    return ShortRocCloseConfig(
        symbol=str(args.symbol).upper().strip(),
        base_url=str(args.base_url),
        timeout=int(args.timeout),
        retries=int(args.retries),
        requests_per_second=float(args.requests_per_second),
        interval_seconds=float(args.interval_seconds),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        webhook_url=_env_value("SHORT_ROC_CLOSE_DISCORD_WEBHOOK_URL", _env_value("DISCORD_WEBHOOK_URL", "")),
        once=bool(args.once),
        dry_run=bool(args.dry_run),
        live=bool(args.live),
        trigger_short_roc_pct=abs(float(args.trigger_short_roc_pct)),
        trigger_short_roc_pp=abs(float(args.trigger_short_roc_pp)),
        min_profit_usdt=float(args.min_profit_usdt),
        min_profit_pct=float(args.min_profit_pct),
        require_breakeven_stop=bool(args.require_breakeven_stop),
        block_without_breakeven_stop=bool(args.block_without_breakeven_stop),
        breakeven_tolerance_pct=abs(float(args.breakeven_tolerance_pct)),
        close_once=not bool(args.no_close_once),
        api_key=_env_value("BINANCE_API_KEY", _env_value("BINANCE_FUTURES_API_KEY", "")),
        api_secret=_env_value("BINANCE_API_SECRET", _env_value("BINANCE_FUTURES_API_SECRET", "")),
    )


def main(argv: list[str] | None = None) -> None:
    _load_local_env()
    config = config_from_args(parse_args(argv))
    print(
        f"[{_now_label()}] starting short-ROC close monitor | symbol={config.symbol} "
        f"interval={config.interval_seconds:.0f}s trigger=-{config.trigger_short_roc_pct:.2f}% "
        f"live={config.live} output={config.output_dir}",
        flush=True,
    )
    run_forever(config)


if __name__ == "__main__":
    main()
