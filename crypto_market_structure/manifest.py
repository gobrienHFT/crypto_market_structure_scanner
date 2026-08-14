from __future__ import annotations

"""Reproducibility manifest helpers for offline reviews."""

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit(root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return completed.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _git_tree_clean(root: Path) -> bool | None:
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return not bool(completed.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return None


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def build_manifest(
    *,
    root: Path | str,
    signal_version: str,
    config: Mapping[str, Any],
    event_study_definition: Mapping[str, Any],
    event_study_version: str = "",
    input_paths: Iterable[Path | str] = (),
    artifact_paths: Iterable[Path | str] = (),
    observation_window: Mapping[str, Any] | None = None,
    holdout: Mapping[str, Any] | None = None,
    generated_at: str = "",
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    inputs: list[dict[str, Any]] = []
    for raw_path in input_paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = root_path / path
        if path.exists() and path.is_file():
            inputs.append({"path": _relative(path, root_path), "sha256": sha256_file(path), "bytes": path.stat().st_size})
        else:
            inputs.append({"path": _relative(path, root_path), "sha256": None, "bytes": None, "missing": True})
    artifacts: list[dict[str, Any]] = []
    for raw_path in artifact_paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = root_path / path
        if path.exists() and path.is_file():
            artifacts.append({"path": _relative(path, root_path), "sha256": sha256_file(path), "bytes": path.stat().st_size})
        else:
            artifacts.append({"path": _relative(path, root_path), "sha256": None, "bytes": None, "missing": True})
    config_hash = sha256_bytes(_canonical_json(config))
    definition_hash = sha256_bytes(_canonical_json(event_study_definition))
    return {
        "manifest_version": "1",
        "generated_at_utc": generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "git_commit": _git_commit(root_path),
        "working_tree_is_clean": _git_tree_clean(root_path),
        "signal_version": signal_version,
        "event_study_version": event_study_version or str(event_study_definition.get("version") or "unknown"),
        "config_hash": config_hash,
        "event_study_definition_hash": definition_hash,
        "event_study_definition": dict(event_study_definition),
        "observation_window": dict(observation_window or {}),
        "holdout": dict(holdout or {}),
        "inputs": inputs,
        "artifacts": artifacts,
        "claim_boundary": {
            "supports": "reproduction of the frozen observation-to-state and outcome calculations",
            "does_not_support": "causal proof, guaranteed returns, or a claim that account-count shorting equals short notional",
        },
    }


def write_manifest(path: Path | str, manifest: Mapping[str, Any]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(manifest), indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    return output
