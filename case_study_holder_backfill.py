from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from concentration_scanner import ScannerInput, TokenConcentrationScanner
from concentration_scanner.presentation import result_to_row
from event_study import CASE_STUDY_SYMBOLS, collect_contract_hints


BACKFILL_COLUMNS = [
    "symbol",
    "chain",
    "contract_address",
    "backfill_status",
    "scanner_error",
    "holder_data_usable",
    "holder_failure_mode",
    "holder_next_route",
    "raw_top_1_pct",
    "raw_top_5_pct",
    "raw_top_10_pct",
    "raw_top_100_pct",
    "adjusted_top_1_pct",
    "adjusted_top_5_pct",
    "adjusted_top_10_pct",
    "largest_unexplained_holder_pct",
    "filtered_top_5_manipulable_pct",
    "filtered_top_10_manipulable_pct",
    "largest_manipulable_holder_pct",
    "largest_manipulable_holder_address",
    "risk_score",
    "master_score",
    "master_label",
    "key_flags",
    "summary",
]


class HolderScanner(Protocol):
    def scan(self, scanner_input: ScannerInput) -> Any:
        ...


def _blank_row(symbol: str, *, chain: str = "", contract_address: str = "", status: str = "missing_contract", error: str = "") -> dict[str, Any]:
    row = {column: "" for column in BACKFILL_COLUMNS}
    row.update(
        {
            "symbol": symbol,
            "chain": chain,
            "contract_address": contract_address,
            "backfill_status": status,
            "scanner_error": error,
            "holder_data_usable": False,
            "holder_failure_mode": _failure_mode(error, status=status),
            "holder_next_route": _next_route(error, status=status),
        }
    )
    return row


def _failure_mode(error: Any, *, status: str = "") -> str:
    text = str(error or "").strip().lower()
    if status == "missing_contract":
        return "missing contract hint"
    if not text:
        return ""
    if "notok" in text:
        return "explorer holder endpoint unavailable/not entitled"
    if "rate" in text or "429" in text:
        return "rate limited"
    if "timeout" in text:
        return "explorer timeout"
    if "blocked" in text or "403" in text:
        return "explorer blocked"
    return "scanner error"


def _next_route(error: Any, *, status: str = "") -> str:
    mode = _failure_mode(error, status=status)
    if mode == "missing contract hint":
        return "Add symbol, chain, contract_address to data/discord_holder_contracts.csv."
    if mode == "explorer holder endpoint unavailable/not entitled":
        return "Use a paid holder-list provider or alternate indexer/export; free Etherscan-family API did not return token holders."
    if mode == "rate limited":
        return "Retry with lower request rate or a higher-tier explorer key."
    if mode == "explorer timeout":
        return "Retry later or reduce holder limit."
    if mode == "explorer blocked":
        return "Switch provider or add an approved API route."
    if mode:
        return "Inspect scanner_error and rerun the holder backfill."
    return "Holder data usable."


def _normalise_result_row(symbol: str, chain: str, contract_address: str, payload: dict[str, Any]) -> dict[str, Any]:
    error = payload.get("scanner_error", "")
    usable = not str(error or "").strip() and float(payload.get("raw_top_10_pct") or 0.0) > 0.0
    row = {column: payload.get(column, "") for column in BACKFILL_COLUMNS}
    row.update(
        {
            "symbol": symbol,
            "chain": chain,
            "contract_address": contract_address,
            "backfill_status": "complete" if usable else "partial",
            "scanner_error": error,
            "holder_data_usable": usable,
            "holder_failure_mode": _failure_mode(error, status="partial" if error else ""),
            "holder_next_route": _next_route(error, status="partial" if error else ""),
        }
    )
    return row


def build_case_study_holder_backfill(
    *,
    root: Path | str = ".",
    symbols: tuple[str, ...] = CASE_STUDY_SYMBOLS,
    scanner: HolderScanner | None = None,
    top_n: int = 100,
) -> pd.DataFrame:
    root_path = Path(root)
    hints = collect_contract_hints(root=root_path, symbols=symbols)
    active_scanner = scanner or TokenConcentrationScanner()
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        hint = hints.get(symbol)
        if hint is None:
            rows.append(_blank_row(symbol))
            continue
        try:
            result = active_scanner.scan(
                ScannerInput(
                    symbol=symbol,
                    chain=hint.chain,
                    contract_address=hint.contract_address,
                    top_n=int(top_n),
                    mode="case_study_backfill",
                )
            )
            payload = result_to_row(result)
            rows.append(_normalise_result_row(symbol, hint.chain, hint.contract_address, payload))
        except Exception as exc:
            rows.append(
                _blank_row(
                    symbol,
                    chain=hint.chain,
                    contract_address=hint.contract_address,
                    status="error",
                    error=f"{exc.__class__.__name__}: {exc}",
                )
            )
    return pd.DataFrame(rows, columns=BACKFILL_COLUMNS)


def write_case_study_holder_backfill(
    *,
    root: Path | str = ".",
    output_path: Path | None = None,
    scanner: HolderScanner | None = None,
) -> pd.DataFrame:
    root_path = Path(root)
    frame = build_case_study_holder_backfill(root=root_path, scanner=scanner)
    if output_path is None:
        output_path = root_path / "docs" / "case-study-holder-backfill.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "# Case-Study Holder Backfill\n\n"
        "Generated by `python case_study_holder_backfill.py`. Rows marked `error` usually mean explorer/API coverage needs attention.\n\n"
        + frame.to_markdown(index=False)
        + "\n",
        encoding="utf-8",
    )
    return frame


if __name__ == "__main__":
    write_case_study_holder_backfill()
