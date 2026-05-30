from __future__ import annotations

from concentration_scanner.chains import ChainRegistry
from concentration_scanner.classifier import HolderClassifier, ManualOverride
from concentration_scanner.clients import ExplorerClient
from concentration_scanner.concentration import ConcentrationEngine
from concentration_scanner.fixtures import (
    binance_false_positive_fixture,
    bio_fixture,
    clean_manipulable_whale_fixture,
    kava_wrapped_fixture,
    lab_fixture,
    ravedao_fixture,
    tag_reserve_safe_fixture,
)
from concentration_scanner.models import HolderRecord, TokenMarketData
from concentration_scanner.perp_universe import BinancePerpUniverseBuilder, SeedContract, base_symbol_candidates, load_seed_addresses
from concentration_scanner.presentation import results_to_frame
from concentration_scanner.scanner import TokenConcentrationScanner
from binance_futures import FuturesSymbol


def test_chain_adapter_selection() -> None:
    registry = ChainRegistry()
    assert registry.get("eth").name == "Ethereum"
    assert registry.get("BNB Chain").explorer_name == "BscScan"
    assert registry.get("arb").explorer_name == "Arbiscan"
    assert registry.get("arbscan").explorer_name == "Arbiscan"
    assert registry.platform_to_chain("binance-smart-chain") == "bsc"
    assert registry.platform_to_chain("arbitrum-one") == "arbitrum"


def test_explorer_client_uses_etherscan_family_api_key_fallbacks(monkeypatch) -> None:
    for env_name in ("ETHERSCAN_API_KEY", "ETHERSCAN_V2_API_KEY", "BSCSCAN_API_KEY", "ARBISCAN_API_KEY", "ARBSCAN_API_KEY"):
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setenv("ARBSCAN_API_KEY", "arbscan-alias-key")

    client = ExplorerClient(ChainRegistry().get("arbitrum"))

    assert client.api_key == "arbscan-alias-key"


def test_coingecko_contract_resolution_from_platforms() -> None:
    class FakeCoinGecko:
        def fetch_coin(self, coin_id: str) -> dict:
            return {"id": coin_id, "name": "API3", "symbol": "api3", "platforms": {"ethereum": "0xapi3"}}

        def parse_market_data(self, raw: dict) -> TokenMarketData:
            return TokenMarketData(
                coin_id=raw["id"],
                name=raw["name"],
                symbol=raw["symbol"].upper(),
                platforms=raw["platforms"],
            )

    scanner = TokenConcentrationScanner(coingecko=FakeCoinGecko())  # type: ignore[arg-type]
    market, chain, contract = scanner.resolve_contract(scanner_input=__import__("concentration_scanner").ScannerInput(coin_id="api3", chain="ethereum"))
    assert market.coin_id == "api3"
    assert chain == "ethereum"
    assert contract == "0xapi3"


def test_coingecko_contract_resolution_supports_arbitrum() -> None:
    class FakeCoinGecko:
        def fetch_coin(self, coin_id: str) -> dict:
            return {"id": coin_id, "name": "Arb Token", "symbol": "arbx", "platforms": {"arbitrum-one": "0xarb"}}

        def parse_market_data(self, raw: dict) -> TokenMarketData:
            return TokenMarketData(
                coin_id=raw["id"],
                name=raw["name"],
                symbol=raw["symbol"].upper(),
                platforms=raw["platforms"],
            )

    scanner = TokenConcentrationScanner(coingecko=FakeCoinGecko())  # type: ignore[arg-type]
    market, chain, contract = scanner.resolve_contract(scanner_input=__import__("concentration_scanner").ScannerInput(coin_id="arb-token", chain=""))
    assert market.coin_id == "arb-token"
    assert chain == "arbitrum"
    assert contract == "0xarb"


def test_holder_classification_exchange_bitget_burn_round_and_unexplained() -> None:
    classifier = HolderClassifier(token_name="Bio Protocol", token_symbol="BIO")
    holders = classifier.classify_all(
        [
            HolderRecord(rank=1, address="0x1", label="Bitget", balance_decimal=264_114_000, pct_total_supply=26.4114),
            HolderRecord(rank=2, address="0x000000000000000000000000000000000000dead", balance_decimal=1, pct_total_supply=0.1),
            HolderRecord(rank=3, address="0x3", label="", balance_decimal=100_000_000, pct_total_supply=10),
            HolderRecord(rank=4, address="0x4", label="Bio Protocol Gnosis Safe Proxy", balance_decimal=11_009_200, pct_total_supply=11.0092, is_contract=True),
        ]
    )
    assert holders[0].holder_category == "exchange"
    assert holders[0].is_exchange_inventory
    assert holders[0].is_round_allocation
    assert holders[1].holder_category == "burn"
    assert holders[2].holder_category == "unexplained_whale"
    assert holders[3].holder_category == "dao_multisig"


def test_adjusted_float_recomputes_after_manual_override() -> None:
    classifier = HolderClassifier()
    holders = classifier.classify_all(
        [
            HolderRecord(rank=1, address="0x1", label="", balance_decimal=50, pct_total_supply=50),
            HolderRecord(rank=2, address="0x2", label="Binance", balance_decimal=25, pct_total_supply=25),
            HolderRecord(rank=3, address="0x3", label="", balance_decimal=25, pct_total_supply=25),
        ]
    )
    engine = ConcentrationEngine()
    before = engine.compute(holders, total_supply=100)
    overridden = classifier.classify_all(
        [HolderRecord(rank=1, address="0x1", label="", balance_decimal=50, pct_total_supply=50)],
        overrides=[ManualOverride(address="0x1", holder_category="vesting", excluded_from_adjusted_float=True)],
    )
    after = engine.compute([overridden[0], *holders[1:]], total_supply=100)
    assert before.adjusted_float_supply == 75
    assert after.adjusted_float_supply == 25
    assert after.adjusted_top_1_pct == 100


def test_ravedao_acceptance_case_scores_extreme_and_uses_structural_language() -> None:
    result = ravedao_fixture()
    assert result.flags.dominant_holder_warning
    assert result.flags.extreme_dominant_holder
    assert result.flags.nuclear_dominant_holder
    assert result.flags.unresolved_dominant_holder
    assert result.flags.cap_table_token
    assert result.flags.one_wallet_market
    assert result.flags.ravedao_archetype
    assert result.flags.extreme_ravedao_archetype
    assert result.flags.one_wallet_mark_to_market
    assert result.flags.cap_table_marked_to_market
    assert result.flags.billion_dollar_thin_float_print
    assert result.flags.collapsed_after_concentrated_pump
    assert result.flags.unresolved_dominant_holder_after_pump
    assert result.flags.fake_headline_market_cap_risk
    assert result.scores.ravedao_archetype_score == 100
    assert result.scores.risk_label == "Extreme"
    assert "This does not prove manipulation" in result.summary


def test_lab_acceptance_case_controlled_float_squeeze() -> None:
    result = lab_fixture()
    assert result.flags.low_float
    assert result.flags.bitget_rank_1_inventory_dominance
    assert result.flags.controlled_float_squeeze_structure
    assert result.flags.extreme_controlled_float_squeeze_structure
    assert result.scores.risk_label == "Extreme"


def test_bio_acceptance_case_high_structural_risk() -> None:
    result = bio_fixture()
    assert result.flags.dominant_unexplained_holder
    assert result.concentration.largest_unexplained_holder_pct > 30
    assert result.flags.protocol_multisig_concentration
    assert result.flags.exchange_inventory_dominance
    assert result.scores.risk_label in {"High", "Extreme"}
    assert result.scores.confidence in {"low", "medium"}


def test_kava_wrapped_acceptance_case_guardrail() -> None:
    result = kava_wrapped_fixture()
    assert result.representation.wrapper_concentration_score == 100
    assert result.representation.global_concentration_score == 0
    assert result.representation.representation_confidence == "low"
    assert result.representation.wrapped_representation_warning
    assert result.representation.holder_table_not_global_supply
    assert result.representation.native_chain_data_required
    assert result.scores.risk_label != "Extreme" or result.representation.false_positive_concentration_risk
    assert result.scores.manipulable_whale_score < 25
    assert result.manipulable.largest_manipulable_holder_pct == 0


def test_tag_like_reserve_safe_suppresses_anonymous_whale_score() -> None:
    result = tag_reserve_safe_fixture()
    top = result.holders[0]
    assert top.holder_category in {"treasury_reserve", "dao_multisig_reserve"}
    assert result.flags.top_holder_is_benign_storage
    assert result.scores.supply_overhang_score >= 75
    assert result.scores.manipulable_whale_score < 75
    assert result.manipulable.largest_manipulable_holder_pct < 10
    assert "custody/storage/reserve" in result.summary


def test_clean_manipulable_whale_ranks_extreme() -> None:
    result = clean_manipulable_whale_fixture()
    assert result.manipulable.largest_manipulable_holder_pct == 58.0
    assert result.scores.manipulable_whale_score == 100
    assert result.master_score.master_label == "Extreme"
    assert result.master_score.one_line_mission_match
    assert result.master_score.pre_pump_risk_score >= 75
    assert result.flags.deployer_funded_cluster
    assert result.flags.same_gas_funder_cluster
    assert result.flags.cex_distribution_cluster
    assert result.scores.distribution_risk_score >= 50
    assert result.manipulable.cluster_manipulable_supply_pct > 20


def test_binance_false_positive_is_filtered_from_manipulable_whales() -> None:
    result = binance_false_positive_fixture()
    assert result.concentration.raw_top_1_pct == 45
    assert result.manipulable.cex_storage_supply_pct > 50
    assert result.flags.cex_false_positive_risk
    assert result.flags.top_holder_is_benign_storage
    assert result.scores.manipulable_whale_score < 50
    assert result.manipulable.largest_manipulable_holder_pct <= 3
    assert not result.flags.dominant_unexplained_holder


def test_manipulable_whales_leaderboard_prioritizes_filtered_whales() -> None:
    frame = results_to_frame([tag_reserve_safe_fixture(), clean_manipulable_whale_fixture(), binance_false_positive_fixture(), kava_wrapped_fixture()])
    filtered = frame[~frame["wrapped_representation_warning"].fillna(False)]
    filtered = filtered.sort_values(
        ["largest_manipulable_holder_pct", "manipulable_whale_score", "cluster_manipulable_supply_pct"],
        ascending=[False, False, False],
    )
    assert filtered.iloc[0]["symbol"] == "WHALE"
    assert filtered.loc[filtered["symbol"] == "BCHV", "manipulable_whale_score"].iloc[0] < 50


def test_binance_perp_multiplier_symbol_candidates() -> None:
    assert base_symbol_candidates("1000PEPE") == ["1000PEPE", "PEPE"]
    assert "MOG" in base_symbol_candidates("1000000MOG")


def test_seed_address_loader_accepts_raw_comma_file(tmp_path) -> None:
    seed = tmp_path / "seed.txt"
    seed.write_text("0x1111111111111111111111111111111111111111, bad, 0x2222222222222222222222222222222222222222")
    assert load_seed_addresses(seed) == [
        "0x1111111111111111111111111111111111111111",
        "0x2222222222222222222222222222222222222222",
    ]


def test_binance_perp_universe_uses_seed_contracts_without_coingecko() -> None:
    class FakeBinance:
        def perpetual_usdt_symbols(self) -> list[FuturesSymbol]:
            return [
                FuturesSymbol(symbol="API3USDT", base_asset="API3", quote_asset="USDT", underlying_type="COIN"),
                FuturesSymbol(symbol="1000PEPEUSDT", base_asset="1000PEPE", quote_asset="USDT", underlying_type="COIN"),
            ]

        def ticker_24hr(self) -> list[dict]:
            return [
                {"symbol": "API3USDT", "lastPrice": "2", "quoteVolume": "1000", "priceChangePercent": "25"},
                {"symbol": "1000PEPEUSDT", "lastPrice": "0.001", "quoteVolume": "2000", "priceChangePercent": "80"},
            ]

        def open_interest(self, symbol: str) -> dict:
            return {"openInterest": "10"}

    class FakeSpot:
        def ticker_24hr(self) -> list[dict]:
            return [{"symbol": "API3USDT", "quoteVolume": "100"}]

    builder = BinancePerpUniverseBuilder(
        binance=FakeBinance(),  # type: ignore[arg-type]
        spot=FakeSpot(),  # type: ignore[arg-type]
        seed_contracts=[
            SeedContract(chain="ethereum", contract_address="0xapi3", token_symbol="API3", token_name="API3", total_supply=1_000),
            SeedContract(chain="bsc", contract_address="0xpepe", token_symbol="PEPE", token_name="Pepe", total_supply=1_000_000),
        ],
    )
    candidates = builder.build_candidates(enrich_open_interest_top_n=2)
    api3 = next(item for item in candidates if item.symbol == "API3USDT")
    pepe = next(item for item in candidates if item.symbol == "1000PEPEUSDT")
    assert api3.contract_address == "0xapi3"
    assert api3.coingecko_id == ""
    assert api3.futures_to_spot_volume_ratio == 10
    assert api3.market_cap == 2_000
    assert api3.context().current_price == 2
    assert pepe.contract_address == "0xpepe"


def test_generated_summaries_avoid_legal_accusatory_language() -> None:
    banned = ("confirmed fraud", "confirmed manipulation", "confirmed crime", "illegal", "scam")
    for result in (
        ravedao_fixture(),
        lab_fixture(),
        bio_fixture(),
        kava_wrapped_fixture(),
        tag_reserve_safe_fixture(),
        clean_manipulable_whale_fixture(),
        binance_false_positive_fixture(),
    ):
        lower = result.summary.lower()
        for phrase in banned:
            assert phrase not in lower


def test_risk_score_capped_at_100() -> None:
    assert ravedao_fixture().scores.ravedao_archetype_score == 100
