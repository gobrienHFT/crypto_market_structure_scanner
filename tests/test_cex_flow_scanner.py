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


def test_enrich_cex_deposit_flows_adds_columns_when_disabled() -> None:
    frame = pd.DataFrame([{"symbol": "PLAYUSDT"}])

    output = cex.enrich_cex_deposit_flows(frame, enabled=False)

    for column in cex.CEX_DEPOSIT_FLOW_COLUMNS:
        assert column in output.columns
