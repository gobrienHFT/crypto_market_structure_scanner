from __future__ import annotations

import pandas as pd

import cex_flow_scanner as cex
from holder_composition import HolderComposition, HolderRow


def _composition(*, top10_pct: float = 91.0, top100_pct: float = 99.0) -> HolderComposition:
    top_rows = [HolderRow(rank=1, address="0x1111111111111111111111111111111111111111", percent=top10_pct)]
    for rank in range(2, 11):
        top_rows.append(
            HolderRow(rank=rank, address=f"0x{rank:040x}", percent=0.0)
        )
    if top100_pct > top10_pct:
        top_rows.append(
            HolderRow(rank=11, address="0x2222222222222222222222222222222222222222", percent=top100_pct - top10_pct)
        )
    return HolderComposition(
        symbol="PLAYUSDT",
        chain="base",
        contract_address="0x853a7c99227499dba9db8c3a02aa691afdebf841",
        explorer_name="BaseScan",
        total_supply=1_000_000_000,
        top_holders=top_rows,
    )


class _Response:
    status_code = 200
    text = """
    <table>
      <thead>
        <tr><th>Transaction Hash</th><th>Age</th><th>From</th><th>To</th><th>Amount</th><th>Asset</th></tr>
      </thead>
      <tbody>
        <tr><td>0xaaa</td><td>3 hrs ago</td><td>0xabc</td><td>Bitget Deposit</td><td>1,200,000</td><td>PLAY</td></tr>
        <tr><td>0xbbb</td><td>2 days ago</td><td>0xdef</td><td>Binance 14</td><td>2,000,000</td><td>PLAY</td></tr>
        <tr><td>0xccc</td><td>4 hrs ago</td><td>Kraken 246</td><td>0xghi</td><td>1,000,000</td><td>PLAY</td></tr>
      </tbody>
    </table>
    """


def test_scan_cex_deposit_flow_scores_only_recent_deposits_after_concentration_gate(monkeypatch) -> None:
    monkeypatch.setattr(cex, "fetch_holder_composition", lambda *args, **kwargs: _composition())
    monkeypatch.setattr(cex.requests, "get", lambda *args, **kwargs: _Response())

    result = cex.scan_cex_deposit_flow(
        {
            "symbol": "PLAYUSDT",
            "token_platform": "base",
            "token_contract": "0x853a7c99227499dba9db8c3a02aa691afdebf841",
        }
    )

    assert result["cex_deposit_flow_flag"] is True
    assert result["cex_deposit_flow_score"] > 0
    assert result["cex_deposit_24h_count"] == 1
    assert result["cex_deposit_24h_target_exchanges"] == "Bitget"
    assert result["cex_deposit_24h_token_amount"] == 1_200_000
    assert "top10 91.0%" in result["cex_deposit_concentration_gate"]
    assert "basescan.org/advanced-filter" in result["cex_deposit_24h_source_url"]
    assert result["cex_deposit_flow_risk_level"] in {"Elevated", "High", "Extreme"}
    assert "wallet-to-CEX flow" in result["cex_deposit_flow_evidence_summary"]
    assert "not a conclusion about intent" in result["cex_deposit_flow_interpretation"]
    assert "OI/volume" in result["cex_deposit_flow_next_check"]
    assert "PLAYUSDT | flow" in result["cex_deposit_flow_alert_line"]
    assert "crime" not in result["cex_deposit_flow_evidence_summary"].lower()
    assert "scam" not in result["cex_deposit_flow_evidence_summary"].lower()


def test_scan_cex_deposit_flow_does_not_fetch_when_concentration_gate_fails(monkeypatch) -> None:
    monkeypatch.setattr(cex, "fetch_holder_composition", lambda *args, **kwargs: _composition(top10_pct=20.0, top100_pct=45.0))

    def _no_http(*args, **kwargs):  # pragma: no cover - this should never run
        raise AssertionError("advanced filter should not be fetched without concentration")

    monkeypatch.setattr(cex.requests, "get", _no_http)

    result = cex.scan_cex_deposit_flow(
        {
            "symbol": "PLAYUSDT",
            "token_platform": "base",
            "token_contract": "0x853a7c99227499dba9db8c3a02aa691afdebf841",
        }
    )

    assert result["cex_deposit_flow_flag"] is False
    assert result["cex_deposit_flow_score"] == 0.0
    assert "concentration gate not met" in result["cex_deposit_flow_note"]
    assert result["cex_deposit_flow_risk_level"] == "Watch only"
    assert "no large labelled CEX transfer flow" in result["cex_deposit_flow_evidence_summary"]


def test_build_cex_flow_discord_block_has_shared_product_language() -> None:
    row = {
        "symbol": "PLAYUSDT",
        "cex_deposit_flow_score": 88,
        "cex_deposit_flow_risk_level": "High",
        "cex_deposit_24h_count": 3,
        "cex_deposit_24h_token_amount": 2_500_000,
        "cex_deposit_24h_max_amount": 1_200_000,
        "cex_deposit_24h_total_pct_supply": 2.5,
        "cex_deposit_24h_max_pct_supply": 1.2,
        "cex_deposit_24h_target_exchanges": "Bitget, Gate",
        "cex_deposit_concentration_gate": "top10 91.0% / top100 99.0%",
        "cex_deposit_24h_source_url": "https://basescan.org/advanced-filter?tkn=0xabc",
    }

    output = cex.build_cex_flow_discord_block(row, max_chars=900)

    assert "/PLAYUSDT" in output
    assert "CEX Flow Score: 88/100 | Risk: High" in output
    assert "Evidence:" in output
    assert "Venue-flow read:" in output
    assert "Next check:" in output
    assert "Source: https://basescan.org/advanced-filter?tkn=0xabc" in output
    assert "pump call" not in output.lower()
    assert len(output) <= 900


def test_enrich_cex_deposit_flows_adds_columns_when_disabled() -> None:
    frame = pd.DataFrame([{"symbol": "PLAYUSDT"}])

    output = cex.enrich_cex_deposit_flows(frame, enabled=False)

    for column in cex.CEX_DEPOSIT_FLOW_COLUMNS:
        assert column in output.columns


def test_build_advanced_filter_url_supports_basescan_example() -> None:
    url = cex.build_advanced_filter_url(
        "base",
        "0x853a7c99227499dba9db8c3a02aa691afdebf841",
        min_amount=500_000,
    )

    assert url.startswith("https://basescan.org/advanced-filter?")
    assert "tkn=0x853a7c99227499dba9db8c3a02aa691afdebf841" in url
    assert "txntype=2" in url
    assert "amt=500000~999999999999" in url


def test_enrich_cex_deposit_flows_with_zero_limit_scans_all_contract_rows(monkeypatch) -> None:
    calls: list[str] = []

    def fake_scan(row, **_kwargs):
        calls.append(str(row["symbol"]))
        result = cex._default_result()
        result.update({"cex_deposit_flow_score": 1.0, "cex_deposit_flow_flag": True})
        return result

    monkeypatch.setattr(cex, "scan_cex_deposit_flow", fake_scan)
    frame = pd.DataFrame(
        [
            {
                "symbol": "PLAYUSDT",
                "token_platform": "base",
                "token_contract": "0x853a7c99227499dba9db8c3a02aa691afdebf841",
            },
            {
                "symbol": "LABUSDT",
                "token_platform": "bsc",
                "token_contract": "0x7ec43cf65f1663f820427c62a5780b8f2e25593a",
            },
        ]
    )

    output = cex.enrich_cex_deposit_flows(frame, max_symbols=0)

    assert set(calls) == {"PLAYUSDT", "LABUSDT"}
    assert output["cex_deposit_flow_flag"].astype(bool).all()
