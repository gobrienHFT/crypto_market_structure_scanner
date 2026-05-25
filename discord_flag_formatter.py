from __future__ import annotations

import re
from typing import Any, Mapping

import pandas as pd


DISCORD_PRODUCT_IDENTITY = (
    "Latest scanner sample - market-structure candidates\n\n"
    "The scanner identifies abnormal structure: concentrated float, unusual positioning, "
    "OI stress, thin liquidity, and reflexive upside conditions.\n\n"
    "This is research tooling, not trade instruction. Entries, sizing, stops, and execution "
    "are your own responsibility.\n\n"
    "Most flags will fail. Losses must stay small. The rare outliers pay in lumps."
)
DISCORD_FOOTER = "Research tooling only. Structural-risk screen, not trade instruction."
DISCORD_EMBED_DESCRIPTION_LIMIT = 3900
DISCORD_FLAG_CARD_TARGET_CHARS = 1450


LANGUAGE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\bpump call\b", "market-structure flag"),
    (r"\bbuy call\b", "market-structure flag"),
    (r"\bbuy signal\b", "confirmation signal"),
    (r"\bpump signal\b", "structure signal"),
    (r"\bpump\b", "price expansion"),
    (r"\bbuying\b", "spot demand"),
    (r"\bbuyers\b", "participants"),
    (r"\bbuy\b", "enter"),
    (r"\bworth holding longer\b", "structure remains relevant while"),
    (r"\bholding longer\b", "remaining exposed"),
    (r"\bhold longer\b", "remain exposed"),
)


def sanitize_discord_language(text: str) -> str:
    sanitized = str(text or "")
    for pattern, replacement in LANGUAGE_REPLACEMENTS:
        sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)
    return sanitized


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _row_value(row: Mapping[str, Any] | pd.Series, key: str) -> Any:
    try:
        return row.get(key)  # type: ignore[attr-defined]
    except Exception:
        return None


def _first_float(row: Mapping[str, Any] | pd.Series, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _safe_float(_row_value(row, key))
        if value is not None:
            return value
    return None


def _first_text(row: Mapping[str, Any] | pd.Series, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _row_value(row, key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() not in {"nan", "none", "null"}:
            return text
    return ""


def _pct_value(value: float | None) -> float | None:
    if value is None:
        return None
    if value != 0.0 and abs(value) <= 1.0:
        return value * 100.0
    return value


def _score(row: Mapping[str, Any] | pd.Series) -> float:
    return _first_float(row, ("trade_bucket_score", "_discord_bucket_score", "convexity_entry_score", "convexity_score")) or 0.0


def _holder_pct(holder_text: str, label: str) -> float | None:
    match = re.search(rf"{re.escape(label)}\s+([0-9]+(?:\.[0-9]+)?)%", holder_text or "", flags=re.IGNORECASE)
    return _safe_float(match.group(1)) if match else None


def _clip_sentence(text: str, max_chars: int = 260) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= max_chars:
        return clean
    return f"{clean[: max_chars - 3].rstrip()}..."


def _metric_note(row: Mapping[str, Any] | pd.Series) -> str:
    return _first_text(
        row,
        (
            "cex_deposit_flow_note",
            "accumulation_absorption_note",
            "terminal_structural_opacity_note",
            "trade_bucket_note",
            "convexity_summary",
            "rave_lab_setup_note",
            "dormant_short_fuse_note",
            "pre_pump_precision_note",
        ),
    )


def _has_note(row: Mapping[str, Any] | pd.Series, *needles: str) -> bool:
    haystack = " | ".join(
        _first_text(row, (key,))
        for key in (
            "cex_deposit_flow_note",
            "accumulation_absorption_note",
            "terminal_structural_opacity_note",
            "trade_bucket_note",
            "convexity_summary",
            "rave_lab_setup_note",
            "dormant_short_fuse_note",
            "pre_pump_precision_note",
        )
    ).lower()
    return any(needle.lower() in haystack for needle in needles)


def _opaque_score(row: Mapping[str, Any] | pd.Series) -> float:
    return _max_float(
        row,
        (
            "terminal_hidden_float_reflexivity_score",
            "hidden_float_reflexivity_score",
            "terminal_opaque_supply_score",
            "opaque_supply_score",
        ),
    ) or 0.0


def _exchange_flow_score(row: Mapping[str, Any] | pd.Series) -> float:
    return _max_float(row, ("cex_deposit_flow_score", "terminal_exchange_flow_score", "insider_cex_flow_score")) or 0.0


def _private_unlock_score(row: Mapping[str, Any] | pd.Series) -> float:
    return _max_float(row, ("terminal_private_unlock_score", "private_unlock_overhang_score")) or 0.0


def _structure_edge_score(row: Mapping[str, Any] | pd.Series) -> float:
    return _first_float(row, ("terminal_structure_edge_score",)) or 0.0


def _control_plane_score(row: Mapping[str, Any] | pd.Series) -> float:
    return _first_float(row, ("terminal_control_plane_score",)) or 0.0


def _distribution_pressure_score(row: Mapping[str, Any] | pd.Series) -> float:
    return _first_float(row, ("terminal_distribution_pressure_score",)) or 0.0


def _pre_ignition_quality_score(row: Mapping[str, Any] | pd.Series) -> float:
    return _first_float(row, ("terminal_pre_ignition_quality_score",)) or 0.0


def _inventory_stress_score(row: Mapping[str, Any] | pd.Series) -> float:
    return _first_float(row, ("cex_deposit_inventory_stress_score",)) or 0.0


def _archetype_match_score(row: Mapping[str, Any] | pd.Series) -> float:
    return _first_float(row, ("archetype_match_score",)) or 0.0


def _row_boolish(row: Mapping[str, Any] | pd.Series, key: str) -> bool:
    value = _row_value(row, key)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    try:
        if value is None or pd.isna(value):
            return False
    except Exception:
        pass
    return bool(value)


def _accumulation_score(row: Mapping[str, Any] | pd.Series) -> float:
    return _first_float(row, ("accumulation_absorption_score", "accumulation_cvd_proxy_score")) or 0.0


def infer_accumulation_read(row: Mapping[str, Any] | pd.Series) -> str:
    score = _accumulation_score(row)
    if score < 45.0 and not _row_boolish(row, "accumulation_absorption_flag"):
        return ""
    note = _first_text(row, ("accumulation_absorption_note",))
    if note:
        return _clip_sentence(note, 260)
    taker_share = _pct_value(_first_float(row, ("taker_buy_share_pct",)))
    hour_return = _first_float(row, ("hour_return_pct",))
    parts = [f"score {score:.0f}/100"]
    if taker_share is not None:
        parts.append(f"taker demand {taker_share:.1f}%")
    if hour_return is not None:
        parts.append(f"1h response {hour_return:.1f}%")
    return "aggressive taker demand absorbed with muted price response; " + " | ".join(parts) + "; requires source/holder review"


def infer_case_study_analogue(row: Mapping[str, Any] | pd.Series) -> str:
    score = _archetype_match_score(row)
    if score < 35.0:
        return ""
    note = _first_text(row, ("archetype_match_note",))
    if note:
        return _clip_sentence(note, 220)
    label = _first_text(row, ("archetype_best_match",)) or "case-study analogue"
    return f"{label} {score:.0f}/100"


def infer_risk_level(row: Mapping[str, Any] | pd.Series, holder_text: str = "") -> str:
    score = _score(row)
    levels = ["Watch only", "Elevated", "High", "Extreme"]
    if score >= 90:
        index = 3
    elif score >= 75:
        index = 2
    elif score >= 60:
        index = 1
    else:
        index = 0

    top1 = _holder_pct(holder_text, "Top1")
    top5 = _holder_pct(holder_text, "Top5")
    top10 = _first_float(row, ("top10_holder_pct",)) or _holder_pct(holder_text, "Top10")
    centralized = _first_float(row, ("centralized_ownership_score", "owner_holder_pct", "creator_holder_pct")) or 0.0
    low_float = _first_float(row, ("low_float_score", "rave_lab_float_control_score")) or 0.0
    short_fuse = _first_float(row, ("dormant_short_fuse_score", "pre_pump_short_fuse_score")) or 0.0
    structure_edge = _structure_edge_score(row)
    distribution_pressure = _distribution_pressure_score(row)
    inventory_stress = _inventory_stress_score(row)
    if (
        (top1 is not None and top1 >= 50.0)
        or (top5 is not None and top5 >= 80.0)
        or (top10 is not None and top10 >= 80.0)
        or centralized >= 75.0
        or low_float >= 75.0
        or short_fuse >= 70.0
        or structure_edge >= 78.0
        or distribution_pressure >= 72.0
        or inventory_stress >= 65.0
    ):
        index = min(3, index + 1)
    return levels[index]


def infer_structure(row: Mapping[str, Any] | pd.Series, holder_text: str = "") -> str:
    short_pct = _pct_value(_first_float(row, ("short_account_pct",)))
    oi_delta = _first_float(row, ("oi_delta_pct", "oi_value_change_since_scan_pct"))
    volume_multiple = _first_float(row, ("hour_volume_multiple", "daily_quote_volume_multiple"))
    top5 = _holder_pct(holder_text, "Top5")
    top10 = _first_float(row, ("top10_holder_pct",)) or _holder_pct(holder_text, "Top10")
    low_float = _first_float(row, ("low_float_score",)) or 0.0
    accumulation = _accumulation_score(row)
    structure_edge = _structure_edge_score(row)
    distribution_pressure = _distribution_pressure_score(row)

    if short_pct is not None and short_pct >= 60.0:
        pressure = "High short pressure"
    elif short_pct is not None and short_pct >= 50.0:
        pressure = "Short crowd building"
    elif short_pct is not None and short_pct <= 30.0:
        pressure = "Long-heavy positioning"
    else:
        pressure = "Mixed account skew"

    if accumulation >= 65.0 or _row_boolish(row, "accumulation_absorption_flag"):
        flow = "aggressive taker demand absorbed"
    elif distribution_pressure >= 65.0:
        flow = "venue-inventory pressure"
    elif oi_delta is not None and oi_delta >= 2.0:
        flow = "rising OI"
    elif oi_delta is not None and oi_delta < -2.0:
        flow = "OI already flushing"
    elif volume_multiple is not None and volume_multiple >= 1.5:
        flow = "volume expanding"
    else:
        flow = "flow confirmation pending"

    opaque_score = _opaque_score(row)
    if structure_edge >= 70.0:
        float_text = "structural edge confirmed"
    elif opaque_score >= 70.0:
        float_text = "opaque-float / hidden-unlock risk"
    elif (top5 is not None and top5 >= 60.0) or (top10 is not None and top10 >= 70.0) or low_float >= 60.0:
        float_text = "thin upside liquidity"
    elif _has_note(row, "controlled float", "float trap", "low float", "opaque public float"):
        float_text = "controlled-float risk"
    else:
        float_text = "float risk unconfirmed"
    return f"{pressure} + {flow} + {float_text}"


def infer_why_flagged(row: Mapping[str, Any] | pd.Series, holder_text: str = "") -> str:
    note = _metric_note(row)
    score = _score(row)
    short_pct = _pct_value(_first_float(row, ("short_account_pct",)))
    bits: list[str] = []
    range_event = _first_text(row, ("range_breakout_event",))
    archetype = infer_case_study_analogue(row)
    if score:
        bits.append(f"scanner score {score:.0f}/100")
    if archetype:
        bits.append(archetype)
    if short_pct is not None and short_pct >= 50.0:
        bits.append(f"{short_pct:.1f}% short-account pressure")
    if range_event:
        bits.append(range_event)
    if _has_note(row, "breakout"):
        bits.append("breakout pressure")
    if _opaque_score(row) >= 60.0 or _private_unlock_score(row) >= 60.0:
        bits.append("opaque supply/unlock risk")
    if _exchange_flow_score(row) >= 60.0:
        bits.append("concentration-gated CEX-flow signal")
    if _inventory_stress_score(row) >= 45.0:
        bits.append("CEX inventory stress versus visible liquidity")
    if _structure_edge_score(row) >= 65.0:
        bits.append("structure-edge confluence")
    if _pre_ignition_quality_score(row) >= 65.0:
        bits.append("pre-ignition quality still intact")
    if _accumulation_score(row) >= 60.0 or _row_boolish(row, "accumulation_absorption_flag"):
        bits.append("accumulation-like absorption")
    if _has_note(row, "controlled float", "float trap", "low float", "opaque public float"):
        bits.append("controlled-float risk")
    if _has_note(row, "MM/sponsor", "DWF", "venue support", "CEX/spot lane"):
        bits.append("venue/sponsor-flow signal")
    if not bits and note:
        bits.append(note)
    if not bits:
        bits.append("market-structure setup has enough evidence for review")
    return _clip_sentence(" + ".join(bits), 300)


def infer_convex_trigger(row: Mapping[str, Any] | pd.Series) -> str:
    short_pct = _pct_value(_first_float(row, ("short_account_pct",)))
    oi_delta = _first_float(row, ("oi_delta_pct", "oi_value_change_since_scan_pct"))
    price_24h = _first_float(row, ("price_change_24h_pct", "change_24h_pct", "day_change_pct"))
    volume_multiple = _first_float(row, ("hour_volume_multiple", "daily_quote_volume_multiple"))
    range_event = _first_text(row, ("range_breakout_event",))

    if _accumulation_score(row) >= 65.0 or _row_boolish(row, "accumulation_absorption_flag"):
        return "aggressive taker demand is being absorbed while price response remains muted; OI/volume confirmation keeps the setup under review."
    if _inventory_stress_score(row) >= 55.0:
        return "recent venue inventory is large versus visible liquidity; constructive absorption plus stable OI keeps the setup under review."
    if range_event and (oi_delta is None or oi_delta >= 0.0):
        return f"{range_event} while flow conditions remain under review."
    if short_pct is not None and short_pct >= 60.0 and (oi_delta is None or oi_delta >= 0.0):
        return "short crowd remains crowded while OI holds or expands; reclaim pressure can create reflexive conditions."
    if _has_note(row, "taker buyers", "strong hourly close"):
        return "taker flow and close quality suggest momentum while the structure remains early."
    if price_24h is not None and price_24h > 0.0 and volume_multiple is not None and volume_multiple >= 1.5:
        return "price is expanding with volume confirmation before the structure appears fully extended."
    if oi_delta is not None and oi_delta > 0.0:
        return "OI is expanding into an abnormal market-structure window."
    return "reclaim plus volume/OI confirmation would improve the structural read."


def infer_invalidation(row: Mapping[str, Any] | pd.Series) -> str:
    if _has_note(row, "failed", "decay", "unwind"):
        return "OI contracts, volume fades, reclaim fails, and short pressure unwinds."
    short_pct = _pct_value(_first_float(row, ("short_account_pct",)))
    if short_pct is not None and short_pct >= 60.0:
        return "OI contracts, short crowd normalizes, price fails to reclaim, and volume fades."
    return "OI contracts, volume fades, reclaim fails, and short pressure unwinds."


def infer_liquidity_warning(row: Mapping[str, Any] | pd.Series, holder_text: str = "") -> str:
    top1 = _holder_pct(holder_text, "Top1")
    top5 = _holder_pct(holder_text, "Top5")
    top100 = _holder_pct(holder_text, "Top100")
    range_pct = _first_float(row, ("range_24h_pct",))
    volume = _first_float(row, ("quote_volume_24h", "volume_24h"))
    if _opaque_score(row) >= 70.0 or _private_unlock_score(row) >= 70.0:
        return "reported float may not capture private unlock/OTC supply; visible liquidity can reprice abruptly."
    if _exchange_flow_score(row) >= 70.0:
        return "recent concentration-gated CEX-flow signal; visible depth can change quickly around stress."
    if _inventory_stress_score(row) >= 55.0:
        note = _first_text(row, ("cex_deposit_inventory_stress_note",))
        if note:
            return _clip_sentence(note + "; visible depth can change quickly around stress.", 260)
        return "recent venue inventory is large versus visible liquidity; verify whether the book absorbs it."
    if _accumulation_score(row) >= 65.0 or _row_boolish(row, "accumulation_absorption_flag"):
        return "absorption-like tape can release into gaps if displayed liquidity thins; verify depth before acting."
    if top100 is not None and top100 >= 95.0:
        return f"top 100 holders control {top100:.1f}% observed supply; exits can gap if flow flips."
    if top5 is not None and top5 >= 60.0:
        return f"top 5 holders control {top5:.1f}% observed supply; reflexive slippage risk is elevated."
    if top1 is not None and top1 >= 20.0:
        return f"dominant holder controls {top1:.1f}% observed supply; liquidity can vanish around stress."
    if range_pct is not None and range_pct >= 15.0:
        return f"24h range is {range_pct:.1f}%; volatility should be treated as a core risk input."
    if volume is not None and volume < 5_000_000:
        return "thin quoted volume; fills may deteriorate when the structure moves."
    return "liquidity is not the edge; slippage risk can rise when momentum crowds in."


def infer_dead_setup(row: Mapping[str, Any] | pd.Series) -> str:
    if _has_note(row, "late", "chase"):
        return "late extension without fresh OI/volume confirmation."
    if _opaque_score(row) >= 70.0 or _private_unlock_score(row) >= 70.0:
        return "exchange-flow dries up, OI rolls over, and unlock/holder evidence no longer supports float scarcity."
    return "OI contracts, short pressure unwinds, reclaim fails, and volume fades across the next scan window."


def infer_hold_longer_condition(row: Mapping[str, Any] | pd.Series) -> str:
    short_pct = _pct_value(_first_float(row, ("short_account_pct",)))
    if _accumulation_score(row) >= 65.0 or _row_boolish(row, "accumulation_absorption_flag"):
        return "absorption persists, OI does not flush, and price avoids chase extension"
    if short_pct is not None and short_pct >= 60.0:
        return "higher lows continue while short pressure stays elevated and OI/volume expand without a liquidation flush."
    if _opaque_score(row) >= 70.0 or _has_note(row, "controlled float", "float trap", "opaque public float"):
        return "structure remains controlled-float, liquidity stays thin, and reclaim levels keep holding."
    return "trend keeps reclaiming levels with expanding volume and no OI flush."


def infer_perp_positioning(row: Mapping[str, Any] | pd.Series) -> str:
    short_pct = _pct_value(_first_float(row, ("short_account_pct",)))
    long_pct = _pct_value(_first_float(row, ("long_account_pct",)))
    ratio = _first_float(row, ("long_short_account_ratio",))
    oi_delta = _first_float(row, ("oi_delta_pct", "oi_value_change_since_scan_pct"))
    oi_to_volume = _first_float(row, ("oi_to_24h_volume_pct",))

    parts = [f"short accounts {short_pct:.1f}%" if short_pct is not None else "short accounts n/a"]
    if long_pct is not None:
        parts.append(f"long accounts {long_pct:.1f}%")
    if ratio is not None:
        parts.append(f"L/S acct {ratio:.2f}")
    if oi_delta is not None:
        parts.append(f"OI change {oi_delta:+.1f}%")
    if oi_to_volume is not None:
        parts.append(f"OI/24h vol {oi_to_volume:.1f}%")
    return " | ".join(parts)


def _format_amount(value: float | None) -> str:
    if value is None:
        return ""
    for suffix, divisor in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if abs(value) >= divisor:
            return f"{value / divisor:.2f}{suffix}"
    return f"{value:.2f}"


def _max_float(row: Mapping[str, Any] | pd.Series, keys: tuple[str, ...]) -> float | None:
    values = [_first_float(row, (key,)) for key in keys]
    present = [value for value in values if value is not None]
    return max(present) if present else None


def infer_evidence_stack(row: Mapping[str, Any] | pd.Series, holder_text: str = "") -> str:
    components: list[tuple[str, float]] = []

    def add(label: str, value: float | None) -> None:
        if value is not None and value > 0.0:
            components.append((label, max(0.0, min(100.0, value))))

    add("terminal", _first_float(row, ("terminal_edge_score",)))
    add("early radar", _first_float(row, ("early_pump_radar_score",)))
    add("timing", _first_float(row, ("timing_score",)))
    add("structure edge", _first_float(row, ("terminal_structure_edge_score",)))
    add("archetype", _first_float(row, ("archetype_match_score",)))
    add(
        "perp fuel",
        _max_float(
            row,
            (
                "short_liquidation_fuel_score",
                "short_dominance_score",
                "short_account_build_score",
                "perp_pressure_score",
                "convexity_squeeze_score",
            ),
        ),
    )
    top5 = _holder_pct(holder_text, "Top5")
    top10 = _first_float(row, ("top10_holder_pct",)) or _holder_pct(holder_text, "Top10")
    holder_float_score = max(value for value in (top5, top10) if value is not None) if any(value is not None for value in (top5, top10)) else None
    model_float_score = _max_float(
        row,
        (
            "terminal_float_score",
            "centralized_ownership_score",
            "low_float_score",
            "float_trap_score",
            "terminal_opaque_supply_score",
            "terminal_hidden_float_reflexivity_score",
        ),
    )
    float_scores = [value for value in (model_float_score, holder_float_score) if value is not None]
    add(
        "float control",
        max(float_scores) if float_scores else None,
    )
    add(
        "CEX flow",
        _max_float(
            row,
            (
                "cex_deposit_flow_score",
                "terminal_exchange_flow_score",
                "target_cex_flow_score",
                "insider_cex_flow_score",
            ),
        ),
    )
    add("inventory stress", _first_float(row, ("cex_deposit_inventory_stress_score",)))
    add("pre-ignition", _first_float(row, ("terminal_pre_ignition_quality_score",)))
    add("distribution pressure", _first_float(row, ("terminal_distribution_pressure_score",)))
    add(
        "venue support",
        _max_float(row, ("venue_support_score", "binance_bitget_gate_share_score", "mm_sponsor_confluence_score")),
    )
    add("runway", _first_float(row, ("convexity_runway_score",)))
    if not components:
        score = _score(row)
        return f"scanner {score:.0f}/100; component evidence pending" if score else "component evidence pending"

    components = sorted(components, key=lambda item: (-item[1], item[0]))
    return " | ".join(f"{label} {value:.0f}" for label, value in components[:6])


def infer_early_radar(row: Mapping[str, Any] | pd.Series) -> str:
    score = _first_float(row, ("early_pump_radar_score",))
    if score is None or score < 35.0:
        return ""
    state = _first_text(row, ("early_pump_state",)) or "watch"
    signal = _first_text(row, ("early_pump_primary_signal",))
    next_check = _first_text(row, ("early_pump_next_check",))
    parts = [f"{state} {score:.0f}/100"]
    if signal:
        parts.append(signal)
    if next_check:
        parts.append(f"next: {_clip_sentence(next_check, 120)}")
    return " | ".join(parts)


def infer_convex_thesis(row: Mapping[str, Any] | pd.Series, holder_text: str = "") -> str:
    short_pct = _pct_value(_first_float(row, ("short_account_pct",)))
    oi_delta = _first_float(row, ("oi_delta_pct", "oi_value_change_since_scan_pct"))
    cex_flow = _exchange_flow_score(row)
    opaque = _opaque_score(row)
    private_unlock = _private_unlock_score(row)
    accumulation = _accumulation_score(row)
    structure_edge = _structure_edge_score(row)
    control_plane = _control_plane_score(row)
    pre_ignition = _pre_ignition_quality_score(row)
    distribution_pressure = _distribution_pressure_score(row)
    top10 = _first_float(row, ("top10_holder_pct",)) or _holder_pct(holder_text, "Top10")
    low_float = _first_float(row, ("low_float_score", "float_trap_score", "centralized_ownership_score")) or 0.0
    constrained_float = (top10 is not None and top10 >= 75.0) or low_float >= 65.0 or opaque >= 65.0

    if cex_flow >= 70.0 and constrained_float:
        return "concentrated holder structure plus fresh CEX-flow creates a venue-inventory stress window; validate against OI and price absorption."
    if structure_edge >= 75.0 and pre_ignition >= 60.0:
        return "control-plane, pre-ignition, and flow evidence line up before full chase extension; timing decides whether the edge survives."
    if distribution_pressure >= 70.0 and control_plane >= 60.0:
        return "controlled float plus venue-inventory pressure creates a stress window; validate whether added supply is absorbed or rejected."
    if short_pct is not None and short_pct >= 60.0 and constrained_float:
        return "crowded shorts are leaning into constrained or opaque float; payoff turns convex only if OI expands and reclaim levels hold."
    if accumulation >= 65.0 or _row_boolish(row, "accumulation_absorption_flag"):
        return "absorption-like tape suggests patient demand under the surface; needs OI and volume confirmation before it graduates."
    if cex_flow >= 60.0:
        return "fresh wallet-to-CEX flow raises venue-inventory risk; strongest read comes from the next balance, OI, and price response."
    if opaque >= 70.0 or private_unlock >= 70.0:
        return "reported float may be thinner than common screens imply; reflexivity improves only when market flow confirms."
    if short_pct is not None and short_pct >= 60.0 and (oi_delta is None or oi_delta >= 0.0):
        return "short accounts are crowded while OI is stable or rising; monitor for forced-flow pressure after reclaim."
    if _score(row) >= 75.0:
        return "multi-factor market-structure evidence is present; timing and liquidity decide whether the setup is actionable."
    return "watchlist candidate until structural evidence, timing, and venue flow line up."


def infer_next_check(row: Mapping[str, Any] | pd.Series) -> str:
    timing_state = _first_text(row, ("timing_state",))
    if _inventory_stress_score(row) >= 45.0:
        return "recheck whether recent venue inventory is absorbed by price, OI, volume, and visible depth."
    if _exchange_flow_score(row) >= 60.0 or infer_recent_cex_flow(row):
        return "recheck target-exchange balances, OI expansion, and whether price absorbs or rejects added venue inventory."
    if _accumulation_score(row) >= 65.0 or _row_boolish(row, "accumulation_absorption_flag"):
        return "recheck whether absorption persists with higher volume, stable OI, and no chase extension."
    short_pct = _pct_value(_first_float(row, ("short_account_pct",)))
    if short_pct is not None and short_pct >= 60.0:
        return "recheck short-account pressure, OI, funding, and reclaim or failed-reclaim behavior on the next scan."
    if timing_state:
        return f"recheck that timing remains {timing_state} while volume, OI, and liquidity do not deteriorate."
    return "recheck after the next scan window for volume, OI, holder, and venue-flow confirmation."


def _fit_labeled_lines(lines: list[str], max_chars: int) -> str:
    candidate = "\n".join(lines)
    if len(candidate) <= max_chars:
        return candidate

    protected_prefixes = ("Convex Score:", "Risk level:", "Research constraint:", "Principle:")
    variable: list[tuple[int, str, str]] = []
    fixed_len = 0
    prefix_len = 0
    for index, line in enumerate(lines):
        if ": " in line and not line.startswith(protected_prefixes):
            label, text = line.split(": ", 1)
            prefix = f"{label}: "
            variable.append((index, prefix, text))
            prefix_len += len(prefix)
        else:
            fixed_len += len(line)

    if not variable:
        return candidate[: max_chars - 3].rstrip() + "..."

    newline_len = max(0, len(lines) - 1)
    remaining_text_budget = max_chars - fixed_len - prefix_len - newline_len
    per_line_budget = max(14, remaining_text_budget // len(variable))
    for budget in (per_line_budget, 90, 75, 60, 48, 36, 28, 20, 14):
        compact = list(lines)
        for index, prefix, text in variable:
            compact[index] = f"{prefix}{_clip_sentence(text, budget)}"
        candidate = "\n".join(compact)
        if len(candidate) <= max_chars:
            return candidate
    return candidate[: max_chars - 3].rstrip() + "..."


def infer_recent_cex_flow(row: Mapping[str, Any] | pd.Series) -> str:
    score = _first_float(row, ("cex_deposit_flow_score",))
    count = _first_float(row, ("cex_deposit_24h_count",))
    if (score is None or score <= 0.0) and (count is None or count <= 0.0):
        return ""
    parts: list[str] = []
    if score is not None:
        parts.append(f"score {score:.0f}/100")
    if count is not None:
        parts.append(f"{int(count)} large deposit(s)")
    targets = _first_text(row, ("cex_deposit_24h_target_exchanges",))
    if targets:
        parts.append(targets)
    gate = _first_text(row, ("cex_deposit_concentration_gate",))
    if gate:
        parts.append(gate)
    amount = _first_float(row, ("cex_deposit_24h_token_amount",))
    formatted_amount = _format_amount(amount)
    if formatted_amount:
        parts.append(f"{formatted_amount} tokens")
    notional = _first_float(row, ("cex_deposit_24h_notional_usd",))
    formatted_notional = _format_amount(notional)
    if formatted_notional:
        parts.append(f"{formatted_notional} notional")
    inventory_stress = _inventory_stress_score(row)
    if inventory_stress > 0.0:
        parts.append(f"inventory stress {inventory_stress:.0f}/100")
    return _clip_sentence(" | ".join(parts), 260)


def build_discord_flag_card(
    row: Mapping[str, Any] | pd.Series,
    *,
    holder_text: str = "",
    max_chars: int = DISCORD_FLAG_CARD_TARGET_CHARS,
) -> str:
    symbol = str(_row_value(row, "symbol") or "UNKNOWN").upper().strip()
    score = _score(row)
    recent_cex_flow = infer_recent_cex_flow(row)
    accumulation_read = infer_accumulation_read(row)
    case_study_analogue = infer_case_study_analogue(row)
    early_radar = infer_early_radar(row)
    lines = [
        f"/{symbol}",
        "",
        f"Convex Score: {score:.0f}/100",
        f"Structure: {infer_structure(row, holder_text)}",
        f"Convex thesis: {_clip_sentence(infer_convex_thesis(row, holder_text), 190)}",
        f"Evidence stack: {infer_evidence_stack(row, holder_text)}",
        *( [f"Case-study analogue: {case_study_analogue}"] if case_study_analogue else [] ),
        *( [f"Early radar: {early_radar}"] if early_radar else [] ),
        f"Perp positioning: {infer_perp_positioning(row)}",
        *( [f"Recent CEX flow: {recent_cex_flow}"] if recent_cex_flow else [] ),
        *( [f"Accumulation read: {accumulation_read}"] if accumulation_read else [] ),
        f"Why flagged: {infer_why_flagged(row, holder_text)}",
        f"Observed trigger: {infer_convex_trigger(row)}",
        f"Next check: {_clip_sentence(infer_next_check(row), 180)}",
        f"Invalidation: {infer_invalidation(row)}",
        f"Liquidity warning: {infer_liquidity_warning(row, holder_text)}",
        f"Risk level: {infer_risk_level(row, holder_text)}",
        f"Failure condition: {infer_dead_setup(row)}",
        f"Structure remains relevant while: {infer_hold_longer_condition(row)}",
        "Research constraint: user owns entries, sizing, stops, and execution",
        "Principle: small losses; stay exposed only while structure remains intact",
    ]
    base = "\n".join(lines)
    if holder_text:
        holder_block = _clip_sentence(holder_text, max(180, max_chars - len(base) - 2))
        candidate = f"{base}\n{holder_block}" if holder_block else base
    else:
        candidate = base
    candidate = sanitize_discord_language(candidate)
    if len(candidate) <= max_chars:
        return candidate
    return sanitize_discord_language(_fit_labeled_lines(lines, max_chars))


def _symbol_from_card(card: str) -> str:
    match = re.search(r"^\s*/([A-Z0-9_:-]+)", card or "", flags=re.MULTILINE)
    return match.group(1).upper() if match else ""


def _candidate_summary_line(cards: list[str]) -> str:
    symbols: list[str] = []
    seen: set[str] = set()
    for card in cards:
        symbol = _symbol_from_card(card)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(f"/{symbol}")
    return f"Candidates: {' '.join(symbols)}" if symbols else ""


def join_discord_flag_cards(cards: list[str], *, max_chars: int = DISCORD_EMBED_DESCRIPTION_LIMIT) -> str:
    summary = _candidate_summary_line(cards)
    output: list[str] = [summary] if summary else []
    used = len(summary)
    for index, card in enumerate(cards):
        block = sanitize_discord_language(card.strip())
        separator = "\n\n" if output else ""
        next_len = used + len(separator) + len(block)
        if next_len > max_chars:
            remaining = len(cards) - index
            suffix = (
                f"\n\n... detailed commentary for {remaining} more candidate(s) omitted for Discord length; "
                "see Candidates line above."
            )
            if used + len(suffix) <= max_chars:
                output.append(suffix.strip())
            break
        output.append(block)
        used = next_len
    return sanitize_discord_language("\n\n".join(output))
