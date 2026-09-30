"""Public full-universe snapshots and point-in-time breakout measurements."""
from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pandas as pd

from binance_futures import BinanceFuturesPublic, BinanceHTTPError
from breakouts import recent_pump_stats_from_klines
from short_account_roc import short_account_history_stats
from squeeze_radar import oi_history_stats
from volume_metrics import closed_daily_anchored_vwap_metrics, closed_hour_volume_metrics

DAY = 86_400_000
WINDOWS = (5, 20, 90, 180)
TRADFI = {"COMMODITY", "EQUITY", "HK_EQUITY", "KR_EQUITY", "INDEX", "PREMARKET"}


def number(value: Any) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else float("nan")
    except (ValueError, TypeError):
        return float("nan")


def ratio(value: float, baseline: float) -> float:
    return value / baseline if baseline > 0 else float("nan")


def closed_bars(rows: list, now_ms: int) -> list:
    return sorted({int(r[0]): r for r in rows if len(r) >= 8 and int(r[6]) < now_ms}.values(), key=lambda r: int(r[0]))


def crypto_universe(info: dict) -> list[dict]:
    return [r for r in info.get("symbols", []) if r.get("status") == "TRADING"
            and r.get("contractType") == "PERPETUAL"
            and str(r.get("underlyingType", "")).upper() not in TRADFI]


def daily_levels(daily: list, day_ms: int) -> dict:
    prior = closed_bars(daily, day_ms)
    out = {}
    for days in WINDOWS:
        sample = prior[-days:]
        complete = len(sample) == days and int(sample[0][0]) == day_ms - days * DAY
        complete = complete and all(int(b[0]) - int(a[0]) == DAY for a, b in zip(sample, sample[1:]))
        out[f"high_{days}d"] = max(number(r[2]) for r in sample) if complete else float("nan")
        out[f"low_{days}d"] = min(number(r[3]) for r in sample) if complete else float("nan")
    sample = prior[-200:]
    complete = len(sample) == 200 and int(sample[0][0]) == day_ms - 200 * DAY
    complete = complete and all(int(b[0]) - int(a[0]) == DAY for a, b in zip(sample, sample[1:]))
    out["ma200"] = sum(number(r[4]) for r in sample) / 200 if complete else float("nan")
    return out


def breakout_events(daily: list, intraday: list, now_ms: int, resolution: int) -> dict:
    """Latest excursion across the threshold known at that UTC day's start.

    Candle highs/lows identify a crossing interval, never an exact trade timestamp.
    A new rolling threshold alone is not a price crossing.
    """
    bars = sorted([r for r in intraday if len(r) >= 8 and int(r[0]) <= now_ms], key=lambda r: int(r[0]))
    levels_by_day = {day: daily_levels(daily, day) for day in {int(r[0]) // DAY * DAY for r in bars}}
    output = {}
    specs = [(f"{side}_{d}d", side) for d in WINDOWS for side in ("high", "low")]
    specs += [("ma200_up", "high"), ("ma200_down", "low")]
    for key, side in specs:
        event = None
        for previous, bar in zip(bars, bars[1:]):
            if int(bar[0]) - int(previous[0]) != resolution * 60_000:
                continue
            level = levels_by_day[int(bar[0]) // DAY * DAY].get("ma200" if key.startswith("ma200") else key)
            old_extreme = number(previous[2 if side == "high" else 3])
            new_extreme = number(bar[2 if side == "high" else 3])
            crossed = old_extreme <= level < new_extreme if side == "high" else old_extreme >= level > new_extreme
            if crossed:
                event = int(bar[0])
        output[f"{key}_event_utc"] = pd.to_datetime(event, unit="ms", utc=True).isoformat() if event is not None else None
        output[f"{key}_age_minutes"] = (now_ms - event) / 60_000 if event is not None else float("nan")
    output["event_resolution_minutes"] = resolution
    output["event_lookback_hours"] = (now_ms - int(bars[0][0])) / 3_600_000 if bars else 0
    return output


def daily_returns(daily: list, now_ms: int) -> pd.Series:
    rows = closed_bars(daily, now_ms)
    series = pd.Series({int(r[0]): number(r[4]) for r in rows}, dtype=float).sort_index()
    returns = series.pct_change(fill_method=None)
    return returns.where(series.index.to_series().diff().eq(DAY).to_numpy())


def contiguous_hourly(rows: list[dict], fields: tuple[str, ...]) -> list[dict]:
    """Use a contiguous tail so missing hours cannot masquerade as 1h changes."""
    ordered = sorted({int(r["timestamp"]): r for r in rows}.values(), key=lambda r: int(r["timestamp"]))
    tail = []
    for row in reversed(ordered):
        if not all(math.isfinite(number(row.get(f))) for f in fields):
            break
        if tail and int(tail[-1]["timestamp"]) - int(row["timestamp"]) != 3_600_000:
            break
        tail.append(row)
    return list(reversed(tail))


def market_metrics(ticker: dict, daily: list, hourly: list, shorts: list, oi: list,
                   oi_daily: list, funding: dict, btc_daily: list, now_ms: int) -> dict:
    price = number(ticker.get("lastPrice"))
    day_start = now_ms // DAY * DAY
    closed = closed_bars(daily, now_ms)
    hours = closed_bars(hourly, now_ms)
    levels = daily_levels(daily, day_start)
    # Exclude every calendar day overlapping the current rolling 24-hour window.
    baseline = [r for r in closed if int(r[6]) < now_ms - DAY][-30:]
    volumes = [number(r[7]) for r in baseline]
    vol_total = sum(volumes) if volumes else float("nan")
    vol_avg = vol_total / len(volumes) if volumes else float("nan")
    quote = number(ticker.get("quoteVolume"))
    short_rows = contiguous_hourly([r for r in shorts if number(r.get("timestamp")) <= now_ms], ("shortAccount", "longAccount"))
    latest = short_rows[-1] if short_rows else {}
    oi = contiguous_hourly([r for r in oi if number(r.get("timestamp")) <= now_ms], ("sumOpenInterestValue", "sumOpenInterest"))
    oi_stats = oi_history_stats(oi)
    oi_last = oi[-1] if oi else {}
    oi_baseline = sorted({int(r["timestamp"]): r for r in oi_daily
                          if number(r.get("timestamp")) < day_start}.values(), key=lambda r: int(r["timestamp"]))[-30:]
    oi_avg = sum(number(r.get("sumOpenInterestValue")) for r in oi_baseline) / len(oi_baseline) if oi_baseline else float("nan")
    oi_units_avg = sum(number(r.get("sumOpenInterest")) for r in oi_baseline) / len(oi_baseline) if oi_baseline else float("nan")
    corr = pd.concat([daily_returns(daily, now_ms).rename("coin"), daily_returns(btc_daily, now_ms).rename("btc")], axis=1).dropna().tail(180)
    short_values = [number(r.get("shortAccount")) * 100 for r in short_rows]
    pump = recent_pump_stats_from_klines([*closed, [now_ms]], lookback_days=60)
    row = {
        "last_price": price, "quote_volume_24h": quote,
        "price_change_24h_pct": number(ticker.get("priceChangePercent")),
        "day_return_pct": number(ticker.get("priceChangePercent")),
        "quote_volume_prior_30d_total": vol_total,
        "quote_volume_prior_30d_daily_avg": vol_avg, "quote_volume_prior_30d_days": len(volumes),
        "quote_volume_24h_vs_prior_30d_avg_ratio": ratio(quote, vol_avg),
        "carry_funding_pct": number(funding.get("lastFundingRate")) * 100,
        "funding_interval_hours": number(funding.get("fundingIntervalHours")),
        "next_funding_utc": pd.to_datetime(number(funding.get("nextFundingTime")), unit="ms", utc=True).isoformat() if funding.get("nextFundingTime") else None,
        "price_observed_at_utc": pd.to_datetime(number(ticker.get("closeTime")), unit="ms", utc=True).isoformat() if ticker.get("closeTime") else None,
        "recent_max_pump_60d_pct": pump.max_pump_pct,
        "recent_pump_60d_days": pump.used_days,
        "short_account_pct": number(latest.get("shortAccount")) * 100,
        "long_account_pct": number(latest.get("longAccount")) * 100,
        "long_short_account_ratio": number(latest.get("longShortRatio")),
        "short_account_peak_pct": max(short_values) if short_values else float("nan"),
        "short_account_peak_drawdown_pp": short_values[-1] - max(short_values) if short_values else float("nan"),
        "short_sample_age_minutes": (now_ms - number(latest.get("timestamp"))) / 60_000,
        "oi_value_usdt": number(oi_last.get("sumOpenInterestValue")),
        "oi_units": number(oi_last.get("sumOpenInterest")),
        "oi_prior_30d_avg": oi_avg, "oi_prior_30d_days": len(oi_baseline),
        "oi_vs_30d_avg_ratio": ratio(number(oi_last.get("sumOpenInterestValue")), oi_avg),
        "oi_units_vs_30d_avg_ratio": ratio(number(oi_last.get("sumOpenInterest")), oi_units_avg),
        "oi_delta_pct": oi_stats.get("oi_change_1h_pct"),
        "oi_sample_age_minutes": (now_ms - number(oi_last.get("timestamp"))) / 60_000,
        "history_days": len(closed), "corr_window_days": len(corr),
        "corr_to_btc_6m": corr.coin.corr(corr.btc) if len(corr) >= 3 and corr.coin.std() > 0 and corr.btc.std() > 0 else float("nan"),
        **levels, **short_account_history_stats(short_rows, windows=(1, 3, 4, 6, 12, 24)),
        **closed_hour_volume_metrics(hours, exclude_forming_bar=False),
        **closed_daily_anchored_vwap_metrics(closed, last_price=price, exclude_forming_bar=False),
        **breakout_events(daily, hourly, now_ms, 60),
    }
    row.update({k: v for k, v in oi_stats.items() if k not in row})
    if len(hours) < 2 or int(hours[-1][0]) - int(hours[-2][0]) != 3_600_000:
        row["hour_volume_roc_1h_pct"] = float("nan")
    row["price_vs_ma200_pct"] = (ratio(price, levels["ma200"]) - 1) * 100
    for d in WINDOWS:
        for side in ("high", "low"):
            level = levels[f"{side}_{d}d"]
            row[f"broke_{side}_{d}d"] = (price > level if side == "high" else price < level) if math.isfinite(level) else None
    if hours:
        last = hours[-1]
        row["hour_return_pct"] = (ratio(number(last[4]), number(last[1])) - 1) * 100
        row["hour_volume_multiple"] = ratio(number(last[7]), sum(number(r[7]) for r in hours[-25:-1]) / len(hours[-25:-1])) if len(hours) > 1 else float("nan")
        spread = number(last[2]) - number(last[3])
        row["hour_close_location_pct"] = ratio(number(last[4]) - number(last[3]), spread) * 100
        row["hour_upper_wick_pct"] = ratio(number(last[2]) - max(number(last[1]), number(last[4])), spread) * 100
    row["scanned_at_utc"] = pd.to_datetime(now_ms, unit="ms", utc=True).isoformat()
    row["received_at_utc"] = row["scanned_at_utc"]
    row["event_time_utc"] = pd.to_datetime(min(number(latest.get("timestamp")), number(oi_last.get("timestamp"))), unit="ms", utc=True).isoformat() if latest and oi_last else None
    row["source"] = "Binance Futures public endpoints"
    row["provenance"] = "full USD-M crypto perpetual universe; public market snapshots"
    return row


class PublicCache:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, at REAL, payload TEXT)")

    def get(self, key: str, ttl: float):
        entry = self.get_entry(key, ttl)
        return entry[1] if entry else None

    def get_entry(self, key: str, ttl: float):
        """Return capture time with data so cached forming bars stay provisional."""
        with sqlite3.connect(self.path, timeout=20) as db:
            row = db.execute("SELECT at, payload FROM responses WHERE key=?", (key,)).fetchone()
        if row and 0 <= time.time() - row[0] < ttl:
            try:
                return row[0], json.loads(row[1])
            except (ValueError, TypeError):
                return None
        return None

    def put(self, key: str, value: Any):
        with sqlite3.connect(self.path, timeout=20) as db:
            db.execute("INSERT OR REPLACE INTO responses VALUES (?, ?, ?)", (key, time.time(), json.dumps(value)))


class ScanService:
    """One process-wide scan, bounded workers and shared request pacing."""
    def __init__(self, path: Path, base_url: str = "https://fapi.binance.com"):
        self.cache = PublicCache(path)
        self.base_url = base_url
        self.lock = threading.Lock()
        self.pacing = threading.Lock()
        self.next_request = 0.0
        self.next_data = 0.0
        self.rows = {}
        self.running = False
        self.cancel = threading.Event()
        self.status = "Ready"
        self.completed = 0
        self.total = 0
        self.started_monotonic = 0.0
        self.saved_at = None
        self.bars = {}
        saved = self.cache.get("snapshot", 7 * 86400)
        if saved:
            self.rows = {r["symbol"]: r for r in saved}
            self.total = len(self.rows)
            self.status = "Saved snapshot"

    def snapshot(self):
        with self.lock:
            remaining = ((time.monotonic() - self.started_monotonic) / self.completed * (self.total - self.completed)
                         if self.running and self.completed >= 10 else None)
            return pd.DataFrame([dict(r) for r in self.rows.values()]), {
                "running": self.running, "status": self.status, "completed": self.completed, "total": self.total,
                "remaining_seconds": remaining}

    def chart(self, symbol: str) -> pd.DataFrame:
        with self.lock:
            bars = list(self.bars.get(symbol, []))
        if not bars:
            key = json.dumps([self.base_url, "klines", [symbol], {"interval": "1d", "limit": 240}], sort_keys=True)
            entry = self.cache.get_entry(key, 7 * 86400)
            bars = closed_bars(entry[1], int(entry[0] * 1000)) if entry else []
        rows = closed_bars(bars, int(time.time() * 1000))
        if not rows:
            return pd.DataFrame()
        frame = pd.DataFrame({"Date": pd.to_datetime([r[0] for r in rows], unit="ms", utc=True),
                              "Close": [number(r[4]) for r in rows]})
        frame["MA200"] = frame.Close.rolling(200, min_periods=200).mean()
        return frame.set_index("Date")

    def start(self, minute_events: bool = True):
        with self.lock:
            if self.running:
                return
            self.running = True
            self.completed = 0
            self.started_monotonic = time.monotonic()
            self.status = "Loading Binance universe"
            self.cancel.clear()
        threading.Thread(target=self._run, args=(minute_events,), daemon=True).start()

    def stop(self):
        self.cancel.set()

    def fetch(self, client, method, *args, ttl=240, **kwargs):
        if self.cancel.is_set():
            raise RuntimeError("Scan stopped")
        key = json.dumps([self.base_url, method, args, kwargs], sort_keys=True)
        entry = self.cache.get_entry(key, ttl)
        if entry is not None:
            captured_at, cached = entry
            # A cached forming candle must be fetched again once its close time passes.
            if method != "klines" or not cached or not any(
                int(bar[6]) >= int(captured_at * 1000) and int(bar[6]) < int(time.time() * 1000)
                for bar in cached if len(bar) >= 7
            ):
                return cached
        data_endpoint = method in {"global_long_short_account_ratio", "open_interest_statistics"}
        with self.pacing:
            now = time.monotonic()
            wait_until = max(self.next_request, self.next_data if data_endpoint else 0)
            if self.cancel.wait(max(0, wait_until - now)):
                raise RuntimeError("Scan stopped")
            self.next_request = time.monotonic() + 0.15
            if data_endpoint:
                self.next_data = time.monotonic() + 0.4
        try:
            result = getattr(client, method)(*args, **kwargs)
        except BinanceHTTPError as exc:
            if exc.status_code in {418, 429}:
                self.cancel.set()
                with self.lock:
                    self.status = "Binance rate limit: scan stopped; wait before refreshing"
            raise
        if result:
            self.cache.put(key, result)
        return result

    def _run(self, minute_events):
        client = BinanceFuturesPublic(base_url=self.base_url, timeout=8, retries=1)
        try:
            universe = crypto_universe(self.fetch(client, "exchange_info", ttl=120))
            if not universe:
                raise ValueError("No eligible contracts returned; previous snapshot retained")
            tickers = {r["symbol"]: r for r in self.fetch(client, "ticker_24hr", ttl=15)}
            try:
                funding = {r["symbol"]: r for r in self.fetch(client, "mark_price", ttl=30)}
            except (BinanceHTTPError, RuntimeError, OSError):
                funding = {}
            try:
                intervals = {r["symbol"]: r for r in self.fetch(client, "funding_info", ttl=300)}
                for symbol, record in funding.items():
                    record["fundingIntervalHours"] = intervals.get(symbol, {}).get("fundingIntervalHours", 8)
            except (BinanceHTTPError, RuntimeError, OSError):
                pass
            try:
                btc = self.fetch(client, "klines", "BTCUSDT", interval="1d", limit=240, ttl=300)
            except (BinanceHTTPError, RuntimeError, OSError):
                btc = []
            universe.sort(key=lambda r: number(tickers.get(r["symbol"], {}).get("quoteVolume")) if r["symbol"] in tickers else -1, reverse=True)
            with self.lock:
                self.total = len(universe)
                self.rows = {r["symbol"]: {"symbol": r["symbol"], "base_asset": r.get("baseAsset"),
                             "quote_asset": r.get("quoteAsset"), "last_price": number(tickers.get(r["symbol"], {}).get("lastPrice")),
                             "quote_volume_24h": number(tickers.get(r["symbol"], {}).get("quoteVolume")),
                             "scan_status": "Pending"} for r in universe}
                self.status = "Scanning all pairs"
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {pool.submit(self._symbol, item, tickers.get(item["symbol"], {}), funding.get(item["symbol"], {}), btc, minute_events): item["symbol"] for item in universe}
                for future in as_completed(futures):
                    if self.cancel.is_set():
                        for pending in futures:
                            pending.cancel()
                        break
                    symbol = futures[future]
                    try:
                        row = future.result()
                    except Exception as exc:
                        row = {"scan_status": "Unavailable", "scan_error": str(exc)[:250]}
                    with self.lock:
                        self.rows[symbol].update(row)
                        self.completed += 1
                    if self.completed % 25 == 0:
                        self.cache.put("snapshot", self.snapshot()[0].to_dict("records"))
            with self.lock:
                if not self.cancel.is_set():
                    self.status = "Scan complete"
                elif not self.status.startswith("Binance rate"):
                    self.status = "Stopped; partial results retained"
            self.cache.put("snapshot", self.snapshot()[0].to_dict("records"))
        except Exception as exc:
            with self.lock:
                self.status = f"Scan failed: {str(exc)[:250]}"
        finally:
            client.session.close()
            with self.lock:
                self.running = False

    def _symbol(self, item, ticker, funding, btc, minute_events):
        client = BinanceFuturesPublic(base_url=self.base_url, timeout=8, retries=1)
        errors = []
        if not funding:
            errors.append("funding: unavailable")
        if not btc:
            errors.append("BTC correlation history: unavailable")
        def get(method, *args, **kwargs):
            try:
                result = self.fetch(client, method, *args, **kwargs)
                if not result:
                    errors.append(f"{method}: no data")
                return result
            except Exception as exc:
                errors.append(f"{method}: {str(exc)[:100]}")
                return []
        symbol = item["symbol"]
        try:
            daily = get("klines", symbol, interval="1d", limit=240, ttl=300)
            hourly = get("klines", symbol, interval="1h", limit=73, ttl=120)
            shorts = get("global_long_short_account_ratio", symbol, period="1h", limit=30)
            oi = get("open_interest_statistics", symbol, period="1h", limit=25)
            oi_daily = get("open_interest_statistics", symbol, period="1d", limit=30, ttl=3600)
            now_ms = int(time.time() * 1000)
            row = market_metrics(ticker, daily, hourly, shorts, oi, oi_daily, funding, btc, now_ms)
            # Refine only actual event hours; one 61-bar request serves all levels in an hour.
            if minute_events:
                event_groups = {}
                for key, value in row.items():
                    if key.endswith("_event_utc") and value:
                        event_groups.setdefault(int(pd.Timestamp(value).timestamp() * 1000), []).append(key[:-10])
                for start, keys in event_groups.items():
                    minutes = get("klines", symbol, interval="1m", limit=61, start_time=start - 60_000,
                                  end_time=min(now_ms, start + 3_600_000 - 1), ttl=300)
                    refined = breakout_events(daily, minutes, now_ms, 1)
                    for key in keys:
                        if refined.get(f"{key}_event_utc"):
                            row[f"{key}_event_utc"] = refined[f"{key}_event_utc"]
                            row[f"{key}_age_minutes"] = refined[f"{key}_age_minutes"]
                            row[f"{key}_resolution_minutes"] = 1
            for key in list(row):
                if key.endswith("_event_utc"):
                    row.setdefault(f"{key[:-10]}_resolution_minutes", 60 if row[key] else None)
            row.update(symbol=symbol, base_asset=item.get("baseAsset"), quote_asset=item.get("quoteAsset"),
                       market_type=item.get("underlyingType", "COIN"), binance_perp_universe=True,
                       scan_status="Partial" if errors else "Complete", scan_error="; ".join(errors))
            with self.lock:
                self.bars[symbol] = closed_bars(daily, now_ms)
            return row
        finally:
            client.session.close()
