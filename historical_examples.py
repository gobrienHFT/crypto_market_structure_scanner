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
}

EXEMPLARS_BY_ARCHETYPE = {
    exemplar.archetype_label: exemplar
    for exemplar in HISTORICAL_PUMP_EXEMPLARS.values()
}


def exemplar_for_archetype(label: str) -> HistoricalPumpExemplar | None:
    return EXEMPLARS_BY_ARCHETYPE.get(str(label or "").strip())
