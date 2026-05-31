from __future__ import annotations

import os

import pandas as pd


os.environ["CRYPTO_SCANNER_IMPORT_ONLY"] = "1"

import app


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
    assert bool(scored.loc["GOODUSDT", "thesis_gate"])
    assert "thesis pass" in scored.loc["GOODUSDT", "trade_bucket_note"]
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


def test_cex_flow_dashboard_promotes_whale_sender_provenance() -> None:
    whale_sender_columns = set(app.CEX_FLOW_WHALE_SENDER_COLUMNS)
    whale_sender_index = app.CEX_FLOW_DASHBOARD_COLUMNS.index("cex_deposit_24h_whale_sender_count")

    assert whale_sender_columns.issubset(app.CEX_FLOW_DASHBOARD_COLUMNS)
    assert whale_sender_columns.issubset(app.CEX_FLOW_DIAGNOSTIC_COLUMNS)
    assert whale_sender_index > app.CEX_FLOW_DASHBOARD_COLUMNS.index("cex_deposit_24h_token_amount")
    assert whale_sender_index < app.CEX_FLOW_DASHBOARD_COLUMNS.index("cex_deposit_24h_notional_usd")
