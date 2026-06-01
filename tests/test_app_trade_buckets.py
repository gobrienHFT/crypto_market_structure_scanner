from __future__ import annotations

import os

import pandas as pd


os.environ["CRYPTO_SCANNER_IMPORT_ONLY"] = "1"

import app


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


def test_cex_flow_dashboard_promotes_whale_sender_provenance() -> None:
    whale_sender_columns = set(app.CEX_FLOW_WHALE_SENDER_COLUMNS)
    whale_sender_index = app.CEX_FLOW_DASHBOARD_COLUMNS.index("cex_deposit_24h_whale_sender_count")

    assert whale_sender_columns.issubset(app.CEX_FLOW_DASHBOARD_COLUMNS)
    assert whale_sender_columns.issubset(app.CEX_FLOW_DIAGNOSTIC_COLUMNS)
    assert whale_sender_index > app.CEX_FLOW_DASHBOARD_COLUMNS.index("cex_deposit_24h_token_amount")
    assert whale_sender_index < app.CEX_FLOW_DASHBOARD_COLUMNS.index("cex_deposit_24h_notional_usd")
