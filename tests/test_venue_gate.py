from __future__ import annotations

import pandas as pd

from venue_gate import apply_binance_bitget_venue_gate, apply_thesis_alert_gate, binance_bitget_venue_header, thesis_alert_header


def test_binance_bitget_venue_gate_rejects_gate_only_rows(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_REQUIRE_BITGET_OR_GATE", raising=False)
    frame = pd.DataFrame(
        [
            {"symbol": "GATEONLYUSDT", "trade_bucket_score": 90, "gate_volume_share_pct": 4.0},
            {"symbol": "TARGETONLYUSDT", "trade_bucket_score": 88, "cex_deposit_24h_target_exchanges": "Bitget"},
            {"symbol": "BITGETUSDT", "trade_bucket_score": 86, "bitget_volume_share_pct": 0.5},
        ]
    )

    selected = apply_binance_bitget_venue_gate(frame, allow_cex_flow_targets=True)

    assert selected["symbol"].tolist() == ["BITGETUSDT"]


def test_binance_bitget_venue_header_treats_gate_as_optional(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_REQUIRE_BITGET_OR_GATE", raising=False)

    header = binance_bitget_venue_header(allow_cex_flow_targets=True)

    assert "Binance perp + Bitget trading evidence required" in header
    assert "Gate optional" in header
    assert "transfer targets are supporting evidence only" in header


def test_thesis_alert_header_names_holder_and_venue_gates(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_REQUIRE_BITGET_OR_GATE", raising=False)

    header = thesis_alert_header(allow_cex_flow_targets=True)

    assert "Holder gate: observed top-holder concentration >= 90.0%" in header
    assert "ETH/BNB/ARB chain+contract source/count evidence" in header
    assert "Binance perp + Bitget trading evidence required" in header
    assert "Gate optional" in header


def test_thesis_alert_gate_requires_holder_evidence_and_binance_bitget(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_REQUIRE_BITGET_OR_GATE", raising=False)
    frame = pd.DataFrame(
        [
            {
                "symbol": "GOODUSDT",
                "trade_bucket_score": 90,
                "bitget_volume_share_pct": 1.0,
                "token_platform": "ethereum",
                "token_contract": "0x1111111111111111111111111111111111111111",
                "holder_source": "Etherscan holder endpoint",
                "top100_holder_pct": 99.0,
            },
            {
                "symbol": "PCTONLYUSDT",
                "trade_bucket_score": 95,
                "bitget_volume_share_pct": 1.0,
                "top100_holder_pct": 99.0,
            },
            {
                "symbol": "BASEUSDT",
                "trade_bucket_score": 94,
                "bitget_volume_share_pct": 1.0,
                "token_platform": "base",
                "token_contract": "0x2222222222222222222222222222222222222222",
                "holder_source": "BaseScan holder endpoint",
                "top100_holder_pct": 99.0,
            },
            {
                "symbol": "LOWWHALEUSDT",
                "trade_bucket_score": 93,
                "bitget_volume_share_pct": 1.0,
                "token_platform": "ethereum",
                "token_contract": "0x3333333333333333333333333333333333333333",
                "holder_source": "Etherscan holder endpoint",
                "top100_holder_pct": 89.9,
            },
            {
                "symbol": "GATEONLYUSDT",
                "trade_bucket_score": 92,
                "gate_volume_share_pct": 3.0,
                "token_platform": "ethereum",
                "token_contract": "0x4444444444444444444444444444444444444444",
                "holder_source": "Etherscan holder endpoint",
                "top100_holder_pct": 99.0,
            },
        ]
    )

    selected = apply_thesis_alert_gate(frame)

    assert selected["symbol"].tolist() == ["GOODUSDT"]
