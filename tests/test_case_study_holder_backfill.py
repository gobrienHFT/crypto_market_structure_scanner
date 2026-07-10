from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from case_study_holder_backfill import build_case_study_holder_backfill, write_case_study_holder_backfill


def test_holder_backfill_uses_contract_hints_and_scanner_rows(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    pd.DataFrame(
        [
            {"symbol": "RAVEUSDT", "chain": "ethereum", "contract_address": "0x123"},
        ]
    ).to_csv(tmp_path / "data" / "discord_holder_contracts.csv", index=False)

    class FakeScanner:
        def scan(self, scanner_input):
            assert scanner_input.symbol == "RAVEUSDT"
            assert scanner_input.chain == "ethereum"
            assert scanner_input.contract_address == "0x123"
            return SimpleNamespace(
                token=SimpleNamespace(
                    name="RAVE",
                    symbol="RAVEUSDT",
                    current_price=None,
                    market_cap=None,
                    fully_diluted_valuation=None,
                    volume_24h=None,
                    price_change_24h=None,
                    price_change_7d=None,
                    price_change_30d=None,
                    all_time_low_price=None,
                    all_time_high_price=None,
                ),
                chain="ethereum",
                contract_address="0x123",
                holders=[],
                concentration=SimpleNamespace(
                    raw_top_1_pct=20.0,
                    raw_top_5_pct=60.0,
                    raw_top_10_pct=82.0,
                    raw_top_100_pct=99.0,
                    adjusted_top_1_pct=18.0,
                    adjusted_top_5_pct=55.0,
                    adjusted_top_10_pct=76.0,
                    largest_unexplained_holder_pct=12.0,
                    excluded_supply_pct=0.0,
                    concentration_gini=0.0,
                    holder_hhi_index=0.0,
                    whale_concentration_pct=0.0,
                ),
                contract_control=SimpleNamespace(),
                representation=SimpleNamespace(wrapped_representation_warning=False, holder_table_not_global_supply=False),
                manipulable=SimpleNamespace(
                    largest_manipulable_holder_pct=11.0,
                    largest_manipulable_holder_address="0xwhale",
                    largest_manipulable_holder_category="whale",
                    largest_manipulable_holder_score=80.0,
                    filtered_top_5_manipulable_pct=50.0,
                    filtered_top_10_manipulable_pct=70.0,
                    cluster_manipulable_supply_pct=0.0,
                    cluster_confidence="",
                    cex_storage_supply_pct=0.0,
                    treasury_storage_supply_pct=0.0,
                    vesting_lockup_supply_pct=0.0,
                    key_forensic_flags=[],
                ),
                wallet_forensics=[],
                wallet_clusters=[],
                thin_float=SimpleNamespace(
                    ath_multiple_from_atl=None,
                    current_drawdown_from_ath_pct=None,
                    current_market_cap=None,
                    peak_market_cap=None,
                    current_fdv=None,
                    peak_fdv=None,
                    circulating_to_total_supply_pct=None,
                    estimated_non_top100_float_pct=None,
                    estimated_non_top10_float_pct=None,
                    peak_value_of_non_top100_float=None,
                    top_1_wallet_peak_value=None,
                    top_5_wallet_peak_value=None,
                ),
                scores=SimpleNamespace(
                    ravedao_archetype_score=0.0,
                    manipulable_whale_score=0.0,
                    custody_concentration_score=0.0,
                    protocol_storage_score=0.0,
                    supply_overhang_score=0.0,
                    adjusted_score_after_custody_filter=0.0,
                    composite_structural_manipulation_risk_score=91.0,
                    risk_label="High",
                    confidence="medium",
                ),
                flags=SimpleNamespace(),
                status=SimpleNamespace(scanner_status="complete", scanner_error=""),
                summary="holder scan ok",
                key_flags=["controlled_float"],
                perp_context=SimpleNamespace(
                    binance_symbol="RAVEUSDT",
                    perp_volume_24h=None,
                    spot_volume_24h=None,
                    futures_to_spot_volume_ratio=None,
                    open_interest_notional=None,
                    oi_to_market_cap_ratio=None,
                    oi_to_adjusted_float_market_cap_ratio=None,
                    volume_to_adjusted_float_market_cap=None,
                ),
                master_score=SimpleNamespace(
                    master_score=88.0,
                    pre_pump_risk_score=0.0,
                    controlled_float_squeeze_score=0.0,
                    insider_whale_concentration_score=0.0,
                    master_label="High",
                    ranked_reasons=["controlled float"],
                ),
            )

    frame = build_case_study_holder_backfill(root=tmp_path, symbols=("RAVEUSDT",), scanner=FakeScanner())
    row = frame.iloc[0]

    assert row["backfill_status"] == "complete"
    assert bool(row["holder_data_usable"])
    assert row["raw_top_10_pct"] == 82.0
    assert row["filtered_top_10_manipulable_pct"] == 70.0
    assert row["risk_score"] == 91.0


def test_holder_backfill_records_scanner_errors(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    pd.DataFrame(
        [
            {"symbol": "LABUSDT", "chain": "bsc", "contract_address": "0x456"},
        ]
    ).to_csv(tmp_path / "data" / "discord_holder_contracts.csv", index=False)

    class FailingScanner:
        def scan(self, scanner_input):
            raise RuntimeError("explorer blocked")

    frame = build_case_study_holder_backfill(root=tmp_path, symbols=("LABUSDT",), scanner=FailingScanner())

    assert frame.iloc[0]["backfill_status"] == "error"
    assert not bool(frame.iloc[0]["holder_data_usable"])
    assert frame.iloc[0]["holder_failure_mode"] == "explorer blocked"
    assert "explorer blocked" in frame.iloc[0]["scanner_error"]


def test_holder_backfill_classifies_notok_as_unusable_endpoint() -> None:
    from case_study_holder_backfill import _normalise_result_row

    row = _normalise_result_row(
        "RAVEUSDT",
        "ethereum",
        "0x123",
        {
            "scanner_error": "NOTOK; NOTOK",
            "raw_top_10_pct": 0.0,
        },
    )

    assert row["backfill_status"] == "partial"
    assert row["holder_data_usable"] is False
    assert row["holder_failure_mode"] == "explorer holder endpoint unavailable/not entitled"
    assert "alternate indexer" in row["holder_next_route"]


def test_write_holder_backfill_creates_markdown(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    pd.DataFrame(
        [
            {"symbol": "MISSINGUSDT", "chain": "", "contract_address": ""},
        ]
    ).to_csv(tmp_path / "data" / "discord_holder_contracts.csv", index=False)

    output_path = tmp_path / "docs" / "holder.md"
    frame = write_case_study_holder_backfill(root=tmp_path, output_path=output_path, scanner=object())

    assert output_path.exists()
    assert "Case-Study Holder Backfill" in output_path.read_text(encoding="utf-8")
    assert set(frame["backfill_status"]) == {"missing_contract"}
