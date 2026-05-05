from __future__ import annotations

from .models import ContractControlStats, HolderRecord, TokenMarketData, TokenScanResult
from .scanner import TokenConcentrationScanner


def _holders(percentages: list[float], labels: list[str] | None = None, *, supply: float = 1_000_000_000) -> list[HolderRecord]:
    labels = labels or []
    rows: list[HolderRecord] = []
    for index, pct in enumerate(percentages, start=1):
        label = labels[index - 1] if index <= len(labels) else ""
        balance = supply * pct / 100.0
        rows.append(
            HolderRecord(
                rank=index,
                address=f"0x{index:040x}",
                label=label,
                balance_decimal=balance,
                pct_total_supply=pct,
                is_contract=bool("proxy" in label.lower() or "protocol" in label.lower()),
            )
        )
    return rows


def ravedao_fixture() -> TokenScanResult:
    scanner = TokenConcentrationScanner()
    percentages = [79.2336, 8.0, 4.0, 2.5, 2.2464, 0.5, 0.4, 0.3, 0.28, 0.25]
    percentages += [0.0227] * 90
    market = TokenMarketData(
        coin_id="ravedao",
        name="RaveDAO",
        symbol="RAVE",
        current_price=1.5,
        market_cap=300_000_000,
        fully_diluted_valuation=350_000_000,
        circulating_supply=990_000_000,
        total_supply=1_000_000_000,
        volume_24h=20_000_000,
        price_change_30d=-80,
        all_time_low_price=0.2063,
        all_time_high_price=27.88,
        peak_market_cap=6_000_000_000,
    )
    return scanner.build_result(market=market, chain="ethereum", contract="0xrave", holders=_holders(percentages), contract_control=ContractControlStats(contract_verified=True))


def lab_fixture() -> TokenScanResult:
    scanner = TokenConcentrationScanner()
    percentages = [26.4114, 20, 15, 13.8, 10.8, 9.36]
    percentages += [0.0528] * 94
    labels = ["Bitget"] + [""] * 99
    market = TokenMarketData(
        coin_id="lab",
        name="LAB-like Token",
        symbol="LAB",
        current_price=1.788,
        market_cap=136_886_131,
        fully_diluted_valuation=1_788_283_562,
        circulating_supply=76_546_099,
        total_supply=1_000_000_000,
        volume_24h=290_824_303,
        price_change_30d=800,
    )
    return scanner.build_result(market=market, chain="bsc", contract="0xlab", holders=_holders(percentages, labels))


def bio_fixture() -> TokenScanResult:
    scanner = TokenConcentrationScanner()
    percentages = [34.7538, 11.0092, 9.1651, 5.1684, 3.6345, 3.2, 2.9, 1.9, 1.3, 1.1784]
    labels = [
        "",
        "Bio Protocol Gnosis Safe Proxy",
        "Binance",
        "",
        "",
        "Bio Protocol Treasury",
        "Bio Protocol Vesting",
        "Binance 2",
        "Bio Protocol Vault",
        "Bio Protocol Voting",
    ]
    market = TokenMarketData(
        coin_id="bio-protocol",
        name="Bio Protocol",
        symbol="BIO",
        current_price=0.2,
        market_cap=300_000_000,
        fully_diluted_valuation=1_000_000_000,
        circulating_supply=1_500_000_000,
        total_supply=3_000_000_000,
        volume_24h=100_000_000,
    )
    return scanner.build_result(market=market, chain="ethereum", contract="0xbio", holders=_holders(percentages, labels, supply=3_000_000_000))


def kava_wrapped_fixture() -> TokenScanResult:
    scanner = TokenConcentrationScanner()
    percentages = [37.1, 32.0, 12.0, 8.0, 5.0] + [0.06] * 95
    labels = ["Binance", "Binance 2", "", "", ""]
    market = TokenMarketData(
        coin_id="kava",
        name="Kava",
        symbol="KAVA",
        current_price=0.5,
        market_cap=500_000_000,
        circulating_supply=1_000_000_000,
        total_supply=1_000_000_000,
        volume_24h=20_000_000,
        canonical_chain="kava",
        is_native_asset=True,
    )
    return scanner.build_result(market=market, chain="bsc", contract="0xwrappedkava", holders=_holders(percentages, labels))


def tag_reserve_safe_fixture() -> TokenScanResult:
    scanner = TokenConcentrationScanner()
    percentages = [73.15, 4.0, 0.5, 0.25, 0.2] + [0.05] * 95
    labels = ["TAG Reserve Safe", "Bitget", "Gate", "", ""]
    market = TokenMarketData(
        coin_id="tag-like",
        name="TAG-like Reserve Token",
        symbol="TAG",
        current_price=0.08,
        market_cap=8_000_000,
        fully_diluted_valuation=80_000_000,
        circulating_supply=100_000_000,
        total_supply=1_000_000_000,
        volume_24h=2_000_000,
    )
    return scanner.build_result(market=market, chain="ethereum", contract="0xtag", holders=_holders(percentages, labels))


def clean_manipulable_whale_fixture() -> TokenScanResult:
    scanner = TokenConcentrationScanner()
    holders = [
        HolderRecord(
            rank=1,
            address="0x00000000000000000000000000000000000000a1",
            balance_decimal=580_000_000,
            pct_total_supply=58.0,
            gas_funder="0xdeployerfund",
            token_source="0xdeployer",
            funding_source="deployer funded fresh purpose-built wallet; sent 5% supply to MEXC CEX deposit after pump",
            net_balance_change_7d=-50_000_000,
        ),
        HolderRecord(
            rank=2,
            address="0x00000000000000000000000000000000000000a2",
            balance_decimal=100_000_000,
            pct_total_supply=10.0,
            gas_funder="0xdeployerfund",
            token_source="0xdeployer",
            funding_source="same gas funder as deployer",
        ),
        HolderRecord(rank=3, address="0x00000000000000000000000000000000000000a3", label="Uniswap LP", balance_decimal=80_000_000, pct_total_supply=8.0, is_contract=True),
        HolderRecord(rank=4, address="0x00000000000000000000000000000000000000a4", label="Binance", balance_decimal=50_000_000, pct_total_supply=5.0),
    ]
    holders.extend(HolderRecord(rank=index, address=f"0x{index:040x}", balance_decimal=500_000, pct_total_supply=0.05) for index in range(5, 101))
    market = TokenMarketData(
        coin_id="clean-whale",
        name="Clean Manipulable Whale",
        symbol="WHALE",
        current_price=1.0,
        market_cap=1_000_000_000,
        fully_diluted_valuation=1_000_000_000,
        circulating_supply=1_000_000_000,
        total_supply=1_000_000_000,
        volume_24h=1_500_000_000,
        price_change_30d=2_000,
        all_time_low_price=0.05,
        all_time_high_price=1.2,
        peak_market_cap=1_200_000_000,
    )
    return scanner.build_result(market=market, chain="ethereum", contract="0xwhale", holders=holders)


def binance_false_positive_fixture() -> TokenScanResult:
    scanner = TokenConcentrationScanner()
    percentages = [45, 10, 7, 5, 3] + [0.1] * 95
    labels = ["Binance Hot Wallet", "Binance Cold Wallet", "Gate", "MEXC", ""]
    market = TokenMarketData(
        coin_id="binance-false-positive",
        name="Binance Custody Heavy",
        symbol="BCHV",
        current_price=0.4,
        market_cap=40_000_000,
        fully_diluted_valuation=100_000_000,
        circulating_supply=100_000_000,
        total_supply=250_000_000,
        volume_24h=8_000_000,
    )
    return scanner.build_result(market=market, chain="bsc", contract="0xbchv", holders=_holders(percentages, labels, supply=250_000_000))


def acceptance_fixture_results() -> list[TokenScanResult]:
    return [
        ravedao_fixture(),
        lab_fixture(),
        bio_fixture(),
        kava_wrapped_fixture(),
        tag_reserve_safe_fixture(),
        clean_manipulable_whale_fixture(),
        binance_false_positive_fixture(),
    ]
