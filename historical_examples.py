from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HistoricalPumpExemplar:
    key: str
    symbol: str
    event_date: str
    archetype_label: str
    pattern: str
    pre_activity_fingerprint: str


HISTORICAL_PUMP_EXEMPLARS = {
    "rave_2026_04_18": HistoricalPumpExemplar(
        key="rave_2026_04_18",
        symbol="RAVEUSDT",
        event_date="2026-04-18",
        archetype_label="RAVE-style cap-table reflexivity",
        pattern="Binance perp vertical squeeze from a quiet sub-dollar base into a blowoff wick, then collapse.",
        pre_activity_fingerprint=(
            "dormant base, fake-looking FDV/float asymmetry, thin book, concentrated holder/control plane, "
            "and later reflexive forced-flow behavior"
        ),
    ),
    "lab_2026_05_11": HistoricalPumpExemplar(
        key="lab_2026_05_11",
        symbol="LABUSDT",
        event_date="2026-05-11",
        archetype_label="LAB-style venue-inventory stress",
        pattern="Binance perp vertical move into a high-volume venue-inventory stress event.",
        pre_activity_fingerprint=(
            "controlled float, target-venue inventory pressure, quiet-to-grind transition, thin displayed liquidity, "
            "and violent repricing once flow arrived"
        ),
    ),
    "siren_short_fuse": HistoricalPumpExemplar(
        key="siren_short_fuse",
        symbol="SIRENUSDT",
        event_date="scanner-observed",
        archetype_label="SIREN-style short-fuse compression",
        pattern="Short-fuse compression setup: quiet tape, short/oi pressure, and pre-ignition structure before chase heat.",
        pre_activity_fingerprint=(
            "short crowding, low-volatility compression, silent OI accumulation, pre-ignition quality, "
            "and no fully extended blowoff yet"
        ),
    ),
    "river_runway_breakout": HistoricalPumpExemplar(
        key="river_runway_breakout",
        symbol="RIVERUSDT",
        event_date="scanner-observed",
        archetype_label="RIVER-style runway breakout",
        pattern="Runway breakout setup: high-break structure with significant distance to prior extremes and persistent venue support.",
        pre_activity_fingerprint=(
            "open ATH runway, range-high breakout stack, constructive close location, venue support, "
            "and short/oi fuel that has not fully exhausted"
        ),
    ),
    "sto_target_venue_squeeze": HistoricalPumpExemplar(
        key="sto_target_venue_squeeze",
        symbol="STOUSDT",
        event_date="scanner-observed",
        archetype_label="STO-style target-venue squeeze",
        pattern="Target-venue squeeze setup: whale/control pressure, supported venues, and short crowding before late-stage chase.",
        pre_activity_fingerprint=(
            "target exchange support, concentrated/whale control evidence, short crowding, early timing, "
            "and high-break confirmation without exhaustion"
        ),
    ),
}

EXEMPLARS_BY_ARCHETYPE = {
    exemplar.archetype_label: exemplar
    for exemplar in HISTORICAL_PUMP_EXEMPLARS.values()
}


def exemplar_for_archetype(label: str) -> HistoricalPumpExemplar | None:
    return EXEMPLARS_BY_ARCHETYPE.get(str(label or "").strip())
