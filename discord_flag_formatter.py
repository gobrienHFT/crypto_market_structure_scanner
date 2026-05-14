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
    return _first_float(
        row,
        (
            "terminal_hidden_float_reflexivity_score",
            "hidden_float_reflexivity_score",
            "terminal_opaque_supply_score",
            "opaque_supply_score",
        ),
    ) or 0.0


def _exchange_flow_score(row: Mapping[str, Any] | pd.Series) -> float:
    return _first_float(row, ("terminal_exchange_flow_score", "insider_cex_flow_score")) or 0.0


def _private_unlock_score(row: Mapping[str, Any] | pd.Series) -> float:
    return _first_float(row, ("terminal_private_unlock_score", "private_unlock_overhang_score")) or 0.0


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
    if (
        (top1 is not None and top1 >= 50.0)
        or (top5 is not None and top5 >= 80.0)
        or (top10 is not None and top10 >= 80.0)
        or centralized >= 75.0
        or low_float >= 75.0
        or short_fuse >= 70.0
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

    if short_pct is not None and short_pct >= 60.0:
        pressure = "High short pressure"
    elif short_pct is not None and short_pct >= 50.0:
        pressure = "Short crowd building"
    elif short_pct is not None and short_pct <= 30.0:
        pressure = "Long-heavy positioning"
    else:
        pressure = "Mixed account skew"

    if oi_delta is not None and oi_delta >= 2.0:
        flow = "rising OI"
    elif oi_delta is not None and oi_delta < -2.0:
        flow = "OI already flushing"
    elif volume_multiple is not None and volume_multiple >= 1.5:
        flow = "volume expanding"
    else:
        flow = "flow confirmation pending"

    opaque_score = _opaque_score(row)
    if opaque_score >= 70.0:
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
    if score:
        bits.append(f"scanner score {score:.0f}/100")
    if short_pct is not None and short_pct >= 50.0:
        bits.append(f"{short_pct:.1f}% short-account pressure")
    if range_event:
        bits.append(range_event)
    if _has_note(row, "breakout"):
        bits.append("breakout pressure")
    if _opaque_score(row) >= 60.0 or _private_unlock_score(row) >= 60.0:
        bits.append("opaque supply/unlock risk")
    if _exchange_flow_score(row) >= 60.0:
        bits.append("issuer-linked CEX-flow signal")
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
        return "clustered CEX-flow signal; visible depth can change quickly around stress."
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


def build_discord_flag_card(
    row: Mapping[str, Any] | pd.Series,
    *,
    holder_text: str = "",
    max_chars: int = DISCORD_FLAG_CARD_TARGET_CHARS,
) -> str:
    symbol = str(_row_value(row, "symbol") or "UNKNOWN").upper().strip()
    score = _score(row)
    lines = [
        f"/{symbol}",
        "",
        f"Convex Score: {score:.0f}/100",
        f"Structure: {infer_structure(row, holder_text)}",
        f"Perp positioning: {infer_perp_positioning(row)}",
        f"Why flagged: {infer_why_flagged(row, holder_text)}",
        f"Observed trigger: {infer_convex_trigger(row)}",
        f"Invalidation: {infer_invalidation(row)}",
        f"Liquidity warning: {infer_liquidity_warning(row, holder_text)}",
        f"Risk level: {infer_risk_level(row, holder_text)}",
        f"Failure condition: {infer_dead_setup(row)}",
        f"Structure remains relevant while: {infer_hold_longer_condition(row)}",
        "Research constraint: entries, sizing, stops, and execution are your own responsibility",
        "Principle: losses must stay small; only stay exposed while structure remains intact",
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
    return sanitize_discord_language(f"{base[: max_chars - 3].rstrip()}...")


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
