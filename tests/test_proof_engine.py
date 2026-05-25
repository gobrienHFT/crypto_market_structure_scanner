from __future__ import annotations

import json

import pandas as pd

from proof_engine import archive_alerts, load_archive, refresh_outcomes, weekly_scoreboard_text, write_weekly_report


class FakeKlineClient:
    def __init__(self, rows: list[list[object]]):
        self.rows = rows

    def klines(self, symbol: str, *, interval: str, limit: int, start_time: int, end_time: int) -> list[list[object]]:
        return [row for row in self.rows if start_time <= int(row[0]) <= end_time]


def _kline(ts: str, high: float, low: float) -> list[object]:
    open_ms = int(pd.Timestamp(ts).tz_convert("UTC").timestamp() * 1000)
    return [open_ms, "1", str(high), str(low), "1", "0", open_ms + 59_999, "0", 1, "0", "0", "0"]


def test_archive_alerts_records_proof_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_PROOF_ARCHIVE_ROOT", str(tmp_path / "data_archive"))
    path = tmp_path / "archive.csv"
    rows = pd.DataFrame(
        [
            {
                "symbol": "PLAYUSDT",
                "last_price": 1.0,
                "trade_bucket_score": 88.4,
                "trade_bucket_note": "controlled float | short-account skew",
                "short_account_pct": 62.5,
                "long_account_pct": 37.5,
                "oi_delta_pct": 4.2,
                "quote_volume_24h": 12_000_000,
                "terminal_edge_score": 77.7,
                "terminal_structure_edge_score": 81.2,
                "terminal_control_plane_score": 79.0,
                "terminal_distribution_pressure_score": 73.5,
                "terminal_pre_ignition_quality_score": 68.0,
                "terminal_setup_archetype": "low-vol short-fuse",
                "terminal_market_regime": "calm beta tape",
                "terminal_liquidity_reality": "cap-table supply; exits can gap",
                "terminal_evidence_summary": "terminal 78/100 | short accounts 62.5%",
                "cex_deposit_flow_score": 88.0,
                "cex_deposit_flow_source": "token_transfer_api",
                "cex_deposit_24h_source_url": "https://api.etherscan.io/v2/api?chainid=8453&module=account&action=tokentx",
                "cex_deposit_24h_target_exchanges": "Bitget",
                "cex_deposit_24h_notional_usd": 750_000,
                "cex_deposit_24h_notional_to_ask_depth_pct": 240.0,
                "cex_deposit_inventory_stress_score": 71.0,
                "cex_deposit_inventory_stress_note": "venue-inventory stress 71/100; total notional $750.00K",
                "archetype_match_score": 86.0,
                "archetype_best_match": "LAB-style venue-inventory stress",
                "archetype_match_note": "LAB-style venue-inventory stress 86/100; controlled float plus CEX flow",
                "early_pump_radar_score": 89.0,
                "early_pump_state": "Prime early squeeze",
                "early_pump_primary_signal": "target CEX flow 88/100",
                "early_pump_confirmed_target_flow": True,
                "early_pump_next_check": "check whether deposited inventory is absorbed",
                "timing_score": 66.6,
                "timing_inventory_response_score": 70.0,
                "timing_state": "Triggering",
                "timing_observed_trigger": "OI expanding, volume lifting",
                "_holder_text": "Holder composition Top1 22.0% | Top5 61.0% | Top100 97.0%",
            }
        ]
    )

    archive = archive_alerts(rows, scan_mode="Deep", path=path, flagged_at_utc="2026-01-01T00:00:00Z")

    assert len(archive) == 1
    row = archive.iloc[0]
    assert row["symbol"] == "PLAYUSDT"
    assert row["flagged_price"] == 1.0
    assert row["convex_score"] == 88.4
    assert "controlled float" in row["reason_tags"]
    assert "Top5 61.0%" in row["chain_concentration"]
    assert "short 62.5%" in row["oi_volume_state"]
    assert row["terminal_edge_score"] == 77.7
    assert row["terminal_structure_edge_score"] == 81.2
    assert row["terminal_distribution_pressure_score"] == 73.5
    assert row["cex_deposit_flow_score"] == 88.0
    assert row["cex_deposit_flow_source"] == "token_transfer_api"
    assert row["cex_deposit_24h_target_exchanges"] == "Bitget"
    assert row["cex_deposit_24h_notional_usd"] == 750_000
    assert row["cex_deposit_inventory_stress_score"] == 71.0
    assert "venue-inventory stress" in row["cex_deposit_inventory_stress_note"]
    assert row["archetype_best_match"] == "LAB-style venue-inventory stress"
    assert row["early_pump_radar_score"] == 89.0
    assert row["early_pump_state"] == "Prime early squeeze"
    assert row["timing_inventory_response_score"] == 70.0
    assert row["terminal_setup_archetype"] == "low-vol short-fuse"
    assert row["timing_score"] == 66.6
    assert row["timing_state"] == "Triggering"
    assert load_archive(path).iloc[0]["alert_id"] == row["alert_id"]
    flag_path = tmp_path / "data_archive" / "flags" / "2026-01-01.jsonl"
    flag_record = json.loads(flag_path.read_text(encoding="utf-8").splitlines()[0])
    assert flag_record["ticker"] == "PLAYUSDT"
    assert flag_record["reason_tags"] == ["high_scanner_score", "controlled_float", "short-account_skew", "short_account_pressure"]
    assert flag_record["terminal_edge_score"] == 77.7
    assert flag_record["terminal_structure_edge_score"] == 81.2
    assert flag_record["archetype_best_match"] == "LAB-style venue-inventory stress"
    assert flag_record["early_pump_radar_score"] == 89.0
    assert flag_record["early_pump_state"] == "Prime early squeeze"
    assert flag_record["early_pump_confirmed_target_flow"] is True
    assert flag_record["cex_deposit_flow_score"] == 88.0
    assert flag_record["cex_deposit_flow_source"] == "token_transfer_api"
    assert flag_record["cex_deposit_24h_target_exchanges"] == "Bitget"
    assert flag_record["cex_deposit_inventory_stress_score"] == 71.0
    assert "venue-inventory stress" in flag_record["cex_deposit_inventory_stress_note"]
    assert flag_record["terminal_liquidity_reality"] == "cap-table supply; exits can gap"
    assert flag_record["timing_score"] == 66.6
    assert flag_record["timing_inventory_response_score"] == 70.0
    assert flag_record["timing_state"] == "Triggering"
    assert flag_record["disclaimer"] == "research_tooling_only"


def test_refresh_outcomes_and_weekly_scoreboard(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_PROOF_ARCHIVE_ROOT", str(tmp_path / "data_archive"))
    path = tmp_path / "archive.csv"
    rows = pd.DataFrame(
        [{"symbol": "PLAYUSDT", "last_price": 1.0, "trade_bucket_score": 90, "trade_bucket_note": "test"}]
    )
    archive_alerts(rows, scan_mode="Deep", path=path, flagged_at_utc="2026-01-01T00:00:00Z")
    client = FakeKlineClient(
        [
            _kline("2026-01-01T00:30:00Z", 1.25, 0.96),
            _kline("2026-01-01T02:00:00Z", 1.60, 0.90),
            _kline("2026-01-01T10:00:00Z", 2.10, 0.88),
        ]
    )

    archive = refresh_outcomes(path=path, client=client, now=pd.Timestamp("2026-01-02T00:00:00Z"))
    row = archive.iloc[0]

    assert float(row["max_upside_1h_pct"]) == 25.0
    assert float(row["max_upside_24h_pct"]) == 110.0
    assert float(row["max_drawdown_pct"]) == -12.0
    assert float(row["time_to_20pct_minutes"]) == 30.0
    assert float(row["time_to_50pct_minutes"]) == 120.0
    assert float(row["time_to_2x_minutes"]) == 600.0
    outcome_path = tmp_path / "data_archive" / "outcomes" / "2026-01-01_outcomes.jsonl"
    assert "calculated_at_utc" in json.loads(outcome_path.read_text(encoding="utf-8").splitlines()[0])
    scoreboard = weekly_scoreboard_text(path, now=pd.Timestamp("2026-01-02T00:00:00Z"))
    assert "Total archived flags: 1" in scoreboard
    assert "Hit rate to +20%: 100.0%" in scoreboard
    assert "Best outlier: PLAYUSDT (110.0%)" in scoreboard
    md_path, csv_path = write_weekly_report(path, now=pd.Timestamp("2026-01-02T00:00:00Z"))
    assert md_path is not None and md_path.exists()
    assert csv_path is not None and csv_path.exists()
