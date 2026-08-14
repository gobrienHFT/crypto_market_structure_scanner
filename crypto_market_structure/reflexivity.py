from __future__ import annotations

"""Canonical, provenance-aware reflexivity observation and state model.

This module deliberately uses a small number of mechanism-linked components.
It is not an ML model and it does not turn missing data into a neutral score.
Missing, stale, proxy-only, and contested observations remain visible in the
assessment so the dashboard can distinguish a weak setup from weak coverage.
"""

import math
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Mapping


SIGNAL_VERSION = "reflexivity-v1.1"

FUNDING_SEMANTICS = {
    "positive": "positive funding means longs pay shorts",
    "negative": "negative funding means shorts pay longs",
    "research_use": "funding is carry/crowding context; it is not proof of a squeeze direction",
}


class ReflexivityState(str, Enum):
    DISCOVERY = "DISCOVERY"
    BUILDING = "BUILDING"
    ACTIVE_REFLEXIVITY = "ACTIVE_REFLEXIVITY"
    ACCELERATING = "ACCELERATING"
    EXHAUSTION_RISK = "EXHAUSTION_RISK"
    INVALIDATED = "INVALIDATED"


WALLET_CATEGORIES = (
    "exchange",
    "custody",
    "bridge",
    "burn",
    "lp",
    "protocol_system",
    "staking",
    "vesting",
    "treasury",
    "team_founder",
    "unidentified_whale",
    "ordinary_holder",
)


@dataclass(frozen=True)
class WalletClassification:
    """Auditable classification for one holder or control address.

    The canonical layer stores evidence about a label, never an inferred owner
    identity. ``category`` is a research classification and ``confidence`` is
    confidence in that classification, not confidence in the trade thesis.
    """

    address: str
    category: str = "unidentified_whale"
    label: str = ""
    confidence: str = "unknown"
    confidence_score: float | None = None
    pct_total_supply: float | None = None
    excluded_from_adjusted_float: bool = False
    evidence_source: str = ""
    evidence_note: str = ""
    classified_at: datetime | None = None
    provenance: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "category": self.category,
            "label": self.label,
            "confidence": self.confidence,
            "confidence_score": self.confidence_score,
            "pct_total_supply": self.pct_total_supply,
            "excluded_from_adjusted_float": self.excluded_from_adjusted_float,
            "evidence_source": self.evidence_source,
            "evidence_note": self.evidence_note,
            "classified_at": _iso(self.classified_at),
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class OwnershipSnapshot:
    """Ownership/float snapshot with raw and adjusted views side by side."""

    circulating_supply: float | None = None
    total_supply: float | None = None
    fdv_usd: float | None = None
    market_cap_usd: float | None = None
    estimated_tradable_float_tokens: float | None = None
    estimated_tradable_float_usd: float | None = None
    tradable_float_pct: float | None = None
    raw_top10_pct: float | None = None
    raw_top100_pct: float | None = None
    adjusted_top10_pct: float | None = None
    adjusted_top100_pct: float | None = None
    holder_hhi: float | None = None
    holder_gini: float | None = None
    holder_count: float | None = None
    classification_coverage_pct: float | None = None
    classification_confidence: float | None = None
    event_time: datetime | None = None
    received_at: datetime | None = None
    source: str = ""
    provenance: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "circulating_supply": self.circulating_supply,
            "total_supply": self.total_supply,
            "fdv_usd": self.fdv_usd,
            "market_cap_usd": self.market_cap_usd,
            "estimated_tradable_float_tokens": self.estimated_tradable_float_tokens,
            "estimated_tradable_float_usd": self.estimated_tradable_float_usd,
            "tradable_float_pct": self.tradable_float_pct,
            "raw_top10_pct": self.raw_top10_pct,
            "raw_top100_pct": self.raw_top100_pct,
            "adjusted_top10_pct": self.adjusted_top10_pct,
            "adjusted_top100_pct": self.adjusted_top100_pct,
            "holder_hhi": self.holder_hhi,
            "holder_gini": self.holder_gini,
            "holder_count": self.holder_count,
            "classification_coverage_pct": self.classification_coverage_pct,
            "classification_confidence": self.classification_confidence,
            "event_time": _iso(self.event_time),
            "received_at": _iso(self.received_at),
            "source": self.source,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class VenueObservation:
    """Point-in-time venue metadata kept separate from venue inference."""

    venue: str
    market_type: str = "perpetual"
    available: bool | None = None
    volume_share_pct: float | None = None
    source: str = ""
    event_time: datetime | None = None
    received_at: datetime | None = None
    units: str = "boolean / percent"
    freshness_seconds: int | None = None
    provenance: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "market_type": self.market_type,
            "available": self.available,
            "volume_share_pct": self.volume_share_pct,
            "source": self.source,
            "event_time": _iso(self.event_time),
            "received_at": _iso(self.received_at),
            "units": self.units,
            "freshness_seconds": self.freshness_seconds,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class SupplyFlowObservation:
    """A labelled or classified wallet-to-CEX supply-flow observation."""

    target_exchange: str
    token_amount: float | None = None
    notional_usd: float | None = None
    sender_category: str = "unidentified_whale"
    sender_confidence: str = "unknown"
    transfer_to_float_pct: float | None = None
    notional_to_spot_volume_pct: float | None = None
    notional_to_visible_liquidity_pct: float | None = None
    source: str = ""
    event_time: datetime | None = None
    received_at: datetime | None = None
    units: str = "tokens / USD / percent"
    freshness_seconds: int | None = None
    provenance: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_exchange": self.target_exchange,
            "token_amount": self.token_amount,
            "notional_usd": self.notional_usd,
            "sender_category": self.sender_category,
            "sender_confidence": self.sender_confidence,
            "transfer_to_float_pct": self.transfer_to_float_pct,
            "notional_to_spot_volume_pct": self.notional_to_spot_volume_pct,
            "notional_to_visible_liquidity_pct": self.notional_to_visible_liquidity_pct,
            "source": self.source,
            "event_time": _iso(self.event_time),
            "received_at": _iso(self.received_at),
            "units": self.units,
            "freshness_seconds": self.freshness_seconds,
            "provenance": self.provenance,
        }


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if type(value).__name__ in {"NAType", "NaTType"}:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "nan", "nat", "none", "null", "<na>"}
    if isinstance(value, bool):
        return False
    try:
        result = value != value
        if isinstance(result, bool) and result:
            return True
    except Exception:
        pass
    try:
        scalar = value.item() if hasattr(value, "item") else value
        if isinstance(scalar, float) and math.isnan(scalar):
            return True
    except Exception:
        pass
    return False


def _number(value: Any) -> float | None:
    if _is_missing(value) or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _bool(value: Any) -> bool | None:
    if _is_missing(value):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "y", "on"}:
            return True
        if text in {"false", "0", "no", "n", "off"}:
            return False
        return None
    number = _number(value)
    return None if number is None else bool(number)


def parse_utc(value: Any) -> datetime | None:
    """Parse a timestamp without importing pandas into the research core."""

    if isinstance(value, datetime):
        parsed = value
    elif _is_missing(value):
        return None
    else:
        text = str(value).strip()
        if text.endswith(" UTC"):
            text = text[:-4] + "+00:00"
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    parsed = None
            if parsed is None:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


@dataclass(frozen=True)
class MetricObservation:
    """One metric with the metadata needed to decide whether it is usable."""

    name: str
    value: Any = None
    event_time: datetime | None = None
    received_at: datetime | None = None
    source: str = ""
    venue: str = ""
    units: str = ""
    freshness_seconds: int | None = None
    missing_reason: str = ""
    definition: str = ""
    provenance: str = ""
    event_time_basis: str = "source_event"

    def status(self, *, as_of: datetime | None = None) -> str:
        if _is_missing(self.value) or self.missing_reason:
            return "missing"
        if self.event_time is None or self.received_at is None:
            return "invalid"
        if not self.source or not self.venue or not self.units or not self.provenance:
            return "invalid"
        reference = as_of or self.received_at
        reference = reference.astimezone(timezone.utc) if reference.tzinfo else reference.replace(tzinfo=timezone.utc)
        age = (reference - self.event_time).total_seconds()
        if age < -300:
            return "invalid"
        if self.freshness_seconds is not None and age > float(self.freshness_seconds):
            return "stale"
        return "observed"

    def freshness_age_seconds(self, *, as_of: datetime | None = None) -> float | None:
        if self.event_time is None:
            return None
        reference = as_of or self.received_at
        if reference is None:
            return None
        return max(0.0, (reference - self.event_time).total_seconds())

    def to_dict(self, *, as_of: datetime | None = None) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "event_time": _iso(self.event_time),
            "received_at": _iso(self.received_at),
            "source": self.source,
            "venue": self.venue,
            "units": self.units,
            "freshness_seconds": self.freshness_seconds,
            "freshness_age_seconds": self.freshness_age_seconds(as_of=as_of),
            "status": self.status(as_of=as_of),
            "missing_reason": self.missing_reason,
            "definition": self.definition,
            "provenance": self.provenance,
            "event_time_basis": self.event_time_basis,
        }


@dataclass(frozen=True)
class ReflexivityObservation:
    """Point-in-time normalized snapshot used by the state engine."""

    symbol: str
    event_time: datetime | None
    received_at: datetime | None
    source: str
    venue: str
    event_time_basis: str
    metrics: Mapping[str, MetricObservation]
    provenance: str = ""
    observation_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    ownership: OwnershipSnapshot | None = None
    wallet_classifications: tuple[WalletClassification, ...] = ()
    venue_observations: tuple[VenueObservation, ...] = ()
    supply_flows: tuple[SupplyFlowObservation, ...] = ()

    def metric(self, name: str) -> MetricObservation:
        return self.metrics.get(
            name,
            MetricObservation(
                name=name,
                event_time=self.event_time,
                received_at=self.received_at,
                source=self.source,
                venue=self.venue,
                units="",
                missing_reason="not present in canonical observation",
                definition="canonical metric is unavailable",
                provenance=f"observation:{self.observation_id or self.symbol}",
                event_time_basis=self.event_time_basis,
            ),
        )

    def statuses(self, *, as_of: datetime | None = None) -> dict[str, str]:
        return {name: metric.status(as_of=as_of) for name, metric in self.metrics.items()}

    def validation(self, *, as_of: datetime | None = None) -> dict[str, Any]:
        missing = [name for name, status in self.statuses(as_of=as_of).items() if status == "missing"]
        stale = [name for name, status in self.statuses(as_of=as_of).items() if status == "stale"]
        invalid = [name for name, status in self.statuses(as_of=as_of).items() if status == "invalid"]
        return {
            "valid_envelope": bool(self.symbol and self.source and self.venue and self.event_time and self.received_at),
            "missing": missing,
            "stale": stale,
            "invalid": invalid,
            "event_time_basis": self.event_time_basis,
            "provenance": self.provenance,
        }

    def to_dict(self, *, as_of: datetime | None = None) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "event_time": _iso(self.event_time),
            "received_at": _iso(self.received_at),
            "source": self.source,
            "venue": self.venue,
            "event_time_basis": self.event_time_basis,
            "provenance": self.provenance,
            "observation_id": self.observation_id,
            "metadata": dict(self.metadata),
            "ownership": self.ownership.to_dict() if self.ownership else None,
            "wallet_classifications": [item.to_dict() for item in self.wallet_classifications],
            "venue_observations": [item.to_dict() for item in self.venue_observations],
            "supply_flows": [item.to_dict() for item in self.supply_flows],
            "validation": self.validation(as_of=as_of),
            "metrics": {name: metric.to_dict(as_of=as_of) for name, metric in self.metrics.items()},
        }


@dataclass(frozen=True)
class ComponentAssessment:
    name: str
    score: float | None
    status: str
    evidence: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    definition: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "status": self.status,
            "evidence": list(self.evidence),
            "missing_fields": list(self.missing_fields),
            "definition": self.definition,
        }


@dataclass(frozen=True)
class ReflexivityAssessment:
    symbol: str
    state: ReflexivityState
    score: float
    data_quality_pct: float
    market_trigger: bool
    structural_watch: bool
    gates: Mapping[str, bool | None]
    components: Mapping[str, ComponentAssessment]
    explanation: tuple[str, ...]
    missing_fields: tuple[str, ...]
    invalidation: tuple[str, ...]
    funding_read: str
    funding_regime: str = "unknown"
    signal_version: str = SIGNAL_VERSION
    event_time: datetime | None = None
    observation_id: str = ""

    def component_summary(self) -> str:
        parts = []
        for name, component in self.components.items():
            label = name.replace("_", " ")
            score = "n/a" if component.score is None else f"{component.score:.0f}"
            parts.append(f"{label} {score} ({component.status})")
        return " | ".join(parts)

    def gate_summary(self) -> str:
        return " | ".join(
            f"{name.replace('_', ' ')}={'unknown' if value is None else 'pass' if value else 'fail'}"
            for name, value in self.gates.items()
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "state": self.state.value,
            "score": self.score,
            "data_quality_pct": self.data_quality_pct,
            "market_trigger": self.market_trigger,
            "structural_watch": self.structural_watch,
            "gates": dict(self.gates),
            "components": {name: component.to_dict() for name, component in self.components.items()},
            "explanation": list(self.explanation),
            "missing_fields": list(self.missing_fields),
            "invalidation": list(self.invalidation),
            "funding_read": self.funding_read,
            "funding_regime": self.funding_regime,
            "signal_version": self.signal_version,
            "event_time": _iso(self.event_time),
            "observation_id": self.observation_id,
        }


@dataclass(frozen=True)
class ReflexivityConfig:
    """Frozen rule thresholds; changing these should create a new config hash."""

    min_short_account_pct: float = 60.0
    min_short_roc_1h_pp: float = 0.25
    min_short_change_3h_pp: float = 0.50
    min_volume_ratio: float = 1.50
    min_hour_volume_roc_pct: float = 25.0
    min_oi_delta_1h_pct: float = 0.50
    min_oi_change_3h_pct: float = 0.50
    min_persistence: int = 2
    min_score: float = 55.0
    exhaustion_short_roc_pp: float = -2.50
    exhaustion_short_level_pct: float = 65.0
    exhaustion_peak_drawdown_pp: float = -4.0
    invalidation_price_return_pct: float = -8.0
    max_extension_24h_pct: float = 35.0
    max_avwap_extension_pct: float = 35.0
    max_upper_wick_pct: float = 45.0
    extreme_positive_funding_pct: float = 0.10
    extreme_negative_funding_pct: float = -0.10
    cex_flow_veto_transfer_to_float_pct: float = 1.0
    cex_flow_veto_notional_to_volume_pct: float = 25.0
    cex_flow_veto_notional_to_visible_liquidity_pct: float = 100.0
    max_data_age_minutes: int = 90


METRIC_SPECS: dict[str, tuple[str, int | None, str]] = {
    "circulating_supply": ("tokens", 30 * 86400, "reported circulating supply at the observation time"),
    "total_supply": ("tokens", 30 * 86400, "reported total supply at the observation time"),
    "fdv_usd": ("USD", 30 * 86400, "fully diluted valuation using the source definition"),
    "market_cap_usd": ("USD", 30 * 86400, "market capitalization using the source definition"),
    "estimated_tradable_float_tokens": ("tokens", 30 * 86400, "estimated economically tradable token amount after explicit exclusions"),
    "estimated_tradable_float_usd": ("USD", 30 * 86400, "estimated economically tradable float marked at the observation price"),
    "tradable_float_pct": ("percent of total supply", 30 * 86400, "estimated genuinely tradable supply after explicit exclusions"),
    "raw_top1_pct": ("percent of total supply", 30 * 86400, "raw top-1 holder concentration"),
    "raw_top3_pct": ("percent of total supply", 30 * 86400, "raw top-3 holder concentration"),
    "raw_top5_pct": ("percent of total supply", 30 * 86400, "raw top-5 holder concentration"),
    "adjusted_top10_pct": ("percent of total supply", 30 * 86400, "top-10 concentration after documented custody/storage adjustments"),
    "adjusted_top1_pct": ("percent of total supply", 30 * 86400, "adjusted top-1 concentration after documented exclusions"),
    "adjusted_top5_pct": ("percent of total supply", 30 * 86400, "adjusted top-5 concentration after documented exclusions"),
    "adjusted_top20_pct": ("percent of total supply", 30 * 86400, "adjusted top-20 concentration after documented exclusions"),
    "adjusted_top50_pct": ("percent of total supply", 30 * 86400, "adjusted top-50 concentration after documented exclusions"),
    "adjusted_top100_pct": ("percent of total supply", 30 * 86400, "adjusted top-100 concentration after documented exclusions"),
    "top10_holder_pct": ("percent of total supply", 30 * 86400, "raw top-10 holder concentration"),
    "top100_holder_pct": ("percent of total supply", 30 * 86400, "raw top-100 holder concentration"),
    "holder_hhi": ("index", 30 * 86400, "holder Herfindahl-Hirschman concentration index"),
    "holder_gini": ("index", 30 * 86400, "holder Gini-style distribution concentration index"),
    "holder_count": ("holders", 30 * 86400, "holder count in the source representation"),
    "wallet_classification_coverage_pct": ("percent of holder value", 30 * 86400, "share of observed holder value with an explicit classification"),
    "wallet_classification_confidence": ("0-100 confidence score", 30 * 86400, "confidence in wallet classification coverage"),
    "founder_team_treasury_pct": ("percent of total supply", 30 * 86400, "supported founder/team/treasury attribution, not an identity guess"),
    "controlled_supply_pct": ("percent of total supply", 30 * 86400, "supply associated with a documented control cluster"),
    "holder_confidence": ("0-100 confidence score", 30 * 86400, "confidence in holder classification, not market conviction"),
    "holder_evidence_level": ("categorical", 30 * 86400, "NONE, PROXY, or VERIFIED contract-backed holder evidence"),
    "holder_storage_checked": ("boolean", 30 * 86400, "whether custody, protocol storage, wrappers, and representation were checked"),
    "holder_table_not_global_supply": ("boolean", 30 * 86400, "holder table may not represent global token supply"),
    "wrapped_representation_warning": ("boolean", 30 * 86400, "wrapped or non-canonical representation warning"),
    "protocol_storage_score": ("0-100 risk score", 30 * 86400, "probability that concentration is protocol/custody storage rather than manipulable float"),
    "cex_storage_supply_pct": ("percent of total supply", 30 * 86400, "identified CEX custody/storage share"),
    "wallet_classification_timestamp": ("timestamp", 30 * 86400, "timestamp of the holder classification snapshot"),
    "binance_perp_available": ("boolean", 6 * 3600, "explicit Binance perpetual availability"),
    "bitget_perp_available": ("boolean", 6 * 3600, "explicit Bitget perpetual availability"),
    "gate_perp_available": ("boolean", 6 * 3600, "explicit Gate perpetual availability"),
    "spot_venue_metadata": ("categorical", 6 * 3600, "spot venue metadata retained from the source"),
    "perp_venue_metadata": ("categorical", 6 * 3600, "perpetual venue metadata retained from the source"),
    "binance_venue_presence": ("boolean", 6 * 3600, "explicit Binance perpetual venue presence"),
    "binance_volume_share_pct": ("percent of observed venue volume", 6 * 3600, "Binance share of observed venue volume"),
    "bitget_volume_share_pct": ("percent of observed venue volume", 6 * 3600, "Bitget share of observed venue volume"),
    "gate_volume_share_pct": ("percent of observed venue volume", 6 * 3600, "Gate share of observed venue volume"),
    "target_cex_volume_share_pct": ("percent of observed venue volume", 6 * 3600, "Bitget/Gate target-venue share"),
    "venue_evidence_level": ("categorical", 6 * 3600, "quality of venue participation evidence"),
    "cex_deposit_24h_notional_usd": ("USD", 2 * 3600, "labelled or classified wallet-to-CEX transfer notional"),
    "cex_deposit_24h_notional_to_volume_pct": ("percent of 24h quote volume", 2 * 3600, "CEX transfer notional relative to market activity"),
    "cex_deposit_24h_total_pct_supply": ("percent of total supply", 2 * 3600, "CEX transfer token amount relative to total supply"),
    "quote_volume_24h_usd": ("USD", 2 * 3600, "rolling 24h perp quote volume"),
    "perp_volume_7d_avg_usd": ("USD/day", 8 * 86400, "average closed daily perpetual volume over the prior 7D"),
    "perp_volume_30d_avg_usd": ("USD/day", 32 * 86400, "average closed daily perpetual volume over the prior 30D"),
    "perp_volume_90d_avg_usd": ("USD/day", 92 * 86400, "average closed daily perpetual volume over the prior 90D"),
    "perp_volume_abnormal_multiple": ("multiple", 32 * 86400, "current perpetual volume versus the frozen trailing baseline"),
    "volume_ratio_24h_to_prior_30d_avg": ("multiple", 2 * 3600, "24h quote volume divided by average prior closed 30D daily quote volume"),
    "hour_volume_roc_pct": ("percent change", 2 * 3600, "latest closed hour quote-volume change versus preceding closed hour"),
    "hour_volume_multiple": ("multiple", 2 * 3600, "latest closed hour quote volume versus local hourly baseline"),
    "oi_delta_1h_pct": ("percent change", 2 * 3600, "one-hour open-interest change"),
    "oi_change_3h_pct": ("percent change", 4 * 3600, "three-hour open-interest change"),
    "oi_acceleration_1h_pct": ("percentage points", 4 * 3600, "change in one-hour open-interest growth versus the prior closed hour"),
    "oi_build_persistence": ("closed observations", 4 * 3600, "consecutive closed observations with positive OI change"),
    "oi_to_24h_volume_pct": ("percent", 2 * 3600, "open interest notional relative to 24h quote volume"),
    "oi_usd": ("USD", 2 * 3600, "open-interest notional using the source convention"),
    "oi_to_market_cap_pct": ("percent", 2 * 3600, "open interest relative to reported market capitalization"),
    "oi_to_tradable_float_pct": ("percent", 2 * 3600, "open interest relative to estimated tradable-float value"),
    "funding_rate_pct": ("percent per funding interval", 2 * 3600, "latest exchange funding rate; sign follows exchange convention"),
    "funding_interval_hours": ("hours", 2 * 3600, "funding interval used for carry context"),
    "funding_persistence": ("closed observations", 8 * 3600, "consecutive observations with the same funding sign or regime"),
    "funding_zscore": ("standard deviations", 8 * 3600, "funding dislocation relative to its frozen historical baseline"),
    "short_account_pct": ("percent of accounts", 2 * 3600, "global short-account share by clientele count, not short dollar notional"),
    "global_long_account_pct": ("percent of accounts", 2 * 3600, "global long-account share by clientele count"),
    "global_short_account_pct": ("percent of accounts", 2 * 3600, "global short-account share by clientele count"),
    "short_account_roc_1h_pp": ("percentage points", 2 * 3600, "one-hour change in global short-account share"),
    "short_account_change_3h_pp": ("percentage points", 4 * 3600, "three-hour change in global short-account share"),
    "short_account_change_4h_pp": ("percentage points", 5 * 3600, "four-hour change in global short-account share"),
    "short_account_roc_24h_pp": ("percentage points", 26 * 3600, "24-hour change in global short-account share"),
    "short_account_peak_drawdown_pp": ("percentage points", 4 * 3600, "current short-account share relative to observed recent peak"),
    "short_account_direction_persistence": ("closed observations", 4 * 3600, "consecutive observations with the same short-account direction"),
    "top_trader_short_account_pct": ("percent of accounts", 2 * 3600, "top-trader short-account share"),
    "top_trader_short_position_pct": ("percent of position notional", 2 * 3600, "top-trader short-position share"),
    "top_trader_long_account_pct": ("percent of accounts", 2 * 3600, "top-trader long-account share"),
    "top_trader_long_position_pct": ("percent of position notional", 2 * 3600, "top-trader long-position share"),
    "crowd_top_account_divergence_pp": ("percentage points", 2 * 3600, "broad-crowd long share minus top-trader long-account share"),
    "crowd_top_position_divergence_pp": ("percentage points", 2 * 3600, "broad-crowd long share minus top-trader long-position share"),
    "taker_buy_share_pct": ("percent of taker volume", 2 * 3600, "sampled taker buy volume share"),
    "last_price": ("quote currency", 2 * 3600, "latest exchange mark/last price"),
    "price_change_24h_pct": ("percent change", 2 * 3600, "24h price change"),
    "hour_return_pct": ("percent change", 2 * 3600, "latest closed hourly return"),
    "return_4h_pct": ("percent change", 6 * 3600, "four-hour price return"),
    "return_7d_pct": ("percent change", 8 * 86400, "seven-day price return"),
    "return_30d_pct": ("percent change", 32 * 86400, "30-day price return"),
    "return_90d_pct": ("percent change", 92 * 86400, "90-day price return"),
    "price_vs_anchored_vwap_30d_pct": ("percent difference", 2 * 3600, "price distance from closed daily 30D anchored VWAP"),
    "broke_high_5d": ("boolean", 2 * 3600, "current high crossed the prior 5D high"),
    "broke_high_20d": ("boolean", 2 * 3600, "current high crossed the prior 20D high"),
    "broke_high_90d": ("boolean", 2 * 3600, "current high crossed the prior 90D high"),
    "broke_high_180d": ("boolean", 2 * 3600, "current high crossed the prior 180D high"),
    "broke_low_20d": ("boolean", 2 * 3600, "current low crossed the prior 20D low"),
    "distance_to_recent_high_pct": ("percent", 2 * 3600, "distance from the selected recent high"),
    "distance_to_ath_pct": ("percent", 30 * 86400, "distance from the available all-time high"),
    "ath_runway_multiple": ("multiple", 30 * 86400, "available upside to the all-time high relative to current price"),
    "realized_volatility_24h_pct": ("percent", 2 * 3600, "realized volatility from closed hourly returns"),
    "realized_volatility_7d_pct": ("percent", 8 * 86400, "realized volatility from closed daily returns"),
    "price_acceleration_1h_pct": ("percent change", 2 * 3600, "change in hourly return versus the prior closed hour"),
    "large_move_pre_detection_pct": ("percent change", 30 * 86400, "largest measured move before the observation time"),
    "large_move_pre_detection_flag": ("boolean", 30 * 86400, "whether the pre-detection move exceeds the frozen chase threshold"),
    "hour_close_location_pct": ("percent of candle range", 2 * 3600, "hourly close location in its high-low range"),
    "hour_upper_wick_pct": ("percent of candle range", 2 * 3600, "hourly upper-wick share"),
    "recent_max_pump_60d_pct": ("percent change", 30 * 86400, "largest recent daily pump in the measured lookback"),
    "prior_observations_24h": ("observations", 26 * 3600, "prior canonical observations for persistence context"),
    "spot_volume_24h_usd": ("USD", 2 * 3600, "rolling 24h spot volume where available"),
    "cex_deposit_24h_token_amount": ("tokens", 2 * 3600, "classified token amount transferred to labelled CEX wallets"),
    "cex_deposit_24h_target_exchanges": ("categorical", 2 * 3600, "labelled CEX transfer destinations"),
    "cex_deposit_24h_transfer_to_float_pct": ("percent of estimated float", 2 * 3600, "CEX transfer amount relative to estimated tradable float"),
    "cex_deposit_24h_notional_to_spot_volume_pct": ("percent of spot volume", 2 * 3600, "CEX transfer notional relative to spot volume"),
    "cex_deposit_24h_notional_to_visible_liquidity_pct": ("percent of visible liquidity", 2 * 3600, "CEX transfer notional relative to visible ask liquidity"),
    "cex_deposit_24h_whale_sender_count": ("wallets", 2 * 3600, "number of classified whale senders in the flow window"),
    "cex_deposit_24h_top_sender_pct": ("percent of flow", 2 * 3600, "largest sender share of classified CEX flow"),
    "cex_deposit_24h_flow_confidence": ("0-100 confidence score", 2 * 3600, "confidence in wallet labels and transfer interpretation"),
    "cex_deposit_24h_source": ("categorical", 2 * 3600, "source and coverage label for CEX-flow evidence"),
}


_ROW_FIELDS: dict[str, tuple[str, ...]] = {
    "circulating_supply": ("circulating_supply", "circulating_supply_tokens"),
    "total_supply": ("total_supply", "total_supply_tokens", "max_supply"),
    "fdv_usd": ("fdv_usd", "fully_diluted_valuation", "fdv"),
    "market_cap_usd": ("market_cap_usd", "cmc_market_cap_usd", "market_cap"),
    "estimated_tradable_float_tokens": ("estimated_tradable_float_tokens", "tradable_float_tokens"),
    "estimated_tradable_float_usd": ("estimated_tradable_float_usd", "tradable_float_market_cap_usd"),
    "tradable_float_pct": ("tradable_float_pct", "estimated_tradable_float_pct"),
    "raw_top1_pct": ("raw_top1_pct", "top1_holder_pct"),
    "raw_top3_pct": ("raw_top3_pct", "top3_holder_pct"),
    "raw_top5_pct": ("raw_top5_pct", "top5_holder_pct"),
    "adjusted_top10_pct": ("adjusted_top10_pct", "adjusted_top_10_pct", "filtered_top_10_manipulable_pct"),
    "adjusted_top1_pct": ("adjusted_top1_pct", "adjusted_top_1_pct"),
    "adjusted_top5_pct": ("adjusted_top5_pct", "adjusted_top_5_pct", "filtered_top_5_manipulable_pct"),
    "adjusted_top20_pct": ("adjusted_top20_pct", "adjusted_top_20_pct"),
    "adjusted_top50_pct": ("adjusted_top50_pct", "adjusted_top_50_pct"),
    "adjusted_top100_pct": ("adjusted_top100_pct", "adjusted_top_100_pct"),
    "top10_holder_pct": ("top10_holder_pct",),
    "top100_holder_pct": ("top100_holder_pct",),
    "holder_hhi": ("holder_hhi", "holder_hhi_index"),
    "holder_gini": ("holder_gini", "concentration_gini"),
    "holder_count": ("holder_count",),
    "wallet_classification_coverage_pct": ("wallet_classification_coverage_pct", "holder_classification_coverage_pct"),
    "wallet_classification_confidence": ("wallet_classification_confidence", "holder_confidence_score"),
    "founder_team_treasury_pct": ("founder_team_treasury_pct", "insider_team_holder_pct", "owner_related_cluster_pct"),
    "controlled_supply_pct": ("controlled_supply_pct", "cluster_manipulable_supply_pct", "controlled_holder_pct"),
    "holder_confidence": ("holder_confidence", "structural_data_confidence"),
    "holder_evidence_level": ("structural_evidence_level", "holder_evidence_level"),
    "holder_storage_checked": ("structural_storage_checked", "holder_storage_checked"),
    "holder_table_not_global_supply": ("holder_table_not_global_supply",),
    "wrapped_representation_warning": ("wrapped_representation_warning",),
    "protocol_storage_score": ("protocol_storage_score",),
    "cex_storage_supply_pct": ("cex_storage_supply_pct",),
    "wallet_classification_timestamp": ("wallet_classification_timestamp", "structural_evidence_timestamp", "holder_snapshot_at"),
    "binance_perp_available": ("binance_perp_available", "binance_perp_universe"),
    "bitget_perp_available": ("bitget_perp_available", "bitget_perp_universe"),
    "gate_perp_available": ("gate_perp_available", "gate_perp_universe"),
    "spot_venue_metadata": ("spot_venue_metadata", "spot_venues"),
    "perp_venue_metadata": ("perp_venue_metadata", "perp_venues"),
    "binance_venue_presence": ("binance_venue_presence", "binance_perp_universe"),
    "binance_volume_share_pct": ("binance_volume_share_pct",),
    "bitget_volume_share_pct": ("bitget_volume_share_pct",),
    "gate_volume_share_pct": ("gate_volume_share_pct",),
    "target_cex_volume_share_pct": ("target_cex_volume_share_pct", "gate_volume_share_pct", "bitget_volume_share_pct"),
    "venue_evidence_level": ("venue_evidence_level", "structural_evidence_level"),
    "cex_deposit_24h_notional_usd": ("cex_deposit_24h_notional_usd", "cex_deposit_24h_max_notional_usd"),
    "cex_deposit_24h_notional_to_volume_pct": ("cex_deposit_24h_notional_to_volume_pct",),
    "cex_deposit_24h_total_pct_supply": ("cex_deposit_24h_total_pct_supply",),
    "quote_volume_24h_usd": ("quote_volume_24h", "quote_volume_24h_usd"),
    "perp_volume_7d_avg_usd": ("perp_volume_7d_avg_usd", "prior_7d_avg_quote_volume"),
    "perp_volume_30d_avg_usd": ("perp_volume_30d_avg_usd", "prior_30d_avg_quote_volume", "prior_daily_avg_quote_volume"),
    "perp_volume_90d_avg_usd": ("perp_volume_90d_avg_usd", "prior_90d_avg_quote_volume"),
    "perp_volume_abnormal_multiple": ("perp_volume_abnormal_multiple", "quote_volume_24h_vs_prior_30d_avg_ratio"),
    "volume_ratio_24h_to_prior_30d_avg": ("quote_volume_24h_vs_prior_30d_avg_ratio", "volume_ratio_24h_to_prior_30d_avg"),
    "hour_volume_roc_pct": ("hour_volume_roc_1h_pct",),
    "hour_volume_multiple": ("hour_volume_multiple",),
    "oi_delta_1h_pct": ("oi_delta_pct", "oi_delta_1h_pct"),
    "oi_change_3h_pct": ("oi_change_3p_pct", "oi_change_3h_pct"),
    "oi_acceleration_1h_pct": ("oi_acceleration_1h_pct", "oi_acceleration_pct"),
    "oi_build_persistence": ("oi_build_persistence",),
    "oi_to_24h_volume_pct": ("oi_to_24h_volume_pct",),
    "oi_usd": ("oi_usd", "oi_value_usdt"),
    "oi_to_market_cap_pct": ("oi_to_market_cap_pct",),
    "oi_to_tradable_float_pct": ("oi_to_tradable_float_pct",),
    "funding_rate_pct": ("carry_funding_pct", "funding_rate_pct", "last_funding_rate_pct"),
    "funding_interval_hours": ("funding_interval_hours",),
    "funding_persistence": ("funding_persistence", "funding_sign_persistence"),
    "funding_zscore": ("funding_zscore",),
    "short_account_pct": ("short_account_pct",),
    "global_long_account_pct": ("long_account_pct", "global_long_account_pct"),
    "global_short_account_pct": ("short_account_pct", "global_short_account_pct"),
    "short_account_roc_1h_pp": ("short_account_roc_1h_pp",),
    "short_account_change_3h_pp": ("short_account_change_3p_pp", "short_account_change_3h_pp"),
    "short_account_change_4h_pp": ("short_account_change_4p_pp", "short_account_change_4h_pp"),
    "short_account_roc_24h_pp": ("short_account_change_24p_pp", "short_account_roc_24h_pp"),
    "short_account_peak_drawdown_pp": ("short_account_peak_drawdown_pp",),
    "short_account_direction_persistence": ("short_account_direction_persistence",),
    "top_trader_short_account_pct": ("top_trader_short_account_pct",),
    "top_trader_short_position_pct": ("top_trader_short_position_pct",),
    "top_trader_long_account_pct": ("top_trader_long_account_pct",),
    "top_trader_long_position_pct": ("top_trader_long_position_pct",),
    "crowd_top_account_divergence_pp": ("crowd_top_account_divergence_pct", "crowd_top_account_divergence_pp"),
    "crowd_top_position_divergence_pp": ("crowd_top_position_divergence_pct", "crowd_top_position_divergence_pp"),
    "taker_buy_share_pct": ("taker_buy_share_pct",),
    "last_price": ("last_price",),
    "price_change_24h_pct": ("price_change_24h_pct", "day_return_pct"),
    "hour_return_pct": ("hour_return_pct",),
    "return_4h_pct": ("return_4h_pct", "four_hour_return_pct"),
    "return_7d_pct": ("return_7d_pct", "week_return_pct", "price_change_7d_pct"),
    "return_30d_pct": ("return_30d_pct", "month_return_pct", "price_change_30d_pct"),
    "return_90d_pct": ("return_90d_pct", "quarter_return_pct"),
    "price_vs_anchored_vwap_30d_pct": ("price_vs_anchored_vwap_30d_pct",),
    "broke_high_5d": ("broke_high_5d",),
    "broke_high_20d": ("broke_high_20d",),
    "broke_high_90d": ("broke_high_90d",),
    "broke_high_180d": ("broke_high_180d",),
    "broke_low_20d": ("broke_low_20d",),
    "distance_to_recent_high_pct": ("distance_to_recent_high_pct", "distance_to_high_20d_pct"),
    "distance_to_ath_pct": ("distance_to_ath_pct", "ath_distance_pct"),
    "ath_runway_multiple": ("ath_runway_multiple", "ath_multiple", "ath_multiple_from_atl"),
    "realized_volatility_24h_pct": ("realized_volatility_24h_pct", "hourly_realized_volatility_pct"),
    "realized_volatility_7d_pct": ("realized_volatility_7d_pct", "daily_realized_volatility_pct"),
    "price_acceleration_1h_pct": ("price_acceleration_1h_pct", "hour_return_acceleration_pct"),
    "large_move_pre_detection_pct": ("large_move_pre_detection_pct", "recent_max_pump_60d_pct"),
    "large_move_pre_detection_flag": ("large_move_pre_detection_flag", "blowoff_risk_flag", "convexity_chase_risk_flag"),
    "hour_close_location_pct": ("hour_close_location_pct",),
    "hour_upper_wick_pct": ("hour_upper_wick_pct",),
    "recent_max_pump_60d_pct": ("recent_max_pump_60d_pct",),
    "prior_observations_24h": ("radar_prior_observations", "prior_observations_24h"),
    "spot_volume_24h_usd": ("spot_volume_24h_usd", "spot_quote_volume_24h", "spot_volume_24h"),
    "cex_deposit_24h_token_amount": ("cex_deposit_24h_token_amount", "cex_deposit_24h_token_amount", "cex_deposit_24h_max_amount"),
    "cex_deposit_24h_target_exchanges": ("cex_deposit_24h_target_exchanges",),
    "cex_deposit_24h_transfer_to_float_pct": ("cex_deposit_24h_transfer_to_float_pct", "cex_deposit_24h_total_pct_supply"),
    "cex_deposit_24h_notional_to_spot_volume_pct": ("cex_deposit_24h_notional_to_spot_volume_pct", "cex_deposit_24h_notional_to_volume_pct"),
    "cex_deposit_24h_notional_to_visible_liquidity_pct": ("cex_deposit_24h_notional_to_visible_liquidity_pct", "cex_deposit_24h_notional_to_ask_depth_pct"),
    "cex_deposit_24h_whale_sender_count": ("cex_deposit_24h_whale_sender_count",),
    "cex_deposit_24h_top_sender_pct": ("cex_deposit_24h_top_sender_pct", "cex_deposit_24h_top_sender_pct"),
    "cex_deposit_24h_flow_confidence": ("cex_deposit_24h_flow_confidence", "cex_deposit_flow_confidence"),
    "cex_deposit_24h_source": ("cex_deposit_24h_source", "cex_deposit_flow_source"),
}


def _row_get(row: Mapping[str, Any], key: str) -> Any:
    try:
        return row.get(key)
    except AttributeError:
        return None


def _first_row_value(row: Mapping[str, Any], fields: tuple[str, ...]) -> tuple[Any, str]:
    for field_name in fields:
        value = _row_get(row, field_name)
        if not _is_missing(value):
            return value, field_name
    return None, ""


def _structured_rows(value: Any) -> list[Mapping[str, Any]]:
    """Accept fixture lists or JSON-encoded evidence without guessing text."""

    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, Mapping)]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return _structured_rows(parsed)
    return []


def _parse_wallet_classifications(
    row: Mapping[str, Any],
    *,
    event_time: datetime | None,
    received_at: datetime | None,
    default_provenance: str,
) -> tuple[WalletClassification, ...]:
    raw = row.get("wallet_classifications")
    if raw is None:
        raw = row.get("holder_classifications")
    records: list[WalletClassification] = []
    for index, item in enumerate(_structured_rows(raw)):
        address = str(item.get("address") or f"record-{index}").strip()
        category = str(item.get("category") or item.get("holder_category") or "unidentified_whale").strip().lower()
        if category not in WALLET_CATEGORIES:
            category = "unidentified_whale"
        confidence_score = _number(item.get("confidence_score"))
        records.append(
            WalletClassification(
                address=address,
                category=category,
                label=str(item.get("label") or ""),
                confidence=str(item.get("confidence") or "unknown"),
                confidence_score=confidence_score,
                pct_total_supply=_number(item.get("pct_total_supply")),
                excluded_from_adjusted_float=bool(_bool(item.get("excluded_from_adjusted_float")) or False),
                evidence_source=str(item.get("evidence_source") or item.get("source") or ""),
                evidence_note=str(item.get("evidence_note") or item.get("note") or ""),
                classified_at=parse_utc(item.get("classified_at") or item.get("classification_timestamp") or event_time),
                provenance=str(item.get("provenance") or f"{default_provenance}:wallet_classifications[{index}]"),
            )
        )
    return tuple(records)


def _parse_venue_observations(
    row: Mapping[str, Any],
    *,
    event_time: datetime | None,
    received_at: datetime | None,
    source: str,
    default_provenance: str,
) -> tuple[VenueObservation, ...]:
    raw = row.get("venue_observations")
    if raw is None:
        raw = row.get("venue_metadata")
    records: list[VenueObservation] = []
    for index, item in enumerate(_structured_rows(raw)):
        records.append(
            VenueObservation(
                venue=str(item.get("venue") or item.get("name") or "unknown"),
                market_type=str(item.get("market_type") or "perpetual"),
                available=_bool(item.get("available")),
                volume_share_pct=_number(item.get("volume_share_pct")),
                source=str(item.get("source") or source),
                event_time=parse_utc(item.get("event_time") or event_time),
                received_at=parse_utc(item.get("received_at") or received_at),
                units=str(item.get("units") or "boolean / percent"),
                freshness_seconds=int(_number(item.get("freshness_seconds")) or 6 * 3600),
                provenance=str(item.get("provenance") or f"{default_provenance}:venue_observations[{index}]"),
            )
        )
    return tuple(records)


def _parse_supply_flows(
    row: Mapping[str, Any],
    *,
    event_time: datetime | None,
    received_at: datetime | None,
    source: str,
    default_provenance: str,
) -> tuple[SupplyFlowObservation, ...]:
    raw = row.get("supply_flows")
    if raw is None:
        raw = row.get("cex_flow_observations")
    records: list[SupplyFlowObservation] = []
    for index, item in enumerate(_structured_rows(raw)):
        records.append(
            SupplyFlowObservation(
                target_exchange=str(item.get("target_exchange") or item.get("exchange") or "unknown"),
                token_amount=_number(item.get("token_amount")),
                notional_usd=_number(item.get("notional_usd")),
                sender_category=str(item.get("sender_category") or "unidentified_whale"),
                sender_confidence=str(item.get("sender_confidence") or "unknown"),
                transfer_to_float_pct=_number(item.get("transfer_to_float_pct")),
                notional_to_spot_volume_pct=_number(item.get("notional_to_spot_volume_pct")),
                notional_to_visible_liquidity_pct=_number(item.get("notional_to_visible_liquidity_pct")),
                source=str(item.get("source") or source),
                event_time=parse_utc(item.get("event_time") or event_time),
                received_at=parse_utc(item.get("received_at") or received_at),
                units=str(item.get("units") or "tokens / USD / percent"),
                freshness_seconds=int(_number(item.get("freshness_seconds")) or 2 * 3600),
                provenance=str(item.get("provenance") or f"{default_provenance}:supply_flows[{index}]"),
            )
        )
    return tuple(records)


def observation_from_row(
    row: Mapping[str, Any],
    *,
    source: str | None = None,
    venue: str | None = None,
    received_at: datetime | None = None,
    observation_id: str | None = None,
) -> ReflexivityObservation:
    """Normalize a live radar row without hiding fallbacks.

    When a source event timestamp is unavailable, the row's snapshot timestamp
    is used explicitly as ``event_time_basis='snapshot_time'``.  This prevents
    a receipt timestamp from masquerading as a precisely timed market event.
    """

    symbol = str(_row_get(row, "symbol") or "").strip().upper()
    received = received_at or parse_utc(
        _row_get(row, "received_at_utc")
        or _row_get(row, "observed_at_utc")
        or _row_get(row, "scanned_at_utc")
    )
    explicit_event = parse_utc(
        _row_get(row, "event_time_utc")
        or _row_get(row, "market_event_time_utc")
        or _row_get(row, "latest_source_event_utc")
    )
    event = explicit_event or parse_utc(_row_get(row, "scanned_at_utc")) or received
    event_basis = "source_event" if explicit_event else "snapshot_time"
    source_name = str(source or _row_get(row, "source") or "Binance Futures radar snapshot").strip()
    venue_name = str(venue or _row_get(row, "venue") or "Binance Futures").strip()
    provenance = str(
        _row_get(row, "provenance")
        or _row_get(row, "source_provenance")
        or "normalized from a bounded radar row; source field names retained below"
    ).strip()
    metrics: dict[str, MetricObservation] = {}
    for name, (units, max_age, definition) in METRIC_SPECS.items():
        value, source_field = _first_row_value(row, _ROW_FIELDS.get(name, (name,)))
        # ``binance_perp_universe`` is evidence of presence, while a numeric
        # share is evidence of observed participation. Keep the distinction.
        if name in {"binance_perp_available", "bitget_perp_available", "gate_perp_available", "binance_venue_presence"}:
            value = _bool(value)
        if name in {
            "holder_storage_checked",
            "holder_table_not_global_supply",
            "wrapped_representation_warning",
            "broke_high_5d",
            "broke_high_20d",
            "broke_high_90d",
            "broke_high_180d",
            "broke_low_20d",
            "large_move_pre_detection_flag",
        }:
            value = _bool(value)
        metric_provenance = f"row:{source_field}" if source_field else f"row missing:{name}"
        missing_reason = "" if source_field and not _is_missing(value) else "field not supplied by source row"
        metrics[name] = MetricObservation(
            name=name,
            value=value,
            event_time=event,
            received_at=received,
            source=source_name,
            venue=venue_name,
            units=units,
            freshness_seconds=max_age,
            missing_reason=missing_reason,
            definition=definition,
            provenance=metric_provenance,
            event_time_basis=event_basis,
        )
    ownership = OwnershipSnapshot(
        circulating_supply=_number(metrics["circulating_supply"].value),
        total_supply=_number(metrics["total_supply"].value),
        fdv_usd=_number(metrics["fdv_usd"].value),
        market_cap_usd=_number(metrics["market_cap_usd"].value),
        estimated_tradable_float_tokens=_number(metrics["estimated_tradable_float_tokens"].value),
        estimated_tradable_float_usd=_number(metrics["estimated_tradable_float_usd"].value),
        tradable_float_pct=_number(metrics["tradable_float_pct"].value),
        raw_top10_pct=_number(metrics["top10_holder_pct"].value),
        raw_top100_pct=_number(metrics["top100_holder_pct"].value),
        adjusted_top10_pct=_number(metrics["adjusted_top10_pct"].value),
        adjusted_top100_pct=_number(metrics["adjusted_top100_pct"].value),
        holder_hhi=_number(metrics["holder_hhi"].value),
        holder_gini=_number(metrics["holder_gini"].value),
        holder_count=_number(metrics["holder_count"].value),
        classification_coverage_pct=_number(metrics["wallet_classification_coverage_pct"].value),
        classification_confidence=_number(metrics["wallet_classification_confidence"].value),
        event_time=event,
        received_at=received,
        source=source_name,
        provenance=f"{provenance}:ownership",
    )
    wallet_classifications = _parse_wallet_classifications(
        row,
        event_time=event,
        received_at=received,
        default_provenance=provenance,
    )
    venue_observations = _parse_venue_observations(
        row,
        event_time=event,
        received_at=received,
        source=source_name,
        default_provenance=provenance,
    )
    supply_flows = _parse_supply_flows(
        row,
        event_time=event,
        received_at=received,
        source=source_name,
        default_provenance=provenance,
    )
    return ReflexivityObservation(
        symbol=symbol,
        event_time=event,
        received_at=received,
        source=source_name,
        venue=venue_name,
        event_time_basis=event_basis,
        metrics=metrics,
        provenance=provenance,
        observation_id=str(observation_id or _row_get(row, "observation_id") or f"{symbol}:{_iso(event) or 'unknown'}"),
        ownership=ownership,
        wallet_classifications=wallet_classifications,
        venue_observations=venue_observations,
        supply_flows=supply_flows,
        metadata={
            "scan_mode": _row_get(row, "scan_mode"),
            "market_type": _row_get(row, "market_type"),
            "structural_evidence_source": _row_get(row, "structural_evidence_source"),
        },
    )


def _metric_value(observation: ReflexivityObservation, name: str, as_of: datetime) -> tuple[Any, str]:
    metric = observation.metric(name)
    return metric.value, metric.status(as_of=as_of)


def _num_value(observation: ReflexivityObservation, name: str, as_of: datetime) -> float | None:
    value, status = _metric_value(observation, name, as_of)
    return _number(value) if status == "observed" else None


def _bool_value(observation: ReflexivityObservation, name: str, as_of: datetime) -> bool | None:
    value, status = _metric_value(observation, name, as_of)
    return _bool(value) if status == "observed" else None


def _scale(value: float | None, low: float, high: float, *, inverse: bool = False) -> float | None:
    if value is None:
        return None
    if high <= low:
        return None
    score = (value - low) / (high - low) * 100.0
    score = max(0.0, min(100.0, score))
    return 100.0 - score if inverse else score


def _average(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None and math.isfinite(value)]
    return None if not clean else sum(clean) / len(clean)


def _component(
    name: str,
    required: tuple[str, ...],
    observation: ReflexivityObservation,
    as_of: datetime,
    score: float | None,
    evidence: list[str],
    *,
    definition: str,
    proxy: bool = False,
    contested: bool = False,
) -> ComponentAssessment:
    statuses = {field_name: observation.metric(field_name).status(as_of=as_of) for field_name in required}
    missing = tuple(field_name for field_name, status in statuses.items() if status != "observed")
    observed_count = len(required) - len(missing)
    if observed_count == 0 and score is None:
        status = "missing"
    elif any(status == "stale" for status in statuses.values()):
        status = "stale"
    elif any(status == "invalid" for status in statuses.values()):
        status = "invalid"
    elif contested:
        status = "contested"
    elif proxy:
        status = "proxy"
    elif missing:
        status = "partial"
    else:
        status = "observed"
    return ComponentAssessment(
        name=name,
        score=None if score is None else round(max(0.0, min(100.0, score)), 2),
        status=status,
        evidence=tuple(evidence),
        missing_fields=missing,
        definition=definition,
    )


def _late_heat(observation: ReflexivityObservation, as_of: datetime) -> tuple[float, list[str]]:
    extension = _average(
        [
            _scale(_num_value(observation, "price_change_24h_pct", as_of), 20.0, 90.0),
            _scale(_num_value(observation, "price_vs_anchored_vwap_30d_pct", as_of), 20.0, 90.0),
            _scale(_num_value(observation, "recent_max_pump_60d_pct", as_of), 50.0, 150.0),
        ]
    ) or 0.0
    rejection = _average(
        [
            _scale(_num_value(observation, "hour_upper_wick_pct", as_of), 35.0, 80.0),
            _scale(_num_value(observation, "hour_return_pct", as_of), 12.0, 30.0),
            _scale(_num_value(observation, "hour_close_location_pct", as_of), 55.0, 85.0, inverse=True),
        ]
    ) or 0.0
    return round(max(extension, rejection), 2), [
        f"extension heat {extension:.0f}/100",
        f"rejection heat {rejection:.0f}/100",
    ]


def _gate_all(values: list[bool | None]) -> bool | None:
    if any(value is False for value in values):
        return False
    if not values or all(value is None for value in values):
        return None
    return True if all(value is True for value in values) else None


def _weighted_component_score(components: Mapping[str, ComponentAssessment], weights: Mapping[str, float]) -> float:
    numerator = 0.0
    denominator = 0.0
    for name, weight in weights.items():
        component = components.get(name)
        if component is None or component.score is None:
            continue
        # A proxy or contested component still informs ranking, but the status
        # remains visible and structural gates stay independent.
        numerator += component.score * weight
        denominator += weight
    return 0.0 if denominator == 0.0 else round(numerator / denominator, 2)


def _funding_regime(value: float | None, *, config: ReflexivityConfig) -> str:
    if value is None:
        return "unknown"
    if value >= config.extreme_positive_funding_pct:
        return "extreme_positive_longs_pay_shorts"
    if value > 0.0:
        return "positive_longs_pay_shorts"
    if value <= config.extreme_negative_funding_pct:
        return "extreme_negative_shorts_pay_longs"
    if value < 0.0:
        return "negative_shorts_pay_longs"
    return "neutral"


def assess_reflexivity(
    observation: ReflexivityObservation,
    *,
    as_of: datetime | None = None,
    config: ReflexivityConfig | None = None,
) -> ReflexivityAssessment:
    """Evaluate one observation using explicit mechanical state transitions."""

    cfg = config or ReflexivityConfig()
    reference = as_of or observation.received_at or observation.event_time or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference = reference.astimezone(timezone.utc)

    required_quality_fields = (
        "short_account_pct",
        "short_account_roc_1h_pp",
        "volume_ratio_24h_to_prior_30d_avg",
        "oi_delta_1h_pct",
        "funding_rate_pct",
        "price_change_24h_pct",
        "last_price",
    )
    quality_statuses = [observation.metric(name).status(as_of=reference) for name in required_quality_fields]
    quality = round(sum(status == "observed" for status in quality_statuses) / len(quality_statuses) * 100.0, 2)
    stale_snapshot = (
        observation.received_at is None
        or (reference - observation.received_at).total_seconds() > cfg.max_data_age_minutes * 60
    )

    short_pct = _num_value(observation, "short_account_pct", reference)
    short_roc = _num_value(observation, "short_account_roc_1h_pp", reference)
    short_change_3h = _num_value(observation, "short_account_change_3h_pp", reference)
    short_change_4h = _num_value(observation, "short_account_change_4h_pp", reference)
    short_change_24h = _num_value(observation, "short_account_roc_24h_pp", reference)
    short_peak_drawdown = _num_value(observation, "short_account_peak_drawdown_pp", reference)
    short_persistence = _num_value(observation, "short_account_direction_persistence", reference)
    volume_ratio = _num_value(observation, "volume_ratio_24h_to_prior_30d_avg", reference)
    hour_volume_roc = _num_value(observation, "hour_volume_roc_pct", reference)
    oi_delta = _num_value(observation, "oi_delta_1h_pct", reference)
    oi_change_3h = _num_value(observation, "oi_change_3h_pct", reference)
    oi_acceleration = _num_value(observation, "oi_acceleration_1h_pct", reference)
    oi_persistence = _num_value(observation, "oi_build_persistence", reference)
    funding = _num_value(observation, "funding_rate_pct", reference)
    day_return = _num_value(observation, "price_change_24h_pct", reference)
    avwap_distance = _num_value(observation, "price_vs_anchored_vwap_30d_pct", reference)
    price = _num_value(observation, "last_price", reference)
    close_location = _num_value(observation, "hour_close_location_pct", reference)
    upper_wick = _num_value(observation, "hour_upper_wick_pct", reference)

    float_values = [
        _scale(_num_value(observation, "tradable_float_pct", reference), 10.0, 60.0, inverse=True),
        _scale(_num_value(observation, "adjusted_top10_pct", reference), 50.0, 90.0),
        _scale(_num_value(observation, "controlled_supply_pct", reference), 20.0, 80.0),
    ]
    float_score = _average(float_values)
    float_evidence = []
    if _num_value(observation, "tradable_float_pct", reference) is not None:
        float_evidence.append(f"tradable float {_num_value(observation, 'tradable_float_pct', reference):.1f}%")
    if _num_value(observation, "adjusted_top10_pct", reference) is not None:
        float_evidence.append(f"adjusted top10 {_num_value(observation, 'adjusted_top10_pct', reference):.1f}%")
    float_component = _component(
        "float_constraint",
        ("tradable_float_pct", "adjusted_top10_pct", "controlled_supply_pct"),
        observation,
        reference,
        float_score,
        float_evidence,
        definition="Low genuinely tradable float or concentrated adjusted supply can make marginal demand nonlinear; raw concentration alone is not enough.",
        proxy=not bool(_num_value(observation, "tradable_float_pct", reference) is not None),
    )

    top10 = _num_value(observation, "top10_holder_pct", reference)
    top100 = _num_value(observation, "top100_holder_pct", reference)
    adjusted_top10 = _num_value(observation, "adjusted_top10_pct", reference)
    holder_hhi = _num_value(observation, "holder_hhi", reference)
    holder_gini = _num_value(observation, "holder_gini", reference)
    storage_score = _num_value(observation, "protocol_storage_score", reference)
    cex_storage = _num_value(observation, "cex_storage_supply_pct", reference)
    storage_warning = (
        (_bool_value(observation, "holder_table_not_global_supply", reference) is True)
        or (_bool_value(observation, "wrapped_representation_warning", reference) is True)
        or (storage_score is not None and storage_score >= 65.0)
        or (cex_storage is not None and cex_storage >= 70.0)
    )
    holder_score = _average(
        [
            _scale(top10, 50.0, 95.0),
            _scale(top100, 80.0, 100.0),
            _scale(adjusted_top10, 45.0, 90.0),
            _scale(holder_hhi, 0.01, 0.20),
            _scale(holder_gini, 0.50, 1.0),
        ]
    )
    holder_evidence = []
    if top10 is not None:
        holder_evidence.append(f"raw top10 {top10:.1f}%")
    if adjusted_top10 is not None:
        holder_evidence.append(f"adjusted top10 {adjusted_top10:.1f}%")
    if storage_warning:
        holder_evidence.append("storage/representation warning")
    holder_level = str(observation.metric("holder_evidence_level").value or "NONE").upper()
    holder_component = _component(
        "holder_concentration",
        ("top10_holder_pct", "top100_holder_pct", "adjusted_top10_pct", "holder_hhi", "holder_gini", "holder_evidence_level", "holder_storage_checked"),
        observation,
        reference,
        holder_score,
        holder_evidence,
        definition="Holder concentration is useful only after custody, protocol storage, wrappers, and representation are separated from potentially manipulable supply.",
        proxy=holder_level == "PROXY",
        contested=storage_warning,
    )
    holder_verified = holder_level == "VERIFIED" and _bool_value(observation, "holder_storage_checked", reference) is True and not storage_warning
    if holder_component.status == "observed" and holder_level == "PROXY":
        holder_component = ComponentAssessment(
            name=holder_component.name,
            score=holder_component.score,
            status="proxy",
            evidence=holder_component.evidence,
            missing_fields=holder_component.missing_fields,
            definition=holder_component.definition,
        )

    binance_presence = _bool_value(observation, "binance_venue_presence", reference)
    binance_share = _num_value(observation, "binance_volume_share_pct", reference)
    bitget_share = _num_value(observation, "bitget_volume_share_pct", reference)
    gate_share = _num_value(observation, "gate_volume_share_pct", reference)
    target_share = _num_value(observation, "target_cex_volume_share_pct", reference)
    has_binance = binance_presence is True or (binance_share is not None and binance_share > 0.0)
    has_target = (bitget_share is not None and bitget_share > 0.0) or (gate_share is not None and gate_share > 0.0) or (target_share is not None and target_share > 0.0)
    venue_values = [_scale(binance_share, 0.0, 50.0), _scale(target_share if target_share is not None else max(bitget_share or 0.0, gate_share or 0.0), 0.0, 15.0)]
    venue_score = _average(venue_values)
    venue_evidence = ["Binance perp presence" if has_binance else "Binance venue evidence missing"]
    venue_evidence.append("Bitget/Gate participation observed" if has_target else "Bitget/Gate participation missing")
    venue_component = _component(
        "venue_confirmation",
        ("binance_venue_presence", "bitget_volume_share_pct", "gate_volume_share_pct"),
        observation,
        reference,
        venue_score,
        venue_evidence,
        definition="The target venue gate is an observation about where the market trades, not proof that a venue is manipulating price or hedging a specific flow.",
    )

    derivative_score = _average([_scale(volume_ratio, 1.0, 5.0), _scale(hour_volume_roc, 0.0, 300.0), _scale(_num_value(observation, "hour_volume_multiple", reference), 1.0, 5.0)])
    derivative_component = _component(
        "derivatives_activity_shock",
        ("volume_ratio_24h_to_prior_30d_avg", "hour_volume_roc_pct", "hour_volume_multiple"),
        observation,
        reference,
        derivative_score,
        [f"24h/30D volume {volume_ratio:.2f}x" if volume_ratio is not None else "24h/30D volume missing"],
        definition="Abnormal perp participation relative to a closed historical baseline is a fuel/context measure, not direction by itself.",
    )

    oi_score = _average([_scale(oi_delta, 0.0, 8.0), _scale(oi_change_3h, 0.0, 12.0), _scale(oi_acceleration, -2.0, 4.0), _scale(oi_persistence, 0.0, 6.0)])
    oi_component = _component(
        "oi_expansion",
        ("oi_delta_1h_pct", "oi_change_3h_pct", "oi_acceleration_1h_pct", "oi_build_persistence"),
        observation,
        reference,
        oi_score,
        [
            f"OI 1h {oi_delta:+.2f}%" if oi_delta is not None else "OI 1h missing",
            f"OI 3h {oi_change_3h:+.2f}%" if oi_change_3h is not None else "OI 3h missing",
            f"OI acceleration {oi_acceleration:+.2f}pp" if oi_acceleration is not None else "OI acceleration missing",
        ],
        definition="Rising open interest alongside price and participation can indicate new derivatives exposure; it does not reveal who will be forced.",
    )

    short_score = _average([_scale(short_pct, 50.0, 80.0), _scale(short_roc, -1.0, 2.0), _scale(short_change_3h, -2.0, 5.0), _scale(short_change_4h, -3.0, 7.0), _scale(short_change_24h, -5.0, 10.0), _scale(short_persistence, 0.0, 6.0)])
    short_component = _component(
        "short_account_crowding_acceleration",
        ("short_account_pct", "short_account_roc_1h_pp", "short_account_change_3h_pp", "short_account_change_4h_pp", "short_account_roc_24h_pp", "short_account_direction_persistence"),
        observation,
        reference,
        short_score,
        [
            f"short accounts {short_pct:.1f}%" if short_pct is not None else "short account level missing",
            f"short ROC {short_roc:+.2f}pp" if short_roc is not None else "short ROC missing",
            f"short 4h change {short_change_4h:+.2f}pp" if short_change_4h is not None else "short 4h change missing",
            f"short 24h change {short_change_24h:+.2f}pp" if short_change_24h is not None else "short 24h change missing",
        ],
        definition="Global short-account share measures clientele breadth, not short dollar notional; the hypothesis must be tested against OI, top-trader positioning, and outcomes.",
    )

    trend_values = [
        _scale(day_return, 0.0, 25.0),
        _scale(avwap_distance, 0.0, 25.0),
        100.0 if _bool_value(observation, "broke_high_5d", reference) is True else 0.0 if _bool_value(observation, "broke_high_5d", reference) is False else None,
        100.0 if _bool_value(observation, "broke_high_20d", reference) is True else 0.0 if _bool_value(observation, "broke_high_20d", reference) is False else None,
        100.0 if _bool_value(observation, "broke_high_90d", reference) is True else 0.0 if _bool_value(observation, "broke_high_90d", reference) is False else None,
        100.0 if _bool_value(observation, "broke_high_180d", reference) is True else 0.0 if _bool_value(observation, "broke_high_180d", reference) is False else None,
    ]
    trend_score = _average(trend_values)
    trend_evidence = []
    if day_return is not None:
        trend_evidence.append(f"24h price {day_return:+.1f}%")
    if avwap_distance is not None:
        trend_evidence.append(f"30D AVWAP {avwap_distance:+.1f}%")
    trend_component = _component(
        "trend_breakout",
        ("price_change_24h_pct", "price_vs_anchored_vwap_30d_pct", "broke_high_5d", "broke_high_20d", "broke_high_90d", "broke_high_180d"),
        observation,
        reference,
        trend_score,
        trend_evidence,
        definition="Price must confirm the fuel; a breakout is an observable state transition, not a prediction of continuation.",
    )

    funding_score = _scale(funding, 0.0, 0.10)
    funding_persistence = _num_value(observation, "funding_persistence", reference)
    funding_zscore = _num_value(observation, "funding_zscore", reference)
    funding_score = _average(
        [
            funding_score,
            _scale(funding_persistence, 0.0, 6.0),
            _scale(abs(funding_zscore), 0.0, 3.0) if funding_zscore is not None else None,
        ]
    )
    funding_component = _component(
        "funding_dislocation",
        ("funding_rate_pct", "funding_interval_hours", "funding_persistence"),
        observation,
        reference,
        funding_score,
        [FUNDING_SEMANTICS["positive"], FUNDING_SEMANTICS["negative"]],
        definition="Funding sign is exchange-defined carry: positive means longs pay shorts; negative means shorts pay longs. It is not synonymous with backwardation or squeeze direction.",
    )

    persistence_score = _average([_scale(short_persistence, 0.0, 6.0), _scale(oi_persistence, 0.0, 6.0), _scale(_num_value(observation, "prior_observations_24h", reference), 0.0, 6.0)])
    persistence_component = _component(
        "reflexivity_persistence",
        ("short_account_direction_persistence", "oi_build_persistence", "prior_observations_24h"),
        observation,
        reference,
        persistence_score,
        [f"short direction persistence {short_persistence:.0f}" if short_persistence is not None else "short persistence missing", f"OI build persistence {oi_persistence:.0f}" if oi_persistence is not None else "OI persistence missing"],
        definition="Repeated observations make a regime more credible than a single noisy print; persistence is still not proof of future returns.",
    )

    flow_to_float = _num_value(observation, "cex_deposit_24h_transfer_to_float_pct", reference)
    flow_to_spot = _num_value(observation, "cex_deposit_24h_notional_to_spot_volume_pct", reference)
    flow_to_liquidity = _num_value(observation, "cex_deposit_24h_notional_to_visible_liquidity_pct", reference)
    flow_risk_score = _average(
        [
            _scale(flow_to_float, 0.0, 5.0),
            _scale(flow_to_spot, 0.0, 100.0),
            _scale(flow_to_liquidity, 0.0, 300.0),
        ]
    )
    flow_evidence = []
    if flow_to_float is not None:
        flow_evidence.append(f"CEX flow/float {flow_to_float:.2f}%")
    if flow_to_spot is not None:
        flow_evidence.append(f"CEX flow/spot volume {flow_to_spot:.1f}%")
    if flow_to_liquidity is not None:
        flow_evidence.append(f"CEX flow/visible liquidity {flow_to_liquidity:.1f}%")
    cex_supply_component = _component(
        "cex_supply_risk",
        (
            "cex_deposit_24h_transfer_to_float_pct",
            "cex_deposit_24h_notional_to_spot_volume_pct",
            "cex_deposit_24h_notional_to_visible_liquidity_pct",
        ),
        observation,
        reference,
        flow_risk_score,
        flow_evidence or ["no classified CEX supply-flow observation"],
        definition="Concentrated holder deposits to labelled CEX wallets are a supply-overhang risk measure. They do not establish wallet intent or a future sell order.",
    )

    components = {
        "float_constraint": float_component,
        "holder_concentration": holder_component,
        "venue_confirmation": venue_component,
        "derivatives_activity_shock": derivative_component,
        "oi_expansion": oi_component,
        "short_account_crowding_acceleration": short_component,
        "trend_breakout": trend_component,
        "funding_dislocation": funding_component,
        "reflexivity_persistence": persistence_component,
        "cex_supply_risk": cex_supply_component,
    }

    short_gate: bool | None = None if short_pct is None else short_pct >= cfg.min_short_account_pct
    build_inputs = [
        short_roc >= cfg.min_short_roc_1h_pp if short_roc is not None else None,
        short_change_3h >= cfg.min_short_change_3h_pp if short_change_3h is not None else None,
        short_persistence >= cfg.min_persistence if short_persistence is not None else None,
    ]
    build_gate = True if any(value is True for value in build_inputs) else False if all(value is False for value in build_inputs if value is not None) and any(value is not None for value in build_inputs) else None
    hour_multiple = _num_value(observation, "hour_volume_multiple", reference)
    volume_inputs = [
        hour_volume_roc >= cfg.min_hour_volume_roc_pct if hour_volume_roc is not None else None,
        hour_multiple >= 1.5 if hour_multiple is not None else None,
    ]
    volume_confirmation = True if any(value is True for value in volume_inputs) else False if all(value is False for value in volume_inputs if value is not None) and any(value is not None for value in volume_inputs) else None
    volume_gate = None if volume_ratio is None or volume_confirmation is None else volume_ratio >= cfg.min_volume_ratio and volume_confirmation
    oi_inputs = [
        oi_change_3h >= cfg.min_oi_change_3h_pct if oi_change_3h is not None else None,
        oi_persistence >= cfg.min_persistence if oi_persistence is not None else None,
    ]
    oi_confirmation = True if any(value is True for value in oi_inputs) else False if all(value is False for value in oi_inputs if value is not None) and any(value is not None for value in oi_inputs) else None
    oi_gate = None if oi_delta is None or oi_confirmation is None else oi_delta >= cfg.min_oi_delta_1h_pct and oi_confirmation
    breakout = any(
        value is True
        for value in (
            _bool_value(observation, "broke_high_5d", reference),
            _bool_value(observation, "broke_high_20d", reference),
            _bool_value(observation, "broke_high_90d", reference),
        )
    )
    trend_available = breakout or day_return is not None or avwap_distance is not None
    trend_gate = None if not trend_available else (
        (breakout or (day_return is not None and day_return > 2.0) or (avwap_distance is not None and avwap_distance > 0.0))
        and (day_return is None or day_return > -2.0)
    )
    funding_gate: bool | None = None if funding is None else funding > 0.0
    crowd_position = _num_value(observation, "crowd_top_position_divergence_pp", reference)
    crowd_account = _num_value(observation, "crowd_top_account_divergence_pp", reference)
    crowd_available = crowd_position is not None or crowd_account is not None
    crowd_veto = crowd_available and ((crowd_position is not None and crowd_position > 2.0) or (crowd_account is not None and crowd_account > 2.0))
    crowd_gate: bool | None = None if not crowd_available else not crowd_veto
    late_heat, late_notes = _late_heat(observation, reference)
    late_gate = late_heat < 75.0
    if stale_snapshot:
        late_gate = False

    flow_veto = (
        (flow_to_float is not None and flow_to_float >= cfg.cex_flow_veto_transfer_to_float_pct)
        or (flow_to_spot is not None and flow_to_spot >= cfg.cex_flow_veto_notional_to_volume_pct)
        or (flow_to_liquidity is not None and flow_to_liquidity >= cfg.cex_flow_veto_notional_to_visible_liquidity_pct)
    )
    flow_gate: bool | None = None if flow_risk_score is None else not flow_veto

    gates: dict[str, bool | None] = {
        "short_crowding": short_gate,
        "short_build": build_gate,
        "volume_ignition": volume_gate,
        "oi_expansion": oi_gate,
        "trend_confirmation": trend_gate,
        "funding_positive": funding_gate,
        "crowd_not_already_long": crowd_gate,
        "not_exhausted": late_gate,
        "holder_proof": None if holder_level == "NONE" else holder_verified,
        "venue_confirmation": None if binance_presence is None and binance_share is None and bitget_share is None and gate_share is None else has_binance and has_target,
        "supply_flow_clear": flow_gate,
    }
    market_trigger = bool(short_gate is True and build_gate is True and volume_gate is True and oi_gate is True and trend_gate is True and late_gate and not crowd_veto and flow_gate is not False)
    structural_watch = bool(market_trigger and (holder_component.score is not None or venue_component.score is not None))
    score = _weighted_component_score(
        components,
        {
            "float_constraint": 0.13,
            "holder_concentration": 0.13,
            "venue_confirmation": 0.08,
            "derivatives_activity_shock": 0.14,
            "oi_expansion": 0.13,
            "short_account_crowding_acceleration": 0.16,
            "trend_breakout": 0.13,
            "funding_dislocation": 0.04,
            "reflexivity_persistence": 0.06,
        },
    )
    if flow_risk_score is not None:
        score = round(score - flow_risk_score * 0.05, 2)
    observed_component_count = sum(component.score is not None for component in components.values())
    score = round(score * (0.65 + 0.35 * observed_component_count / len(components)), 2)

    price_invalidated = (
        price is not None
        and day_return is not None
        and day_return <= cfg.invalidation_price_return_pct
        and (_bool_value(observation, "broke_low_20d", reference) is True or (avwap_distance is not None and avwap_distance < -5.0))
    )
    rollover_invalidated = (
        short_roc is not None
        and short_roc <= -4.0
        and short_pct is not None
        and short_pct <= cfg.exhaustion_short_level_pct
        and (day_return is not None and day_return < 0.0 or oi_delta is not None and oi_delta < 0.0)
    )
    exhaustion_fuel = (
        short_roc is not None
        and short_roc <= cfg.exhaustion_short_roc_pp
        and (
            (short_pct is not None and short_pct <= cfg.exhaustion_short_level_pct)
            or (short_peak_drawdown is not None and short_peak_drawdown <= cfg.exhaustion_peak_drawdown_pp)
        )
    )
    exhaustion = late_heat >= 75.0 or exhaustion_fuel or (upper_wick is not None and upper_wick >= cfg.max_upper_wick_pct and close_location is not None and close_location < 50.0)
    if price_invalidated or rollover_invalidated:
        state = ReflexivityState.INVALIDATED
    elif exhaustion:
        state = ReflexivityState.EXHAUSTION_RISK
    elif market_trigger and score >= 72.0 and build_gate and oi_gate and volume_gate and (breakout or day_return is not None and day_return >= 8.0):
        state = ReflexivityState.ACCELERATING
    elif market_trigger and score >= cfg.min_score:
        state = ReflexivityState.ACTIVE_REFLEXIVITY
    elif short_gate is True and any(value is True for value in (build_gate, volume_gate, oi_gate)) and not stale_snapshot:
        state = ReflexivityState.BUILDING
    else:
        state = ReflexivityState.DISCOVERY

    missing_fields = sorted(
        {
            field_name
            for component in components.values()
            for field_name in component.missing_fields
            if component.status in {"missing", "partial", "stale", "invalid"}
        }
    )
    explanation: list[str] = []
    if short_pct is not None:
        explanation.append(f"global short accounts {short_pct:.1f}% by account count")
    else:
        explanation.append("global short-account level unavailable")
    if short_roc is not None:
        explanation.append(f"short-account ROC {short_roc:+.2f}pp over 1h")
    if volume_ratio is not None:
        explanation.append(f"24h quote volume is {volume_ratio:.2f}x the prior closed 30D daily average")
    if oi_delta is not None:
        explanation.append(f"OI is {oi_delta:+.2f}% over 1h")
    if funding is not None:
        explanation.append(f"funding {funding:+.4f}%: {FUNDING_SEMANTICS['positive'] if funding > 0 else FUNDING_SEMANTICS['negative']}")
    if holder_verified:
        explanation.append("holder proof is verified and storage/representation controls pass")
    elif holder_component.score is not None:
        explanation.append(f"holder evidence is {holder_component.status}; it is not confirmation")
    if not has_target:
        explanation.append("Bitget/Gate venue participation is unavailable or not observed")
    explanation.extend(late_notes)
    if missing_fields:
        explanation.append("missing/stale fields: " + ", ".join(missing_fields[:12]))
    invalidation = [
        "price loss plus 20D breakdown/negative 30D AVWAP",
        "short-account ROC <= -4pp while the short-account level is <= 65% and price/OI weakens",
        "fresh concentrated-holder CEX inflow becomes large relative to float, spot volume, or visible liquidity",
        "freshness failure: refresh before treating the state as current",
    ]
    return ReflexivityAssessment(
        symbol=observation.symbol,
        state=state,
        score=score,
        data_quality_pct=quality,
        market_trigger=market_trigger,
        structural_watch=structural_watch,
        gates=gates,
        components=components,
        explanation=tuple(explanation),
        missing_fields=tuple(missing_fields),
        invalidation=tuple(invalidation),
        funding_read=FUNDING_SEMANTICS["research_use"],
        funding_regime=_funding_regime(funding, config=cfg),
        event_time=observation.event_time,
        observation_id=observation.observation_id,
    )


def assessment_to_row(assessment: ReflexivityAssessment) -> dict[str, Any]:
    """Compact dashboard projection; full provenance remains in the object."""

    return {
        "reflexivity_state": assessment.state.value,
        "reflexivity_score": assessment.score,
        "reflexivity_data_quality_pct": assessment.data_quality_pct,
        "reflexivity_market_trigger": assessment.market_trigger,
        "reflexivity_structural_watch": assessment.structural_watch,
        "reflexivity_component_summary": assessment.component_summary(),
        "reflexivity_gate_summary": assessment.gate_summary(),
        "reflexivity_missing_fields": ", ".join(assessment.missing_fields),
        "reflexivity_explanation": " | ".join(assessment.explanation),
        "reflexivity_invalidation": " | ".join(assessment.invalidation),
        "reflexivity_funding_regime": assessment.funding_regime,
        "reflexivity_component_scores": {
            name: component.score for name, component in assessment.components.items()
        },
        "reflexivity_component_status": {
            name: component.status for name, component in assessment.components.items()
        },
        "reflexivity_component_evidence": {
            name: list(component.evidence) for name, component in assessment.components.items()
        },
    }
