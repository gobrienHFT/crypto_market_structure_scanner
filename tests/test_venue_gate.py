from __future__ import annotations

import pandas as pd

from venue_gate import apply_binance_bitget_venue_gate, binance_bitget_venue_header


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
