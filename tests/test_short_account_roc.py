from __future__ import annotations

from pathlib import Path

import pandas as pd

from binance_futures import FuturesSymbol
from short_account_roc import (
    ShortAccountRocConfig,
    active_signal_keys,
    build_discord_payload,
    build_short_account_roc_row,
    flagged_frame,
    scan_short_account_roc,
    short_account_history_stats,
)


def _ratio(timestamp: int, short: float) -> dict[str, object]:
    long = 1.0 - short
    return {
        "timestamp": timestamp,
        "longShortRatio": long / short if short else 0.0,
        "longAccount": str(long),
        "shortAccount": str(short),
    }


def _symbol(symbol: str = "TESTUSDT") -> FuturesSymbol:
    return FuturesSymbol(symbol=symbol, base_asset=symbol.replace("USDT", ""), quote_asset="USDT", underlying_type="COIN")


def test_short_account_history_stats_exposes_1h_roc_aliases() -> None:
    stats = short_account_history_stats(
        [
            _ratio(1, 0.52),
            _ratio(2, 0.55),
            _ratio(3, 0.58),
        ],
        windows=(1, 2),
    )

    assert stats["short_account_history_points"] == 3
    assert round(float(stats["short_account_previous_1h_pct"]), 6) == 55.0
    assert round(float(stats["short_account_roc_1h_pp"]), 6) == 3.0
    assert round(float(stats["short_account_roc_1h_pct"]), 6) == round((58.0 / 55.0 - 1.0) * 100.0, 6)
    assert stats["short_account_roc_1h_direction"] == "build"


def test_short_account_roc_row_and_flags_cover_builds_and_covers() -> None:
    build = build_short_account_roc_row(
        futures_symbol=_symbol("BUILDUSDT"),
        ratio_rows=[_ratio(1, 0.50), _ratio(2, 0.535)],
        ticker={"lastPrice": "1.2", "quoteVolume": "1000000"},
    )
    cover = build_short_account_roc_row(
        futures_symbol=_symbol("COVERUSDT"),
        ratio_rows=[_ratio(1, 0.62), _ratio(2, 0.58)],
        ticker={"lastPrice": "2.4", "quoteVolume": "2000000"},
    )
    quiet = build_short_account_roc_row(
        futures_symbol=_symbol("QUIETUSDT"),
        ratio_rows=[_ratio(1, 0.51), _ratio(2, 0.512)],
        ticker={"lastPrice": "0.4", "quoteVolume": "500000"},
    )

    frame = pd.DataFrame([build, cover, quiet])
    flagged = flagged_frame(frame, min_abs_pp=1.5, min_abs_pct=3.0, top_n=10)
    keys = active_signal_keys(frame, min_abs_pp=1.5, min_abs_pct=3.0)

    assert flagged["symbol"].tolist() == ["COVERUSDT", "BUILDUSDT"]
    assert keys == {"BUILDUSDT:build", "COVERUSDT:cover"}


def test_short_account_discord_payload_labels_state_diff_rows() -> None:
    row = build_short_account_roc_row(
        futures_symbol=_symbol("BUILDUSDT"),
        ratio_rows=[_ratio(1, 0.50), _ratio(2, 0.535)],
        ticker={"lastPrice": "1.2", "quoteVolume": "1000000"},
    )
    config = ShortAccountRocConfig(
        base_url="https://example.test",
        timeout=1,
        retries=0,
        requests_per_second=1,
        interval_seconds=60,
        max_symbols=0,
        symbols=(),
        period="1h",
        history_limit=2,
        min_abs_pp=1.5,
        min_abs_pct=3.0,
        min_quote_volume=0,
        top_n=25,
        realert_hours=6,
        output_dir=Path("."),
        webhook_url="",
        once=True,
        dry_run=True,
        write_full_scan=True,
        suppress_initial_alerts=False,
    )

    payload = build_discord_payload(pd.DataFrame([row]), config, flagged_count=25)
    description = payload["embeds"][0]["description"]

    assert "New/re-alert rows: 1 | Flagged snapshot: 25" in description
    assert "state-diff alerts only" in description
    assert "/BUILDUSDT" in description
    assert "vol24 $1.00M" in description


def test_scan_short_account_roc_uses_quote_volume_filter_and_history() -> None:
    class FakeClient:
        def perpetual_usdt_symbols(self):
            return [_symbol("AAAUSDT"), _symbol("BBBUSDT")]

        def ticker_24hr(self):
            return [
                {"symbol": "AAAUSDT", "lastPrice": "1", "quoteVolume": "1000000"},
                {"symbol": "BBBUSDT", "lastPrice": "2", "quoteVolume": "10"},
            ]

        def global_long_short_account_ratio(self, symbol: str, *, period: str = "1h", limit: int = 2):
            assert period == "1h"
            assert limit == 2
            return [_ratio(1, 0.50), _ratio(2, 0.54)]

    frame, errors = scan_short_account_roc(FakeClient(), min_quote_volume=1000)

    assert errors == []
    assert frame["symbol"].tolist() == ["AAAUSDT"]
    assert round(float(frame.iloc[0]["short_account_roc_1h_pp"]), 6) == 4.0
