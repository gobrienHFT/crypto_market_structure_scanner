from __future__ import annotations

import os
from types import SimpleNamespace

import pandas as pd


os.environ["CRYPTO_SCANNER_IMPORT_ONLY"] = "1"

import app


def test_all_crypto_perp_universe_keeps_new_crypto_symbols_and_excludes_tradfi() -> None:
    ticker = pd.DataFrame(
        [
            {"symbol": "BTCUSDT", "quoteVolume": 1_000_000},
            {"symbol": "AKEUSDT", "quoteVolume": 25_000},
            {"symbol": "SKHYNIXUSDT", "quoteVolume": 2_000_000},
        ]
    )
    symbol_meta = {
        "BTCUSDT": SimpleNamespace(underlying_type="COIN"),
        "AKEUSDT": SimpleNamespace(underlying_type="COIN"),
        "SKHYNIXUSDT": SimpleNamespace(underlying_type="EQUITY"),
    }

    selected = app._crypto_perp_ticker(ticker, symbol_meta)

    assert selected["symbol"].tolist() == ["BTCUSDT", "AKEUSDT"]


def test_all_crypto_short_account_frame_only_returns_pair_and_short_pct() -> None:
    class Client:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, int]] = []

        def perpetual_usdt_symbols(self):
            return [
                SimpleNamespace(symbol="BTCUSDT", underlying_type="COIN"),
                SimpleNamespace(symbol="AKEUSDT", underlying_type="COIN"),
                SimpleNamespace(symbol="NEWUSDT", underlying_type=""),
                SimpleNamespace(symbol="NVDAUSDT", underlying_type="EQUITY"),
            ]

        def global_long_short_account_ratio(self, symbol: str, *, period: str, limit: int):
            self.calls.append((symbol, period, limit))
            if symbol == "AKEUSDT":
                return [{"shortAccount": "0.72"}]
            if symbol == "BTCUSDT":
                return [{"shortAccount": "0.48"}]
            return []

    client = Client()
    frame = app._all_crypto_short_account_frame(client)

    assert frame.columns.tolist() == ["symbol", "short_account_pct"]
    assert frame["symbol"].tolist() == ["AKEUSDT", "BTCUSDT", "NEWUSDT"]
    assert frame["short_account_pct"].iloc[:2].tolist() == [72.0, 48.0]
    assert pd.isna(frame["short_account_pct"].iloc[2])
    assert client.calls == [
        ("AKEUSDT", app.LONG_SHORT_RATIO_PERIOD, 1),
        ("BTCUSDT", app.LONG_SHORT_RATIO_PERIOD, 1),
        ("NEWUSDT", app.LONG_SHORT_RATIO_PERIOD, 1),
    ]


def test_all_crypto_run_scan_bypasses_the_heavy_breakout_pipeline(monkeypatch) -> None:
    constructor_kwargs = {}

    class Client:
        def perpetual_usdt_symbols(self):
            return [SimpleNamespace(symbol="AKEUSDT", underlying_type="COIN")]

        def global_long_short_account_ratio(self, symbol: str, *, period: str, limit: int):
            assert symbol == "AKEUSDT"
            assert period == app.LONG_SHORT_RATIO_PERIOD
            assert limit == 1
            return [{"shortAccount": "0.68"}]

    def client_factory(**kwargs):
        constructor_kwargs.update(kwargs)
        return Client()

    monkeypatch.setattr(app, "BinanceFuturesPublic", client_factory)

    highs, all_pairs = app.run_scan(987_654_321, "All Short Account %")

    assert highs.empty
    assert all_pairs.to_dict("records") == [{"symbol": "AKEUSDT", "short_account_pct": 68.0}]
    assert constructor_kwargs["requests_per_second"] == app.ALL_CRYPTO_SHORTS_REQUESTS_PER_SECOND


def test_breakout_universe_includes_btc_and_all_crypto_pairs_with_eight_flags() -> None:
    ticker = pd.DataFrame(
        [
            {"symbol": "BTCUSDT", "lastPrice": 11.0, "highPrice": 13.0, "lowPrice": 7.0, "quoteVolume": 1_000_000},
            {"symbol": "AKEUSDT", "lastPrice": 11.0, "highPrice": 13.0, "lowPrice": 7.0, "quoteVolume": 25_000},
            {"symbol": "SKHYNIXUSDT", "lastPrice": 11.0, "highPrice": 13.0, "lowPrice": 7.0, "quoteVolume": 2_000_000},
        ]
    )
    symbol_meta = {
        "BTCUSDT": SimpleNamespace(base_asset="BTC", underlying_type="COIN"),
        "AKEUSDT": SimpleNamespace(base_asset="AKE", underlying_type="COIN"),
        "SKHYNIXUSDT": SimpleNamespace(base_asset="SKHYNIX", underlying_type="EQUITY"),
    }
    closed_days = [
        [index, "10", "12", "8", "10", "100", index + 1, "1000"]
        for index in range(181)
    ]
    daily_klines = {symbol: [*closed_days, [182, "10", "11", "9", "10", "100", 183, "1000"]] for symbol in ("BTCUSDT", "AKEUSDT")}

    frame = app._build_breakout_universe_frame(ticker, symbol_meta, daily_klines).set_index("symbol")

    assert set(frame.index) == {"BTCUSDT", "AKEUSDT"}
    assert frame.loc["BTCUSDT", "history_status"] == "ready"
    assert frame.loc["BTCUSDT", "breakout_count"] == 8
    assert set(frame.loc["BTCUSDT", "breakout_flags"].split(" | ")) == {
        "5D high",
        "5D low",
        "20D high",
        "20D low",
        "90D high",
        "90D low",
        "180D high",
        "180D low",
    }


def test_breakout_universe_keeps_pairs_with_limited_daily_history() -> None:
    ticker = pd.DataFrame(
        [{"symbol": "NEWUSDT", "lastPrice": 1.0, "highPrice": 1.2, "lowPrice": 0.8, "quoteVolume": 5_000}]
    )
    symbol_meta = {"NEWUSDT": SimpleNamespace(base_asset="NEW", underlying_type="COIN")}
    daily_klines = {
        "NEWUSDT": [[index, "1", "1.1", "0.9", "1", "100", index + 1, "100"] for index in range(20)]
    }

    frame = app._build_breakout_universe_frame(ticker, symbol_meta, daily_klines)

    assert frame["symbol"].tolist() == ["NEWUSDT"]
    assert frame.iloc[0]["history_status"] == "limited"
    assert frame.iloc[0]["breakout_count"] == 2
    assert frame.iloc[0]["breakout_flags"] == "5D high | 5D low"


def test_display_frame_injects_sortable_hour_volume_roc_into_every_table() -> None:
    frame = pd.DataFrame([{"symbol": "AKEUSDT", "trade_bucket": "Watch", "hour_volume_roc_1h_pct": 125.0}])

    displayed = app._display_frame(frame, ["symbol", "trade_bucket"])

    assert displayed.columns.tolist() == ["symbol", "hour_volume_roc_1h_pct", "trade_bucket"]
    assert displayed.iloc[0]["hour_volume_roc_1h_pct"] == 125.0


def test_daily_quote_volume_30d_context_uses_prior_completed_days() -> None:
    rows = [
        [index, "0", "0", "0", "0", "0", index + 1, str((index + 1) * 1000)]
        for index in range(32)
    ]
    rows.append([33, "0", "0", "0", "0", "0", 34, "999999999"])

    metrics = app._daily_quote_volume_30d_context(rows, 49_500)

    assert metrics["quote_volume_prior_30d_days"] == 30
    assert metrics["quote_volume_prior_30d_total"] == sum(range(3, 33)) * 1000
    assert metrics["quote_volume_prior_30d_daily_avg"] == 17_500
    assert round(metrics["quote_volume_24h_vs_prior_30d_avg_ratio"], 6) == round(49_500 / 17_500, 6)


def test_dashboard_holder_chain_options_include_arbitrum() -> None:
    assert app.THESIS_HOLDER_CHAIN_LABEL == "ETH/BNB/ARB"
    assert app.THESIS_HOLDER_CHAIN_OPTIONS == ("ethereum", "bsc", "arbitrum")


def test_score_trade_buckets_requires_hard_thesis_before_convex_long(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_ASSUME_SYMBOLS_ARE_BINANCE_PERPS", raising=False)
    frame = pd.DataFrame(
        [
            {
                "symbol": "GOODUSDT",
                "pre_pump_candidate_flag": True,
                "top10_holder_pct": 94.0,
                "token_platform": "ethereum",
                "token_contract": "0x1111111111111111111111111111111111111111",
                "holder_source": "Etherscan holder endpoint",
                "binance_perp_universe": True,
                "bitget_volume_share_pct": 1.0,
                "history_days": 180,
                "recent_max_pump_60d_pct": 6.0,
                "recent_pump_60d_days": 60,
                "no_large_pump_60d_flag": True,
                "low_float_score": 82.0,
                "fdv_to_market_cap": 8.0,
                "short_account_pct": 63.0,
                "short_account_build_score": 52.0,
                "pre_pump_precision_score": 76.0,
            },
            {
                "symbol": "BASEONLYUSDT",
                "pre_pump_candidate_flag": True,
                "top10_holder_pct": 94.0,
                "token_platform": "ethereum",
                "token_contract": "0x3333333333333333333333333333333333333333",
                "holder_source": "Etherscan holder endpoint",
                "binance_perp_universe": True,
                "bitget_volume_share_pct": 1.0,
                "history_days": 180,
                "recent_max_pump_60d_pct": 6.0,
                "recent_pump_60d_days": 60,
                "no_large_pump_60d_flag": True,
                "short_account_pct": 63.0,
                "pre_pump_precision_score": 76.0,
            },
            {
                "symbol": "SOFTUSDT",
                "pre_pump_candidate_flag": True,
                "top10_holder_pct": 55.0,
                "binance_perp_universe": True,
                "bitget_volume_share_pct": 1.0,
                "history_days": 180,
                "recent_max_pump_60d_pct": 6.0,
                "recent_pump_60d_days": 60,
                "no_large_pump_60d_flag": True,
            },
        ]
    )

    scored = app._score_trade_buckets(frame).set_index("symbol")

    assert scored.loc["GOODUSDT", "trade_bucket"] == "Convex Long"
    assert bool(scored.loc["GOODUSDT", "raw_convex_long_signal"])
    assert bool(scored.loc["GOODUSDT", "thesis_base_gate"])
    assert bool(scored.loc["GOODUSDT", "thesis_gate"])
    assert bool(scored.loc["GOODUSDT", "thesis_core_gate"])
    assert bool(scored.loc["GOODUSDT", "thesis_float_gate"])
    assert bool(scored.loc["GOODUSDT", "thesis_short_squeeze_gate"])
    assert "thesis pass" in scored.loc["GOODUSDT", "trade_bucket_note"]
    assert scored.loc["BASEONLYUSDT", "trade_bucket"] == "Watch"
    assert bool(scored.loc["BASEONLYUSDT", "raw_convex_long_signal"])
    assert bool(scored.loc["BASEONLYUSDT", "thesis_base_gate"])
    assert not bool(scored.loc["BASEONLYUSDT", "thesis_gate"])
    assert "missing low-float/FDV evidence, short crowd+fuel" in scored.loc["BASEONLYUSDT", "thesis_gate_note"]
    assert scored.loc["SOFTUSDT", "trade_bucket"] == "Watch"
    assert bool(scored.loc["SOFTUSDT", "raw_convex_long_signal"])
    assert not bool(scored.loc["SOFTUSDT", "thesis_gate"])
    assert "missing top10 >= 90%" in scored.loc["SOFTUSDT", "trade_bucket_note"]


def test_score_trade_buckets_explains_missing_bitget_and_no_pump_proof(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_ASSUME_SYMBOLS_ARE_BINANCE_PERPS", raising=False)
    frame = pd.DataFrame(
        [
            {
                "symbol": "BLOCKEDUSDT",
                "pre_pump_candidate_flag": True,
                "top10_holder_pct": 96.0,
                "token_platform": "bsc",
                "token_contract": "0x2222222222222222222222222222222222222222",
                "holder_source": "BscScan holder endpoint",
                "binance_perp_universe": True,
                "history_days": 14,
                "recent_max_pump_60d_pct": 80.0,
                "recent_pump_60d_days": 14,
                "no_large_pump_60d_flag": False,
            }
        ]
    )

    scored = app._score_trade_buckets(frame).iloc[0]

    assert scored["trade_bucket"] == "Watch"
    assert bool(scored["raw_convex_long_signal"])
    assert bool(scored["thesis_holder_gate"])
    assert not bool(scored["thesis_venue_gate"])
    assert not bool(scored["thesis_no_pump_gate"])
    assert "missing Binance+Bitget, 60D no-pump proof" in scored["thesis_gate_note"]


def test_discord_convex_cache_candidates_require_full_thesis_gate(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_ASSUME_SYMBOLS_ARE_BINANCE_PERPS", raising=False)
    base = {
        "trade_bucket": "Convex Long",
        "trade_bucket_score": 90,
        "top10_holder_pct": 94.0,
        "token_platform": "ethereum",
        "holder_source": "Etherscan holder endpoint",
        "binance_perp_universe": True,
        "bitget_volume_share_pct": 1.0,
        "history_days": 180,
        "recent_max_pump_60d_pct": 6.0,
        "recent_pump_60d_days": 60,
        "no_large_pump_60d_flag": True,
    }
    frame = pd.DataFrame(
        [
            {
                **base,
                "symbol": "STALEBASEUSDT",
                "token_contract": "0x4444444444444444444444444444444444444444",
                "thesis_gate": False,
            },
            {
                **base,
                "symbol": "FULLCOREUSDT",
                "token_contract": "0x5555555555555555555555555555555555555555",
                "thesis_gate": True,
                "low_float_score": 82.0,
                "fdv_to_market_cap": 8.0,
                "short_account_pct": 63.0,
                "short_account_build_score": 52.0,
                "pre_pump_precision_score": 76.0,
                "pre_pump_candidate_flag": True,
            },
        ]
    )

    selected = app._discord_convex_candidates(frame)

    assert selected["symbol"].tolist() == ["FULLCOREUSDT"]
    assert bool(selected.iloc[0]["thesis_core_gate"])


def test_discord_convex_candidates_reject_stale_convex_long_without_current_core_gate(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_ASSUME_SYMBOLS_ARE_BINANCE_PERPS", raising=False)
    frame = pd.DataFrame(
        [
            {
                "symbol": "STALECOREUSDT",
                "trade_bucket": "Convex Long",
                "trade_bucket_score": 99,
                "thesis_gate": True,
                "thesis_core_gate": True,
                "top10_holder_pct": 94.0,
                "token_platform": "ethereum",
                "token_contract": "0x6666666666666666666666666666666666666666",
                "holder_source": "Etherscan holder endpoint",
                "binance_perp_universe": True,
                "bitget_volume_share_pct": 1.0,
                "history_days": 180,
                "recent_max_pump_60d_pct": 6.0,
                "recent_pump_60d_days": 60,
                "no_large_pump_60d_flag": True,
                "short_account_pct": 72.0,
            }
        ]
    )

    selected = app._discord_convex_candidates(frame)

    assert selected.empty


def test_dashboard_discord_candidate_line_prints_gate_proof(monkeypatch) -> None:
    monkeypatch.setattr(app, "_discord_holder_composition_text", lambda row: "")
    row = pd.Series(
        {
            "symbol": "PROOFUSDT",
            "trade_bucket_score": 88,
            "thesis_core_gate": True,
            "thesis_holder_gate": True,
            "thesis_venue_gate": True,
            "thesis_no_pump_gate": True,
            "top10_holder_pct": 94.0,
            "short_account_pct": 63.0,
            "low_float_score": 82.0,
            "cex_deposit_flow_score": 0,
        }
    )

    output = app._discord_candidate_line(row)

    assert output.startswith(
        "Dashboard gate: coreThesis Y | holder Y top10 94.0% | BnBg Y | noPump60 Y | shorts 63.0%"
    )
    assert "/PROOFUSDT" in output


def test_early_pump_dashboard_watch_requires_full_hard_gates() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "GOODUSDT",
                "early_pump_radar_score": 60.0,
                "early_pump_alert_flag": False,
                "early_pump_holder_evidence_gate": True,
                "early_pump_whale_gate": True,
                "early_pump_binance_bitget_gate": True,
                "early_pump_float_gate": True,
                "early_pump_short_gate": True,
                "early_pump_not_late_gate": True,
                "early_pump_no_recent_pump_gate": True,
            },
            {
                "symbol": "STALEALERTUSDT",
                "early_pump_radar_score": 88.0,
                "early_pump_alert_flag": True,
                "early_pump_holder_evidence_gate": True,
                "early_pump_whale_gate": True,
                "early_pump_binance_bitget_gate": False,
                "early_pump_float_gate": True,
                "early_pump_short_gate": True,
                "early_pump_not_late_gate": True,
                "early_pump_no_recent_pump_gate": True,
            },
            {
                "symbol": "DORMANTONLYUSDT",
                "early_pump_radar_score": 91.0,
                "early_pump_no_recent_pump_gate": True,
            },
        ]
    )

    selected = frame[app._early_pump_dashboard_watch_mask(frame)]

    assert selected["symbol"].tolist() == ["GOODUSDT"]


def test_pre_activity_dashboard_watch_requires_full_hard_gates() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "LATENTUSDT",
                "pre_activity_pump_score": 60.0,
                "pre_activity_alert_flag": False,
                "pre_activity_holder_evidence_gate": True,
                "pre_activity_whale_gate": True,
                "pre_activity_binance_bitget_gate": True,
                "pre_activity_float_gate": True,
                "pre_activity_structure_gate": True,
                "pre_activity_short_gate": True,
                "pre_activity_behavior_gate": True,
                "pre_activity_quiet_gate": True,
                "pre_activity_no_recent_pump_gate": True,
            },
            {
                "symbol": "NOFUELUSDT",
                "pre_activity_pump_score": 90.0,
                "pre_activity_alert_flag": True,
                "pre_activity_holder_evidence_gate": True,
                "pre_activity_whale_gate": True,
                "pre_activity_binance_bitget_gate": True,
                "pre_activity_float_gate": True,
                "pre_activity_structure_gate": True,
                "pre_activity_short_gate": False,
                "pre_activity_behavior_gate": True,
                "pre_activity_quiet_gate": True,
                "pre_activity_no_recent_pump_gate": True,
            },
            {
                "symbol": "DORMANTONLYUSDT",
                "pre_activity_pump_score": 92.0,
                "pre_activity_no_recent_pump_gate": True,
            },
        ]
    )

    selected = frame[app._pre_activity_dashboard_watch_mask(frame)]

    assert selected["symbol"].tolist() == ["LATENTUSDT"]


def test_crowded_short_uptrend_candidates_require_funding_shorts_build_and_trend() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "WINUSDT",
                "base_asset": "WIN",
                "market_type": "CRYPTO",
                "carry_funding_pct": 0.012,
                "predicted_funding_pct": 0.018,
                "short_account_pct": 62.0,
                "short_account_roc_1h_pp": 1.2,
                "short_account_change_max_pp": 2.0,
                "short_account_change_max_pct": 4.0,
                "short_account_change_max_window": "3p",
                "broke_high_20d": True,
                "range_high_break_count": 1,
                "day_return_pct": 12.0,
                "oi_delta_pct": 4.0,
                "quote_volume_24h": 1_000_000,
            },
            {
                "symbol": "NOFUNDUSDT",
                "market_type": "CRYPTO",
                "carry_funding_pct": -0.010,
                "predicted_funding_pct": -0.006,
                "short_account_pct": 68.0,
                "short_account_roc_1h_pp": 2.0,
                "broke_high_20d": True,
                "day_return_pct": 14.0,
            },
            {
                "symbol": "NOBUILDUSDT",
                "market_type": "CRYPTO",
                "carry_funding_pct": 0.020,
                "short_account_pct": 66.0,
                "short_account_roc_1h_pp": 0.0,
                "short_account_change_max_pp": 0.0,
                "short_account_change_max_pct": 0.0,
                "broke_high_20d": True,
                "day_return_pct": 10.0,
            },
            {
                "symbol": "EQUITYUSDT",
                "market_type": "EQUITY",
                "carry_funding_pct": 0.020,
                "short_account_pct": 66.0,
                "short_account_roc_1h_pp": 2.0,
                "broke_high_20d": True,
                "day_return_pct": 10.0,
            },
        ]
    )

    selected = app._crowded_short_uptrend_candidates(frame)

    assert selected["symbol"].tolist() == ["WINUSDT"]
    row = selected.iloc[0]
    assert bool(row["crowded_short_uptrend_funding_gate"])
    assert bool(row["crowded_short_uptrend_short_gate"])
    assert bool(row["crowded_short_uptrend_build_gate"])
    assert bool(row["crowded_short_uptrend_trend_gate"])
    assert "funding 0.0180%" in row["crowded_short_uptrend_note"]
    assert "shorts 62.0%" in row["crowded_short_uptrend_note"]

    scored_all = app._crowded_short_uptrend_candidates(frame, min_funding_pct=-1.0, return_all=True)

    assert "NOFUNDUSDT" in scored_all["symbol"].tolist()
    assert "EQUITYUSDT" not in scored_all["symbol"].tolist()


def test_cex_flow_dashboard_promotes_whale_sender_provenance() -> None:
    whale_sender_columns = set(app.CEX_FLOW_WHALE_SENDER_COLUMNS)
    whale_sender_index = app.CEX_FLOW_DASHBOARD_COLUMNS.index("cex_deposit_24h_whale_sender_count")

    assert whale_sender_columns.issubset(app.CEX_FLOW_DASHBOARD_COLUMNS)
    assert whale_sender_columns.issubset(app.CEX_FLOW_DIAGNOSTIC_COLUMNS)
    assert whale_sender_index > app.CEX_FLOW_DASHBOARD_COLUMNS.index("cex_deposit_24h_token_amount")
    assert whale_sender_index < app.CEX_FLOW_DASHBOARD_COLUMNS.index("cex_deposit_24h_notional_usd")
