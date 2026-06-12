from __future__ import annotations

from datetime import datetime, timezone

from inx_hourly_monitor import build_discord_payload, build_inx_hourly_snapshot


def _ratio(timestamp: int, short: float) -> dict[str, object]:
    long = 1.0 - short
    return {
        "timestamp": timestamp,
        "longShortRatio": str(long / short),
        "longAccount": str(long),
        "shortAccount": str(short),
    }


def _oi(timestamp: int, amount: float, value: float) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "sumOpenInterest": str(amount),
        "sumOpenInterestValue": str(value),
    }


def _kline(index: int, quote_volume: float = 1000.0) -> list[object]:
    open_time = 1_700_000_000_000 + (index * 300_000)
    open_price = 1.0 + index * 0.01
    close_price = open_price + 0.005
    return [
        open_time,
        str(open_price),
        str(close_price + 0.01),
        str(open_price - 0.01),
        str(close_price),
        "500",
        open_time + 299_999,
        str(quote_volume),
        10,
        "250",
        str(quote_volume / 2),
        "0",
    ]


def test_inx_hourly_snapshot_and_payload_track_requested_metrics() -> None:
    row = build_inx_hourly_snapshot(
        symbol="INXUSDT",
        ratio_rows=[_ratio(1, 0.50), _ratio(2, 0.535)],
        open_interest_rows=[_oi(1, 1_000_000, 200_000), _oi(2, 1_125_000, 240_000)],
        klines_5m=[_kline(index) for index in range(13)],
        live_open_interest={"openInterest": "1125000"},
        mark_price_rows=[{"markPrice": "1.23"}],
        scanned_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
    )

    assert row["short_account_roc_1h_pp"] == 3.5
    assert round(float(row["open_interest_change_pct"]), 6) == 12.5
    assert row["volume_quote_60m"] == 12_000.0

    payload = build_discord_payload(row)
    description = payload["embeds"][0]["description"]

    assert "/INXUSDT" in description
    assert "short 50.00% -> 53.50%" in description
    assert "OI 1.00M -> 1.12M" in description
    assert "quote $12.00K" in description
