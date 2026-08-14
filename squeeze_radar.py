from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd


@dataclass(frozen=True)
class SqueezeRadarProfile:
    name: str
    min_short_pct: float
    min_short_roc_1h_pp: float
    min_short_change_3p_pp: float
    min_smoothed_short_roc_pp: float
    min_hour_volume_roc_pct: float
    min_daily_volume_ratio: float
    min_oi_delta_pct: float
    min_oi_change_3p_pct: float
    min_oi_build_persistence: int
    min_score: float
    max_late_score: float


SQUEEZE_RADAR_PROFILES: dict[str, SqueezeRadarProfile] = {
    "Early": SqueezeRadarProfile(
        name="Early",
        min_short_pct=57.5,
        min_short_roc_1h_pp=0.10,
        min_short_change_3p_pp=0.0,
        min_smoothed_short_roc_pp=0.10,
        min_hour_volume_roc_pct=0.0,
        min_daily_volume_ratio=1.20,
        min_oi_delta_pct=0.0,
        min_oi_change_3p_pct=0.0,
        min_oi_build_persistence=1,
        min_score=52.0,
        max_late_score=72.0,
    ),
    "Primary": SqueezeRadarProfile(
        name="Primary",
        min_short_pct=60.0,
        min_short_roc_1h_pp=0.25,
        min_short_change_3p_pp=0.15,
        min_smoothed_short_roc_pp=0.15,
        min_hour_volume_roc_pct=25.0,
        min_daily_volume_ratio=1.75,
        min_oi_delta_pct=0.25,
        min_oi_change_3p_pct=0.25,
        min_oi_build_persistence=2,
        min_score=60.0,
        max_late_score=65.0,
    ),
    "Strict": SqueezeRadarProfile(
        name="Strict",
        min_short_pct=65.0,
        min_short_roc_1h_pp=0.50,
        min_short_change_3p_pp=0.25,
        min_smoothed_short_roc_pp=0.25,
        min_hour_volume_roc_pct=50.0,
        min_daily_volume_ratio=2.50,
        min_oi_delta_pct=0.50,
        min_oi_change_3p_pct=0.50,
        min_oi_build_persistence=2,
        min_score=70.0,
        max_late_score=55.0,
    ),
}


# Structural evidence is intentionally held to a higher standard than market
# telemetry. Cached/proxy fields can rank a row for investigation, but cannot
# turn a live trigger into an entry-ready setup without a recent verified read.
STRUCTURAL_EVIDENCE_MAX_AGE_DAYS = 30.0
SQUEEZE_SNAPSHOT_MAX_AGE_MINUTES = 90.0


RADAR_SCORE_COLUMNS = [
    "squeeze_score",
    "squeeze_stage",
    "squeeze_market_trigger",
    "squeeze_entry_ready",
    "squeeze_structural_watch",
    "squeeze_actionable",
    "squeeze_high_conviction",
    "squeeze_watch_flag",
    "squeeze_late_veto",
    "squeeze_structural_evidence_gate",
    "squeeze_structural_evidence_fresh",
    "squeeze_snapshot_stale",
    "squeeze_snapshot_age_minutes",
    "squeeze_market_confidence",
    "squeeze_data_confidence",
    "squeeze_evidence_tier",
    "squeeze_gate_failures",
    "squeeze_signal",
    "squeeze_invalidation",
    "squeeze_short_level_score",
    "squeeze_short_build_score",
    "squeeze_fuel_remaining_score",
    "squeeze_volume_score",
    "squeeze_trend_score",
    "squeeze_oi_score",
    "squeeze_funding_score",
    "squeeze_structure_score",
    "squeeze_venue_score",
    "squeeze_late_score",
    "squeeze_short_confirmation_gate",
    "squeeze_oi_confirmation_gate",
    "squeeze_crowd_fuel_score",
    "squeeze_crowd_fuel_gate",
    "squeeze_taker_flow_score",
    "squeeze_taker_flow_gate",
    "squeeze_short_gate",
    "squeeze_build_gate",
    "squeeze_volume_gate",
    "squeeze_trend_gate",
    "squeeze_oi_gate",
    "squeeze_funding_gate",
    "squeeze_holder_gate",
    "squeeze_venue_gate",
]


def _num(frame: pd.DataFrame, column: str, default: float = float("nan")) -> pd.Series:
    source = frame[column] if column in frame.columns else pd.Series(default, index=frame.index)
    return pd.to_numeric(source, errors="coerce")


def _as_bool(value: Any) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _bool(frame: pd.DataFrame, column: str) -> pd.Series:
    source = frame[column] if column in frame.columns else pd.Series(False, index=frame.index)
    return source.map(_as_bool).astype(bool)


def _history_timestamp(row: Any) -> float:
    if not isinstance(row, dict):
        return float("nan")
    for key in ("timestamp", "time", "T"):
        try:
            value = float(row.get(key))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            return value
    return float("nan")


def _history_value(row: Any, key: str) -> float:
    if not isinstance(row, dict):
        return float("nan")
    try:
        value = float(row.get(key))
    except (TypeError, ValueError):
        return float("nan")
    return value if math.isfinite(value) else float("nan")


def oi_history_stats(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Summarise open-interest expansion over multiple closed hourly observations."""
    stats: dict[str, Any] = {
        "oi_history_points": 0,
        "oi_current_usdt": float("nan"),
        "oi_previous_1h_usdt": float("nan"),
        "oi_change_1h_pct": float("nan"),
        "oi_change_3p_pct": float("nan"),
        "oi_acceleration_1h_pct": float("nan"),
        "oi_change_6p_pct": float("nan"),
        "oi_build_persistence": 0,
        "oi_peak_drawdown_pct": float("nan"),
    }
    ordered = [row for row in rows if isinstance(row, dict)]
    ordered.sort(
        key=lambda row: (
            _history_timestamp(row)
            if math.isfinite(_history_timestamp(row))
            else float("inf")
        )
    )
    values = [_history_value(row, "sumOpenInterestValue") for row in ordered]
    values = [value for value in values if math.isfinite(value) and value > 0.0]
    stats["oi_history_points"] = len(values)
    if not values:
        return stats

    current = values[-1]
    stats["oi_current_usdt"] = current
    if len(values) >= 2:
        previous = values[-2]
        stats["oi_previous_1h_usdt"] = previous
        if previous > 0.0:
            stats["oi_change_1h_pct"] = (current / previous - 1.0) * 100.0
    if len(values) >= 3 and values[-3] > 0.0 and values[-2] > 0.0:
        current_delta = (values[-1] / values[-2] - 1.0) * 100.0
        previous_delta = (values[-2] / values[-3] - 1.0) * 100.0
        stats["oi_acceleration_1h_pct"] = current_delta - previous_delta

    for window in (3, 6):
        key = f"oi_change_{window}p_pct"
        if len(values) > window and values[-1 - window] > 0.0:
            stats[key] = (current / values[-1 - window] - 1.0) * 100.0

    deltas = [values[index] - values[index - 1] for index in range(1, len(values))]
    if deltas and deltas[-1] > 0.0:
        persistence = 0
        for delta in reversed(deltas):
            if delta <= 0.0:
                break
            persistence += 1
        stats["oi_build_persistence"] = persistence
    peak = max(values)
    if peak > 0.0:
        stats["oi_peak_drawdown_pct"] = (current / peak - 1.0) * 100.0
    return stats


def attach_squeeze_history_features(
    frame: pd.DataFrame,
    history: pd.DataFrame,
    *,
    lookback_hours: float = 24.0,
) -> pd.DataFrame:
    """Add scan-to-scan persistence features without changing the live snapshot."""
    out = frame.copy()
    defaults: dict[str, Any] = {
        "radar_prior_observations": 0,
        "radar_prior_trigger_count": 0,
        "radar_prior_entry_ready_count": 0,
        "radar_short_build_consistency_24h": float("nan"),
        "radar_oi_build_consistency_24h": float("nan"),
        "radar_price_up_consistency_24h": float("nan"),
        "radar_previous_stage": "",
        "radar_previous_score": float("nan"),
        "radar_confirmation_label": "NEW",
    }
    for column, default in defaults.items():
        if column not in out.columns:
            out[column] = default
    if out.empty or history is None or history.empty or "symbol" not in history.columns:
        return out

    prior = history.copy()
    prior["symbol"] = prior["symbol"].astype(str).str.upper().str.strip()
    if "scanned_at_utc" not in prior.columns:
        return out
    prior["scanned_at_utc"] = pd.to_datetime(prior["scanned_at_utc"], errors="coerce", utc=True)
    prior = prior.dropna(subset=["scanned_at_utc"])
    if prior.empty:
        return out

    if "scanned_at_utc" not in out.columns:
        return out
    current_times = pd.to_datetime(out["scanned_at_utc"], errors="coerce", utc=True)
    for index, row in out.iterrows():
        symbol = str(row.get("symbol") or "").upper().strip()
        current_time = current_times.get(index)
        if not symbol or pd.isna(current_time):
            continue
        cutoff = current_time - pd.Timedelta(hours=float(lookback_hours))
        candidates = prior[
            (prior["symbol"] == symbol)
            & (prior["scanned_at_utc"] < current_time)
            & (prior["scanned_at_utc"] >= cutoff)
        ].sort_values("scanned_at_utc")
        if candidates.empty:
            continue

        out.at[index, "radar_prior_observations"] = int(len(candidates))
        out.at[index, "radar_prior_trigger_count"] = int(_bool(candidates, "squeeze_market_trigger").sum())
        out.at[index, "radar_prior_entry_ready_count"] = int(_bool(candidates, "squeeze_entry_ready").sum())
        short_build = _num(candidates, "short_account_roc_1h_pp") > 0.0
        oi_build = _num(candidates, "oi_delta_pct") > 0.0
        price_up = _num(candidates, "day_return_pct") > 0.0
        out.at[index, "radar_short_build_consistency_24h"] = float(short_build.mean() * 100.0)
        out.at[index, "radar_oi_build_consistency_24h"] = float(oi_build.mean() * 100.0)
        out.at[index, "radar_price_up_consistency_24h"] = float(price_up.mean() * 100.0)
        out.at[index, "radar_previous_stage"] = str(candidates.iloc[-1].get("squeeze_stage") or "")
        out.at[index, "radar_previous_score"] = _finite(candidates.iloc[-1].get("squeeze_score")) or float("nan")
        out.at[index, "radar_confirmation_label"] = "PERSISTENT" if len(candidates) >= 3 else "REPEATED"
    return out


def _linear(values: pd.Series, low: float, high: float) -> pd.Series:
    if high <= low:
        return pd.Series(0.0, index=values.index)
    return ((values - low) / (high - low) * 100.0).clip(lower=0.0, upper=100.0)


def _mean_available(parts: list[pd.Series], index: pd.Index) -> pd.Series:
    if not parts:
        return pd.Series(0.0, index=index)
    combined = pd.concat(parts, axis=1)
    return combined.mean(axis=1, skipna=True).fillna(0.0)


def _weighted_available(parts: list[tuple[pd.Series, float]], index: pd.Index) -> pd.Series:
    numerator = pd.Series(0.0, index=index)
    denominator = pd.Series(0.0, index=index)
    for values, weight in parts:
        available = values.notna()
        numerator = numerator + values.fillna(0.0) * float(weight)
        denominator = denominator + available.astype(float) * float(weight)
    return (numerator / denominator.where(denominator > 0.0)).fillna(0.0)


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _fmt(value: Any, suffix: str = "", digits: int = 1) -> str | None:
    parsed = _finite(value)
    if parsed is None:
        return None
    return f"{parsed:.{digits}f}{suffix}"


def select_squeeze_candidates(
    ticker: pd.DataFrame,
    *,
    seed_frames: Iterable[pd.DataFrame] = (),
    forced_symbols: Iterable[str] = (),
    max_symbols: int = 36,
) -> pd.DataFrame:
    """Build a bounded live-enrichment universe from bulk Binance data and local scan memory."""
    if ticker.empty:
        return ticker.copy()

    frame = ticker.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    market_type = (
        frame["market_type"].astype(str).str.upper()
        if "market_type" in frame.columns
        else pd.Series("", index=frame.index)
    )
    frame = frame[
        ~market_type.isin(
            {"COMMODITY", "EQUITY", "HK_EQUITY", "KR_EQUITY", "INDEX", "PREMARKET"}
        )
    ].copy()
    if frame.empty:
        return frame

    for column in ("quoteVolume", "priceChangePercent", "highPrice", "lowPrice", "count"):
        frame[column] = pd.to_numeric(frame.get(column), errors="coerce")
    frame["range_24h_pct"] = (
        (frame["highPrice"] / frame["lowPrice"] - 1.0) * 100.0
    ).where(frame["lowPrice"] > 0)

    seed_by_symbol: dict[str, dict[str, float]] = {}
    score_columns = (
        "pre_pump_precision_score",
        "dormant_short_fuse_score",
        "rave_lab_setup_score",
        "short_account_trend_score",
        "trade_bucket_score",
    )
    short_columns = ("short_account_pct",)
    roc_columns = (
        "short_account_roc_1h_pp",
        "short_account_roc_pp",
        "short_account_change_1p_pp",
    )
    for seed in seed_frames:
        if seed is None or seed.empty or "symbol" not in seed.columns:
            continue
        for _, row in seed.iterrows():
            symbol = str(row.get("symbol") or "").upper().strip()
            if not symbol:
                continue
            bucket = seed_by_symbol.setdefault(
                symbol,
                {"cached_short_pct": float("nan"), "cached_short_roc_pp": float("nan"), "cached_radar_score": 0.0},
            )
            for column in short_columns:
                value = _finite(row.get(column))
                if value is not None and (not math.isfinite(bucket["cached_short_pct"]) or value > bucket["cached_short_pct"]):
                    bucket["cached_short_pct"] = value
            for column in roc_columns:
                value = _finite(row.get(column))
                if value is not None and (not math.isfinite(bucket["cached_short_roc_pp"]) or value > bucket["cached_short_roc_pp"]):
                    bucket["cached_short_roc_pp"] = value
            for column in score_columns:
                value = _finite(row.get(column))
                if value is not None:
                    bucket["cached_radar_score"] = max(bucket["cached_radar_score"], value)

    seed_frame = pd.DataFrame.from_dict(seed_by_symbol, orient="index")
    if not seed_frame.empty:
        frame = frame.join(seed_frame, on="symbol")
    for column in ("cached_short_pct", "cached_short_roc_pp", "cached_radar_score"):
        if column not in frame.columns:
            frame[column] = float("nan") if column != "cached_radar_score" else 0.0

    live_short_pct = (
        pd.to_numeric(frame["live_short_account_pct"], errors="coerce")
        if "live_short_account_pct" in frame.columns
        else pd.Series(float("nan"), index=frame.index)
    )
    frame["candidate_short_account_pct"] = live_short_pct.where(
        live_short_pct.notna(),
        pd.to_numeric(frame["cached_short_pct"], errors="coerce"),
    )

    volume_pct = frame["quoteVolume"].rank(pct=True).fillna(0.0) * 100.0
    range_pct = frame["range_24h_pct"].rank(pct=True).fillna(0.0) * 100.0
    gain_score = _linear(frame["priceChangePercent"], -3.0, 24.0)
    overheat_penalty = _linear(frame["priceChangePercent"], 55.0, 140.0)
    candidate_short_score = _linear(
        pd.to_numeric(frame["candidate_short_account_pct"], errors="coerce"),
        52.0,
        75.0,
    )
    cached_roc_score = _linear(pd.to_numeric(frame["cached_short_roc_pp"], errors="coerce"), 0.0, 3.0)
    cached_radar_score = pd.to_numeric(frame["cached_radar_score"], errors="coerce").fillna(0.0).clip(0.0, 100.0)
    frame["candidate_seed_score"] = (
        volume_pct * 0.18
        + range_pct * 0.18
        + gain_score * 0.20
        + candidate_short_score.fillna(0.0) * 0.20
        + cached_roc_score.fillna(0.0) * 0.14
        + cached_radar_score * 0.10
        - overheat_penalty.fillna(0.0) * 0.18
    ).clip(lower=0.0, upper=100.0)

    frame["candidate_priority_bonus"] = 0.0
    slices = (
        ("quoteVolume", 10, 18.0),
        ("priceChangePercent", 10, 16.0),
        ("range_24h_pct", 10, 14.0),
        ("candidate_short_account_pct", 18, 28.0),
        ("cached_short_roc_pp", 15, 24.0),
        ("cached_radar_score", 12, 20.0),
    )
    for column, count, bonus in slices:
        if column not in frame.columns:
            continue
        indexes = pd.to_numeric(frame[column], errors="coerce").nlargest(count).index
        frame.loc[indexes, "candidate_priority_bonus"] += bonus

    forced = {str(symbol).upper().strip() for symbol in forced_symbols if str(symbol).strip()}
    frame["candidate_forced"] = frame["symbol"].isin(forced)
    frame.loc[frame["candidate_forced"], "candidate_priority_bonus"] += 1000.0
    frame["candidate_rank_score"] = frame["candidate_seed_score"] + frame["candidate_priority_bonus"]

    return frame.sort_values(
        ["candidate_forced", "candidate_rank_score", "quoteVolume", "symbol"],
        ascending=[False, False, False, True],
    ).head(max(1, int(max_symbols))).reset_index(drop=True)


def score_squeeze_radar(
    frame: pd.DataFrame,
    *,
    profile: SqueezeRadarProfile | str = "Primary",
) -> pd.DataFrame:
    """Score live squeeze mechanics without treating account count as short notional."""
    if isinstance(profile, str):
        profile = SQUEEZE_RADAR_PROFILES.get(profile, SQUEEZE_RADAR_PROFILES["Primary"])
    if frame.empty:
        empty = frame.copy()
        for column in RADAR_SCORE_COLUMNS:
            empty[column] = pd.Series(dtype="object" if column.endswith(("stage", "tier", "failures", "signal", "invalidation")) else "float64")
        return empty

    out = frame.copy()
    index = out.index
    short_pct = _num(out, "short_account_pct")
    short_roc = _num(out, "short_account_roc_1h_pp")
    short_change_3p = _num(out, "short_account_change_3p_pp")
    short_change_6p = _num(out, "short_account_change_6p_pp")
    short_smoothed = _num(out, "short_account_roc_smoothed_3p_pp")
    persistence = _num(out, "short_account_direction_persistence").fillna(0.0)
    funding = _num(out, "carry_funding_pct")
    hour_volume_roc = _num(out, "hour_volume_roc_1h_pct")
    hour_volume_multiple = _num(out, "hour_volume_multiple")
    daily_volume_ratio = _num(out, "quote_volume_24h_vs_prior_30d_avg_ratio")
    oi_delta = _num(out, "oi_delta_pct")
    oi_change_3p = _num(out, "oi_change_3p_pct")
    oi_change_6p = _num(out, "oi_change_6p_pct")
    oi_persistence = _num(out, "oi_build_persistence").fillna(0.0)
    crowd_position_divergence = _num(out, "crowd_top_position_divergence_pct")
    crowd_account_divergence = _num(out, "crowd_top_account_divergence_pct")
    taker_ratio = _num(out, "taker_buy_sell_ratio")
    day_return = _num(out, "day_return_pct")
    hour_return = _num(out, "hour_return_pct")
    price_vs_avwap = _num(out, "price_vs_anchored_vwap_30d_pct")
    close_location = _num(out, "hour_close_location_pct")
    upper_wick = _num(out, "hour_upper_wick_pct")
    recent_pump = _num(out, "recent_max_pump_60d_pct")

    short_level_score = _linear(short_pct, 52.0, 75.0).fillna(0.0)
    short_build_score = _weighted_available(
        [
            (_linear(short_roc, 0.0, 2.5), 0.36),
            (_linear(short_change_3p, 0.0, 3.0), 0.26),
            (_linear(short_change_6p, 0.0, 5.0), 0.10),
            (_linear(short_smoothed, 0.0, 1.5), 0.20),
            (_linear(persistence, 0.0, 4.0), 0.08),
        ],
        index,
    ).clip(lower=0.0, upper=100.0)
    fuel_remaining_score = (
        short_level_score * 0.58
        + short_build_score * 0.34
        + _linear(_num(out, "short_account_peak_drawdown_pp"), -5.0, 0.0).fillna(50.0) * 0.08
    ).clip(lower=0.0, upper=100.0)

    volume_score = (
        _linear(hour_volume_roc, 0.0, 200.0).fillna(0.0) * 0.42
        + _linear(hour_volume_multiple, 1.0, 5.0).fillna(0.0) * 0.20
        + _linear(daily_volume_ratio, 1.0, 6.0).fillna(0.0) * 0.38
    ).clip(lower=0.0, upper=100.0)

    broke_high = _bool(out, "broke_high_5d") | _bool(out, "broke_high_20d")
    trend_parts = [
        (price_vs_avwap > 0.0).astype(float) * 100.0,
        _linear(day_return, -2.0, 20.0),
        _linear(hour_return, -0.5, 5.0),
        _linear(close_location, 40.0, 82.0),
        broke_high.astype(float) * 100.0,
    ]
    trend_score = _mean_available(trend_parts, index).clip(lower=0.0, upper=100.0)
    trend_agreement = (
        (price_vs_avwap > 0.0).astype(int)
        + (day_return > 0.0).astype(int)
        + (hour_return > -0.5).astype(int)
        + (close_location >= 55.0).astype(int)
        + broke_high.astype(int)
    )

    oi_score = _weighted_available(
        [
            (_linear(oi_delta, -0.5, 5.0), 0.45),
            (_linear(oi_change_3p, -0.5, 8.0), 0.30),
            (_linear(oi_change_6p, -1.0, 12.0), 0.15),
            (_linear(oi_persistence, 0.0, 5.0), 0.10),
        ],
        index,
    ).clip(lower=0.0, upper=100.0)
    funding_score = _linear(funding, 0.0, 0.08).fillna(0.0)
    crowd_fuel_score = _weighted_available(
        [
            (_linear(-crowd_position_divergence, -2.0, 22.0), 0.60),
            (_linear(-crowd_account_divergence, -2.0, 22.0), 0.40),
        ],
        index,
    ).where(crowd_position_divergence.notna() | crowd_account_divergence.notna())
    taker_flow_score = _linear(taker_ratio, 0.85, 1.25)

    top10 = _num(out, "top10_holder_pct")
    top100 = _num(out, "top100_holder_pct")
    adjusted_top10 = _num(out, "adjusted_top_10_pct")
    holder_score = pd.concat(
        [
            _linear(top10, 55.0, 95.0),
            _linear(top100, 82.0, 100.0),
            _linear(adjusted_top10, 45.0, 90.0),
        ],
        axis=1,
    ).max(axis=1, skipna=True)
    low_float_score = pd.concat(
        [
            _num(out, "controlled_float_squeeze_score"),
            _num(out, "low_float_score"),
            _num(out, "centralized_ownership_score"),
        ],
        axis=1,
    ).mean(axis=1, skipna=True)
    archetype_score = pd.concat(
        [
            _num(out, "ravedao_archetype_score"),
            _num(out, "rave_lab_setup_score"),
            _num(out, "pre_pump_precision_score"),
        ],
        axis=1,
    ).mean(axis=1, skipna=True)
    structure_score = _weighted_available(
        [(holder_score, 0.50), (low_float_score, 0.30), (archetype_score, 0.20)],
        index,
    )
    structure_available = holder_score.notna() | low_float_score.notna() | archetype_score.notna()
    structure_score = structure_score.where(structure_available, 0.0).clip(lower=0.0, upper=100.0)

    storage_risk = (
        (_num(out, "protocol_storage_score") >= 65.0)
        | (_num(out, "cex_storage_supply_pct") >= 70.0)
        | _bool(out, "holder_table_not_global_supply")
        | _bool(out, "wrapped_representation_warning")
    )
    storage_checked = _bool(out, "structural_storage_checked")
    structure_score = (structure_score - storage_risk.astype(float) * 35.0).clip(lower=0.0, upper=100.0)
    structural_evidence_level = (
        out["structural_evidence_level"].astype(str).str.upper().str.strip()
        if "structural_evidence_level" in out.columns
        else pd.Series("NONE", index=index)
    ).replace({"NAN": "NONE", "": "NONE"})
    verified_structural_evidence = structural_evidence_level.eq("VERIFIED")
    proxy_structural_evidence = structural_evidence_level.eq("PROXY")
    evidence_age = _num(out, "structural_evidence_age_days")
    structural_evidence_fresh = (
        verified_structural_evidence
        & evidence_age.notna()
        & evidence_age.between(0.0, STRUCTURAL_EVIDENCE_MAX_AGE_DAYS, inclusive="both")
    )
    holder_gate = (
        ((top10 >= 80.0) | (top100 >= 95.0) | (adjusted_top10 >= 72.0))
        & (~storage_risk)
        & storage_checked
        & structural_evidence_fresh
    )

    bitget_share = _num(out, "bitget_volume_share_pct")
    gate_share = _num(out, "gate_volume_share_pct")
    target_cex_share = _num(out, "target_cex_volume_share_pct")
    venue_gate = ((bitget_share > 0.0) | (gate_share > 0.0)) & structural_evidence_fresh
    venue_score = (
        35.0
        + _linear(bitget_share, 0.0, 5.0).fillna(0.0) * 0.25
        + _linear(gate_share, 0.0, 5.0).fillna(0.0) * 0.25
        + _linear(target_cex_share, 0.0, 12.0).fillna(0.0) * 0.20
    ).clip(lower=0.0, upper=100.0)

    weak_close_heat = _linear(100.0 - close_location, 55.0, 85.0)
    extension_heat = pd.concat(
        [
            _linear(day_return, 35.0, 90.0),
            _linear(price_vs_avwap, 35.0, 100.0),
        ],
        axis=1,
    ).max(axis=1, skipna=True).fillna(0.0)
    rejection_heat = pd.concat(
        [
            _linear(hour_return, 12.0, 30.0),
            _linear(upper_wick, 35.0, 80.0),
            weak_close_heat,
        ],
        axis=1,
    ).max(axis=1, skipna=True).fillna(0.0).clip(lower=0.0, upper=100.0)
    prior_heat = _linear(recent_pump, 55.0, 150.0).fillna(0.0)
    late_score = (
        extension_heat * 0.55
        + rejection_heat * 0.35
        + prior_heat * 0.10
    ).clip(lower=0.0, upper=100.0)
    blowoff_flag = _bool(out, "blowoff_risk_flag")
    breakdown = _bool(out, "broke_low_20d") & (day_return < 0.0)
    late_veto = (
        (late_score >= profile.max_late_score)
        | (extension_heat >= 92.0)
        | blowoff_flag
        | breakdown
    )

    critical_columns = (
        "short_account_pct",
        "short_account_roc_1h_pp",
        "short_account_change_3p_pp",
        "hour_volume_roc_1h_pct",
        "quote_volume_24h_vs_prior_30d_avg_ratio",
        "oi_delta_pct",
        "oi_change_3p_pct",
        "carry_funding_pct",
        "price_vs_anchored_vwap_30d_pct",
        "hour_close_location_pct",
    )
    available = pd.DataFrame(
        {column: _num(out, column).notna().astype(float) for column in critical_columns},
        index=index,
    )
    market_confidence = available.mean(axis=1) * 100.0
    data_confidence = (
        market_confidence * 0.80
        + (verified_structural_evidence & evidence_age.notna()).astype(float) * 15.0
        + venue_gate.astype(float) * 5.0
    ).clip(lower=0.0, upper=100.0)

    score = (
        short_level_score * 0.17
        + short_build_score * 0.17
        + volume_score * 0.15
        + trend_score * 0.15
        + oi_score * 0.10
        + funding_score * 0.06
        + structure_score * 0.11
        + venue_score * 0.04
        + crowd_fuel_score.fillna(50.0) * 0.04
        + taker_flow_score.fillna(50.0) * 0.01
        - late_score * 0.28
    ).clip(lower=0.0, upper=100.0)
    score = (score * (0.75 + market_confidence / 400.0)).clip(lower=0.0, upper=100.0)

    short_gate = short_pct >= profile.min_short_pct
    short_confirmation_gate = (
        (short_change_3p >= profile.min_short_change_3p_pp)
        | (persistence >= 2.0)
    )
    build_gate = (
        (short_roc >= profile.min_short_roc_1h_pp)
        & short_confirmation_gate
    ) | (
        (short_smoothed >= profile.min_smoothed_short_roc_pp)
        & (persistence >= 2.0)
    )
    volume_gate = (
        (daily_volume_ratio >= profile.min_daily_volume_ratio)
        & (
            (hour_volume_roc >= profile.min_hour_volume_roc_pct)
            | (hour_volume_multiple >= 1.50)
        )
    )
    trend_gate = (trend_agreement >= 3) & (price_vs_avwap > 0.0) & (day_return > -2.0)
    oi_confirmation_gate = (
        (oi_change_3p >= profile.min_oi_change_3p_pct)
        | (oi_persistence >= profile.min_oi_build_persistence)
    )
    oi_gate = (oi_delta >= profile.min_oi_delta_pct) & oi_confirmation_gate
    funding_gate = funding > 0.0
    crowd_diagnostic_available = crowd_position_divergence.notna() | crowd_account_divergence.notna()
    crowd_fuel_gate = (
        (~crowd_diagnostic_available)
        | (crowd_position_divergence <= 2.0)
        | (crowd_account_divergence <= 2.0)
    )
    taker_diagnostic_available = taker_ratio.notna()
    taker_flow_gate = (~taker_diagnostic_available) | (taker_ratio >= 0.90)

    armed = short_gate & build_gate & (~late_veto)
    ignition = (
        armed
        & volume_gate
        & trend_gate
        & oi_gate
        & funding_gate
        & crowd_fuel_gate
        & taker_flow_gate
        & (score >= profile.min_score)
    )
    reflexive = ignition & (broke_high | (day_return >= 8.0)) & (trend_score >= 65.0)
    unwind = (
        ((short_roc <= -1.0) | (short_smoothed <= -0.50))
        & ((oi_delta < 0.0) | (day_return < 0.0) | (close_location < 45.0))
    )

    stage = pd.Series("OBSERVE", index=index, dtype="object")
    stage.loc[armed] = "ARMED"
    stage.loc[ignition] = "IGNITION"
    stage.loc[reflexive] = "REFLEXIVE"
    stage.loc[unwind] = "UNWIND"
    stage.loc[late_veto] = "LATE"

    snapshot_at = (
        pd.to_datetime(out["scanned_at_utc"], errors="coerce", utc=True)
        if "scanned_at_utc" in out.columns
        else pd.Series(pd.NaT, index=index, dtype="datetime64[ns, UTC]")
    )
    snapshot_age_minutes = (
        (pd.Timestamp.now(tz="UTC") - snapshot_at).dt.total_seconds() / 60.0
    )
    snapshot_stale = snapshot_age_minutes > SQUEEZE_SNAPSHOT_MAX_AGE_MINUTES
    stage.loc[snapshot_stale.fillna(False)] = "STALE"

    evidence_tier = pd.Series("MARKET ONLY", index=index, dtype="object")
    evidence_tier.loc[proxy_structural_evidence] = "PROXY ONLY"
    evidence_tier.loc[verified_structural_evidence] = "VERIFIED"
    evidence_tier.loc[holder_gate] = "HOLDER"
    evidence_tier.loc[venue_gate] = "VENUE"
    evidence_tier.loc[holder_gate & venue_gate] = "FULL"
    stale_evidence = verified_structural_evidence & (~structural_evidence_fresh)
    evidence_tier.loc[stale_evidence] = "VERIFIED / STALE"

    market_trigger = stage.isin({"IGNITION", "REFLEXIVE"}) & (~snapshot_stale.fillna(False))
    structural_evidence_gate = holder_gate & venue_gate
    structural_watch = (
        armed
        & structural_evidence_gate
        & (~late_veto)
        & (~snapshot_stale.fillna(False))
    )
    entry_ready = (
        market_trigger
        & structural_evidence_gate
        & (market_confidence >= 75.0)
        & (~snapshot_stale.fillna(False))
    )
    actionable = entry_ready
    high_conviction = entry_ready & (market_confidence >= 75.0)
    watch = stage.isin({"ARMED", "IGNITION", "REFLEXIVE"})

    out["squeeze_score"] = score
    out["squeeze_stage"] = stage
    out["squeeze_market_trigger"] = market_trigger
    out["squeeze_entry_ready"] = entry_ready
    out["squeeze_structural_watch"] = structural_watch
    out["squeeze_actionable"] = actionable
    out["squeeze_high_conviction"] = high_conviction
    out["squeeze_watch_flag"] = watch
    out["squeeze_late_veto"] = late_veto
    out["squeeze_market_confidence"] = market_confidence
    out["squeeze_data_confidence"] = data_confidence
    out["structural_evidence_level"] = structural_evidence_level
    out["squeeze_evidence_tier"] = evidence_tier
    out["squeeze_structural_evidence_gate"] = structural_evidence_gate.fillna(False)
    out["squeeze_structural_evidence_fresh"] = structural_evidence_fresh.fillna(False)
    out["squeeze_snapshot_stale"] = snapshot_stale.fillna(False)
    out["squeeze_snapshot_age_minutes"] = snapshot_age_minutes
    out["squeeze_short_level_score"] = short_level_score
    out["squeeze_short_build_score"] = short_build_score
    out["squeeze_fuel_remaining_score"] = fuel_remaining_score
    out["squeeze_volume_score"] = volume_score
    out["squeeze_trend_score"] = trend_score
    out["squeeze_oi_score"] = oi_score
    out["squeeze_funding_score"] = funding_score
    out["squeeze_structure_score"] = structure_score
    out["squeeze_venue_score"] = venue_score
    out["squeeze_late_score"] = late_score
    out["squeeze_crowd_fuel_score"] = crowd_fuel_score
    out["squeeze_crowd_fuel_gate"] = crowd_fuel_gate.fillna(False)
    out["squeeze_taker_flow_score"] = taker_flow_score
    out["squeeze_taker_flow_gate"] = taker_flow_gate.fillna(False)
    out["squeeze_short_gate"] = short_gate.fillna(False)
    out["squeeze_build_gate"] = build_gate.fillna(False)
    out["squeeze_short_confirmation_gate"] = short_confirmation_gate.fillna(False)
    out["squeeze_volume_gate"] = volume_gate.fillna(False)
    out["squeeze_trend_gate"] = trend_gate.fillna(False)
    out["squeeze_oi_gate"] = oi_gate.fillna(False)
    out["squeeze_oi_confirmation_gate"] = oi_confirmation_gate.fillna(False)
    out["squeeze_funding_gate"] = funding_gate.fillna(False)
    out["squeeze_holder_gate"] = holder_gate.fillna(False)
    out["squeeze_venue_gate"] = venue_gate.fillna(False)

    def _gate_failures(row: pd.Series) -> str:
        failures: list[str] = []
        checks = (
            ("squeeze_short_gate", "short accounts below gate"),
            ("squeeze_build_gate", "shorts not building now; multi-hour confirmation absent"),
            ("squeeze_volume_gate", "volume ignition absent"),
            ("squeeze_trend_gate", "trend agreement weak"),
            ("squeeze_oi_gate", "OI not expanding with confirmation"),
            ("squeeze_funding_gate", "funding not positive"),
            ("squeeze_crowd_fuel_gate", "crowd/top-trader divergence unfavorable"),
            ("squeeze_taker_flow_gate", "taker flow weak or unavailable"),
            ("squeeze_holder_gate", "holder proof missing"),
            ("squeeze_venue_gate", "Bitget/Gate proof missing"),
        )
        for column, label in checks:
            if not _as_bool(row.get(column)):
                failures.append(label)
        if _as_bool(row.get("squeeze_late_veto")):
            failures.insert(0, "late/exhausted")
        if _as_bool(row.get("squeeze_snapshot_stale")):
            failures.insert(0, "live snapshot stale; refresh required")
        if _as_bool(row.get("squeeze_structural_evidence_fresh")) and not _as_bool(row.get("structural_storage_checked")):
            failures.insert(0, "storage/representation controls not verified")
        if str(row.get("structural_evidence_level") or "NONE").upper() == "PROXY":
            failures.insert(0, "structural evidence is proxy-only")
        return " | ".join(failures)

    def _signal(row: pd.Series) -> str:
        parts: list[str] = []
        short = _fmt(row.get("short_account_pct"), "%")
        roc = _fmt(row.get("short_account_roc_1h_pp"), "pp")
        if short:
            parts.append(f"shorts {short}")
        if roc:
            sign = "+" if (_finite(row.get("short_account_roc_1h_pp")) or 0.0) > 0 else ""
            parts.append(f"1h {sign}{roc}")
        volume = _fmt(row.get("quote_volume_24h_vs_prior_30d_avg_ratio"), "x")
        if volume:
            parts.append(f"vol {volume}")
        oi = _fmt(row.get("oi_delta_pct"), "%")
        if oi:
            sign = "+" if (_finite(row.get("oi_delta_pct")) or 0.0) > 0 else ""
            parts.append(f"OI {sign}{oi}")
        if _as_bool(row.get("broke_high_20d")):
            parts.append("20D high")
        elif _as_bool(row.get("broke_high_5d")):
            parts.append("5D high")
        return " | ".join(parts)

    def _invalidation(row: pd.Series) -> str:
        stage_value = str(row.get("squeeze_stage") or "")
        if stage_value == "STALE":
            return "Refresh the live radar before interpreting this row."
        if stage_value == "LATE":
            return "No-chase veto; wait for a new base and renewed short build."
        if stage_value == "UNWIND":
            return "Fuel is rolling over with weak price/OI confirmation."
        if stage_value in {"IGNITION", "REFLEXIVE"}:
            return "Short ROC rollover plus OI contraction or loss of 30D AVWAP."
        return "No live trigger until short build, volume, OI and trend agree."

    out["squeeze_gate_failures"] = out.apply(_gate_failures, axis=1)
    out["squeeze_signal"] = out.apply(_signal, axis=1)
    out["squeeze_invalidation"] = out.apply(_invalidation, axis=1)

    stage_priority = out["squeeze_stage"].map(
        {"REFLEXIVE": 5, "IGNITION": 4, "ARMED": 3, "OBSERVE": 2, "UNWIND": 1, "LATE": 0, "STALE": -1}
    ).fillna(0)
    out["squeeze_stage_priority"] = stage_priority
    out = out.sort_values(
        [
            "squeeze_high_conviction",
            "squeeze_stage_priority",
            "squeeze_score",
            "squeeze_fuel_remaining_score",
            "squeeze_data_confidence",
            "symbol",
        ],
        ascending=[False, False, False, False, False, True],
    ).reset_index(drop=True)
    out["squeeze_rank"] = range(1, len(out) + 1)
    return out
