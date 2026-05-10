from __future__ import annotations

import pandas as pd

from holder_composition import (
    HolderComposition,
    HolderRow,
    _parse_holder_rows_from_html,
    _read_tables_from_html,
    clean_contract_address,
    format_holder_composition_for_discord,
    load_contract_hints,
    resolve_contract_hint,
)


def test_resolve_contract_hint_uses_builtin_chip_contract() -> None:
    hint = resolve_contract_hint(pd.Series({"symbol": "CHIPUSDT", "base_asset": "CHIP"}))

    assert hint is not None
    assert hint.chain == "arbitrum"
    assert hint.contract_address == "0x0C1c1C109FE34733fca54b82d7B46B75CFb71F6e"


def test_contract_hint_loader_accepts_spreadsheet_safe_addresses(tmp_path) -> None:
    address = "0x0C1c1C109FE34733fca54b82d7B46B75CFb71F6e"
    path = tmp_path / "hints.csv"
    path.write_text(f'symbol,chain,contract_address\nCHIPUSDT,arbitrum,"=""{address}"""\n', encoding="utf-8")

    hints = load_contract_hints(path)

    assert hints["CHIPUSDT"].contract_address == address
    assert clean_contract_address(f'="{address}"') == address
    assert clean_contract_address(f"'{address}") == address
    assert clean_contract_address("6.91348E+46") == ""


def test_contract_hint_file_overrides_scan_row_contract_for_discord(tmp_path) -> None:
    address = "0x0C1c1C109FE34733fca54b82d7B46B75CFb71F6e"
    stale_address = "0x1111111111111111111111111111111111111111"
    path = tmp_path / "hints.csv"
    path.write_text(f"symbol,chain,contract_address\nCHIPUSDT,arbitrum,{address}\n", encoding="utf-8")

    hint = resolve_contract_hint(
        pd.Series({"symbol": "CHIPUSDT", "token_platform": "ethereum", "token_contract": stale_address}),
        hints_path=path,
    )

    assert hint is not None
    assert hint.chain == "arbitrum"
    assert hint.contract_address == address


def test_parse_explorer_holder_rows_computes_percent_from_supply_when_page_percent_is_zero() -> None:
    html = """
    <table><tbody>
    <tr><td>1</td><td>
      <a data-bs-toggle='tooltip' title='Wallet Alpha&#10;(0x1111111111111111111111111111111111111111)'>Wallet Alpha</a>
      <a data-clipboard-text='0x1111111111111111111111111111111111111111'></a>
    </td><td><span data-bs-toggle='tooltip' title='100'>100</span></td><td>0.0000%</td><td>$10</td></tr>
    <tr><td>2</td><td>
      <a data-clipboard-text='0x2222222222222222222222222222222222222222'></a>
    </td><td><span data-bs-toggle='tooltip' title='25'>25</span></td><td>0.0000%</td><td>$2.50</td></tr>
    </tbody></table>
    """

    rows = _parse_holder_rows_from_html(html, total_supply=200)

    assert len(rows) == 2
    assert rows[0].address == "0x1111111111111111111111111111111111111111"
    assert rows[0].label == "Wallet Alpha"
    assert rows[0].percent == 50.0
    assert rows[1].percent == 12.5


def test_read_explorer_tier_table_and_format_discord_summary() -> None:
    html = """
    <table>
      <tr><th>Tier</th><th>Holder Count</th><th>% Holders</th><th>% Market Cap</th></tr>
      <tr><td>Whale</td><td>2</td><td>0.1%</td><td>70.0%</td></tr>
      <tr><td>Shark</td><td>10</td><td>0.5%</td><td>20.0%</td></tr>
    </table>
    """
    tier_rows, cohort_rows = _read_tables_from_html(html)
    composition = HolderComposition(
        symbol="TESTUSDT",
        chain="ethereum",
        contract_address="0x3333333333333333333333333333333333333333",
        explorer_name="Etherscan",
        explorer_url="https://etherscan.io/token/0x3333333333333333333333333333333333333333",
        holder_count=1234,
        total_supply=1_000_000,
        tier_rows=tier_rows,
        cohort_rows=cohort_rows,
        top_holders=[
            HolderRow(1, "0x1111111111111111111111111111111111111111", 42.0, label="Wallet Alpha"),
            HolderRow(2, "0x2222222222222222222222222222222222222222", 18.0),
        ],
    )

    summary = format_holder_composition_for_discord(composition)

    assert "Top1 42.00%" in summary
    assert "Top2 60.00%" in summary
    assert "holders 1,234" in summary
    assert "Tiers: Whale 70.0% | Shark 20.0%" in summary
    assert "Wallet Alpha" in summary
