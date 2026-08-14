from __future__ import annotations

"""Point-in-time event-study utilities for reflexivity observations.

The event is created from the observation and assessment available at that
timestamp.  Forward bars are consulted only after the event is frozen, and
coverage is reported when a horizon is not available.  This keeps the review
workflow honest about lookahead, missing history, and small samples.
"""

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

from .reflexivity import ReflexivityAssessment, ReflexivityObservation, ReflexivityState, parse_utc


DEFAULT_HORIZONS_HOURS = (1, 4, 12, 24, 72, 168)
EVENT_STUDY_VERSION = "event-study-v1.1"


def _pct(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or not math.isfinite(start) or not math.isfinite(end) or start <= 0:
        return None
    return (end / start - 1.0) * 100.0


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def _quantile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


@dataclass(frozen=True)
class EventStudyDefinition:
    signal_version: str
    entry_states: tuple[str, ...] = (ReflexivityState.ACTIVE_REFLEXIVITY.value, ReflexivityState.ACCELERATING.value)
    horizons_hours: tuple[int, ...] = DEFAULT_HORIZONS_HOURS
    positive_return_threshold_pct: float = 0.0
    threshold_return_pct: float = 20.0
    invalidation_return_pct: float = -10.0
    profit_thresholds_pct: tuple[float, ...] = (10.0, 25.0, 50.0, 100.0)
    short_unwind_level_pct: float = 65.0
    short_unwind_roc_pp: float = -2.5
    short_unwind_peak_drawdown_pp: float = -4.0
    dedupe_hours: int = 24
    holdout_start: datetime | None = None
    bootstrap_samples: int = 1000
    bootstrap_seed: int = 17
    # Event outcomes are temporally clustered; block resampling is the safer
    # default. IID remains available for explicit sensitivity comparisons.
    bootstrap_method: str = "block"
    bootstrap_block_size: int = 3
    version: str = EVENT_STUDY_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_version": self.signal_version,
            "entry_states": list(self.entry_states),
            "horizons_hours": list(self.horizons_hours),
            "positive_return_threshold_pct": self.positive_return_threshold_pct,
            "threshold_return_pct": self.threshold_return_pct,
            "invalidation_return_pct": self.invalidation_return_pct,
            "profit_thresholds_pct": list(self.profit_thresholds_pct),
            "short_unwind_level_pct": self.short_unwind_level_pct,
            "short_unwind_roc_pp": self.short_unwind_roc_pp,
            "short_unwind_peak_drawdown_pp": self.short_unwind_peak_drawdown_pp,
            "dedupe_hours": self.dedupe_hours,
            "holdout_start": _iso(self.holdout_start),
            "bootstrap_samples": self.bootstrap_samples,
            "bootstrap_seed": self.bootstrap_seed,
            "bootstrap_method": self.bootstrap_method,
            "bootstrap_block_size": self.bootstrap_block_size,
            "version": self.version,
        }


@dataclass(frozen=True)
class FrozenEvent:
    event_id: str
    symbol: str
    event_time: datetime
    state: str
    score: float
    market_trigger: bool
    structural_watch: bool
    signal_version: str
    split: str
    observation_id: str
    source: str
    venue: str
    evidence_snapshot: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "symbol": self.symbol,
            "event_time": _iso(self.event_time),
            "state": self.state,
            "score": self.score,
            "market_trigger": self.market_trigger,
            "structural_watch": self.structural_watch,
            "signal_version": self.signal_version,
            "split": self.split,
            "observation_id": self.observation_id,
            "source": self.source,
            "venue": self.venue,
            "evidence_snapshot": dict(self.evidence_snapshot),
        }


def _event_evidence(observation: ReflexivityObservation, assessment: ReflexivityAssessment) -> dict[str, Any]:
    """Freeze only information available at event time.

    In particular, this deliberately excludes any post-event price path or
    outcome.  The evidence snapshot is useful for audit and reproductions.
    """

    return {
        "event_time": _iso(observation.event_time),
        "received_at": _iso(observation.received_at),
        "source": observation.source,
        "venue": observation.venue,
        "event_time_basis": observation.event_time_basis,
        "short_account_pct": observation.metric("short_account_pct").value,
        "short_account_roc_1h_pp": observation.metric("short_account_roc_1h_pp").value,
        "short_account_change_3h_pp": observation.metric("short_account_change_3h_pp").value,
        "short_account_change_4h_pp": observation.metric("short_account_change_4h_pp").value,
        "short_account_roc_24h_pp": observation.metric("short_account_roc_24h_pp").value,
        "top_trader_short_account_pct": observation.metric("top_trader_short_account_pct").value,
        "top_trader_short_position_pct": observation.metric("top_trader_short_position_pct").value,
        "top_trader_long_account_pct": observation.metric("top_trader_long_account_pct").value,
        "top_trader_long_position_pct": observation.metric("top_trader_long_position_pct").value,
        "crowd_top_account_divergence_pp": observation.metric("crowd_top_account_divergence_pp").value,
        "crowd_top_position_divergence_pp": observation.metric("crowd_top_position_divergence_pp").value,
        "volume_ratio_24h_to_prior_30d_avg": observation.metric("volume_ratio_24h_to_prior_30d_avg").value,
        "perp_volume_30d_avg_usd": observation.metric("perp_volume_30d_avg_usd").value,
        "perp_volume_abnormal_multiple": observation.metric("perp_volume_abnormal_multiple").value,
        "oi_delta_1h_pct": observation.metric("oi_delta_1h_pct").value,
        "oi_acceleration_1h_pct": observation.metric("oi_acceleration_1h_pct").value,
        "oi_to_market_cap_pct": observation.metric("oi_to_market_cap_pct").value,
        "oi_to_tradable_float_pct": observation.metric("oi_to_tradable_float_pct").value,
        "funding_rate_pct": observation.metric("funding_rate_pct").value,
        "funding_persistence": observation.metric("funding_persistence").value,
        "price_change_24h_pct": observation.metric("price_change_24h_pct").value,
        "broke_high_20d": observation.metric("broke_high_20d").value,
        "broke_high_90d": observation.metric("broke_high_90d").value,
        "holder_raw_top10_pct": observation.metric("top10_holder_pct").value,
        "holder_adjusted_top10_pct": observation.metric("adjusted_top10_pct").value,
        "holder_hhi": observation.metric("holder_hhi").value,
        "holder_gini": observation.metric("holder_gini").value,
        "cex_flow_to_float_pct": observation.metric("cex_deposit_24h_transfer_to_float_pct").value,
        "cex_flow_to_spot_volume_pct": observation.metric("cex_deposit_24h_notional_to_spot_volume_pct").value,
        "cex_flow_to_visible_liquidity_pct": observation.metric("cex_deposit_24h_notional_to_visible_liquidity_pct").value,
        "state": assessment.state.value,
        "score": assessment.score,
        "data_quality_pct": assessment.data_quality_pct,
        "gates": dict(assessment.gates),
        "funding_regime": assessment.funding_regime,
        "component_status": {name: item.status for name, item in assessment.components.items()},
        "missing_fields": list(assessment.missing_fields),
    }


def build_events(
    observations: Sequence[ReflexivityObservation],
    assessments: Sequence[ReflexivityAssessment],
    definition: EventStudyDefinition,
) -> list[FrozenEvent]:
    """Create deduplicated events from same-time observations and assessments."""

    by_id = {assessment.observation_id: assessment for assessment in assessments if assessment.observation_id}
    candidates: list[FrozenEvent] = []
    allowed = {str(state).upper() for state in definition.entry_states}
    holdout = definition.holdout_start
    for index, observation in enumerate(observations):
        assessment = by_id.get(observation.observation_id)
        if assessment is None and index < len(assessments):
            assessment = assessments[index]
        if assessment is None or observation.event_time is None:
            continue
        if assessment.state.value not in allowed or not assessment.market_trigger:
            continue
        split = "holdout" if holdout is not None and observation.event_time >= holdout else "development"
        event_id = f"{observation.symbol}:{observation.event_time.isoformat()}"
        candidates.append(
            FrozenEvent(
                event_id=event_id,
                symbol=observation.symbol,
                event_time=observation.event_time,
                state=assessment.state.value,
                score=assessment.score,
                market_trigger=assessment.market_trigger,
                structural_watch=assessment.structural_watch,
                signal_version=assessment.signal_version,
                split=split,
                observation_id=observation.observation_id,
                source=observation.source,
                venue=observation.venue,
                evidence_snapshot=_event_evidence(observation, assessment),
            )
        )

    candidates.sort(key=lambda event: (event.symbol, event.event_time, event.event_id))
    selected: list[FrozenEvent] = []
    last_by_symbol: dict[str, datetime] = {}
    for event in candidates:
        previous = last_by_symbol.get(event.symbol)
        if previous is not None and event.event_time - previous < timedelta(hours=max(0, definition.dedupe_hours)):
            continue
        selected.append(event)
        last_by_symbol[event.symbol] = event.event_time
    return sorted(selected, key=lambda event: (event.event_time, event.symbol))


def build_matched_baseline_events(
    observations: Sequence[ReflexivityObservation],
    assessments: Sequence[ReflexivityAssessment],
    definition: EventStudyDefinition,
) -> list[FrozenEvent]:
    """Build a simple same-universe non-event comparison set.

    This is intentionally conservative: only observations that were not an
    entry state, exhaustion state, or invalidation are eligible. A production
    study should add richer regime/volume matching and publish that definition
    beside the results; this baseline is a transparent lower bound, not a
    claim of causal identification.
    """

    by_id = {assessment.observation_id: assessment for assessment in assessments if assessment.observation_id}
    output: list[FrozenEvent] = []
    excluded = {
        *definition.entry_states,
        ReflexivityState.EXHAUSTION_RISK.value,
        ReflexivityState.INVALIDATED.value,
    }
    holdout = definition.holdout_start
    for index, observation in enumerate(observations):
        assessment = by_id.get(observation.observation_id)
        if assessment is None and index < len(assessments):
            assessment = assessments[index]
        if assessment is None or observation.event_time is None or assessment.state.value in excluded:
            continue
        split = "holdout" if holdout is not None and observation.event_time >= holdout else "development"
        output.append(
            FrozenEvent(
                event_id=f"baseline:{observation.symbol}:{observation.event_time.isoformat()}",
                symbol=observation.symbol,
                event_time=observation.event_time,
                state="BASELINE_NON_EVENT",
                score=assessment.score,
                market_trigger=False,
                structural_watch=False,
                signal_version=assessment.signal_version,
                split=split,
                observation_id=observation.observation_id,
                source=observation.source,
                venue=observation.venue,
                evidence_snapshot=_event_evidence(observation, assessment),
            )
        )
    return sorted(output, key=lambda event: (event.event_time, event.symbol))


def build_unconditional_baseline_events(
    observations: Sequence[ReflexivityObservation],
    assessments: Sequence[ReflexivityAssessment],
    definition: EventStudyDefinition,
) -> list[FrozenEvent]:
    """Create an unconditional same-universe snapshot set.

    This deliberately includes signal observations. It answers the descriptive
    question "what did the scanned universe do?" and is therefore not a clean
    control group. The report labels it explicitly so it cannot be mistaken for
    a causal comparison.
    """

    by_id = {assessment.observation_id: assessment for assessment in assessments if assessment.observation_id}
    holdout = definition.holdout_start
    output: list[FrozenEvent] = []
    for index, observation in enumerate(observations):
        assessment = by_id.get(observation.observation_id)
        if assessment is None and index < len(assessments):
            assessment = assessments[index]
        if assessment is None or observation.event_time is None:
            continue
        split = "holdout" if holdout is not None and observation.event_time >= holdout else "development"
        output.append(
            FrozenEvent(
                event_id=f"unconditional:{observation.symbol}:{observation.event_time.isoformat()}",
                symbol=observation.symbol,
                event_time=observation.event_time,
                state="UNCONDITIONAL_UNIVERSE",
                score=assessment.score,
                market_trigger=False,
                structural_watch=False,
                signal_version=assessment.signal_version,
                split=split,
                observation_id=observation.observation_id,
                source=observation.source,
                venue=observation.venue,
                evidence_snapshot=_event_evidence(observation, assessment),
            )
        )
    return sorted(output, key=lambda event: (event.event_time, event.symbol))


def build_token_history_baseline_events(
    observations: Sequence[ReflexivityObservation],
    assessments: Sequence[ReflexivityAssessment],
    definition: EventStudyDefinition,
) -> list[FrozenEvent]:
    """Create a token-own historical non-signal baseline.

    The caller should provide a sufficiently long pre-event history. With only
    a handful of snapshots this remains a coverage artifact, not evidence of
    predictive skill.
    """

    by_id = {assessment.observation_id: assessment for assessment in assessments if assessment.observation_id}
    excluded = set(definition.entry_states) | {
        ReflexivityState.EXHAUSTION_RISK.value,
        ReflexivityState.INVALIDATED.value,
    }
    holdout = definition.holdout_start
    candidates: list[FrozenEvent] = []
    for index, observation in enumerate(observations):
        assessment = by_id.get(observation.observation_id)
        if assessment is None and index < len(assessments):
            assessment = assessments[index]
        if assessment is None or observation.event_time is None or assessment.state.value in excluded:
            continue
        split = "holdout" if holdout is not None and observation.event_time >= holdout else "development"
        candidates.append(
            FrozenEvent(
                event_id=f"token-history:{observation.symbol}:{observation.event_time.isoformat()}",
                symbol=observation.symbol,
                event_time=observation.event_time,
                state="TOKEN_HISTORICAL_BASELINE",
                score=assessment.score,
                market_trigger=False,
                structural_watch=False,
                signal_version=assessment.signal_version,
                split=split,
                observation_id=observation.observation_id,
                source=observation.source,
                venue=observation.venue,
                evidence_snapshot=_event_evidence(observation, assessment),
            )
        )
    return sorted(candidates, key=lambda event: (event.event_time, event.symbol))


def _normalize_bars(bars: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in bars:
        timestamp = parse_utc(row.get("event_time") or row.get("timestamp") or row.get("time"))
        if timestamp is None:
            continue
        normalized.append(
            {
                "event_time": timestamp,
                "open": _number(row.get("open")),
                "high": _number(row.get("high")),
                "low": _number(row.get("low")),
                "close": _number(row.get("close")),
            }
        )
    return sorted(normalized, key=lambda row: row["event_time"])


def _bar_at_or_before(bars: Sequence[Mapping[str, Any]], timestamp: datetime) -> Mapping[str, Any] | None:
    previous = [bar for bar in bars if bar["event_time"] <= timestamp and bar.get("close") is not None]
    return previous[-1] if previous else None


def _forward_window(bars: Sequence[Mapping[str, Any]], event_time: datetime, horizon: timedelta) -> list[Mapping[str, Any]]:
    end = event_time + horizon
    return [bar for bar in bars if event_time < bar["event_time"] <= end]


def _threshold_label(value: float) -> str:
    text = f"{float(value):g}"
    return text.replace("-", "minus").replace(".", "p")


def _normalize_fuel_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        timestamp = parse_utc(row.get("event_time") or row.get("timestamp") or row.get("time"))
        if timestamp is None:
            continue
        normalized.append(
            {
                "event_time": timestamp,
                "short_account_pct": _number(row.get("short_account_pct")),
                "short_account_roc_1h_pp": _number(row.get("short_account_roc_1h_pp")),
                "short_account_peak_drawdown_pp": _number(row.get("short_account_peak_drawdown_pp")),
            }
        )
    return sorted(normalized, key=lambda row: row["event_time"])


def evaluate_event(
    event: FrozenEvent,
    bars: Iterable[Mapping[str, Any]],
    definition: EventStudyDefinition,
    *,
    fuel_bars: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Calculate future outcomes without adding future values to the event."""

    normalized = _normalize_bars(bars)
    normalized_fuel = _normalize_fuel_rows(fuel_bars)
    baseline_bar = _bar_at_or_before(normalized, event.event_time)
    baseline = _number(baseline_bar.get("close")) if baseline_bar else None
    output: dict[str, Any] = {
        "event_id": event.event_id,
        "symbol": event.symbol,
        "event_time": _iso(event.event_time),
        "split": event.split,
        "state": event.state,
        "score": event.score,
        "baseline_close": baseline,
        "baseline_bar_time": _iso(baseline_bar.get("event_time")) if baseline_bar else None,
        "fuel_observation_count": len(normalized_fuel),
        "fuel_coverage_status": "observed" if normalized_fuel else "missing",
    }
    if baseline is None:
        for horizon in definition.horizons_hours:
            output[f"return_{horizon}h_pct"] = None
            output[f"mfe_{horizon}h_pct"] = None
            output[f"mae_{horizon}h_pct"] = None
            output[f"threshold_{horizon}h_hit"] = None
            output[f"invalidation_{horizon}h_hit"] = None
            for threshold in definition.profit_thresholds_pct:
                output[f"profit_{_threshold_label(threshold)}_{horizon}h_hit"] = None
        for threshold in definition.profit_thresholds_pct:
            output[f"time_to_plus_{_threshold_label(threshold)}_minutes"] = None
        output["time_to_short_unwind_minutes"] = None
        output["peak_return_before_short_unwind_pct"] = None
        return output

    for horizon in definition.horizons_hours:
        window = _forward_window(normalized, event.event_time, timedelta(hours=horizon))
        target_time = event.event_time + timedelta(hours=horizon)
        target = next((bar for bar in window if bar["event_time"] >= target_time and bar.get("close") is not None), None)
        highs = [_number(bar.get("high")) for bar in window]
        lows = [_number(bar.get("low")) for bar in window]
        highs = [value for value in highs if value is not None]
        lows = [value for value in lows if value is not None]
        output[f"return_{horizon}h_pct"] = _pct(baseline, _number(target.get("close")) if target else None)
        output[f"mfe_{horizon}h_pct"] = _pct(baseline, max(highs)) if highs else None
        output[f"mae_{horizon}h_pct"] = _pct(baseline, min(lows)) if lows else None
        output[f"threshold_{horizon}h_hit"] = bool(highs and max(highs) >= baseline * (1.0 + definition.threshold_return_pct / 100.0)) if window else None
        output[f"invalidation_{horizon}h_hit"] = bool(lows and min(lows) <= baseline * (1.0 + definition.invalidation_return_pct / 100.0)) if window else None
        for threshold in definition.profit_thresholds_pct:
            label = _threshold_label(threshold)
            output[f"profit_{label}_{horizon}h_hit"] = bool(highs and max(highs) >= baseline * (1.0 + threshold / 100.0)) if window else None
        output[f"target_bar_time_{horizon}h"] = _iso(target.get("event_time")) if target else None

    threshold_time: float | None = None
    invalidation_time: float | None = None
    for bar in _forward_window(normalized, event.event_time, timedelta(hours=max(definition.horizons_hours))):
        high = _number(bar.get("high"))
        low = _number(bar.get("low"))
        elapsed = (bar["event_time"] - event.event_time).total_seconds() / 60.0
        if threshold_time is None and high is not None and high >= baseline * (1.0 + definition.threshold_return_pct / 100.0):
            threshold_time = elapsed
        if invalidation_time is None and low is not None and low <= baseline * (1.0 + definition.invalidation_return_pct / 100.0):
            invalidation_time = elapsed
    output["time_to_threshold_minutes"] = threshold_time
    output["time_to_invalidation_minutes"] = invalidation_time

    threshold_times: dict[float, float | None] = {threshold: None for threshold in definition.profit_thresholds_pct}
    max_horizon = timedelta(hours=max(definition.horizons_hours))
    for bar in _forward_window(normalized, event.event_time, max_horizon):
        high = _number(bar.get("high"))
        if high is None:
            continue
        elapsed = (bar["event_time"] - event.event_time).total_seconds() / 60.0
        for threshold in definition.profit_thresholds_pct:
            if threshold_times[threshold] is None and high >= baseline * (1.0 + threshold / 100.0):
                threshold_times[threshold] = elapsed
    for threshold, minutes in threshold_times.items():
        output[f"time_to_plus_{_threshold_label(threshold)}_minutes"] = minutes

    unwind_time: float | None = None
    unwind_timestamp: datetime | None = None
    for row in normalized_fuel:
        if row["event_time"] <= event.event_time or row["event_time"] > event.event_time + max_horizon:
            continue
        short_level = row.get("short_account_pct")
        short_roc = row.get("short_account_roc_1h_pp")
        drawdown = row.get("short_account_peak_drawdown_pp")
        if (
            (short_level is not None and short_level <= definition.short_unwind_level_pct)
            or (short_roc is not None and short_roc <= definition.short_unwind_roc_pp)
            or (drawdown is not None and drawdown <= definition.short_unwind_peak_drawdown_pp)
        ):
            unwind_timestamp = row["event_time"]
            unwind_time = (row["event_time"] - event.event_time).total_seconds() / 60.0
            break
    fuel_window_end = unwind_timestamp or event.event_time + max_horizon
    pre_unwind_bars = [
        bar
        for bar in normalized
        if event.event_time < bar["event_time"] <= fuel_window_end and _number(bar.get("high")) is not None
    ]
    pre_unwind_highs = [_number(bar.get("high")) for bar in pre_unwind_bars]
    pre_unwind_highs = [value for value in pre_unwind_highs if value is not None]
    output["time_to_short_unwind_minutes"] = unwind_time
    output["peak_return_before_short_unwind_pct"] = _pct(baseline, max(pre_unwind_highs)) if pre_unwind_highs else None
    return output


def _bootstrap_interval(
    values: Sequence[float],
    *,
    samples: int,
    seed: int,
    method: str = "iid",
    block_size: int = 3,
) -> tuple[float | None, float | None]:
    clean = [value for value in values if value is not None and math.isfinite(value)]
    if not clean:
        return None, None
    if len(clean) == 1 or samples <= 0:
        return clean[0], clean[0]
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(samples):
        if method == "block" and len(clean) > 1:
            sample = []
            block = max(1, int(block_size))
            while len(sample) < len(clean):
                start = rng.randrange(len(clean))
                sample.extend(clean[start : start + block])
            sample = sample[: len(clean)]
        else:
            sample = [clean[rng.randrange(len(clean))] for _ in clean]
        means.append(sum(sample) / len(sample))
    return _quantile(means, 0.025), _quantile(means, 0.975)


def _summarize_horizon(rows: Sequence[Mapping[str, Any]], horizon: int, definition: EventStudyDefinition) -> dict[str, Any]:
    return_values = [_number(row.get(f"return_{horizon}h_pct")) for row in rows]
    mfe_values = [_number(row.get(f"mfe_{horizon}h_pct")) for row in rows]
    mae_values = [_number(row.get(f"mae_{horizon}h_pct")) for row in rows]
    excess_values = [_number(row.get(f"excess_return_{horizon}h_pct")) for row in rows]
    threshold_values = [row.get(f"threshold_{horizon}h_hit") for row in rows if row.get(f"threshold_{horizon}h_hit") is not None]
    invalidation_values = [row.get(f"invalidation_{horizon}h_hit") for row in rows if row.get(f"invalidation_{horizon}h_hit") is not None]
    clean_returns = [value for value in return_values if value is not None]
    ci_low, ci_high = _bootstrap_interval(
        clean_returns,
        samples=definition.bootstrap_samples,
        seed=definition.bootstrap_seed + horizon,
        method=definition.bootstrap_method,
        block_size=definition.bootstrap_block_size,
    )
    clean_excess = [value for value in excess_values if value is not None]
    positive = [value for value in clean_returns if value >= definition.positive_return_threshold_pct]
    return {
        "horizon_hours": horizon,
        "event_count": len(rows),
        "outcome_count": len(clean_returns),
        "missing_outcome_count": len(rows) - len(clean_returns),
        "coverage_pct": round(len(clean_returns) / len(rows) * 100.0, 2) if rows else 0.0,
        "positive_hit_rate_pct": round(len(positive) / len(clean_returns) * 100.0, 2) if clean_returns else None,
        "threshold_hit_rate_pct": round(sum(bool(value) for value in threshold_values) / len(threshold_values) * 100.0, 2) if threshold_values else None,
        "invalidation_hit_rate_pct": round(sum(bool(value) for value in invalidation_values) / len(invalidation_values) * 100.0, 2) if invalidation_values else None,
        "median_return_pct": median(clean_returns) if clean_returns else None,
        "mean_return_pct": sum(clean_returns) / len(clean_returns) if clean_returns else None,
        "p25_return_pct": _quantile(clean_returns, 0.25),
        "p05_return_pct": _quantile(clean_returns, 0.05),
        "p95_return_pct": _quantile(clean_returns, 0.95),
        "p75_return_pct": _quantile(clean_returns, 0.75),
        "min_return_pct": min(clean_returns) if clean_returns else None,
        "max_return_pct": max(clean_returns) if clean_returns else None,
        "median_mfe_pct": median([value for value in mfe_values if value is not None]) if any(value is not None for value in mfe_values) else None,
        "median_mae_pct": median([value for value in mae_values if value is not None]) if any(value is not None for value in mae_values) else None,
        "excess_outcome_count": len(clean_excess),
        "median_excess_return_pct": median(clean_excess) if clean_excess else None,
        "p25_excess_return_pct": _quantile(clean_excess, 0.25),
        "p75_excess_return_pct": _quantile(clean_excess, 0.75),
        "bootstrap_mean_ci95_pct": [ci_low, ci_high],
        "bootstrap_method": definition.bootstrap_method,
    }


def summarize_outcomes(
    outcomes: Sequence[Mapping[str, Any]],
    definition: EventStudyDefinition,
    *,
    split: str | None = None,
) -> dict[str, Any]:
    rows = [row for row in outcomes if split is None or str(row.get("split")) == split]
    threshold_summary = {}
    for threshold in definition.profit_thresholds_pct:
        key = f"time_to_plus_{_threshold_label(threshold)}_minutes"
        values = [_number(row.get(key)) for row in rows]
        clean = [value for value in values if value is not None]
        threshold_summary[str(threshold)] = {
            "event_count": len(rows),
            "hit_count": len(clean),
            "hit_rate_pct": round(len(clean) / len(rows) * 100.0, 2) if rows else 0.0,
            "median_minutes": median(clean) if clean else None,
        }
    unwind_values = [_number(row.get("time_to_short_unwind_minutes")) for row in rows]
    peak_before_unwind = [_number(row.get("peak_return_before_short_unwind_pct")) for row in rows]
    clean_unwind = [value for value in unwind_values if value is not None]
    clean_peak = [value for value in peak_before_unwind if value is not None]
    fuel_observed = [row for row in rows if _number(row.get("fuel_observation_count")) is not None and _number(row.get("fuel_observation_count")) > 0]
    return {
        "split": split or "all",
        "event_count": len(rows),
        "horizons": {
            str(horizon): _summarize_horizon(rows, horizon, definition)
            for horizon in definition.horizons_hours
        },
        "time_to_threshold_median_minutes": median(
            [value for value in (_number(row.get("time_to_threshold_minutes")) for row in rows) if value is not None]
        )
        if any(_number(row.get("time_to_threshold_minutes")) is not None for row in rows)
        else None,
        "time_to_invalidation_median_minutes": median(
            [value for value in (_number(row.get("time_to_invalidation_minutes")) for row in rows) if value is not None]
        )
        if any(_number(row.get("time_to_invalidation_minutes")) is not None for row in rows)
        else None,
        "time_to_profit_thresholds": threshold_summary,
        "short_unwind_observation_count": len(clean_unwind),
        "time_to_short_unwind_median_minutes": median(clean_unwind) if clean_unwind else None,
        "peak_return_before_short_unwind_median_pct": median(clean_peak) if clean_peak else None,
        "fuel_coverage_pct": round(len(fuel_observed) / len(rows) * 100.0, 2) if rows else 0.0,
    }


def run_event_study(
    events: Sequence[FrozenEvent],
    price_paths: Mapping[str, Iterable[Mapping[str, Any]]],
    definition: EventStudyDefinition,
    *,
    baseline_events: Sequence[FrozenEvent] = (),
    unconditional_events: Sequence[FrozenEvent] = (),
    token_baseline_events: Sequence[FrozenEvent] = (),
    fuel_paths: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
    benchmark_paths: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
    benchmark_symbol: str = "BTCUSDT",
) -> dict[str, Any]:
    fuel_paths = fuel_paths or {}
    benchmark_bars = tuple(benchmark_paths.get(benchmark_symbol, ())) if benchmark_paths else ()

    def evaluate_collection(collection: Sequence[FrozenEvent]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for event in collection:
            outcome = evaluate_event(
                event,
                price_paths.get(event.symbol, ()),
                definition,
                fuel_bars=fuel_paths.get(event.symbol, ()),
            )
            if benchmark_bars:
                benchmark = evaluate_event(event, benchmark_bars, definition)
                for horizon in definition.horizons_hours:
                    event_return = _number(outcome.get(f"return_{horizon}h_pct"))
                    benchmark_return = _number(benchmark.get(f"return_{horizon}h_pct"))
                    outcome[f"benchmark_return_{horizon}h_pct"] = benchmark_return
                    outcome[f"excess_return_{horizon}h_pct"] = (
                        event_return - benchmark_return
                        if event_return is not None and benchmark_return is not None
                        else None
                    )
            output.append(outcome)
        return output

    outcomes = evaluate_collection(events)
    baseline_outcomes = evaluate_collection(baseline_events)
    unconditional_outcomes = evaluate_collection(unconditional_events)
    token_baseline_outcomes = evaluate_collection(token_baseline_events)
    report: dict[str, Any] = {
        "definition": definition.to_dict(),
        "event_study_version": definition.version,
        "event_count": len(events),
        "baseline_event_count": len(baseline_events),
        "unconditional_event_count": len(unconditional_events),
        "token_baseline_event_count": len(token_baseline_events),
        "benchmark_symbol": benchmark_symbol if benchmark_bars else None,
        "events": [event.to_dict() for event in events],
        "outcomes": outcomes,
        "summary": summarize_outcomes(outcomes, definition),
        "baseline_summary": summarize_outcomes(baseline_outcomes, definition),
        "baseline_outcomes": baseline_outcomes,
        "unconditional_summary": summarize_outcomes(unconditional_outcomes, definition),
        "unconditional_outcomes": unconditional_outcomes,
        "token_baseline_summary": summarize_outcomes(token_baseline_outcomes, definition),
        "token_baseline_outcomes": token_baseline_outcomes,
        "comparison_notes": {
            "matched_non_event": "same-universe non-event snapshots; descriptive lower bound, not causal matching",
            "unconditional_universe": "all supplied snapshots, including signal rows; descriptive universe context only",
            "token_historical": "non-signal snapshots from the same token history; requires sufficient pre-event coverage",
            "benchmark_excess": "event return minus benchmark return at the same horizon when benchmark bars are supplied",
        },
    }
    if definition.holdout_start is not None:
        report["development_summary"] = summarize_outcomes(outcomes, definition, split="development")
        report["holdout_summary"] = summarize_outcomes(outcomes, definition, split="holdout")
        report["baseline_development_summary"] = summarize_outcomes(baseline_outcomes, definition, split="development")
        report["baseline_holdout_summary"] = summarize_outcomes(baseline_outcomes, definition, split="holdout")
        report["unconditional_development_summary"] = summarize_outcomes(unconditional_outcomes, definition, split="development")
        report["unconditional_holdout_summary"] = summarize_outcomes(unconditional_outcomes, definition, split="holdout")
        report["token_baseline_development_summary"] = summarize_outcomes(token_baseline_outcomes, definition, split="development")
        report["token_baseline_holdout_summary"] = summarize_outcomes(token_baseline_outcomes, definition, split="holdout")
    return report
