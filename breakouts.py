from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BreakoutLevels:
    high_5d: float
    low_5d: float
    high_20d: float
    low_20d: float
    high_90d: float
    low_90d: float
    high_180d: float
    low_180d: float
    ath_scanned: float


@dataclass(frozen=True)
class RecentPumpStats:
    max_pump_pct: float
    used_days: int


@dataclass(frozen=True)
class BreakoutRow:
    symbol: str
    base_asset: str
    market_type: str
    binance_perp_universe: bool
    last_price: float
    quote_volume_24h: float
    history_days: int
    recent_max_pump_60d_pct: float
    recent_pump_60d_days: int
    no_large_pump_60d_flag: bool
    corr_to_btc_6m: float
    corr_window_days: int
    high_24h: float
    low_24h: float
    carry_funding_pct: float
    carry_funding_annualized_pct: float
    long_carry_pct: float
    long_carry_annualized_pct: float
    funding_interval_hours: int
    funding_countdown_hours: float
    premium_index_pct: float
    predicted_funding_pct: float
    predicted_funding_annualized_pct: float
    predicted_long_carry_pct: float
    predicted_long_carry_annualized_pct: float
    predicted_funding_low_pct: float
    predicted_funding_high_pct: float
    predicted_funding_band_pct: float
    predicted_funding_backtest_mae_pct: float
    predicted_funding_backtest_count: int
    funding_window_elapsed_pct: float
    last_settled_funding_pct: float
    prior_settled_funding_pct: float
    funding_flip_delta_pct: float
    long_short_account_ratio: float
    long_account_pct: float
    short_account_pct: float
    short_account_history_points: int
    short_account_change_1p_pct: float
    short_account_change_1p_pp: float
    short_account_previous_1h_pct: float
    short_account_roc_1h_pct: float
    short_account_roc_1h_pp: float
    short_account_roc_1h_abs_pp: float
    short_account_roc_1h_direction: str
    short_account_change_3p_pct: float
    short_account_change_3p_pp: float
    short_account_change_6p_pct: float
    short_account_change_6p_pp: float
    short_account_change_12p_pct: float
    short_account_change_12p_pp: float
    short_account_change_24p_pct: float
    short_account_change_24p_pp: float
    short_account_change_max_pct: float
    short_account_change_max_pp: float
    short_account_change_max_window: str
    short_account_change_min_pct: float
    short_account_change_min_pp: float
    short_account_change_min_window: str
    hour_return_pct: float
    hour_return_z: float
    day_return_pct: float
    daily_quote_volume_multiple: float
    hour_quote_volume: float
    hour_volume_multiple: float
    hour_trade_count_multiple: float
    hour_upper_wick_pct: float
    hour_close_location_pct: float
    oi_value_usdt: float
    oi_delta_pct: float
    oi_to_24h_volume_pct: float
    taker_buy_sell_ratio: float
    taker_buy_share_pct: float
    top_trader_position_ratio: float
    top_trader_long_position_pct: float
    top_trader_short_position_pct: float
    top_trader_account_ratio: float
    top_trader_long_account_pct: float
    top_trader_short_account_pct: float
    crowd_top_position_divergence_pct: float
    crowd_top_account_divergence_pct: float
    basis_rate_pct: float
    basis_usdt: float
    ask_depth_1pct_usdt: float
    ask_depth_to_24h_volume_pct: float
    crime_carry_stress_score: float
    crime_pump_score: float
    crime_ignition_score: float
    crime_exhaustion_score: float
    crime_pump_flag: bool
    ignition_setup_flag: bool
    exhaustion_flag: bool
    squeeze_risk_flag: bool
    blowoff_risk_flag: bool
    high_5d: float
    low_5d: float
    high_20d: float
    low_20d: float
    high_90d: float
    low_90d: float
    high_180d: float
    low_180d: float
    ath_scanned: float
    upside_to_ath_pct: float
    distance_to_high_5d_pct: float
    distance_to_high_20d_pct: float
    distance_to_high_90d_pct: float
    broke_high_5d: bool
    broke_low_5d: bool
    broke_high_20d: bool
    broke_low_20d: bool
    broke_high_90d: bool
    broke_high_180d: bool
    broke_low_90d: bool
    broke_low_180d: bool


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return float("nan")


def _rolling_level(values: list[float], window: int, *, fn: Any) -> float:
    if len(values) < int(window):
        return float("nan")
    return float(fn(values[-int(window) :]))


def levels_from_klines(klines: list[list[Any]]) -> BreakoutLevels:
    """Compute breakout highs/lows from available *closed* daily candles only."""
    if len(klines) < 2:
        return BreakoutLevels(*(float("nan") for _ in range(9)))

    closed_only = klines[:-1]
    highs = [_to_float(k[2]) for k in closed_only if len(k) > 4]
    lows = [_to_float(k[3]) for k in closed_only if len(k) > 4]

    if not highs or not lows:
        return BreakoutLevels(*(float("nan") for _ in range(9)))

    return BreakoutLevels(
        high_5d=_rolling_level(highs, 5, fn=max),
        low_5d=_rolling_level(lows, 5, fn=min),
        high_20d=_rolling_level(highs, 20, fn=max),
        low_20d=_rolling_level(lows, 20, fn=min),
        high_90d=_rolling_level(highs, 90, fn=max),
        low_90d=_rolling_level(lows, 90, fn=min),
        high_180d=_rolling_level(highs, 180, fn=max),
        low_180d=_rolling_level(lows, 180, fn=min),
        ath_scanned=float(max(highs)),
    )


def recent_pump_stats_from_klines(klines: list[list[Any]], *, lookback_days: int = 60) -> RecentPumpStats:
    """Measure the largest recent daily high expansion from closed candles."""
    if len(klines) < 2:
        return RecentPumpStats(float("nan"), 0)

    closed_only = [row for row in klines[:-1] if isinstance(row, (list, tuple)) and len(row) > 4]
    if not closed_only:
        return RecentPumpStats(float("nan"), 0)

    lookback = max(1, int(lookback_days))
    start = max(0, len(closed_only) - lookback)
    max_pump = 0.0
    valid_days = 0
    for idx in range(start, len(closed_only)):
        row = closed_only[idx]
        open_price = _to_float(row[1])
        high_price = _to_float(row[2])
        close_price = _to_float(row[4])
        candidates: list[float] = []
        if open_price > 0 and high_price > 0:
            candidates.append((high_price / open_price - 1.0) * 100.0)
        if idx > 0:
            prev_close = _to_float(closed_only[idx - 1][4])
            if prev_close > 0:
                if high_price > 0:
                    candidates.append((high_price / prev_close - 1.0) * 100.0)
                if close_price > 0:
                    candidates.append((close_price / prev_close - 1.0) * 100.0)
        if candidates:
            valid_days += 1
            max_pump = max(max_pump, max(candidates))

    if valid_days <= 0:
        return RecentPumpStats(float("nan"), 0)
    return RecentPumpStats(max(0.0, float(max_pump)), valid_days)
