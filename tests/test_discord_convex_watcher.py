import pandas as pd

import discord_convex_watcher as watcher


THESIS_PUMP_PROOF = {
    "binance_perp_universe": True,
    "history_days": 180,
    "recent_max_pump_60d_pct": 6.0,
    "recent_pump_60d_days": 60,
    "no_large_pump_60d_flag": True,
}


def test_terminal_timing_alert_source_requires_both_scores(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_WATCHER_MIN_TERMINAL_SCORE", "60")
    monkeypatch.setenv("DISCORD_WATCHER_MIN_TIMING_SCORE", "55")
    frame = pd.DataFrame(
        [
            {
                "symbol": "BOTHUSDT",
                "terminal_edge_score": 72,
                "timing_score": 64,
                "timing_state": "Triggering",
                "centralized_ownership_score": 80,
                "low_float_score": 75,
                "float_trap_score": 70,
                "short_dominance_score": 85,
                "short_account_build_score": 70,
                "short_liquidation_fuel_score": 65,
                "price_volume_ignition_score": 70,
                "convexity_preignition_score": 65,
                "convexity_runway_score": 80,
                "clean_convex_setup_score": 70,
                "short_account_pct": 62,
                "oi_delta_pct": 3.2,
                "hour_return_pct": 2.4,
                "hour_volume_multiple": 2.1,
                "hour_trade_count_multiple": 1.8,
                "hour_close_location_pct": 78,
                "distance_to_high_5d_pct": 1.5,
                "bitget_volume_share_pct": 6.5,
                **THESIS_PUMP_PROOF,
                "token_platform": "ethereum",
                "token_contract": "0x1111111111111111111111111111111111111111",
                "holder_source": "Etherscan holder endpoint",
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 99.0,
            },
            {
                "symbol": "TERMONLYUSDT",
                "terminal_edge_score": 81,
                "timing_score": 30,
                "timing_state": "Coiling",
                "centralized_ownership_score": 90,
                "low_float_score": 90,
                "float_trap_score": 90,
                "convexity_runway_score": 80,
                "short_account_pct": 35,
                "oi_delta_pct": 0.0,
                "hour_return_pct": 0.0,
            },
            {
                "symbol": "TIMEONLYUSDT",
                "terminal_edge_score": 42,
                "timing_score": 80,
                "timing_state": "Confirmed",
                "centralized_ownership_score": 5,
                "low_float_score": 5,
                "short_account_pct": 65,
                "oi_delta_pct": 4.0,
                "hour_return_pct": 2.0,
                "hour_volume_multiple": 3.0,
                "hour_trade_count_multiple": 2.0,
                "hour_close_location_pct": 80,
            },
            {
                "symbol": "LATEUSDT",
                "terminal_edge_score": 84,
                "timing_score": 78,
                "timing_state": "Extended / fragile",
                "centralized_ownership_score": 90,
                "low_float_score": 90,
                "float_trap_score": 90,
                "short_dominance_score": 80,
                "price_volume_ignition_score": 80,
                "short_account_pct": 65,
                "oi_delta_pct": 4.0,
                "hour_return_pct": 26.0,
                "day_return_pct": 120.0,
                "hour_volume_multiple": 7.0,
                "hour_upper_wick_pct": 48.0,
                "hour_close_location_pct": 28.0,
                "convexity_late_penalty": 85.0,
            },
        ]
    )

    selected = watcher._select_alert_candidates(frame, alert_source="terminal_timing", top_n=10)

    assert selected["symbol"].tolist() == ["BOTHUSDT"]
    assert float(selected.iloc[0]["watcher_alert_score"]) > 0


def test_timing_alert_source_excludes_fragile_states(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_WATCHER_MIN_TIMING_SCORE", "55")
    frame = pd.DataFrame(
        [
            {
                "symbol": "GOODUSDT",
                "terminal_edge_score": 42,
                "timing_score": 74,
                "timing_state": "Triggering",
                "short_account_pct": 65,
                "oi_delta_pct": 3.0,
                "hour_return_pct": 2.0,
                "hour_volume_multiple": 2.5,
                "hour_trade_count_multiple": 2.0,
                "hour_close_location_pct": 82,
                "gate_volume_share_pct": 4.0,
                "bitget_volume_share_pct": 1.0,
                **THESIS_PUMP_PROOF,
                "token_platform": "ethereum",
                "token_contract": "0x2222222222222222222222222222222222222222",
                "holder_source": "Etherscan holder endpoint",
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 99.0,
            },
            {
                "symbol": "BADUSDT",
                "terminal_edge_score": 82,
                "timing_score": 76,
                "timing_state": "Extended / fragile",
                "short_account_pct": 65,
                "oi_delta_pct": -2.0,
                "hour_return_pct": 26.0,
                "day_return_pct": 120,
                "hour_volume_multiple": 7.0,
                "hour_upper_wick_pct": 48,
                "hour_close_location_pct": 28,
                "convexity_late_penalty": 90,
            },
        ]
    )

    selected = watcher._select_alert_candidates(frame, alert_source="timing", top_n=10)

    assert selected["symbol"].tolist() == ["GOODUSDT"]


def test_terminal_alert_source_sorts_by_terminal_score(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_WATCHER_MIN_TERMINAL_SCORE", "50")
    frame = pd.DataFrame(
        [
            {
                "symbol": "LOWUSDT",
                "terminal_edge_score": 58,
                "centralized_ownership_score": 65,
                "low_float_score": 60,
                "float_trap_score": 60,
                "short_dominance_score": 55,
                "bitget_volume_share_pct": 2.0,
                **THESIS_PUMP_PROOF,
                "token_platform": "ethereum",
                "token_contract": "0x3333333333333333333333333333333333333333",
                "holder_source": "Etherscan holder endpoint",
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 95.0,
            },
            {
                "symbol": "HIGHUSDT",
                "terminal_edge_score": 81,
                "centralized_ownership_score": 90,
                "low_float_score": 90,
                "float_trap_score": 90,
                "short_dominance_score": 80,
                "pre_pump_precision_flag": True,
                "gate_volume_share_pct": 8.0,
                "bitget_volume_share_pct": 2.0,
                **THESIS_PUMP_PROOF,
                "token_platform": "bsc",
                "token_contract": "0x4444444444444444444444444444444444444444",
                "holder_source": "BscScan holder endpoint",
                "top10_holder_pct": 92.0,
                "top100_holder_pct": 99.0,
            },
        ]
    )

    selected = watcher._select_alert_candidates(frame, alert_source="terminal", top_n=10)

    assert selected["symbol"].tolist() == ["HIGHUSDT", "LOWUSDT"]


def test_cex_flow_alert_source_uses_concentration_gated_flow(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_WATCHER_MIN_CEX_FLOW_SCORE", "50")
    frame = pd.DataFrame(
        [
            {
                "symbol": "LOWUSDT",
                "cex_deposit_flow_score": 20,
                "cex_deposit_flow_flag": False,
                "cex_deposit_24h_total_pct_supply": 9,
                "cex_deposit_24h_count": 10,
            },
            {
                "symbol": "PLAYUSDT",
                "cex_deposit_flow_score": 88,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_total_pct_supply": 2.5,
                "cex_deposit_24h_count": 3,
                "cex_deposit_24h_target_exchanges": "Bitget",
                "bitget_volume_share_pct": 1.0,
                **THESIS_PUMP_PROOF,
                "token_platform": "ethereum",
                "token_contract": "0x5555555555555555555555555555555555555555",
                "holder_source": "Etherscan holder endpoint",
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 99.0,
            },
            {
                "symbol": "WATCHUSDT",
                "cex_deposit_flow_score": 60,
                "cex_deposit_flow_flag": False,
                "cex_deposit_24h_total_pct_supply": 1.2,
                "cex_deposit_24h_count": 1,
                "cex_deposit_24h_target_exchanges": "GateIO",
                "gate_volume_share_pct": 1.0,
            },
            {
                "symbol": "TARGETONLYUSDT",
                "cex_deposit_flow_score": 91,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_total_pct_supply": 3.1,
                "cex_deposit_24h_count": 2,
                "cex_deposit_24h_target_exchanges": "Binance, Bitget",
                **THESIS_PUMP_PROOF,
                "token_platform": "ethereum",
                "token_contract": "0x7777777777777777777777777777777777777777",
                "holder_source": "Etherscan holder endpoint",
                "top10_holder_pct": 92.0,
                "top100_holder_pct": 99.0,
            },
        ]
    )

    selected = watcher._select_alert_candidates(frame, alert_source="cex_flow", top_n=10)

    assert selected["symbol"].tolist() == ["PLAYUSDT"]
    assert float(selected.iloc[0]["watcher_alert_score"]) == 88.0


def test_cex_flow_watcher_cards_use_flow_format(monkeypatch) -> None:
    monkeypatch.setattr(watcher, "_holder_composition_text", lambda row: "")
    frame = pd.DataFrame(
        [
            {
                "symbol": "PLAYUSDT",
                "watcher_alert_source": "cex_flow",
                "cex_deposit_flow_score": 88,
                "cex_deposit_flow_flag": True,
                "cex_deposit_flow_risk_level": "High",
                "cex_deposit_24h_count": 3,
                "cex_deposit_24h_token_amount": 2_500_000,
                "cex_deposit_24h_max_amount": 1_200_000,
                "cex_deposit_24h_total_pct_supply": 2.5,
                "cex_deposit_24h_target_exchanges": "Bitget",
                "cex_deposit_concentration_gate": "top10 91.0% / top100 99.0%",
            }
        ]
    )

    cards, archive = watcher._candidate_cards_and_archive_rows(frame)

    assert len(cards) == 1
    assert "CEX Flow Score: 88/100 | Risk: High" in cards[0]
    assert "Venue-flow read:" in cards[0]
    assert "Next check:" in cards[0]
    assert archive.iloc[0]["_raw_bot_output"] == cards[0]


def test_terminal_alert_source_requires_binance_bitget_by_default(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_REQUIRE_BITGET_OR_GATE", raising=False)
    monkeypatch.setenv("DISCORD_WATCHER_MIN_TERMINAL_SCORE", "50")
    frame = pd.DataFrame(
        [
            {"symbol": "NOBITGETUSDT", "terminal_edge_score": 90},
            {"symbol": "GATEONLYUSDT", "terminal_edge_score": 85, "gate_volume_share_pct": 1.0},
            {
                "symbol": "BITGETUSDT",
                "terminal_edge_score": 80,
                "bitget_volume_share_pct": 0.1,
                **THESIS_PUMP_PROOF,
                "token_platform": "arbitrum",
                "token_contract": "0x6666666666666666666666666666666666666666",
                "holder_source": "Arbiscan holder endpoint",
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 99.0,
            },
        ]
    )

    selected = watcher._select_alert_candidates(frame, alert_source="terminal", top_n=10)

    assert selected["symbol"].tolist() == ["BITGETUSDT"]
