from __future__ import annotations

"""Deterministic offline replay for reviewer evaluation.

Run from the repository root:

    python -m crypto_market_structure.review_demo

The bundled fixture is explicitly illustrative. It demonstrates the complete
observation -> state -> event-study -> manifest path without contacting an
exchange or claiming that synthetic outcomes are historical performance.
"""

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .casebook import write_casebook
from .event_study import (
    EventStudyDefinition,
    build_events,
    build_matched_baseline_events,
    build_token_history_baseline_events,
    build_unconditional_baseline_events,
    EVENT_STUDY_VERSION,
    run_event_study,
)
from .manifest import build_manifest, sha256_file, write_manifest
from .reflexivity import ReflexivityConfig, SIGNAL_VERSION, assess_reflexivity, observation_from_row


DEFAULT_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "reflexivity_demo.json"
FIXED_GENERATED_AT = "2026-01-10T00:00:00Z"


def _load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _markdown_report(report: dict[str, Any], *, fixture_kind: str, fixture_path: Path) -> str:
    lines = [
        "# Reflexivity Review Demo",
        "",
        "This report is generated from a frozen offline fixture. It is a reproducibility and methodology artifact, not a live signal report or a backtest claim.",
        "",
        f"- Fixture: `{fixture_path.as_posix()}`",
        f"- Fixture kind: `{fixture_kind}`",
        f"- Signal version: `{report['signal_version']}`",
        f"- Frozen observations: `{report['observation_count']}`",
        f"- Frozen events: `{report['event_study']['event_count']}`",
        f"- Matched non-event baselines: `{report['event_study']['baseline_event_count']}`",
        f"- Unconditional universe snapshots: `{report['event_study']['unconditional_event_count']}`",
        f"- Token-history baseline snapshots: `{report['event_study']['token_baseline_event_count']}`",
        f"- Fuel observation coverage: `{report['event_study']['summary']['fuel_coverage_pct']:.1f}%`",
        f"- Benchmark excess path: `{report['event_study']['benchmark_symbol'] or 'not supplied'}`",
        "",
        "## State Replay",
        "",
        "| Symbol | Event time | State | Score | Data quality | Trigger | Missing fields |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for row in report["observations"]:
        lines.append(
            f"| {row['symbol']} | {row['event_time']} | {row['assessment']['state']} | "
            f"{row['assessment']['score']:.2f} | {row['assessment']['data_quality_pct']:.1f}% | "
            f"{str(row['assessment']['market_trigger']).lower()} | "
            f"{', '.join(row['assessment']['missing_fields']) or 'none'} |"
        )
    lines.extend(["", "## Event-Study Summary", "", "| Horizon | Events | Outcomes | Coverage | Median return | Median MFE | Median MAE | Positive hit rate |", "|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for horizon, summary in report["event_study"]["summary"]["horizons"].items():
        fmt = lambda value: "n/a" if value is None else f"{value:.2f}"
        lines.append(
            f"| {horizon}h | {summary['event_count']} | {summary['outcome_count']} | {summary['coverage_pct']:.1f}% | "
            f"{fmt(summary['median_return_pct'])}% | {fmt(summary['median_mfe_pct'])}% | "
            f"{fmt(summary['median_mae_pct'])}% | {fmt(summary['positive_hit_rate_pct'])}% |"
        )
    lines.extend(["", "### Baseline comparison", "", "The bundled baseline is a transparent same-universe non-event set. It is deliberately not described as causal matching; a production study should add and freeze richer regime matching.", "", "| Horizon | Event median | Baseline median | Event coverage | Baseline coverage |", "|---:|---:|---:|---:|---:|"])
    baseline_horizons = report["event_study"]["baseline_summary"]["horizons"]
    for horizon, summary in report["event_study"]["summary"]["horizons"].items():
        baseline = baseline_horizons[horizon]
        fmt = lambda value: "n/a" if value is None else f"{value:.2f}%"
        lines.append(f"| {horizon}h | {fmt(summary['median_return_pct'])} | {fmt(baseline['median_return_pct'])} | {summary['coverage_pct']:.1f}% | {baseline['coverage_pct']:.1f}% |")
    lines.extend(
        [
            "",
            "Additional comparison sets are included in the JSON report: unconditional universe snapshots, token-history non-signal snapshots, and benchmark excess returns when a benchmark path is supplied.",
        ]
    )
    lines.extend(
        [
            "",
            "## Claim Boundary",
            "",
            "- The replay supports reproducibility of the frozen definitions and calculations.",
            "- It does not establish causality, execution quality, profitability, or that account-count shorting equals short notional.",
            "- A real evaluation must replace this fixture with point-in-time source snapshots, preserve missingness, use frozen definitions, and report a holdout sample.",
            "",
            "## Falsification Checks",
            "",
            "- Does global short-account breadth add predictive information after controlling for OI, funding, price, volume, and top-trader positioning?",
            "- Do candidate states outperform matched non-events on the same symbols and market regimes at every horizon, or only in the tail?",
            "- Does the effect survive removal of the largest one or two outcomes and a chronological holdout?",
            "- Are apparent float/holder effects still present after removing custody, protocol storage, wrapper, and venue-label false positives?",
            "",
        ]
    )
    return "\n".join(lines)


def run_demo(*, root: Path, fixture_path: Path, output_dir: Path) -> dict[str, Any]:
    fixture = _load_fixture(fixture_path)
    observations = []
    assessments = []
    observation_rows: list[dict[str, Any]] = []
    for index, raw in enumerate(fixture.get("observations", [])):
        row = dict(raw)
        observation = observation_from_row(row, observation_id=f"demo:{index}:{row.get('symbol', '')}:{row.get('event_time_utc', '')}")
        assessment = assess_reflexivity(observation, as_of=observation.received_at)
        observations.append(observation)
        assessments.append(assessment)
        observation_rows.append(
            {
                "symbol": observation.symbol,
                "event_time": observation.event_time.isoformat().replace("+00:00", "Z") if observation.event_time else None,
                "observation": observation.to_dict(as_of=observation.received_at),
                "assessment": assessment.to_dict(),
            }
        )

    holdout_start = datetime(2026, 1, 4, tzinfo=timezone.utc)
    definition = EventStudyDefinition(
        signal_version=SIGNAL_VERSION,
        holdout_start=holdout_start,
        bootstrap_samples=500,
        bootstrap_seed=17,
    )
    events = build_events(observations, assessments, definition)
    baseline_events = build_matched_baseline_events(observations, assessments, definition)
    unconditional_events = build_unconditional_baseline_events(observations, assessments, definition)
    token_baseline_events = build_token_history_baseline_events(observations, assessments, definition)
    price_paths = fixture.get("price_paths", {})
    event_study = run_event_study(
        events,
        price_paths,
        definition,
        baseline_events=baseline_events,
        unconditional_events=unconditional_events,
        token_baseline_events=token_baseline_events,
        fuel_paths=fixture.get("fuel_paths", {}),
        benchmark_paths=fixture.get("benchmark_paths", {}),
        benchmark_symbol=str(fixture.get("benchmark_symbol") or "BTCUSDT"),
    )
    first_time = min((observation.event_time for observation in observations if observation.event_time), default=None)
    last_time = max((observation.event_time for observation in observations if observation.event_time), default=None)
    report: dict[str, Any] = {
        "report_version": "1",
        "generated_at_utc": FIXED_GENERATED_AT,
        "signal_version": SIGNAL_VERSION,
        "fixture_kind": fixture.get("fixture_kind", "unknown"),
        "fixture_description": fixture.get("description", ""),
        "observation_count": len(observations),
        "observations": observation_rows,
        "state_counts": {
            state: sum(assessment.state.value == state for assessment in assessments)
            for state in ("DISCOVERY", "BUILDING", "ACTIVE_REFLEXIVITY", "ACCELERATING", "EXHAUSTION_RISK", "INVALIDATED")
        },
        "event_study": event_study,
        "baseline_event_count": len(baseline_events),
        "unconditional_event_count": len(unconditional_events),
        "token_baseline_event_count": len(token_baseline_events),
        "review_limits": [
            "synthetic fixture only",
            "not a trading strategy or autonomous execution path",
            "account-count shorting is not short notional",
            "event-study coverage and missingness must be reviewed before any live conclusion",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "review_report.json"
    markdown_path = output_dir / "review_report.md"
    casebook_path = output_dir / "reflexivity-casebook.md"
    manifest_path = output_dir / "manifest.json"
    report["manifest_path"] = str(manifest_path.relative_to(root)).replace("\\", "/")
    report["fixture_sha256"] = sha256_file(fixture_path)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    markdown_path.write_text(
        _markdown_report(
            report,
            fixture_kind=str(report["fixture_kind"]),
            fixture_path=fixture_path.relative_to(root) if fixture_path.is_relative_to(root) else fixture_path,
        ),
        encoding="utf-8",
    )
    write_casebook(casebook_path)
    manifest = build_manifest(
        root=root,
        signal_version=SIGNAL_VERSION,
        event_study_version=EVENT_STUDY_VERSION,
        config={"model": "canonical_reflexivity", "rules": asdict(ReflexivityConfig())},
        event_study_definition=definition.to_dict(),
        input_paths=[fixture_path],
        artifact_paths=[report_path, markdown_path, casebook_path],
        observation_window={"start": first_time.isoformat() if first_time else None, "end": last_time.isoformat() if last_time else None},
        holdout={"start": holdout_start.isoformat(), "method": "chronological event-time split"},
        generated_at=FIXED_GENERATED_AT,
    )
    write_manifest(manifest_path, manifest)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the deterministic offline reflexivity review demo.")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts") / "review_demo")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    report = run_demo(root=root, fixture_path=args.fixture.resolve(), output_dir=(root / args.output_dir if not args.output_dir.is_absolute() else args.output_dir))
    print(json.dumps({"signal_version": report["signal_version"], "observations": report["observation_count"], "events": report["event_study"]["event_count"], "manifest": report["manifest_path"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
