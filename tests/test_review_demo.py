from __future__ import annotations

import json
from pathlib import Path

from crypto_market_structure.review_demo import run_demo


def test_offline_review_demo_writes_report_and_manifest(tmp_path: Path) -> None:
    root = tmp_path
    fixture = Path(__file__).resolve().parents[1] / "crypto_market_structure" / "fixtures" / "reflexivity_demo.json"
    output_dir = tmp_path / "review"

    report = run_demo(root=root, fixture_path=fixture, output_dir=output_dir)

    assert report["signal_version"] == "reflexivity-v1.1"
    assert report["observation_count"] == 4
    assert report["event_study"]["event_count"] == 2
    assert report["event_study"]["baseline_event_count"] == 1
    assert (output_dir / "review_report.json").exists()
    assert (output_dir / "review_report.md").exists()
    assert (output_dir / "manifest.json").exists()
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["event_study_version"] == "event-study-v1.1"
    assert "working_tree_is_clean" in manifest
    assert manifest["inputs"][0]["sha256"]
    assert any(item["path"].endswith("review_report.json") for item in manifest["artifacts"])
    casebook = (root / "docs" / "reflexivity-casebook.md").read_text(encoding="utf-8")
    assert "- The retracement is observed;" in casebook
    assert "- T\n- h\n- e" not in casebook
