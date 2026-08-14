from __future__ import annotations

"""UI-independent projections of canonical research assessments.

Adapters may turn the returned columns into tables, alerts, or reports.  The
projection itself does not know about Streamlit, Discord, live APIs, or local
cache files, and callers can provide a fixed ``as_of`` time for replay.
"""

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .reflexivity import SIGNAL_VERSION, assess_reflexivity, assessment_to_row, observation_from_row


REFLEXIVITY_PROJECTION_COLUMNS = frozenset(
    {
        "reflexivity_state",
        "reflexivity_score",
        "reflexivity_data_quality_pct",
        "reflexivity_market_trigger",
        "reflexivity_structural_watch",
        "reflexivity_component_summary",
        "reflexivity_gate_summary",
        "reflexivity_missing_fields",
        "reflexivity_explanation",
        "reflexivity_invalidation",
        "reflexivity_funding_regime",
        "reflexivity_component_scores",
        "reflexivity_component_status",
        "reflexivity_component_evidence",
        "reflexivity_signal_version",
        "reflexivity_event_time_utc",
        "reflexivity_received_at_utc",
        "reflexivity_source",
        "reflexivity_venue",
    }
)


def project_reflexivity_assessments(
    frame: pd.DataFrame,
    *,
    as_of: datetime | None = None,
) -> pd.DataFrame:
    """Append point-in-time canonical assessments to observation rows."""

    if frame.empty:
        return frame.copy()
    evaluation_time = as_of or datetime.now(timezone.utc)
    output = frame.drop(
        columns=[column for column in REFLEXIVITY_PROJECTION_COLUMNS if column in frame.columns],
        errors="ignore",
    ).copy()
    projected: list[dict[str, Any]] = []
    for index, (_, row) in enumerate(output.iterrows()):
        observation = observation_from_row(
            row.to_dict(),
            observation_id=f"radar:{str(row.get('symbol') or '').upper()}:{row.get('event_time_utc') or row.get('scanned_at_utc') or index}",
        )
        assessment = assess_reflexivity(observation, as_of=evaluation_time)
        projection = assessment_to_row(assessment)
        projection.update(
            {
                "reflexivity_signal_version": SIGNAL_VERSION,
                "reflexivity_event_time_utc": observation.event_time.isoformat().replace("+00:00", "Z") if observation.event_time else "",
                "reflexivity_received_at_utc": observation.received_at.isoformat().replace("+00:00", "Z") if observation.received_at else "",
                "reflexivity_source": observation.source,
                "reflexivity_venue": observation.venue,
            }
        )
        projected.append(projection)
    projected_frame = pd.DataFrame(projected, index=output.index)
    return pd.concat([output, projected_frame], axis=1)
