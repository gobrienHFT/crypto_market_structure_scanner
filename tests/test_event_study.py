from pathlib import Path

import pandas as pd
import pytest

from event_study import build_backfill_checklist, build_case_study_event_frame, collect_contract_hints, write_case_study_event_files


def test_case_study_event_frame_marks_observed_and_missing_rows(tmp_path: Path) -> None:
    pd.DataFrame(
        [
            {
                "symbol": "RAVEUSDT",
                "long_account_pct": 42.0,
                "carry_funding_pct": 0.012,
                "oi_delta_pct": 3.4,
                "crime_exhaustion_score": 82.0,
            }
        ]
    ).to_csv(tmp_path / "2026-04-20T17-22_export.csv", index=False)

    frame = build_case_study_event_frame(root=tmp_path)
    rave = frame[frame["symbol"] == "RAVEUSDT"].iloc[0]
    lab = frame[frame["symbol"] == "LABUSDT"].iloc[0]

    assert rave["local_evidence_status"] == "observed locally"
    assert rave["short_account_pct"] == 58.0
    assert rave["observed_phase"] == "post-blowoff / exhaustion"
    assert "shorts 58.0%" in rave["mechanism_read"]
    assert rave["mechanism_verdict"] == "needs exact event/date evidence"
    assert rave["evidence_gap_severity"] == "high"
    assert "exact event date" in rave["next_data_action"]
    assert lab["local_evidence_status"] == "missing local row"
    assert lab["evidence_gaps"] == "no local snapshot row found"
    assert lab["evidence_gap_severity"] == "critical"
    assert "Backfill" in lab["next_data_action"]


def test_write_case_study_event_files_escapes_markdown_pipes(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    pd.DataFrame(
        [
            {
                "symbol": "VELVETUSDT",
                "short_account_pct": 66.0,
                "broke_high_20d": True,
                "carry_funding_pct": 0.025,
            }
        ]
    ).to_csv(tmp_path / "data" / "pre_pump_scan_snapshots.csv", index=False)

    docs_path = tmp_path / "docs" / "case-study-event-summary.md"
    csv_path = tmp_path / "data" / "case_study_event_summary.csv"
    write_case_study_event_files(root=tmp_path, docs_path=docs_path, csv_path=csv_path)

    markdown = docs_path.read_text(encoding="utf-8")
    velvet_line = [line for line in markdown.splitlines() if line.startswith("| VELVETUSDT")][0]

    assert csv_path.exists()
    assert "Crowded-short uptrend continuation ; shorts 66.0%" in velvet_line


def test_case_study_event_frame_adds_kline_price_path_metrics(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    pd.DataFrame(
        [
            {
                "symbol": "LABUSDT",
                "chain": "bsc",
                "contract_address": "0xabc",
            }
        ]
    ).to_csv(tmp_path / "data" / "discord_holder_contracts.csv", index=False)
    pd.DataFrame(
        [
            {
                "symbol": "LABUSDT",
                "short_account_pct": 67.0,
            }
        ]
    ).to_csv(tmp_path / "data" / "pre_pump_scan_snapshots.csv", index=False)

    class FakeKlineClient:
        def klines_1d(self, symbol: str, limit: int = 200, *, start_time: int | None = None, end_time: int | None = None):
            assert symbol == "LABUSDT"
            base = pd.Timestamp("2026-04-20", tz="UTC")
            rows = []
            for index in range(30):
                open_time = int((base + pd.Timedelta(days=index)).timestamp() * 1000)
                open_price = 10.0 + index
                high = open_price + 1.0
                low = open_price - 1.0
                close = open_price + 0.5
                if index == 21:
                    open_price = 30.0
                    high = 60.0
                    low = 25.0
                    close = 45.0
                if index == 22:
                    high = 70.0
                    low = 40.0
                    close = 50.0
                rows.append([open_time, str(open_price), str(high), str(low), str(close), "0", open_time, "0", 0, "0", "0", "0"])
            return rows

    frame = build_case_study_event_frame(root=tmp_path, kline_client=FakeKlineClient())
    lab = frame[frame["symbol"] == "LABUSDT"].iloc[0]

    assert lab["price_path_status"] == "ok"
    assert lab["event_break_prior_20d_high"] is True
    assert lab["event_day_return_pct"] == 50.0
    assert lab["post_7d_high_return_pct"] > 50.0
    assert lab["mechanism_verdict"] == "violent continuation with large drawdown risk"
    assert "deep pullbacks" in lab["scanner_lesson"]
    assert lab["evidence_gap_severity"] == "high"
    assert lab["contract_hint_status"] == "available"
    assert lab["contract_hint_chain"] == "bsc"
    assert lab["contract_hint_address"] == "0xabc"
    assert "existing contract hint" in lab["next_data_action"]


def test_case_study_event_frame_infers_missing_event_date_from_largest_impulse(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    pd.DataFrame(
        [
            {
                "symbol": "VELVETUSDT",
                "short_account_pct": 67.0,
            }
        ]
    ).to_csv(tmp_path / "data" / "pre_pump_scan_snapshots.csv", index=False)

    class FakeKlineClient:
        def klines_1d(self, symbol: str, limit: int = 200, *, start_time: int | None = None, end_time: int | None = None):
            assert symbol == "VELVETUSDT"
            base = pd.Timestamp("2026-06-01", tz="UTC")
            rows = []
            for index in range(12):
                open_time = int((base + pd.Timedelta(days=index)).timestamp() * 1000)
                open_price = 1.0
                high = 1.1
                low = 0.9
                close = 1.0
                if index == 7:
                    open_price = 1.0
                    high = 3.5
                    low = 0.95
                    close = 2.8
                if index == 8:
                    open_price = 2.8
                    high = 3.8
                    low = 2.4
                    close = 3.2
                if index > 8:
                    open_price = 3.0
                    high = 3.3
                    low = 2.6
                    close = 3.1
                rows.append([open_time, str(open_price), str(high), str(low), str(close), "0", open_time, "0", 0, "0", "0", "0"])
            return rows

    frame = build_case_study_event_frame(root=tmp_path, kline_client=FakeKlineClient())
    velvet = frame[frame["symbol"] == "VELVETUSDT"].iloc[0]

    assert velvet["price_path_status"] == "ok"
    assert velvet["price_event_date"] == "2026-06-08"
    assert velvet["price_event_date_source"] == "inferred_largest_daily_impulse"
    assert velvet["event_day_return_pct"] == pytest.approx(180.0)
    assert velvet["mechanism_verdict"] == "impulse day can still have continuation fuel"
    assert "not the terminal high" in velvet["scanner_lesson"]


def test_backfill_checklist_groups_actions_by_priority() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "RAVEUSDT",
                "evidence_gap_severity": "high",
                "next_data_action": "Resolve token contract.",
                "evidence_gaps": "holder snapshot missing",
            },
            {
                "symbol": "LABUSDT",
                "evidence_gap_severity": "high",
                "next_data_action": "Resolve token contract.",
                "evidence_gaps": "holder snapshot missing",
            },
            {
                "symbol": "VELVETUSDT",
                "evidence_gap_severity": "medium",
                "next_data_action": "Backfill short accounts.",
                "evidence_gaps": "short-account snapshot missing",
            },
        ]
    )

    checklist = build_backfill_checklist(frame)

    assert checklist.iloc[0]["priority"] == "high"
    assert checklist.iloc[0]["symbols"] == "RAVEUSDT, LABUSDT"
    assert checklist.iloc[0]["count"] == 2
    assert checklist.iloc[1]["priority"] == "medium"


def test_collect_contract_hints_accepts_symbol_and_base_rows(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    pd.DataFrame(
        [
            {"symbol": "RAVE", "chain": "ethereum", "contract_address": '="0x123"'},
            {"symbol": "LABUSDT", "chain": "bsc", "contract_address": "0x456"},
        ]
    ).to_csv(tmp_path / "data" / "discord_holder_contracts.csv", index=False)

    hints = collect_contract_hints(root=tmp_path, symbols=["RAVEUSDT", "LABUSDT"])

    assert hints["RAVEUSDT"].contract_address == "0x123"
    assert hints["RAVEUSDT"].chain == "ethereum"
    assert hints["LABUSDT"].contract_address == "0x456"
