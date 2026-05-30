from __future__ import annotations

from breakouts import recent_pump_stats_from_klines


def _daily(open_price: float, high_price: float, low_price: float, close_price: float) -> list[float]:
    return [0, open_price, high_price, low_price, close_price]


def test_recent_pump_stats_uses_closed_daily_high_expansion() -> None:
    klines = [
        _daily(1.00, 1.05, 0.95, 1.00),
        _daily(1.00, 1.80, 0.98, 1.20),
        _daily(1.20, 1.26, 1.10, 1.18),
        _daily(1.18, 5.00, 1.12, 4.00),  # current unfinished candle ignored
    ]

    stats = recent_pump_stats_from_klines(klines, lookback_days=2)

    assert stats.used_days == 2
    assert round(stats.max_pump_pct, 1) == 80.0


def test_recent_pump_stats_uses_previous_close_gap() -> None:
    klines = [
        _daily(1.00, 1.02, 0.98, 1.00),
        _daily(1.10, 1.60, 1.05, 1.20),
        _daily(1.20, 1.25, 1.10, 1.15),  # current unfinished candle ignored
    ]

    stats = recent_pump_stats_from_klines(klines, lookback_days=2)

    assert stats.used_days == 2
    assert round(stats.max_pump_pct, 1) == 60.0
