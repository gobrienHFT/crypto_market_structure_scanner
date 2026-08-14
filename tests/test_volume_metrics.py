from __future__ import annotations

import csv
import math
from pathlib import Path

from volume_metrics import (
    append_csv_row_schema_safe,
    closed_daily_anchored_vwap_metrics,
    closed_hour_volume_metrics,
)


def _kline(open_time: int, quote_volume: float) -> list[object]:
    return [open_time, "1", "1", "1", "1", "0", open_time + 1, str(quote_volume), 1]


def test_closed_hour_volume_roc_uses_latest_two_completed_hourly_bars() -> None:
    rows = [_kline(1, 100), _kline(2, 150), _kline(3, 999)]

    metrics = closed_hour_volume_metrics(rows)

    assert metrics["hour_quote_volume_previous_1h"] == 100
    assert metrics["hour_quote_volume"] == 150
    assert metrics["hour_volume_roc_1h_pct"] == 50


def test_closed_hour_volume_roc_aggregates_two_5m_hour_windows() -> None:
    rows = [_kline(index, 10) for index in range(12)]
    rows += [_kline(index, 15) for index in range(12, 24)]
    rows += [_kline(24, 999)]

    metrics = closed_hour_volume_metrics(rows, bars_per_hour=12)

    assert metrics["hour_quote_volume_previous_1h"] == 120
    assert metrics["hour_quote_volume"] == 180
    assert metrics["hour_volume_roc_1h_pct"] == 50


def test_closed_hour_volume_roc_is_nan_without_two_complete_windows() -> None:
    metrics = closed_hour_volume_metrics([_kline(1, 100), _kline(2, 999)])

    assert math.isnan(metrics["hour_volume_roc_1h_pct"])


def test_daily_anchored_vwap_uses_completed_base_and_quote_volume() -> None:
    rows = [
        [1, "0", "0", "0", "0", "10", 2, "100"],
        [2, "0", "0", "0", "0", "20", 3, "300"],
        [3, "0", "0", "0", "0", "999", 4, "999999"],
    ]

    metrics = closed_daily_anchored_vwap_metrics(rows, last_price=20)

    assert round(float(metrics["anchored_vwap_30d"]), 6) == round(400 / 30, 6)
    assert round(float(metrics["price_vs_anchored_vwap_30d_pct"]), 6) == 50.0
    assert metrics["anchored_vwap_30d_days"] == 2


def test_daily_anchored_vwap_uses_available_history_for_new_tokens() -> None:
    rows = [[1, "0", "0", "0", "0", "5", 2, "50"]]

    metrics = closed_daily_anchored_vwap_metrics(
        rows,
        last_price=12,
        exclude_forming_bar=False,
    )

    assert metrics["anchored_vwap_30d"] == 10
    assert math.isclose(float(metrics["price_vs_anchored_vwap_30d_pct"]), 20.0)
    assert metrics["anchored_vwap_30d_days"] == 1


def test_schema_safe_csv_append_adds_new_volume_columns_without_corrupting_history(tmp_path: Path) -> None:
    path = tmp_path / "history.csv"
    append_csv_row_schema_safe(path, {"symbol": "AKEUSDT", "volume": 100})
    append_csv_row_schema_safe(path, {"symbol": "AKEUSDT", "volume": 150, "hour_volume_roc_1h_pct": 50})

    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 2
    assert rows[0]["hour_volume_roc_1h_pct"] == ""
    assert rows[1]["hour_volume_roc_1h_pct"] == "50"
