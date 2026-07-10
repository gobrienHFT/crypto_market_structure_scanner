from __future__ import annotations

import math
from typing import Any

import pandas as pd


MECHANISM_SCORE_COLUMNS = [
    "mechanism_score",
    "mechanism_primary",
    "mechanism_stage",
    "mechanism_reflexivity_loop",
    "mechanism_playbook_label",
    "mechanism_playbook_rule",
    "mechanism_evidence_note",
    "mechanism_next_check",
    "mechanism_invalidation",
    "mechanism_hidden_float_score",
    "mechanism_inventory_squeeze_score",
    "mechanism_crowded_short_uptrend_score",
    "mechanism_compression_ignition_score",
    "mechanism_runway_breakout_score",
    "mechanism_late_failure_score",
]


MECHANISM_TEXT_COLUMNS = {
    "mechanism_primary",
    "mechanism_stage",
    "mechanism_reflexivity_loop",
    "mechanism_playbook_label",
    "mechanism_playbook_rule",
    "mechanism_evidence_note",
    "mechanism_next_check",
    "mechanism_invalidation",
}


def _num(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").fillna(default).astype("float64")


def _bool(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index, dtype="bool")
    return frame[column].fillna(False).astype(bool)


def _max_series(frame: pd.DataFrame, *columns: str) -> pd.Series:
    if not columns:
        return pd.Series(0.0, index=frame.index, dtype="float64")
    parts = [_num(frame, column) for column in columns]
    return pd.concat(parts, axis=1).max(axis=1).fillna(0.0).clip(lower=0.0, upper=100.0)


def _linear(series: pd.Series, *, low: float, high: float) -> pd.Series:
    if high <= low:
        return pd.Series(0.0, index=series.index, dtype="float64")
    score = (series.astype("float64") - low) / (high - low) * 100.0
    return score.clip(lower=0.0, upper=100.0).fillna(0.0)


def _safe_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return number if math.isfinite(number) else float("nan")


def _effective_funding(frame: pd.DataFrame) -> pd.Series:
    return pd.concat(
        [
            _num(frame, "effective_funding_pct", float("nan")),
            _num(frame, "carry_funding_pct", float("nan")),
            _num(frame, "predicted_funding_pct", float("nan")),
        ],
        axis=1,
    ).max(axis=1, skipna=True).fillna(0.0)


def apply_mechanism_model(frame: pd.DataFrame) -> pd.DataFrame:
    """Score the likely reflexivity mechanism behind each market-structure row."""
    out = frame.copy()
    if out.empty:
        for column in MECHANISM_SCORE_COLUMNS:
            out[column] = pd.Series(dtype="object" if column in MECHANISM_TEXT_COLUMNS else "float64")
        return out

    funding = _effective_funding(out)
    short_pct = _num(out, "short_account_pct")
    short_build = pd.concat(
        [
            _linear(_num(out, "short_account_roc_1h_pp"), low=0.20, high=3.0),
            _linear(_num(out, "short_account_change_max_pp"), low=0.75, high=6.0),
            _linear(_num(out, "short_account_change_max_pct"), low=2.0, high=12.0),
            _num(out, "short_account_build_score"),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    short_crowd = pd.concat(
        [
            _linear(short_pct, low=50.0, high=70.0),
            _num(out, "short_crowding_score"),
            _num(out, "short_dominance_score"),
            _num(out, "terminal_short_pressure_score"),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    funding_pressure = _linear(funding, low=0.0001, high=0.08)

    high_break_count = (
        _bool(out, "broke_high_5d").astype(float)
        + _bool(out, "broke_high_20d").astype(float)
        + _bool(out, "broke_high_90d").astype(float)
        + _bool(out, "broke_high_180d").astype(float)
    )
    low_break_count = (
        _bool(out, "broke_low_5d").astype(float)
        + _bool(out, "broke_low_20d").astype(float)
        + _bool(out, "broke_low_90d").astype(float)
        + _bool(out, "broke_low_180d").astype(float)
    )
    trend_pressure = pd.concat(
        [
            (high_break_count * 28.0).clip(lower=0.0, upper=100.0),
            _linear(_num(out, "range_high_break_count"), low=0.5, high=3.0),
            _num(out, "breakout_pressure_score"),
            _num(out, "trend_confluence_score"),
            _linear(_num(out, "day_return_pct"), low=2.0, high=35.0),
            _linear(_num(out, "hour_return_pct"), low=0.5, high=10.0),
            _linear(_num(out, "hour_close_location_pct"), low=55.0, high=85.0),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    runway_pressure = _max_series(
        out,
        "terminal_runway_score",
        "convexity_runway_score",
        "ath_runway_confluence_score",
        "runway_score",
    )

    float_control = _max_series(
        out,
        "terminal_hidden_float_reflexivity_score",
        "terminal_control_plane_score",
        "terminal_float_score",
        "centralized_ownership_score",
        "low_float_score",
        "float_trap_score",
        "convexity_float_score",
    )
    holder_concentration = pd.concat(
        [
            _linear(_num(out, "top10_holder_pct"), low=55.0, high=90.0),
            _linear(_num(out, "top100_holder_pct"), low=75.0, high=98.0),
            _linear(_num(out, "insider_team_holder_pct"), low=10.0, high=45.0),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    cex_inventory = _max_series(
        out,
        "cex_deposit_flow_score",
        "cex_deposit_inventory_stress_score",
        "terminal_exchange_flow_score",
        "target_cex_flow_score",
        "inventory_transfer_risk_score",
        "cex_lane_wakeup_score",
    )
    compression = _max_series(
        out,
        "pre_pump_compression_score",
        "pre_pump_short_fuse_score",
        "low_volatility_coil_score",
        "dormant_short_fuse_score",
        "silent_oi_accumulation_score",
        "terminal_pre_ignition_quality_score",
        "pre_activity_quiet_score",
        "pre_activity_preignition_score",
    )
    oi_fuel = pd.concat(
        [
            _linear(_num(out, "oi_delta_pct"), low=0.5, high=8.0),
            _linear(_num(out, "oi_to_24h_volume_pct"), low=2.0, high=25.0),
            _num(out, "forced_buying_setup_score"),
            _num(out, "short_liquidation_fuel_score"),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    late_failure = pd.concat(
        [
            _num(out, "crime_exhaustion_score"),
            _num(out, "convexity_late_penalty"),
            _num(out, "rave_lab_late_penalty_score"),
            _num(out, "timing_too_late_score"),
            _num(out, "terminal_risk_score"),
            _num(out, "exit_fragility_score"),
            _bool(out, "blowoff_risk_flag").astype(float) * 100.0,
            _bool(out, "unwind_risk_flag").astype(float) * 70.0,
            low_break_count * 22.0,
        ],
        axis=1,
    ).max(axis=1).fillna(0.0).clip(lower=0.0, upper=100.0)

    hidden_float = (
        float_control * 0.42
        + holder_concentration * 0.23
        + runway_pressure * 0.18
        + compression * 0.10
        + trend_pressure * 0.07
        - late_failure * 0.10
    ).clip(lower=0.0, upper=100.0)
    inventory_squeeze = (
        cex_inventory * 0.40
        + float_control * 0.22
        + short_crowd * 0.14
        + oi_fuel * 0.12
        + trend_pressure * 0.12
        - late_failure * 0.08
    ).clip(lower=0.0, upper=100.0)
    crowded_short_uptrend = (
        funding_pressure * 0.18
        + short_crowd * 0.23
        + short_build * 0.24
        + trend_pressure * 0.25
        + oi_fuel * 0.10
        - late_failure * 0.12
    ).clip(lower=0.0, upper=100.0)
    compression_ignition = (
        compression * 0.32
        + short_build * 0.22
        + short_crowd * 0.18
        + oi_fuel * 0.12
        + float_control * 0.10
        + trend_pressure * 0.06
        - late_failure * 0.10
    ).clip(lower=0.0, upper=100.0)
    runway_breakout = (
        runway_pressure * 0.34
        + trend_pressure * 0.26
        + float_control * 0.14
        + short_crowd * 0.12
        + funding_pressure * 0.08
        + oi_fuel * 0.06
        - late_failure * 0.10
    ).clip(lower=0.0, upper=100.0)

    mechanism_scores = pd.DataFrame(
        {
            "Hidden-float cap-table reflexivity": hidden_float,
            "CEX inventory squeeze": inventory_squeeze,
            "Crowded-short uptrend continuation": crowded_short_uptrend,
            "Compression ignition": compression_ignition,
            "Runway breakout reflexivity": runway_breakout,
        },
        index=out.index,
    )
    primary_score = mechanism_scores.max(axis=1).fillna(0.0).clip(lower=0.0, upper=100.0)
    primary_label = mechanism_scores.idxmax(axis=1).where(primary_score >= 25.0, "No dominant mechanism")

    out["mechanism_score"] = primary_score
    out["mechanism_primary"] = primary_label
    out["mechanism_hidden_float_score"] = hidden_float
    out["mechanism_inventory_squeeze_score"] = inventory_squeeze
    out["mechanism_crowded_short_uptrend_score"] = crowded_short_uptrend
    out["mechanism_compression_ignition_score"] = compression_ignition
    out["mechanism_runway_breakout_score"] = runway_breakout
    out["mechanism_late_failure_score"] = late_failure

    def _stage(row: pd.Series) -> str:
        late = _safe_float(row.get("mechanism_late_failure_score"))
        trend = _safe_float(row.get("_mechanism_trend_pressure"))
        comp = _safe_float(row.get("_mechanism_compression_pressure"))
        score = _safe_float(row.get("mechanism_score"))
        if late >= 72.0:
            return "distribution/exhaustion risk"
        if trend >= 70.0 and score >= 55.0:
            return "active continuation"
        if comp >= 60.0 and trend < 45.0:
            return "pre-ignition compression"
        if trend >= 45.0:
            return "ignition / breakout"
        return "watchlist structure"

    out["_mechanism_trend_pressure"] = trend_pressure
    out["_mechanism_compression_pressure"] = compression

    def _evidence(row: pd.Series) -> str:
        bits: list[str] = []
        primary = str(row.get("mechanism_primary", ""))
        if primary == "Crowded-short uptrend continuation":
            funding_value = _safe_float(row.get("_mechanism_funding"))
            shorts = _safe_float(row.get("short_account_pct"))
            build = _safe_float(row.get("_mechanism_short_build"))
            trend = _safe_float(row.get("_mechanism_trend_pressure"))
            if math.isfinite(funding_value):
                bits.append(f"funding {funding_value:.4f}%")
            if math.isfinite(shorts):
                bits.append(f"shorts {shorts:.1f}%")
            if math.isfinite(build):
                bits.append(f"short build {build:.0f}")
            if math.isfinite(trend):
                bits.append(f"trend {trend:.0f}")
            return " | ".join(bits[:5]) or "shorts are fighting an advancing tape"
        if primary == "CEX inventory squeeze":
            bits.append(f"CEX/inventory {(_safe_float(row.get('mechanism_inventory_squeeze_score')) or 0.0):.0f}")
            if _safe_float(row.get("cex_deposit_24h_token_amount")) > 0:
                bits.append(f"24h deposits {row.get('cex_deposit_24h_token_amount'):.0f} tokens")
            target = str(row.get("cex_deposit_24h_target_exchanges", "") or "").strip()
            if target:
                bits.append(f"targets {target[:48]}")
            return " | ".join(bits)
        if primary == "Hidden-float cap-table reflexivity":
            bits.append(f"float/control {(_safe_float(row.get('mechanism_hidden_float_score')) or 0.0):.0f}")
            top10 = _safe_float(row.get("top10_holder_pct"))
            if math.isfinite(top10) and top10 > 0:
                bits.append(f"top10 {top10:.1f}%")
            runway = _safe_float(row.get("terminal_runway_score"))
            if math.isfinite(runway):
                bits.append(f"runway {runway:.0f}")
            return " | ".join(bits)
        if primary == "Compression ignition":
            return f"compression {(_safe_float(row.get('mechanism_compression_ignition_score')) or 0.0):.0f} | shorts/build fuel before full chase"
        if primary == "Runway breakout reflexivity":
            return f"runway {(_safe_float(row.get('mechanism_runway_breakout_score')) or 0.0):.0f} | high-break structure with fuel still present"
        return "No single reflexive loop dominates this row yet."

    def _loop(row: pd.Series) -> str:
        primary = str(row.get("mechanism_primary", ""))
        mapping = {
            "Crowded-short uptrend continuation": "uptrend -> shorts add -> positive funding paid -> liquidation/fomo fuel -> higher trend",
            "CEX inventory squeeze": "controlled float -> inventory routed to CEX -> thin sellable float -> perp/spot chase -> forced repricing",
            "Hidden-float cap-table reflexivity": "concentrated float -> low real supply -> breakout visibility -> forced chase -> vertical repricing",
            "Compression ignition": "quiet range -> shorts/oi build -> first breakout -> volatility expansion -> squeeze attempt",
            "Runway breakout reflexivity": "distance to prior ATH -> breakout stack -> narrative runway -> incremental chase flow",
        }
        return mapping.get(primary, "watch for a cleaner float/flow/short/trend loop")

    def _next_check(row: pd.Series) -> str:
        primary = str(row.get("mechanism_primary", ""))
        if primary == "Crowded-short uptrend continuation":
            return "Watch shorts keep rising while price holds above breakout levels and funding stays positive."
        if primary == "CEX inventory squeeze":
            return "Confirm labelled CEX deposits, target exchange, and whether sell pressure is absorbed."
        if primary == "Hidden-float cap-table reflexivity":
            return "Confirm real float, holder unlock paths, and whether highs break before volume fully chases."
        if primary == "Compression ignition":
            return "Wait for range high break, OI expansion, and close-location confirmation."
        if primary == "Runway breakout reflexivity":
            return "Track breakout stack, ATH runway, volume expansion, and whether shorts keep leaning wrong-way."
        return "Wait for at least two of float, CEX flow, short pressure, or breakout structure to align."

    def _invalidation(row: pd.Series) -> str:
        primary = str(row.get("mechanism_primary", ""))
        if primary == "Crowded-short uptrend continuation":
            return "Invalidates if price breaks recent lows while shorts stop building or funding flips negative."
        if primary == "CEX inventory squeeze":
            return "Invalidates if CEX inflow converts into persistent sell pressure or flow evidence disappears."
        if primary == "Hidden-float cap-table reflexivity":
            return "Invalidates if float proves broad/liquid or breakout fails back into the base."
        if primary == "Compression ignition":
            return "Invalidates if compression resolves down or OI/short build unwinds before breakout."
        if primary == "Runway breakout reflexivity":
            return "Invalidates if high-break stack fails and volume/OI contract into the prior range."
        return "No trade thesis until a dominant mechanism appears."

    def _playbook_label(row: pd.Series) -> str:
        primary = str(row.get("mechanism_primary", ""))
        stage = str(row.get("mechanism_stage", ""))
        score = _safe_float(row.get("mechanism_score"))
        late = _safe_float(row.get("mechanism_late_failure_score"))
        if late >= 72.0 or stage == "distribution/exhaustion risk":
            return "C: no-chase / unwind risk"
        if primary == "Crowded-short uptrend continuation" and score >= 50.0:
            return "A: continuation watch"
        if primary == "CEX inventory squeeze" and score >= 55.0:
            return "A: CEX-inventory watch"
        if primary == "Compression ignition" and stage == "pre-ignition compression":
            return "B: pre-ignition proof watch"
        if primary in {"Hidden-float cap-table reflexivity", "Runway breakout reflexivity"} and score >= 45.0:
            return "B: trigger proof needed"
        if score >= 35.0:
            return "B: structure watch"
        return "D: insufficient mechanism"

    def _playbook_rule(row: pd.Series) -> str:
        label = str(row.get("mechanism_playbook_label", ""))
        primary = str(row.get("mechanism_primary", ""))
        if label.startswith("C:"):
            return "Respect the RAVE lesson: prior-high blowoffs with late-risk are review-only until structure resets."
        if primary == "Crowded-short uptrend continuation":
            return "Use the VELVET lesson: keep watching while shorts rebuild, funding stays positive, and highs persist; invalidate on low break/funding flip."
        if primary == "CEX inventory squeeze":
            return "Use the LAB lesson: require CEX/holder proof plus breakout confirmation, and assume deep pullbacks are normal."
        if primary == "Compression ignition":
            return "Wait for the first clean range-high break with OI/short expansion before promoting."
        if primary == "Runway breakout reflexivity":
            return "Runway alone is not enough; require high-break stack, short fuel, and venue/holder proof."
        if primary == "Hidden-float cap-table reflexivity":
            return "Require real float/control proof and avoid buying after exhaustion appears."
        return "Keep as context until float, flow, shorts, and structure align."

    out["_mechanism_funding"] = funding
    out["_mechanism_short_build"] = short_build
    out["mechanism_stage"] = out.apply(_stage, axis=1)
    out["mechanism_reflexivity_loop"] = out.apply(_loop, axis=1)
    out["mechanism_playbook_label"] = out.apply(_playbook_label, axis=1)
    out["mechanism_playbook_rule"] = out.apply(_playbook_rule, axis=1)
    out["mechanism_evidence_note"] = out.apply(_evidence, axis=1)
    out["mechanism_next_check"] = out.apply(_next_check, axis=1)
    out["mechanism_invalidation"] = out.apply(_invalidation, axis=1)
    return out.drop(columns=["_mechanism_trend_pressure", "_mechanism_compression_pressure", "_mechanism_funding", "_mechanism_short_build"])
