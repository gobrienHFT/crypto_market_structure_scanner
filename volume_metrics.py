from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any


def _to_float(value: Any) -> float:
    try:
        parsed = float(value)
    except Exception:
        return float("nan")
    return parsed if math.isfinite(parsed) else float("nan")


def closed_hour_volume_metrics(
    klines: list[list[Any]],
    *,
    bars_per_hour: int = 1,
    exclude_forming_bar: bool = True,
) -> dict[str, float]:
    """Compare the latest completed hour's quote volume with the preceding hour."""
    bars_per_hour = max(1, int(bars_per_hour))
    closed_rows = klines[:-1] if exclude_forming_bar and klines else klines
    required = bars_per_hour * 2
    if len(closed_rows) < required:
        return {
            "hour_quote_volume_previous_1h": float("nan"),
            "hour_quote_volume": float("nan"),
            "hour_volume_roc_1h_pct": float("nan"),
        }

    sample = closed_rows[-required:]
    previous_rows = sample[:bars_per_hour]
    latest_rows = sample[bars_per_hour:]

    def quote_volume(rows: list[list[Any]]) -> float:
        values = [_to_float(row[7]) for row in rows if len(row) > 7]
        return sum(values) if len(values) == len(rows) and all(math.isfinite(value) for value in values) else float("nan")

    previous = quote_volume(previous_rows)
    latest = quote_volume(latest_rows)
    roc = (
        (latest / previous - 1.0) * 100.0
        if math.isfinite(latest) and math.isfinite(previous) and previous > 0
        else float("nan")
    )
    return {
        "hour_quote_volume_previous_1h": previous,
        "hour_quote_volume": latest,
        "hour_volume_roc_1h_pct": roc,
    }


def closed_daily_anchored_vwap_metrics(
    klines: list[list[Any]],
    *,
    last_price: Any,
    lookback_days: int = 30,
    exclude_forming_bar: bool = True,
) -> dict[str, float | int]:
    """Calculate VWAP anchored to the start of the completed daily lookback."""
    lookback_days = max(1, int(lookback_days))
    closed_rows = klines[:-1] if exclude_forming_bar and klines else klines
    valid_rows: list[list[Any]] = []
    for row in closed_rows[-lookback_days:]:
        if len(row) <= 7:
            continue
        base_volume = _to_float(row[5])
        quote_volume = _to_float(row[7])
        if (
            math.isfinite(base_volume)
            and base_volume > 0
            and math.isfinite(quote_volume)
            and quote_volume >= 0
        ):
            valid_rows.append(row)

    total_base_volume = sum(_to_float(row[5]) for row in valid_rows)
    total_quote_volume = sum(_to_float(row[7]) for row in valid_rows)
    anchored_vwap = (
        total_quote_volume / total_base_volume
        if valid_rows and total_base_volume > 0
        else float("nan")
    )
    current_price = _to_float(last_price)
    distance_pct = (
        (current_price / anchored_vwap - 1.0) * 100.0
        if math.isfinite(current_price)
        and current_price > 0
        and math.isfinite(anchored_vwap)
        and anchored_vwap > 0
        else float("nan")
    )
    return {
        "anchored_vwap_30d": anchored_vwap,
        "price_vs_anchored_vwap_30d_pct": distance_pct,
        "anchored_vwap_30d_days": len(valid_rows),
    }


def append_csv_row_schema_safe(path: Path, row: dict[str, Any]) -> None:
    """Append while migrating an existing CSV header when new monitor fields appear."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(row.keys())
    existing_rows: list[dict[str, Any]] = []
    existing_fieldnames: list[str] = []
    if path.exists() and path.stat().st_size > 0:
        with path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            existing_fieldnames = list(reader.fieldnames or [])
            if existing_fieldnames != fieldnames:
                existing_rows = list(reader)
    if existing_fieldnames and existing_fieldnames != fieldnames:
        fieldnames = list(dict.fromkeys([*existing_fieldnames, *fieldnames]))
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(existing_rows)
    file_exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
