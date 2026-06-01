from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_core_thesis_gate_audit_references_existing_tests() -> None:
    audit = (ROOT / "docs" / "core-thesis-gate-audit.md").read_text(encoding="utf-8")
    references = re.findall(r"`(tests/[^`]+?\.py)::(test_[A-Za-z0-9_]+)`", audit)

    assert references
    missing: list[str] = []
    for relative_path, test_name in references:
        path = ROOT / Path(relative_path)
        if not path.exists():
            missing.append(f"{relative_path}::{test_name}")
            continue
        source = path.read_text(encoding="utf-8")
        if not re.search(rf"^def {re.escape(test_name)}\b", source, flags=re.MULTILINE):
            missing.append(f"{relative_path}::{test_name}")

    assert not missing
