from types import SimpleNamespace

import pandas as pd

import app


def _fake_result() -> SimpleNamespace:
    return SimpleNamespace(
        holders=[object()] * 10,
        concentration=SimpleNamespace(
            raw_top_10_pct=88.0,
            raw_top_100_pct=99.0,
            adjusted_top_10_pct=81.0,
        ),
        master_score=SimpleNamespace(controlled_float_squeeze_score=84.0),
        thin_float=SimpleNamespace(squeeze_proxy_score=76.0),
        scores=SimpleNamespace(
            ravedao_archetype_score=79.0,
            protocol_storage_score=12.0,
        ),
        manipulable=SimpleNamespace(cex_storage_supply_pct=4.0),
        representation=SimpleNamespace(
            holder_table_not_global_supply=False,
            wrapped_representation_warning=False,
        ),
        status=SimpleNamespace(scanner_status="complete", scanner_error=""),
    )


def test_structural_refresh_is_bounded_persisted_and_updates_rows(monkeypatch, tmp_path) -> None:
    class FakeScanner:
        calls = 0

        def __init__(self, *, cache) -> None:
            self.cache = cache

        def scan(self, scanner_input):
            FakeScanner.calls += 1
            return _fake_result()

    monkeypatch.setattr(app, "TokenConcentrationScanner", FakeScanner)
    monkeypatch.setattr(app, "ScanCache", lambda path: path)
    monkeypatch.setattr(
        app,
        "resolve_contract_hint",
        lambda row, hints_path=None: SimpleNamespace(
            contract_address="0x0000000000000000000000000000000000000001",
            chain="ethereum",
        ),
    )
    monkeypatch.setattr(app, "SQUEEZE_RADAR_STRUCTURAL_EVIDENCE_PATH", tmp_path / "structure.csv")

    frame = pd.DataFrame(
        [
            {
                "symbol": "LABUSDT",
                "base_asset": "LAB",
                "squeeze_market_trigger": True,
                "squeeze_entry_ready": False,
                "squeeze_score": 82.0,
                "squeeze_market_confidence": 90.0,
                "squeeze_fuel_remaining_score": 80.0,
                "structural_evidence_level": "PROXY",
            },
            {
                "symbol": "OTHERUSDT",
                "base_asset": "OTHER",
                "squeeze_market_trigger": False,
                "squeeze_entry_ready": False,
                "squeeze_score": 40.0,
                "squeeze_market_confidence": 60.0,
                "squeeze_fuel_remaining_score": 50.0,
            },
        ]
    )

    updated, metadata = app._refresh_squeeze_structural_evidence(frame, max_symbols=1)

    assert FakeScanner.calls == 1
    assert metadata["attempted"] == 1
    assert metadata["verified"] == 1
    assert updated.loc[updated["symbol"] == "LABUSDT", "structural_evidence_level"].iloc[0] == "VERIFIED"
    assert float(updated.loc[updated["symbol"] == "LABUSDT", "top10_holder_pct"].iloc[0]) == 88.0
    assert bool(updated.loc[updated["symbol"] == "LABUSDT", "structural_storage_checked"].iloc[0])
    assert app.SQUEEZE_RADAR_STRUCTURAL_EVIDENCE_PATH.exists()
