from __future__ import annotations

"""Neutral casebook records for historical and illustrative episodes."""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class CasebookEntry:
    key: str
    symbol: str
    event_date: str
    archetype: str
    observed_facts: tuple[str, ...]
    inferences: tuple[str, ...]
    hypotheses: tuple[str, ...]
    unavailable: tuple[str, ...]
    sources: tuple[str, ...]
    phases: tuple[tuple[str, tuple[str, ...]], ...] = ()


CASEBOOK: tuple[CasebookEntry, ...] = (
    CasebookEntry(
        key="rave_2026_04_18",
        symbol="RAVEUSDT",
        event_date="2026-04-18",
        archetype="historical anchor: vertical repricing and unwind",
        observed_facts=(
            "The supplied chart identifies a Binance RAVE/USDT perpetual daily chart.",
            "The chart shows a quiet sub-dollar region followed by a very large upward wick and a sharp subsequent retracement.",
        ),
        inferences=(
            "The price path is consistent with a thin-liquidity, reflexive repricing episode.",
            "The episode is useful as a shape anchor for testing entry and exhaustion rules, not as proof of a repeatable cause.",
        ),
        hypotheses=(
            "A concentrated or constrained spot supply could have amplified marginal perp demand and forced buying.",
            "Crowded retail short accounts may have supplied fuel, but this must be tested against OI, top-trader positioning, and account-level outcomes.",
        ),
        unavailable=(
            "Point-in-time holder classification, adjusted float, labelled CEX flow, venue depth, funding, OI, and short-account observations are not reconstructed by the screenshots alone.",
            "Exact entry timestamp, fills, liquidation tape, and a no-lookahead event-study row are unavailable until a frozen source snapshot is imported.",
        ),
        sources=("user-supplied chart reference", "historical_examples.py"),
        phases=(
            ("BEFORE", ("A point-in-time ownership/float and derivatives baseline is not present in the supplied chart.", "The visible chart suggests a quieter lower-price regime before the large repricing.")),
            ("DETECTION", ("A historical detection row cannot be reconstructed from the screenshot alone; volume, OI, short-account, funding, and venue timestamps remain unavailable.",)),
            ("ACTIVE MOVE", ("The daily chart records a very large upside wick followed by a sharp retracement.", "Whether short covering or liquidation contributed is an unverified hypothesis.")),
            ("EXHAUSTION", ("The retracement is observed; the specific fuel-reset sequence, holder CEX flows, and liquidation tape are unavailable.",)),
        ),
    ),
    CasebookEntry(
        key="lab_2026_05_11",
        symbol="LABUSDT",
        event_date="2026-05-11",
        archetype="historical anchor: venue/float stress and continuation",
        observed_facts=(
            "The supplied chart identifies a Binance LAB/USDT perpetual daily chart dated May 11, 2026.",
            "The chart shows a long low-price base, a sharp repricing, a large upside wick, and continued high-volatility trading afterward.",
        ),
        inferences=(
            "The episode is consistent with a constrained-liquidity repricing where a large move can coexist with deep intratrend drawdowns.",
            "A high-volume trigger would be more informative when paired with contemporaneous OI, account crowding, venue, and holder evidence.",
        ),
        hypotheses=(
            "Venue inventory and concentrated effective float may have amplified the impact of forced flows.",
            "Positive funding can represent longs paying shorts while still coexisting with a long squeeze thesis; funding sign must not be used as a causal label.",
        ),
        unavailable=(
            "The chart does not establish wallet intent, actual short notional, liquidation volume, or whether observed holders were controllable supply.",
            "The exact point-in-time market and on-chain evidence required for a causal test is unavailable in the chart reference.",
        ),
        sources=("user-supplied chart reference", "historical_examples.py", "event_study.py"),
        phases=(
            ("BEFORE", ("The chart shows an extended low-price/base regime before the May 11, 2026 repricing.", "Normal prior volume, OI, adjusted float, and account positioning are not available from the chart.")),
            ("DETECTION", ("The sharp price/volume change is visually observable, but the exact point-in-time detection threshold cannot be recovered from the screenshot.")),
            ("ACTIVE MOVE", ("The chart shows a large upside move with high volatility and continued elevated trading afterward.", "Venue inventory stress and short-clientele fuel remain hypotheses until source snapshots are replayed.")),
            ("EXHAUSTION", ("A later stabilization/repricing path is visible, but short-share collapse, OI reset, funding extreme, and CEX inflow evidence are unavailable.",)),
        ),
    ),
)


def casebook_markdown(entries: Iterable[CasebookEntry] = CASEBOOK) -> str:
    lines = [
        "# Reflexivity Casebook",
        "",
        "This is a neutral research record. Each section separates observed facts, inferences, hypotheses, and unavailable evidence. Historical examples are anchors for falsifiable tests, not promises or trade instructions.",
        "",
    ]
    for entry in entries:
        lines.extend([f"## {entry.symbol} | {entry.event_date}", "", f"**Archetype:** {entry.archetype}", ""])
        for label, values in (
            ("OBSERVED FACT", entry.observed_facts),
            ("INFERENCE", entry.inferences),
            ("HYPOTHESIS", entry.hypotheses),
            ("UNAVAILABLE", entry.unavailable),
        ):
            lines.append(f"### {label}")
            lines.extend(f"- {value}" for value in values)
            lines.append("")
        if entry.phases:
            lines.append("### PHASE REPLAY")
            lines.append("")
            for phase, values in entry.phases:
                lines.append(f"#### {phase}")
                phase_values = (values,) if isinstance(values, str) else values
                lines.extend(f"- {value}" for value in phase_values)
                lines.append("")
        lines.append("**Sources:** " + "; ".join(entry.sources))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_casebook(path: Path | str, entries: Iterable[CasebookEntry] = CASEBOOK) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(casebook_markdown(entries), encoding="utf-8")
    return output
