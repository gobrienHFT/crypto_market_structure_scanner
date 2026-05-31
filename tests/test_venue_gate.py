from __future__ import annotations

import pandas as pd

from venue_gate import apply_binance_bitget_venue_gate, apply_thesis_alert_gate, binance_bitget_venue_header, thesis_alert_header


THESIS_PUMP_PROOF = {
    "history_days": 180,
    "recent_max_pump_60d_pct": 6.0,
    "recent_pump_60d_days": 60,
    "no_large_pump_60d_flag": True,
}


def test_binance_bitget_venue_gate_rejects_gate_only_rows(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_REQUIRE_BITGET_OR_GATE", raising=False)
    frame = pd.DataFrame(
        [
            {"symbol": "GATEONLYUSDT", "trade_bucket_score": 90, "gate_volume_share_pct": 4.0},
            {"symbol": "TARGETONLYUSDT", "trade_bucket_score": 88, "cex_deposit_24h_target_exchanges": "Bitget"},
            {"symbol": "BITGETUSDT", "trade_bucket_score": 86, "binance_perp_universe": True, "bitget_volume_share_pct": 0.5},
        ]
    )

    selected = apply_binance_bitget_venue_gate(frame, allow_cex_flow_targets=True)

    assert selected["symbol"].tolist() == ["BITGETUSDT"]


def test_binance_bitget_venue_gate_can_require_explicit_binance_evidence(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_REQUIRE_BITGET_OR_GATE", raising=False)
    monkeypatch.setenv("DISCORD_ASSUME_SYMBOLS_ARE_BINANCE_PERPS", "0")
    frame = pd.DataFrame(
        [
            {"symbol": "SYMBOLONLYUSDT", "trade_bucket_score": 90, "bitget_volume_share_pct": 1.0},
            {"symbol": "MARKEDUSDT", "trade_bucket_score": 89, "binance_perp_universe": True, "bitget_volume_share_pct": 1.0},
            {"symbol": "SHAREUSDT", "trade_bucket_score": 88, "binance_volume_share_pct": 0.1, "bitget_volume_share_pct": 1.0},
            {"symbol": "GATEUSDT", "trade_bucket_score": 87, "binance_perp_universe": True, "gate_volume_share_pct": 3.0},
        ]
    )

    selected = apply_binance_bitget_venue_gate(frame)

    assert selected["symbol"].tolist() == ["MARKEDUSDT", "SHAREUSDT"]


def test_binance_bitget_venue_header_treats_gate_as_optional(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_REQUIRE_BITGET_OR_GATE", raising=False)

    header = binance_bitget_venue_header(allow_cex_flow_targets=True)

    assert "Binance perp + Bitget trading evidence required" in header
    assert "Gate optional" in header
    assert "transfer targets are supporting evidence only" in header
    assert "explicit Binance perp marker/share" in header


def test_thesis_alert_header_names_holder_and_venue_gates(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_REQUIRE_BITGET_OR_GATE", raising=False)

    header = thesis_alert_header(allow_cex_flow_targets=True)

    assert "Holder gate: observed top10 holder concentration >= 90.0%" in header
    assert "ETH/BNB/ARB chain+contract explorer holder-source snapshot evidence" in header
    assert "60D no-pump proof required" in header
    assert "Binance perp + Bitget trading evidence required" in header
    assert "Gate optional" in header


def test_thesis_alert_gate_requires_holder_evidence_and_binance_bitget(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_REQUIRE_BITGET_OR_GATE", raising=False)
    frame = pd.DataFrame(
        [
            {
                "symbol": "GOODUSDT",
                "trade_bucket_score": 90,
                "binance_perp_universe": True,
                "bitget_volume_share_pct": 1.0,
                "token_platform": "ethereum",
                "token_contract": "0x1111111111111111111111111111111111111111",
                "holder_source": "Etherscan holder endpoint",
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 99.0,
                **THESIS_PUMP_PROOF,
            },
            {
                "symbol": "PCTONLYUSDT",
                "trade_bucket_score": 95,
                "bitget_volume_share_pct": 1.0,
                "top100_holder_pct": 99.0,
            },
            {
                "symbol": "TOP100ONLYUSDT",
                "trade_bucket_score": 95,
                "bitget_volume_share_pct": 1.0,
                "token_platform": "ethereum",
                "token_contract": "0x6666666666666666666666666666666666666666",
                "holder_source": "Etherscan holder endpoint",
                "top10_holder_pct": 55.0,
                "top100_holder_pct": 99.0,
            },
            {
                "symbol": "SOURCELESSUSDT",
                "trade_bucket_score": 94.5,
                "bitget_volume_share_pct": 1.0,
                "token_platform": "ethereum",
                "token_contract": "0x5555555555555555555555555555555555555555",
                "holder_count": 6_000,
                "top10_holder_pct": 95.0,
                "top100_holder_pct": 99.0,
            },
            {
                "symbol": "GOPLUSONLYUSDT",
                "trade_bucket_score": 94.2,
                "binance_perp_universe": True,
                "bitget_volume_share_pct": 1.0,
                "token_platform": "ethereum",
                "token_contract": "0x7777777777777777777777777777777777777777",
                "holder_source": "GoPlus token security",
                "holder_count": 6_000,
                "top10_holder_pct": 95.0,
                "top100_holder_pct": 99.0,
                **THESIS_PUMP_PROOF,
            },
            {
                "symbol": "BASEUSDT",
                "trade_bucket_score": 94,
                "bitget_volume_share_pct": 1.0,
                "token_platform": "base",
                "token_contract": "0x2222222222222222222222222222222222222222",
                "holder_source": "BaseScan holder endpoint",
                "top10_holder_pct": 95.0,
                "top100_holder_pct": 99.0,
            },
            {
                "symbol": "LOWWHALEUSDT",
                "trade_bucket_score": 93,
                "bitget_volume_share_pct": 1.0,
                "token_platform": "ethereum",
                "token_contract": "0x3333333333333333333333333333333333333333",
                "holder_source": "Etherscan holder endpoint",
                "top10_holder_pct": 89.9,
                "top100_holder_pct": 89.9,
            },
            {
                "symbol": "GATEONLYUSDT",
                "trade_bucket_score": 92,
                "gate_volume_share_pct": 3.0,
                "token_platform": "ethereum",
                "token_contract": "0x4444444444444444444444444444444444444444",
                "holder_source": "Etherscan holder endpoint",
                "top10_holder_pct": 95.0,
                "top100_holder_pct": 99.0,
            },
        ]
    )

    selected = apply_thesis_alert_gate(frame)

    assert selected["symbol"].tolist() == ["GOODUSDT"]


def test_thesis_alert_gate_requires_60d_no_pump_proof(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_REQUIRE_BITGET_OR_GATE", raising=False)
    base = {
        "trade_bucket_score": 90,
        "binance_perp_universe": True,
        "bitget_volume_share_pct": 1.0,
        "token_platform": "ethereum",
        "token_contract": "0x1111111111111111111111111111111111111111",
        "holder_source": "Etherscan holder endpoint",
        "top10_holder_pct": 91.0,
        "top100_holder_pct": 99.0,
    }
    frame = pd.DataFrame(
        [
            {"symbol": "CLEANUSDT", **base, **THESIS_PUMP_PROOF},
            {
                "symbol": "PUMPEDUSDT",
                **base,
                "history_days": 180,
                "recent_max_pump_60d_pct": 82.0,
                "recent_pump_60d_days": 60,
                "no_large_pump_60d_flag": False,
            },
            {"symbol": "MISSINGUSDT", **base},
        ]
    )

    selected = apply_thesis_alert_gate(frame)

    assert selected["symbol"].tolist() == ["CLEANUSDT"]


def test_thesis_alert_gate_ignores_disabled_generic_venue_env(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_REQUIRE_BITGET_OR_GATE", "0")
    frame = pd.DataFrame(
        [
            {
                "symbol": "GOODUSDT",
                "binance_perp_universe": True,
                "bitget_volume_share_pct": 1.0,
                "token_platform": "ethereum",
                "token_contract": "0x1111111111111111111111111111111111111111",
                "holder_source": "Etherscan holder endpoint",
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 99.0,
                **THESIS_PUMP_PROOF,
            },
            {
                "symbol": "GATEONLYUSDT",
                "gate_volume_share_pct": 3.0,
                "token_platform": "ethereum",
                "token_contract": "0x2222222222222222222222222222222222222222",
                "holder_source": "Etherscan holder endpoint",
                "top10_holder_pct": 95.0,
                "top100_holder_pct": 99.0,
            },
        ]
    )

    selected = apply_thesis_alert_gate(frame)
    header = thesis_alert_header()

    assert selected["symbol"].tolist() == ["GOODUSDT"]
    assert "Venue gate: disabled" not in header
    assert "Binance perp + Bitget trading evidence required" in header
