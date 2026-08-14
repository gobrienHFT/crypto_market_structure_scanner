"""Deterministic research primitives for the reflexivity thesis.

The Streamlit app and Discord integrations are presentation layers.  The
modules in this package keep the definitions, provenance rules, state machine,
and offline review workflow importable and testable without a live exchange.
"""

from .reflexivity import (
    FUNDING_SEMANTICS,
    SIGNAL_VERSION,
    ComponentAssessment,
    MetricObservation,
    OwnershipSnapshot,
    ReflexivityAssessment,
    ReflexivityConfig,
    ReflexivityObservation,
    ReflexivityState,
    SupplyFlowObservation,
    VenueObservation,
    WalletClassification,
    assess_reflexivity,
    observation_from_row,
)
from .reporting import project_reflexivity_assessments

__all__ = [
    "FUNDING_SEMANTICS",
    "SIGNAL_VERSION",
    "ComponentAssessment",
    "MetricObservation",
    "OwnershipSnapshot",
    "ReflexivityAssessment",
    "ReflexivityConfig",
    "ReflexivityObservation",
    "ReflexivityState",
    "SupplyFlowObservation",
    "VenueObservation",
    "WalletClassification",
    "assess_reflexivity",
    "observation_from_row",
    "project_reflexivity_assessments",
]
