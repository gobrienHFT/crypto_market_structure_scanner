"""Create a small, fixed synthetic dashboard workspace for offline review."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from market_dashboard_data import DAY, PublicCache, market_metrics

AS_OF = pd.Timestamp("2026-09-01T12:00:00Z")
HOUR = 3_600_000
BASE_URL = "https://fapi.binance.com"


def _bar(start: int, price: float, volume: float, span: int) -> list:
    return [start, str(price), str(price * 1.003), str(price * 0.997), str(price),
            "100", start + span - 1, str(volume), 100]


def build_rows() -> tuple[list[dict], dict[str, list]]:
    now = int(AS_OF.timestamp() * 1000)
    day = now // DAY * DAY
    btc = [_bar(day - (240 - i) * DAY, 100 + i * 0.08 + 3 * math.sin(i / 7), 100_000, DAY)
           for i in range(240)]
    specs = [
        ("DEMOAUSDT", 1.35, 0.70, 1.08, 5.0),
        ("DEMOBUSDT", 0.85, 0.35, 1.08, 0.4),
        ("DEMOCUSDT", 1.02, 0.53, 1.03, 1.2),
    ]
    rows = []
    charts = {}
    for symbol, price, short_share, prior_price, volume_multiple in specs:
        daily = [_bar(day - (240 - i) * DAY, 1 + 0.10 * i / 240 + 0.01 * math.sin(i / 9), 1_000, DAY)
                 for i in range(240)]
        hourly = [_bar(now - (73 - i) * HOUR, prior_price if i < 72 else price,
                       1_000 if i < 72 else 1_000 * volume_multiple, HOUR)
                  for i in range(73)]
        shorts = [{"timestamp": now - (29 - i) * HOUR, "shortAccount": short_share - (29 - i) * 0.002,
                   "longAccount": 1 - (short_share - (29 - i) * 0.002)} for i in range(30)]
        oi = [{"timestamp": now - (24 - i) * HOUR, "sumOpenInterestValue": 1_000_000 + i * 10_000,
               "sumOpenInterest": 100_000 + i * 1_000} for i in range(25)]
        oi_daily = [{"timestamp": day - (30 - i) * DAY, "sumOpenInterestValue": 900_000 + i * 5_000,
                     "sumOpenInterest": 90_000 + i * 500} for i in range(30)]
        ticker = {"lastPrice": str(price), "quoteVolume": str(30_000 * volume_multiple),
                  "priceChangePercent": str((price / prior_price - 1) * 100), "closeTime": now}
        funding = {"lastFundingRate": "0.0002", "fundingIntervalHours": 8}
        row = market_metrics(ticker, daily, hourly, shorts, oi, oi_daily, funding, btc, now)
        row.update(symbol=symbol, base_asset=symbol.removesuffix("USDT"), quote_asset="USDT",
                   market_type="COIN", binance_perp_universe=False, scan_status="Complete",
                   scan_error="", source="Synthetic offline dashboard fixture",
                   provenance="Synthetic; fixed 2026-09-01 observations; no live exchange data")
        rows.append(row)
        charts[symbol] = daily
    return rows, charts


def write_demo(path: Path) -> None:
    rows, charts = build_rows()
    cache = PublicCache(path)
    cache.put("snapshot", rows)
    for symbol, bars in charts.items():
        key = json.dumps([BASE_URL, "klines", [symbol], {"interval": "1d", "limit": 240}], sort_keys=True)
        cache.put(key, bars)


if __name__ == "__main__":
    path = Path(__file__).resolve().parent / "artifacts" / "dashboard_demo" / "market_workspace.sqlite"
    write_demo(path)
    print(f"Synthetic dashboard workspace: {path}")
