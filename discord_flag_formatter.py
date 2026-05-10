from __future__ import annotations

import re
from typing import Any, Mapping

import pandas as pd


DISCORD_PRODUCT_IDENTITY = (
    "The scanner finds convex market-structure setups. "
    "The framework keeps you alive long enough to benefit from them."
)
DISCORD_FOOTER = "Not financial advice. Structural-risk screen only."
DISCORD_EMBED_DESCRIPTION_LIMIT = 3900
DISCORD_FLAG_CARD_TARGET_CHARS = 1450


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
            "trade_bucket_note",
            "convexity_summary",
            "rave_lab_setup_note",
            "dormant_short_fuse_note",
            "pre_pump_precision_note",
        )
    ).lower()
    return any(needle.lower() in haystack for needle in needles)


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
    short_pct = _first_float(row, ("short_account_pct",))
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

    if (top5 is not None and top5 >= 60.0) or (top10 is not None and top10 >= 70.0) or low_float >= 60.0:
        float_text = "thin upside liquidity"
    elif _has_note(row, "controlled float", "float trap", "low float"):
        float_text = "controlled-float risk"
    else:
        float_text = "float risk unconfirmed"
    return f"{pressure} + {flow} + {float_text}"


def infer_why_flagged(row: Mapping[str, Any] | pd.Series, holder_text: str = "") -> str:
    note = _metric_note(row)
    score = _score(row)
    short_pct = _first_float(row, ("short_account_pct",))
    bits: list[str] = []
    if score:
        bits.append(f"scanner score {score:.0f}/100")
    if short_pct is not None and short_pct >= 50.0:
        bits.append(f"{short_pct:.1f}% short-account pressure")
    if _has_note(row, "breakout"):
        bits.append("breakout pressure")
    if _has_note(row, "controlled float", "float trap", "low float"):
        bits.append("controlled-float risk")
    if _has_note(row, "MM/sponsor", "DWF", "venue support", "CEX/spot lane"):
        bits.append("venue/sponsor-flow signal")
    if not bits and note:
        bits.append(note)
    if not bits:
        bits.append("market-structure setup has enough evidence for review")
    return _clip_sentence(" + ".join(bits), 300)


def infer_convex_trigger(row: Mapping[str, Any] | pd.Series) -> str:
    short_pct = _first_float(row, ("short_account_pct",))
    oi_delta = _first_float(row, ("oi_delta_pct", "oi_value_change_since_scan_pct"))
    price_24h = _first_float(row, ("price_change_24h_pct", "change_24h_pct", "day_change_pct"))
    volume_multiple = _first_float(row, ("hour_volume_multiple", "daily_quote_volume_multiple"))

    if short_pct is not None and short_pct >= 60.0 and (oi_delta is None or oi_delta >= 0.0):
        return "short crowd remains crowded while OI holds or expands; reclaim pressure can force reflexive buying."
    if _has_note(row, "taker buyers", "strong hourly close"):
        return "taker buyers and close quality confirm momentum while the setup remains early."
    if price_24h is not None and price_24h > 0.0 and volume_multiple is not None and volume_multiple >= 1.5:
        return "price is expanding with volume confirmation before the structure has fully blown off."
    if oi_delta is not None and oi_delta > 0.0:
        return "OI is expanding into a convex market-structure setup."
    return "needs reclaim plus volume/OI confirmation before the setup graduates from watch to action."


def infer_invalidation(row: Mapping[str, Any] | pd.Series) -> str:
    if _has_note(row, "failed", "decay", "unwind"):
        return "failed reclaim, OI unwind, and volume decay."
    short_pct = _first_float(row, ("short_account_pct",))
    if short_pct is not None and short_pct >= 60.0:
        return "OI flush + short crowd normalizes + price fails to reclaim the trigger area."
    return "OI flush + failed reclaim + volume decay."


def infer_liquidity_warning(row: Mapping[str, Any] | pd.Series, holder_text: str = "") -> str:
    top1 = _holder_pct(holder_text, "Top1")
    top5 = _holder_pct(holder_text, "Top5")
    top100 = _holder_pct(holder_text, "Top100")
    range_pct = _first_float(row, ("range_24h_pct",))
    volume = _first_float(row, ("quote_volume_24h", "volume_24h"))
    if top100 is not None and top100 >= 95.0:
        return f"top 100 holders control {top100:.1f}% observed supply; exits can gap if flow flips."
    if top5 is not None and top5 >= 60.0:
        return f"top 5 holders control {top5:.1f}% observed supply; expect reflexive slippage."
    if top1 is not None and top1 >= 20.0:
        return f"dominant holder controls {top1:.1f}% observed supply; liquidity can vanish around stress."
    if range_pct is not None and range_pct >= 15.0:
        return f"24h range is {range_pct:.1f}%; use volatility as the slippage assumption."
    if volume is not None and volume < 5_000_000:
        return "thin quoted volume; assume limit fills may disappear when the setup moves."
    return "liquidity is not the edge; assume slippage rises when momentum crowds in."


def infer_dead_setup(row: Mapping[str, Any] | pd.Series) -> str:
    if _has_note(row, "late", "chase"):
        return "late extension without fresh OI/volume confirmation; do not chase a spent move."
    return "OI contracts, short pressure unwinds, reclaim fails, and volume fades across the next scan window."


def infer_hold_longer_condition(row: Mapping[str, Any] | pd.Series) -> str:
    short_pct = _first_float(row, ("short_account_pct",))
    if short_pct is not None and short_pct >= 60.0:
        return "higher lows continue while shorts stay trapped and OI/volume expand without a liquidation flush."
    if _has_note(row, "controlled float", "float trap"):
        return "structure remains controlled-float, liquidity stays thin, and reclaim levels keep holding."
    return "trend keeps reclaiming levels with expanding volume and no OI flush."


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
        f"Why flagged: {infer_why_flagged(row, holder_text)}",
        f"Convex trigger: {infer_convex_trigger(row)}",
        f"Invalidation: {infer_invalidation(row)}",
        f"Liquidity/slippage warning: {infer_liquidity_warning(row, holder_text)}",
        f"Risk level: {infer_risk_level(row, holder_text)}",
        f"What would make the setup dead: {infer_dead_setup(row)}",
        f"What would make it worth holding longer: {infer_hold_longer_condition(row)}",
        "Rule: small size, hard stop, no averaging down",
        "Principle: cut loss fast; trail winner only if structure remains intact",
    ]
    base = "\n".join(lines)
    if holder_text:
        holder_block = _clip_sentence(holder_text, max(180, max_chars - len(base) - 2))
        candidate = f"{base}\n{holder_block}" if holder_block else base
    else:
        candidate = base
    if len(candidate) <= max_chars:
        return candidate
    return f"{base[: max_chars - 3].rstrip()}..."


def join_discord_flag_cards(cards: list[str], *, max_chars: int = DISCORD_EMBED_DESCRIPTION_LIMIT) -> str:
    output: list[str] = []
    used = 0
    for index, card in enumerate(cards):
        block = card.strip()
        separator = "\n\n" if output else ""
        next_len = used + len(separator) + len(block)
        if next_len > max_chars:
            remaining = len(cards) - index
            suffix = f"\n\n... {remaining} more setup(s) omitted for Discord length."
            if used + len(suffix) <= max_chars:
                output.append(suffix.strip())
            break
        output.append(block)
        used = next_len
    return "\n\n".join(output)
