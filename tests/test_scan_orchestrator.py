from __future__ import annotations

import pandas as pd
import sys
from types import SimpleNamespace

from market_structure_scoring import apply_lifecycle_model as apply_market_structure_model
from scan_orchestrator import run_scanner_scan, select_convex_long_candidates


def test_select_convex_long_candidates_applies_score_and_venue_gate(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_REQUIRE_BITGET_OR_GATE", raising=False)
    frame = pd.DataFrame(
        [
            {"symbol": "LOWUSDT", "trade_bucket": "Convex Long", "trade_bucket_score": 15, "bitget_volume_share_pct": 2.0},
            {"symbol": "NOGATEUSDT", "trade_bucket": "Convex Long", "trade_bucket_score": 99},
            {"symbol": "GOODUSDT", "trade_bucket": "Convex Long", "trade_bucket_score": 80, "gate_volume_share_pct": 1.0},
            {"symbol": "WATCHUSDT", "trade_bucket": "Watch", "trade_bucket_score": 95, "bitget_volume_share_pct": 5.0},
        ]
    )

    selected = select_convex_long_candidates(frame, min_score=50)

    assert selected["symbol"].tolist() == ["GOODUSDT"]


def test_market_structure_scoring_alias_keeps_legacy_model_compatible() -> None:
    frame = pd.DataFrame([{"symbol": "TESTUSDT", "crime_excluded_major": False}])

    scored = apply_market_structure_model(frame)

    assert "crime_pump_score_v2" in scored.columns
    assert "why_flagged_summary" in scored.columns


def test_run_scanner_scan_temporarily_overrides_cex_flow_threshold(monkeypatch) -> None:
    observed: dict[str, float] = {}

    fake_app = SimpleNamespace(
        CEX_DEPOSIT_FLOW_MIN_TRANSFER_TOKENS=500_000.0,
        CEX_DEPOSIT_FLOW_LOOKBACK_HOURS=24,
        DISCORD_CONVEX_ALERT_MIN_SCORE=0.0,
    )

    def run_scan(_refresh_nonce: int, _scan_mode: str):
        observed["min_transfer"] = fake_app.CEX_DEPOSIT_FLOW_MIN_TRANSFER_TOKENS
        observed["lookback"] = fake_app.CEX_DEPOSIT_FLOW_LOOKBACK_HOURS
        return pd.DataFrame(), pd.DataFrame(
            [
                {
                    "symbol": "FLOWUSDT",
                    "trade_bucket": "Convex Long",
                    "trade_bucket_score": 80,
                    "gate_volume_share_pct": 1.0,
                }
            ]
        )

    fake_app.run_scan = run_scan
    fake_app._write_latest_convex_longs_cache = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "app", fake_app)

    result = run_scanner_scan(
        "Deep",
        refresh_nonce=1,
        cex_min_transfer_tokens=20_000,
        cex_lookback_hours=12,
    )

    assert observed == {"min_transfer": 20_000, "lookback": 12}
    assert "CEX min transfer 20000 tokens" in result.source
    assert fake_app.CEX_DEPOSIT_FLOW_MIN_TRANSFER_TOKENS == 500_000.0
    assert fake_app.CEX_DEPOSIT_FLOW_LOOKBACK_HOURS == 24
