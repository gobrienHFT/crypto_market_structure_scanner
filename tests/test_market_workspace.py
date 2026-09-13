from __future__ import annotations

import math
import json
import sqlite3
import pandas as pd

from market_dashboard_data import DAY, ScanService, breakout_events, crypto_universe, daily_levels, market_metrics


def bar(start, *, high=110, low=90, close=100, volume=1000, span=DAY):
    return [start, str(close), str(high), str(low), str(close), "10", start + span - 1, str(volume), 100]


def history(days=240):
    return [bar(i * DAY) for i in range(days)]


def test_all_crypto_contracts_include_majors_and_multiple_quotes_without_volume_filter():
    items = [{"symbol": s, "status": "TRADING", "contractType": "PERPETUAL", "underlyingType": "COIN"}
             for s in ["BTCUSDT", "ETHUSDC", "NEWUSDT", "BTCUSD1"]]
    items += [dict(items[0], symbol="STOCKUSDT", underlyingType="EQUITY"),
              dict(items[0], symbol="OLDUSDT", status="SETTLING"),
              dict(items[0], symbol="BTC_QUARTER", contractType="CURRENT_QUARTER")]
    assert [r["symbol"] for r in crypto_universe({"symbols": items})] == ["BTCUSDT", "ETHUSDC", "NEWUSDT", "BTCUSD1"]


def test_levels_exclude_current_day_and_require_complete_history():
    rows = history()
    rows.append(bar(240 * DAY, high=9999))
    result = daily_levels(rows, 240 * DAY)
    assert result["high_180d"] == 110
    assert result["ma200"] == 100
    assert math.isnan(daily_levels(rows[-5:], 240 * DAY)["high_5d"])
    assert math.isnan(daily_levels(rows[:230] + rows[231:], 240 * DAY)["high_20d"])


def test_crossing_minutes_and_no_invented_event_for_already_above():
    start = 240 * DAY
    bars = [bar(start, high=109, span=60000), bar(start + 60000, high=112, span=60000),
            bar(start + 120000, high=115, span=60000)]
    result = breakout_events(history(), bars, start + 77 * 60000, 1)
    assert result["high_90d_age_minutes"] == 76
    assert result["high_180d_age_minutes"] == 76
    bars[0][2] = "112"
    assert math.isnan(breakout_events(history(), bars, start + 77 * 60000, 1)["high_90d_age_minutes"])


def test_gap_in_intraday_history_does_not_invent_crossing():
    start = 240 * DAY
    bars = [bar(start, high=109, span=60000), bar(start + 120000, high=112, span=60000)]
    assert math.isnan(breakout_events(history(), bars, start + 180000, 1)["high_5d_age_minutes"])


def test_day_rollover_compares_previous_price_to_new_threshold():
    rows = history()
    rows[-5][2] = "200"
    start = 240 * DAY
    bars = [bar(start - 60000, high=150, span=60000), bar(start, high=150, span=60000)]
    # The old 200 high drops out on a later day; no actual price crossing occurred.
    rows[-5][0] = 235 * DAY
    assert math.isnan(breakout_events(rows, bars, start + 60000, 1)["high_5d_age_minutes"])


def test_low_and_ma200_crosses_are_measured():
    start = 240 * DAY
    bars = [bar(start, high=99, low=95, close=98, span=60000),
            bar(start + 60000, high=102, low=88, close=101, span=60000)]
    result = breakout_events(history(), bars, start + 120000, 1)
    assert result["low_20d_age_minutes"] == 1
    assert result["ma200_up_age_minutes"] == 1


def test_volume_baseline_does_not_overlap_rolling_24h_and_oi_excludes_today():
    now = 240 * DAY + DAY // 2
    rows = history()
    rows[-1][7] = "9999999"
    oi = [{"timestamp": now - 3600000, "sumOpenInterestValue": "200", "sumOpenInterest": "20"}]
    oi_daily = [{"timestamp": i * DAY, "sumOpenInterestValue": "100", "sumOpenInterest": "10"} for i in range(210, 240)]
    oi_daily.append({"timestamp": 240 * DAY, "sumOpenInterestValue": "9000", "sumOpenInterest": "900"})
    result = market_metrics({"lastPrice": "101", "quoteVolume": "5000"}, rows, [], [], oi, oi_daily, {}, rows, now)
    assert result["quote_volume_prior_30d_total"] == 30000
    assert result["quote_volume_24h_vs_prior_30d_avg_ratio"] == 5
    assert result["oi_vs_30d_avg_ratio"] == 2
    assert result["oi_units_vs_30d_avg_ratio"] == 2
    assert result["oi_prior_30d_days"] == 30


def test_missing_data_is_unknown_and_short_history_uses_actual_days():
    rows = history(4)
    for i, r in enumerate(rows):
        r[4] = str(100 + i * i)
    result = market_metrics({"lastPrice": "110"}, rows, [], [], [], [], {}, rows, 4 * DAY)
    assert result["broke_high_5d"] is None
    assert math.isnan(result["short_account_pct"])
    assert result["corr_window_days"] == 3
    assert abs(result["corr_to_btc_6m"] - 1) < 1e-9


def test_two_hour_gap_is_not_reported_as_one_hour_roc():
    now = 240 * DAY
    shorts = [{"timestamp": now - h * 3600000, "shortAccount": s, "longAccount": 1-s}
              for h, s in [(3, .5), (1, .7)]]
    oi = [{"timestamp": now - h * 3600000, "sumOpenInterestValue": v, "sumOpenInterest": v}
          for h, v in [(3, 100), (1, 200)]]
    result = market_metrics({}, history(), [], shorts, oi, [], {}, history(), now)
    assert result["short_account_pct"] == 70
    assert math.isnan(result["short_account_roc_1h_pct"])
    assert math.isnan(result["oi_delta_pct"])


def test_worker_failure_retains_pair_and_snapshot_survives_restart(tmp_path, monkeypatch):
    scanner = ScanService(tmp_path / "cache.sqlite")
    items = [{"symbol": s, "status": "TRADING", "contractType": "PERPETUAL", "underlyingType": "COIN"}
             for s in ["BTCUSDT", "NEWUSDT"]]
    def fetch(client, method, *args, **kwargs):
        if method == "exchange_info":
            return {"symbols": items}
        if method == "ticker_24hr":
            return [{"symbol": s, "quoteVolume": "10", "lastPrice": "1"} for s in ["BTCUSDT", "NEWUSDT"]]
        return []
    def worker(item, *args):
        if item["symbol"] == "NEWUSDT":
            raise ValueError("provider unavailable")
        return {"symbol": "BTCUSDT", "scan_status": "Complete"}
    monkeypatch.setattr(scanner, "fetch", fetch)
    monkeypatch.setattr(scanner, "_symbol", worker)
    scanner._run(False)
    frame, status = scanner.snapshot()
    assert set(frame.symbol) == {"BTCUSDT", "NEWUSDT"}
    assert frame.set_index("symbol").loc["NEWUSDT", "scan_status"] == "Unavailable"
    assert status["completed"] == 2
    assert not status["running"]
    restored, _ = ScanService(tmp_path / "cache.sqlite").snapshot()
    assert set(restored.symbol) == {"BTCUSDT", "NEWUSDT"}


def test_empty_universe_preserves_last_good_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "cache.sqlite"
    scanner = ScanService(path)
    saved = [{"symbol": "BTCUSDT", "scan_status": "Complete"}]
    scanner.cache.put("snapshot", saved)
    scanner = ScanService(path)
    monkeypatch.setattr(scanner, "fetch", lambda *args, **kwargs: {"symbols": []})
    scanner._run(False)
    frame, status = scanner.snapshot()
    assert frame.symbol.tolist() == ["BTCUSDT"]
    assert "previous snapshot retained" in status["status"]
    assert not status["running"]
    assert scanner.cache.get("snapshot", 60) == saved


def test_cached_forming_daily_candle_never_becomes_completed_on_restart(tmp_path, monkeypatch):
    scanner = ScanService(tmp_path / "cache.sqlite")
    captured = 240 * DAY + DAY // 2
    monkeypatch.setattr("market_dashboard_data.time.time", lambda: captured / 1000)
    key = json.dumps([scanner.base_url, "klines", ["BTCUSDT"], {"interval": "1d", "limit": 240}], sort_keys=True)
    scanner.cache.put(key, history() + [bar(240 * DAY, close=999)])
    monkeypatch.setattr("market_dashboard_data.time.time", lambda: (captured + DAY) / 1000)
    frame = ScanService(tmp_path / "cache.sqlite").chart("BTCUSDT")
    assert len(frame) == 240
    assert frame.Close.iloc[-1] == 100
    assert frame.MA200.iloc[-1] == 100


def test_malformed_cached_json_is_a_cache_miss(tmp_path):
    scanner = ScanService(tmp_path / "cache.sqlite")
    scanner.cache.put("bad", [])
    with sqlite3.connect(scanner.cache.path) as db:
        db.execute("UPDATE responses SET payload=? WHERE key=?", ("invalid-json", "bad"))
    assert scanner.cache.get("bad", 60) is None


def test_minute_refinement_preserves_per_event_resolution(tmp_path, monkeypatch):
    scanner = ScanService(tmp_path / "cache.sqlite")
    now = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    day = now // DAY * DAY
    start = now // 3600000 * 3600000 - 3600000
    daily = [bar(day - (240-i)*DAY) for i in range(240)]
    hourly = [bar(start - 3600000, high=109, span=3600000), bar(start, high=112, span=3600000)]
    minutes = [bar(start - 60000, high=109, span=60000), bar(start, high=109, span=60000),
               bar(start + 60000, high=112, span=60000)]
    def fetch(client, method, *args, **kwargs):
        if method != "klines":
            return []
        return {"1d": daily, "1h": hourly, "1m": minutes}[kwargs["interval"]]
    monkeypatch.setattr(scanner, "fetch", fetch)
    result = scanner._symbol({"symbol": "BTCUSDT"}, {"lastPrice": 112}, {}, daily, True)
    assert result["high_90d_resolution_minutes"] == 1
    assert pd.Timestamp(result["high_90d_event_utc"]).timestamp() * 1000 == start + 60000


def test_empty_workspace_renders_without_network(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import market_dashboard_ui
    class FakeScanner:
        def snapshot(self):
            return pd.DataFrame(), {"running": False, "status": "Ready", "completed": 0, "total": 0}
    monkeypatch.setattr(market_dashboard_ui, "service", lambda *args: FakeScanner())
    test = AppTest.from_string("from pathlib import Path\nfrom types import SimpleNamespace\nfrom market_dashboard_ui import render\nrender(SimpleNamespace(APP_DIR=Path('.'), BASE_URL='test'))")
    test.run(timeout=30)
    assert not test.exception
    assert test.title[0].value == "Crypto Market Scanner"


def test_populated_workspace_all_tabs_and_search(monkeypatch):
    import os
    os.environ["CRYPTO_SCANNER_IMPORT_ONLY"] = "1"
    import app
    import market_dashboard_ui
    from streamlit.testing.v1 import AppTest
    now = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    day = now // DAY * DAY
    rows = [bar(day - (240-i)*DAY) for i in range(240)]
    values = market_metrics({"lastPrice": "111", "quoteVolume": "4000"}, rows, [], [], [], [], {}, rows, now)
    frame = pd.DataFrame([dict(values, symbol=s, base_asset=s[:-4], scan_status="Partial", scan_error="test fixture") for s in ["BTCUSDT", "LABUSDT"]])
    class FakeScanner:
        def snapshot(self):
            return frame, {"running": False, "status": "Test fixture", "completed": 2, "total": 2}
    monkeypatch.setattr(market_dashboard_ui, "service", lambda *args: FakeScanner())
    monkeypatch.setattr(app, "_attach_cached_squeeze_evidence", lambda df: df)
    test = AppTest.from_string("import app\nfrom market_dashboard_ui import render\nrender(app)").run(timeout=30)
    assert not test.exception
    assert [tab.label for tab in test.tabs] == ["All Markets", "Reflexivity", "Breakouts", "Volume & OI", "Correlations", "Market Breadth"]
    test.text_input(key="market_search").set_value("LAB").run()
    assert not test.exception
    assert test.dataframe[0].value.symbol.tolist() == ["LABUSDT"]
