from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .cache import ScanCache
from .chains import ChainRegistry
from .classifier import HolderClassifier, ManualOverride
from .clients import CoinGeckoClient, ExplorerClient
from .concentration import ConcentrationEngine
from .models import (
    ContractControlStats,
    HolderRecord,
    ScannerStatus,
    TokenMarketData,
    TokenScanResult,
    utc_now_iso,
)
from .risk import RiskScoringEngine


@dataclass(frozen=True)
class ScannerInput:
    coin_id: str = ""
    symbol: str = ""
    contract_address: str = ""
    chain: str = "ethereum"
    category: str = ""
    mode: str = "manual"
    top_n: int = 100
    exclude_majors: bool = True
    exclude_stablecoins: bool = True
    exclude_wrapped_assets: bool = True


class TokenConcentrationScanner:
    def __init__(
        self,
        *,
        coingecko: CoinGeckoClient | None = None,
        registry: ChainRegistry | None = None,
        cache: ScanCache | None = None,
    ) -> None:
        self.coingecko = coingecko or CoinGeckoClient()
        self.registry = registry or ChainRegistry()
        self.cache = cache
        self.concentration = ConcentrationEngine()
        self.risk = RiskScoringEngine()

    def resolve_contract(self, scanner_input: ScannerInput) -> tuple[TokenMarketData, str, str]:
        chain = self.registry.normalize_key(scanner_input.chain)
        if scanner_input.coin_id:
            raw = self.coingecko.fetch_coin(scanner_input.coin_id)
            market = self.coingecko.parse_market_data(raw)
            if scanner_input.chain:
                adapter = self.registry.get(chain)
                contract = market.platforms.get(adapter.coingecko_platform, "")
            else:
                contract = ""
                for adapter in self.registry.supported():
                    contract = market.platforms.get(adapter.coingecko_platform, "")
                    if contract:
                        chain = adapter.key
                        break
            return market, chain, contract
        if scanner_input.contract_address:
            return (
                TokenMarketData(
                    coin_id=scanner_input.symbol.lower(),
                    name=scanner_input.symbol.upper() if scanner_input.symbol else scanner_input.contract_address[:10],
                    symbol=scanner_input.symbol.upper(),
                    platforms={self.registry.get(chain).coingecko_platform: scanner_input.contract_address},
                ),
                chain,
                scanner_input.contract_address,
            )
        if scanner_input.symbol:
            search = self.coingecko.search(scanner_input.symbol)
            coins = search.get("coins", []) if isinstance(search, dict) else []
            if coins:
                coin_id = str(coins[0].get("id", ""))
                return self.resolve_contract(ScannerInput(coin_id=coin_id, chain=chain))
        raise ValueError("Provide a CoinGecko coin ID, symbol, or contract address.")

    def scan(self, scanner_input: ScannerInput, *, overrides: list[ManualOverride] | None = None) -> TokenScanResult:
        market_fetch_at = utc_now_iso()
        market, chain, contract = self.resolve_contract(scanner_input)
        adapter = self.registry.get(chain)
        holder_fetch_at = utc_now_iso()
        explorer = ExplorerClient(adapter)
        holder_result = explorer.fetch_top_holders(contract, limit=max(100, scanner_input.top_n))
        holder_addresses = {holder.address for holder in holder_result.holders}
        contract_control = explorer.fetch_contract_control(contract, holder_addresses=holder_addresses) if contract else ContractControlStats()
        return self.build_result(
            market=market,
            chain=chain,
            contract=contract,
            holders=holder_result.holders,
            contract_control=contract_control,
            market_fetch_at=market_fetch_at,
            holder_fetch_at=holder_fetch_at,
            scanner_error=holder_result.error,
            partial=holder_result.partial,
            overrides=overrides,
        )

    def build_result(
        self,
        *,
        market: TokenMarketData,
        chain: str,
        contract: str,
        holders: list[HolderRecord],
        contract_control: ContractControlStats | None = None,
        market_fetch_at: str = "",
        holder_fetch_at: str = "",
        scanner_error: str = "",
        partial: bool = False,
        overrides: list[ManualOverride] | None = None,
    ) -> TokenScanResult:
        classifier = HolderClassifier(
            token_name=market.name,
            token_symbol=market.symbol,
            owner_address=(contract_control.owner_address if contract_control else ""),
            proxy_admin_address=(contract_control.proxy_admin_address if contract_control else ""),
            admin_addresses=set(contract_control.default_admin_role_holders if contract_control else []),
        )
        classified = classifier.classify_all(holders, overrides=overrides)
        classification_at = utc_now_iso()
        metrics = self.concentration.compute(
            classified,
            total_supply=market.total_supply,
            circulating_supply=market.circulating_supply,
        )
        if partial:
            metrics = metrics.__class__(**{**metrics.__dict__, "partial_result": True, "data_confidence": "low"})
        control = contract_control or ContractControlStats()
        thin = self.risk.compute_thin_float_stats(market, metrics)
        flags = self.risk.compute_flags(holders=classified, metrics=metrics, market=market, thin=thin)
        representation = self.risk.representation_guardrail(inspected_chain=chain, market=market, metrics=metrics)
        scores = self.risk.compute_scores(metrics=metrics, contract=control, thin=thin, flags=flags)
        key_flags = self.risk.key_flags(flags, representation)
        status = ScannerStatus(
            last_market_data_fetch_at=market_fetch_at,
            last_holder_fetch_at=holder_fetch_at,
            last_classification_at=classification_at,
            scanner_status="partial" if scanner_error or partial else "complete",
            scanner_error=scanner_error,
        )
        summary = self.risk.summary(flags=flags, representation=representation, token_name=market.name or market.symbol)
        result = TokenScanResult(
            token=market,
            chain=chain,
            contract_address=contract,
            holders=classified,
            concentration=metrics,
            contract_control=control,
            representation=representation,
            thin_float=thin,
            scores=scores,
            flags=flags,
            status=status,
            summary=summary,
            key_flags=key_flags,
        )
        if self.cache is not None:
            self.cache.upsert_result(result)
        return result

    def prioritized_universe(self, *, category: str = "", limit: int = 100) -> list[dict[str, Any]]:
        rows = self.coingecko.markets(category=category or None, order="volume_desc", per_page=min(250, limit))
        def priority(row: dict[str, Any]) -> float:
            market_cap = float(row.get("market_cap") or 0.0)
            volume = float(row.get("total_volume") or 0.0)
            fdv = float(row.get("fully_diluted_valuation") or 0.0)
            return (
                max(0.0, float(row.get("price_change_percentage_24h") or 0.0)) * 2
                + max(0.0, float(row.get("price_change_percentage_7d_in_currency") or 0.0))
                + (volume / market_cap * 50 if market_cap > 0 else 0)
                + (fdv / market_cap * 5 if market_cap > 0 else 0)
            )
        return sorted(rows, key=priority, reverse=True)[:limit]
