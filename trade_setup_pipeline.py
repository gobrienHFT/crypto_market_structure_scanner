from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any

import pandas as pd

from binance_futures import BinanceFuturesPublic, BinanceHTTPError


APP_DIR = Path(__file__).resolve().parent
TRADE_EVENT_COLUMNS = [
    "event_id",
    "timestamp_utc",
    "mode",
    "event_type",
    "symbol",
    "message",
    "entry_price",
    "mark_price",
    "stop_price",
    "breakeven_trigger_price",
    "quantity",
    "notional_usdt",
    "equity_fraction",
    "quarter_kelly_fraction",
    "kelly_sample_size",
    "terminal_edge_score",
    "timing_score",
    "convex_score",
    "timing_state",
    "pnl_usdt",
    "pnl_pct",
]


def _env_value(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_bool(name: str, default: bool = False) -> bool:
    fallback = "1" if default else "0"
    return _env_value(name, fallback).strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float, *, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        value = float(_env_value(name, str(default)))
    except Exception:
        value = float(default)
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _env_int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        value = int(float(_env_value(name, str(default))))
    except Exception:
        value = int(default)
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _num(row: pd.Series, key: str, default: float = 0.0) -> float:
    parsed = _safe_float(row.get(key))
    return float(default if parsed is None else parsed)


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clean: dict[str, Any] = {}
    for key, value in record.items():
        if value is pd.NA:
            clean[key] = None
        elif hasattr(value, "item"):
            try:
                clean[key] = value.item()
            except Exception:
                clean[key] = value
        else:
            clean[key] = value
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(clean, ensure_ascii=True, sort_keys=True) + "\n")


def _floor_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def _fmt_decimal(value: Decimal | float | int | None, places: int = 8) -> str:
    if value is None:
        return "n/a"
    dec = value if isinstance(value, Decimal) else Decimal(str(value))
    text = f"{dec:.{places}f}".rstrip("0").rstrip(".")
    return text or "0"


@dataclass
class TradeBotConfig:
    mode: str = "paper"
    scan_mode: str = "Deep"
    interval_seconds: int = 180
    min_terminal_score: float = 65.0
    min_timing_score: float = 58.0
    min_convex_score: float = 65.0
    allowed_timing_states: tuple[str, ...] = ("Triggering", "Confirmed")
    leverage: int = 1
    min_kelly_sample: int = 20
    default_equity_fraction: float = 0.005
    max_equity_fraction: float = 0.02
    min_equity_fraction: float = 0.0
    stop_atr_multiplier: float = 2.5
    min_stop_pct: float = 0.025
    max_stop_pct: float = 0.12
    breakeven_trigger_r: float = 1.0
    breakeven_trigger_pct: float = 0.0
    max_open_minutes: int = 240
    archive_root: Path = field(default_factory=lambda: Path(_env_value("TRADE_BOT_ARCHIVE_ROOT", str(APP_DIR / "data" / "trade_bot"))))

    @classmethod
    def from_env(cls, *, mode: str | None = None, scan_mode: str | None = None) -> "TradeBotConfig":
        raw_mode = (mode or _env_value("TRADE_BOT_MODE", "paper")).strip().lower()
        if raw_mode not in {"paper", "live"}:
            raw_mode = "paper"
        return cls(
            mode=raw_mode,
            scan_mode=(scan_mode or _env_value("TRADE_BOT_SCAN_MODE", "Deep")).strip() or "Deep",
            interval_seconds=_env_int("TRADE_BOT_INTERVAL_SECONDS", 180, minimum=15),
            min_terminal_score=_env_float("TRADE_BOT_MIN_TERMINAL_SCORE", 65.0, minimum=0.0, maximum=100.0),
            min_timing_score=_env_float("TRADE_BOT_MIN_TIMING_SCORE", 58.0, minimum=0.0, maximum=100.0),
            min_convex_score=_env_float("TRADE_BOT_MIN_CONVEX_SCORE", 65.0, minimum=0.0, maximum=100.0),
            leverage=_env_int("TRADE_BOT_LEVERAGE", 1, minimum=1, maximum=20),
            min_kelly_sample=_env_int("TRADE_BOT_MIN_KELLY_SAMPLE", 20, minimum=0),
            default_equity_fraction=_env_float("TRADE_BOT_DEFAULT_EQUITY_FRACTION", 0.005, minimum=0.0, maximum=0.05),
            max_equity_fraction=_env_float("TRADE_BOT_MAX_EQUITY_FRACTION", 0.02, minimum=0.0, maximum=0.10),
            min_equity_fraction=_env_float("TRADE_BOT_MIN_EQUITY_FRACTION", 0.0, minimum=0.0, maximum=0.10),
            stop_atr_multiplier=_env_float("TRADE_BOT_STOP_ATR_MULTIPLIER", 2.5, minimum=0.25, maximum=10.0),
            min_stop_pct=_env_float("TRADE_BOT_MIN_STOP_PCT", 0.025, minimum=0.001, maximum=0.50),
            max_stop_pct=_env_float("TRADE_BOT_MAX_STOP_PCT", 0.12, minimum=0.002, maximum=0.80),
            breakeven_trigger_r=_env_float("TRADE_BOT_BREAKEVEN_TRIGGER_R", 1.0, minimum=0.1, maximum=5.0),
            breakeven_trigger_pct=_env_float("TRADE_BOT_BREAKEVEN_TRIGGER_PCT", 0.0, minimum=0.0, maximum=0.50),
            max_open_minutes=_env_int("TRADE_BOT_MAX_OPEN_MINUTES", 240, minimum=5),
        )


@dataclass
class KellyEstimate:
    full_kelly_fraction: float
    quarter_kelly_fraction: float
    capped_fraction: float
    sample_size: int
    win_rate: float | None
    avg_win_pct: float | None
    avg_loss_pct: float | None
    source: str


@dataclass
class TradeSetup:
    symbol: str
    row: dict[str, Any]
    entry_price: Decimal
    stop_price: Decimal
    breakeven_trigger_price: Decimal
    stop_distance_pct: float
    quantity: Decimal
    notional_usdt: Decimal
    equity_fraction: float
    kelly: KellyEstimate
    combined_score: float
    mode: str
    rejection_reason: str = ""


class SymbolRules:
    def __init__(self, *, tick_size: Decimal, qty_step: Decimal, min_qty: Decimal, min_notional: Decimal):
        self.tick_size = tick_size
        self.qty_step = qty_step
        self.min_qty = min_qty
        self.min_notional = min_notional


def load_trade_events(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=TRADE_EVENT_COLUMNS)
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return pd.DataFrame(rows)


def trade_events_path(config: TradeBotConfig) -> Path:
    return config.archive_root / "events.jsonl"


def trade_stats_path(config: TradeBotConfig) -> Path:
    return config.archive_root / "stats.csv"


def outcome_archive_records(root: Path | None = None) -> list[dict[str, Any]]:
    archive_root = root or Path(_env_value("DISCORD_PROOF_ARCHIVE_ROOT", str(APP_DIR / "data" / "archive")))
    records: list[dict[str, Any]] = []
    for path in sorted((archive_root / "outcomes").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                records.append(json.loads(line))
            except Exception:
                continue
    return records


def estimate_quarter_kelly(
    records: list[dict[str, Any]],
    *,
    config: TradeBotConfig,
    symbol: str | None = None,
) -> KellyEstimate:
    filtered = records
    if symbol:
        symbol_rows = [row for row in records if str(row.get("ticker") or row.get("symbol") or "").upper() == symbol.upper()]
        if len(symbol_rows) >= config.min_kelly_sample:
            filtered = symbol_rows
    usable: list[tuple[float, float]] = []
    latest_by_id: dict[str, dict[str, Any]] = {}
    for record in filtered:
        key = str(record.get("flag_id") or record.get("alert_id") or f"row-{len(latest_by_id)}")
        latest_by_id[key] = record
    for record in latest_by_id.values():
        upside = _safe_float(record.get("max_upside_24h_pct") or record.get("max_upside_4h_pct") or record.get("max_upside_1h_pct"))
        drawdown = _safe_float(record.get("max_drawdown_pct"))
        if upside is None or drawdown is None:
            continue
        usable.append((max(0.0, upside), abs(min(0.0, drawdown))))

    if len(usable) < config.min_kelly_sample:
        fallback = min(config.default_equity_fraction, config.max_equity_fraction)
        return KellyEstimate(
            full_kelly_fraction=fallback * 4.0,
            quarter_kelly_fraction=fallback,
            capped_fraction=fallback,
            sample_size=len(usable),
            win_rate=None,
            avg_win_pct=None,
            avg_loss_pct=None,
            source="default_fraction_insufficient_outcomes",
        )

    wins = [up for up, dd in usable if up >= 20.0]
    losses = [max(dd, 1.0) for up, dd in usable if up < 20.0]
    win_rate = len(wins) / len(usable)
    avg_win_pct = sum(wins) / len(wins) if wins else 0.0
    avg_loss_pct = sum(losses) / len(losses) if losses else max(1.0, sum(dd for _, dd in usable) / len(usable))
    b = max(0.01, avg_win_pct / max(0.01, avg_loss_pct))
    full_kelly = max(0.0, (b * win_rate - (1.0 - win_rate)) / b)
    quarter = full_kelly * 0.25
    capped = min(max(quarter, config.min_equity_fraction), config.max_equity_fraction)
    return KellyEstimate(
        full_kelly_fraction=full_kelly,
        quarter_kelly_fraction=quarter,
        capped_fraction=capped,
        sample_size=len(usable),
        win_rate=win_rate,
        avg_win_pct=avg_win_pct,
        avg_loss_pct=avg_loss_pct,
        source="proof_archive_quarter_kelly",
    )


def select_trade_candidate(frame: pd.DataFrame, config: TradeBotConfig) -> pd.Series | None:
    if frame.empty or "symbol" not in frame.columns:
        return None
    data = frame.copy()
    if "trade_bucket" not in data.columns:
        return None
    data["trade_bucket"] = data["trade_bucket"].astype(str)
    for column in ("terminal_edge_score", "timing_score", "trade_bucket_score"):
        series = data[column] if column in data.columns else pd.Series(0.0, index=data.index)
        data[column] = pd.to_numeric(series, errors="coerce").fillna(0.0)
    state = data.get("timing_state", pd.Series("", index=data.index)).astype(str)
    allowed = {item.strip().lower() for item in config.allowed_timing_states}
    candidates = data[
        data["trade_bucket"].str.lower().eq("convex long")
        & (data["terminal_edge_score"] >= config.min_terminal_score)
        & (data["timing_score"] >= config.min_timing_score)
        & (data["trade_bucket_score"] >= config.min_convex_score)
        & state.str.lower().isin(allowed)
    ].copy()
    if candidates.empty:
        return None
    candidates["execution_setup_score"] = (
        candidates["terminal_edge_score"] * 0.34
        + candidates["timing_score"] * 0.33
        + candidates["trade_bucket_score"] * 0.33
    )
    candidates = candidates.sort_values(
        ["execution_setup_score", "timing_score", "terminal_edge_score", "symbol"],
        ascending=[False, False, False, True],
    )
    return candidates.iloc[0]


def symbol_rules(client: BinanceFuturesPublic, symbol: str) -> SymbolRules:
    info = client.exchange_info()
    symbol_info = next((item for item in info.get("symbols", []) if str(item.get("symbol", "")).upper() == symbol.upper()), None)
    if not symbol_info:
        raise RuntimeError(f"{symbol} not found in futures exchange info.")
    filters = {str(item.get("filterType", "")).upper(): item for item in symbol_info.get("filters", [])}
    price_filter = filters.get("PRICE_FILTER", {})
    lot_filter = filters.get("MARKET_LOT_SIZE") or filters.get("LOT_SIZE", {})
    min_notional_filter = filters.get("MIN_NOTIONAL", {})
    return SymbolRules(
        tick_size=Decimal(str(price_filter.get("tickSize", "0.0001"))),
        qty_step=Decimal(str(lot_filter.get("stepSize", "1"))),
        min_qty=Decimal(str(lot_filter.get("minQty", "0"))),
        min_notional=Decimal(str(min_notional_filter.get("notional", "5"))),
    )


def latest_mark_price(client: BinanceFuturesPublic, symbol: str) -> Decimal:
    rows = client.mark_price(symbol)
    if rows:
        price = rows[0].get("markPrice") or rows[0].get("indexPrice")
        if price is not None:
            return Decimal(str(price))
    ticker = next((item for item in client.ticker_24hr() if str(item.get("symbol", "")).upper() == symbol.upper()), None)
    if ticker and ticker.get("lastPrice") is not None:
        return Decimal(str(ticker["lastPrice"]))
    raise RuntimeError(f"No live price available for {symbol}.")


def volatility_stop_pct(client: BinanceFuturesPublic, symbol: str, config: TradeBotConfig) -> float:
    try:
        klines = client.klines(symbol, interval="1m", limit=60)
    except Exception:
        klines = []
    ranges: list[float] = []
    for row in klines[-60:]:
        try:
            high = float(row[2])
            low = float(row[3])
            close = float(row[4])
        except Exception:
            continue
        if close > 0:
            ranges.append((high - low) / close)
    atr_pct = sum(ranges) / len(ranges) if ranges else config.min_stop_pct / max(1.0, config.stop_atr_multiplier)
    return min(config.max_stop_pct, max(config.min_stop_pct, atr_pct * config.stop_atr_multiplier))


def futures_equity_usdt(client: BinanceFuturesPublic) -> Decimal:
    account = client.account_information_v3()
    for key in ("totalMarginBalance", "totalWalletBalance", "availableBalance"):
        value = account.get(key)
        if value not in (None, ""):
            return Decimal(str(value))
    for asset in account.get("assets", []):
        if str(asset.get("asset", "")).upper() == "USDT":
            for key in ("marginBalance", "walletBalance", "availableBalance"):
                value = asset.get(key)
                if value not in (None, ""):
                    return Decimal(str(value))
    raise RuntimeError("Could not read USDT futures equity.")


def build_trade_setup(
    row: pd.Series,
    *,
    client: BinanceFuturesPublic,
    config: TradeBotConfig,
    equity_usdt: Decimal | None = None,
    outcome_records: list[dict[str, Any]] | None = None,
) -> TradeSetup:
    symbol = str(row.get("symbol", "")).upper().strip()
    if not symbol:
        raise ValueError("Missing symbol.")
    entry = latest_mark_price(client, symbol)
    rules = symbol_rules(client, symbol)
    stop_pct = volatility_stop_pct(client, symbol, config)
    stop = _floor_step(entry * (Decimal("1") - Decimal(str(stop_pct))), rules.tick_size)
    trigger_pct = max(config.breakeven_trigger_pct, stop_pct * config.breakeven_trigger_r)
    breakeven = _floor_step(entry * (Decimal("1") + Decimal(str(trigger_pct))), rules.tick_size)
    records = outcome_records if outcome_records is not None else outcome_archive_records()
    kelly = estimate_quarter_kelly(records, config=config, symbol=symbol)
    fraction = min(config.max_equity_fraction, max(config.min_equity_fraction, kelly.capped_fraction))
    if fraction <= 0:
        return TradeSetup(
            symbol=symbol,
            row=row.to_dict(),
            entry_price=entry,
            stop_price=stop,
            breakeven_trigger_price=breakeven,
            stop_distance_pct=stop_pct * 100.0,
            quantity=Decimal("0"),
            notional_usdt=Decimal("0"),
            equity_fraction=fraction,
            kelly=kelly,
            combined_score=_num(row, "execution_setup_score"),
            mode=config.mode,
            rejection_reason="Kelly/equity fraction is zero.",
        )
    equity = equity_usdt if equity_usdt is not None else futures_equity_usdt(client)
    notional = equity * Decimal(str(fraction)) * Decimal(str(config.leverage))
    qty = _floor_step(notional / entry, rules.qty_step)
    notional = qty * entry
    rejection = ""
    if qty < rules.min_qty:
        rejection = f"quantity {_fmt_decimal(qty)} below exchange minimum {_fmt_decimal(rules.min_qty)}"
    elif notional < rules.min_notional:
        rejection = f"notional {_fmt_decimal(notional, 4)} below exchange minimum {_fmt_decimal(rules.min_notional, 4)}"
    return TradeSetup(
        symbol=symbol,
        row=row.to_dict(),
        entry_price=entry,
        stop_price=stop,
        breakeven_trigger_price=breakeven,
        stop_distance_pct=stop_pct * 100.0,
        quantity=qty,
        notional_usdt=notional,
        equity_fraction=fraction,
        kelly=kelly,
        combined_score=_num(row, "execution_setup_score"),
        mode=config.mode,
        rejection_reason=rejection,
    )


class TradeBotRuntime:
    def __init__(self, config: TradeBotConfig):
        self.config = config
        self.open_trade: dict[str, Any] | None = None
        self.started_at = _now_iso()
        self.last_message = "idle"
        self.cycles = 0

    def event_path(self) -> Path:
        return trade_events_path(self.config)

    def record_event(self, event_type: str, *, setup: TradeSetup | None = None, message: str = "", extra: dict[str, Any] | None = None) -> None:
        row = (setup.row if setup else {}) if setup else {}
        record: dict[str, Any] = {
            "event_id": f"{int(time.time() * 1000)}_{event_type}",
            "timestamp_utc": _now_iso(),
            "mode": self.config.mode,
            "event_type": event_type,
            "symbol": setup.symbol if setup else (self.open_trade or {}).get("symbol", ""),
            "message": message,
            "entry_price": float(setup.entry_price) if setup else (self.open_trade or {}).get("entry_price"),
            "mark_price": (extra or {}).get("mark_price"),
            "stop_price": float(setup.stop_price) if setup else (self.open_trade or {}).get("stop_price"),
            "breakeven_trigger_price": float(setup.breakeven_trigger_price) if setup else (self.open_trade or {}).get("breakeven_trigger_price"),
            "quantity": float(setup.quantity) if setup else (self.open_trade or {}).get("quantity"),
            "notional_usdt": float(setup.notional_usdt) if setup else (self.open_trade or {}).get("notional_usdt"),
            "equity_fraction": setup.equity_fraction if setup else (self.open_trade or {}).get("equity_fraction"),
            "quarter_kelly_fraction": setup.kelly.quarter_kelly_fraction if setup else (self.open_trade or {}).get("quarter_kelly_fraction"),
            "kelly_sample_size": setup.kelly.sample_size if setup else (self.open_trade or {}).get("kelly_sample_size"),
            "terminal_edge_score": _safe_float(row.get("terminal_edge_score")),
            "timing_score": _safe_float(row.get("timing_score")),
            "convex_score": _safe_float(row.get("trade_bucket_score")),
            "timing_state": row.get("timing_state", ""),
            "pnl_usdt": (extra or {}).get("pnl_usdt"),
            "pnl_pct": (extra or {}).get("pnl_pct"),
        }
        _append_jsonl(self.event_path(), record)
        stats = load_trade_events(self.event_path())
        self.config.archive_root.mkdir(parents=True, exist_ok=True)
        stats.to_csv(trade_stats_path(self.config), index=False)

    def _enter_paper(self, setup: TradeSetup) -> str:
        self.open_trade = {
            "symbol": setup.symbol,
            "mode": "paper",
            "opened_at_utc": _now_iso(),
            "opened_at_monotonic": time.monotonic(),
            "entry_price": float(setup.entry_price),
            "stop_price": float(setup.stop_price),
            "breakeven_trigger_price": float(setup.breakeven_trigger_price),
            "quantity": float(setup.quantity),
            "notional_usdt": float(setup.notional_usdt),
            "equity_fraction": setup.equity_fraction,
            "quarter_kelly_fraction": setup.kelly.quarter_kelly_fraction,
            "kelly_sample_size": setup.kelly.sample_size,
            "breakeven_moved": False,
        }
        message = f"Paper long opened for {setup.symbol} at {_fmt_decimal(setup.entry_price)}; stop {_fmt_decimal(setup.stop_price)}; BE trigger {_fmt_decimal(setup.breakeven_trigger_price)}."
        self.record_event("paper_open", setup=setup, message=message)
        return message

    def _enter_live(self, client: BinanceFuturesPublic, setup: TradeSetup) -> str:
        if not _env_bool("TRADE_BOT_LIVE_ENABLED", False):
            raise RuntimeError("Live trading refused: set TRADE_BOT_LIVE_ENABLED=1 to permit real orders.")
        if setup.kelly.sample_size < self.config.min_kelly_sample:
            raise RuntimeError(f"Live trading refused: only {setup.kelly.sample_size} outcome samples for Kelly sizing.")
        client.change_initial_leverage(setup.symbol, self.config.leverage)
        entry_order = client.new_futures_order(
            symbol=setup.symbol,
            side="BUY",
            type="MARKET",
            quantity=_fmt_decimal(setup.quantity),
            newOrderRespType="RESULT",
        )
        stop_order = client.new_futures_algo_order(
            algoType="CONDITIONAL",
            symbol=setup.symbol,
            side="SELL",
            type="STOP_MARKET",
            closePosition="true",
            triggerPrice=_fmt_decimal(setup.stop_price),
            workingType="MARK_PRICE",
            newOrderRespType="ACK",
        )
        self.open_trade = {
            "symbol": setup.symbol,
            "mode": "live",
            "opened_at_utc": _now_iso(),
            "opened_at_monotonic": time.monotonic(),
            "entry_price": float(setup.entry_price),
            "stop_price": float(setup.stop_price),
            "breakeven_trigger_price": float(setup.breakeven_trigger_price),
            "quantity": float(setup.quantity),
            "notional_usdt": float(setup.notional_usdt),
            "equity_fraction": setup.equity_fraction,
            "quarter_kelly_fraction": setup.kelly.quarter_kelly_fraction,
            "kelly_sample_size": setup.kelly.sample_size,
            "breakeven_moved": False,
            "entry_order_id": entry_order.get("orderId"),
            "stop_algo_id": stop_order.get("algoId"),
        }
        message = f"Live long placed for {setup.symbol}; stop {_fmt_decimal(setup.stop_price)}; BE trigger {_fmt_decimal(setup.breakeven_trigger_price)}."
        self.record_event("live_open", setup=setup, message=message)
        return message

    def _manage_open_trade(self, client: BinanceFuturesPublic) -> str:
        if not self.open_trade:
            return "No open trade."
        symbol = str(self.open_trade["symbol"])
        mark = latest_mark_price(client, symbol)
        entry = Decimal(str(self.open_trade["entry_price"]))
        stop = Decimal(str(self.open_trade["stop_price"]))
        trigger = Decimal(str(self.open_trade["breakeven_trigger_price"]))
        qty = Decimal(str(self.open_trade["quantity"]))
        pnl = (mark - entry) * qty
        pnl_pct = float((mark / entry - Decimal("1")) * Decimal("100")) if entry > 0 else 0.0
        if mark <= stop:
            message = f"{symbol} stop condition observed at {_fmt_decimal(mark)}; paper/live state closed in tracker."
            self.record_event("stop_observed", message=message, extra={"mark_price": float(mark), "pnl_usdt": float(pnl), "pnl_pct": pnl_pct})
            self.open_trade = None
            return message
        if not self.open_trade.get("breakeven_moved") and mark >= trigger:
            self.open_trade["stop_price"] = float(entry)
            self.open_trade["breakeven_moved"] = True
            message = f"{symbol} reached BE trigger at {_fmt_decimal(mark)}; tracker stop moved to entry {_fmt_decimal(entry)}."
            if self.open_trade.get("mode") == "live" and _env_bool("TRADE_BOT_LIVE_ENABLED", False):
                try:
                    client.cancel_all_futures_algo_orders(symbol)
                    client.new_futures_algo_order(
                        algoType="CONDITIONAL",
                        symbol=symbol,
                        side="SELL",
                        type="STOP_MARKET",
                        closePosition="true",
                        triggerPrice=_fmt_decimal(entry),
                        workingType="MARK_PRICE",
                        newOrderRespType="ACK",
                    )
                    message = f"{symbol} reached BE trigger at {_fmt_decimal(mark)}; live stop moved to entry {_fmt_decimal(entry)}."
                except BinanceHTTPError as exc:
                    message = f"{symbol} BE move attempted but Binance rejected it: {exc}"
            self.record_event("breakeven_move", message=message, extra={"mark_price": float(mark), "pnl_usdt": float(pnl), "pnl_pct": pnl_pct})
            return message
        if time.monotonic() - float(self.open_trade.get("opened_at_monotonic", time.monotonic())) > self.config.max_open_minutes * 60:
            message = f"{symbol} max-open timer reached; tracker closed at {_fmt_decimal(mark)}."
            self.record_event("timer_close", message=message, extra={"mark_price": float(mark), "pnl_usdt": float(pnl), "pnl_pct": pnl_pct})
            self.open_trade = None
            return message
        self.record_event("monitor", message=f"{symbol} monitored at {_fmt_decimal(mark)}", extra={"mark_price": float(mark), "pnl_usdt": float(pnl), "pnl_pct": pnl_pct})
        return f"{symbol} open; mark {_fmt_decimal(mark)}, tracker PnL {_fmt_decimal(pnl, 4)} USDT ({pnl_pct:.2f}%)."

    def run_cycle(self, frame: pd.DataFrame, client: BinanceFuturesPublic) -> str:
        self.cycles += 1
        if self.open_trade:
            self.last_message = self._manage_open_trade(client)
            return self.last_message
        candidate = select_trade_candidate(frame, self.config)
        if candidate is None:
            self.last_message = "No setup currently passes terminal + timing + convex gates."
            self.record_event("no_setup", message=self.last_message)
            return self.last_message
        setup = build_trade_setup(candidate, client=client, config=self.config)
        if setup.rejection_reason:
            self.last_message = f"{setup.symbol} passed gates but was not tradable: {setup.rejection_reason}."
            self.record_event("rejected", setup=setup, message=self.last_message)
            return self.last_message
        if self.config.mode == "live":
            self.last_message = self._enter_live(client, setup)
        else:
            self.last_message = self._enter_paper(setup)
        return self.last_message

    def status_text(self) -> str:
        rows = load_trade_events(self.event_path())
        open_text = "none"
        if self.open_trade:
            open_text = (
                f"{self.open_trade['symbol']} {self.open_trade['mode']} entry {self.open_trade['entry_price']} "
                f"stop {self.open_trade['stop_price']} BE {self.open_trade.get('breakeven_moved', False)}"
            )
        closed = rows[rows["event_type"].isin(["stop_observed", "timer_close"])] if not rows.empty and "event_type" in rows.columns else pd.DataFrame()
        pnl = pd.to_numeric(closed.get("pnl_usdt", pd.Series(dtype="float64")), errors="coerce").fillna(0.0).sum() if not closed.empty else 0.0
        return "\n".join(
            [
                f"Mode: {self.config.mode}",
                f"Started: {self.started_at}",
                f"Cycles: {self.cycles}",
                f"Open trade: {open_text}",
                f"Closed tracker PnL: {pnl:.4f} USDT",
                f"Last: {self.last_message}",
                f"Events: {self.event_path()}",
            ]
        )
