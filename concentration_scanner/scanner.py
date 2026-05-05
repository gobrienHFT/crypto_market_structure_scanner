from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .cache import ScanCache
from .chains import ChainRegistry
from .classifier import HolderClassifier, ManualOverride
from .clients import CoinGeckoClient, ExplorerClient
from .concentration import ConcentrationEngine
from .manipulable import ManipulableWhaleEngine
from .models import (
    ConcentrationMetrics,
    ContractControlStats,
    HolderRecord,
    ManipulableWhaleMetrics,
    PerpMarketContext,
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
        self.coingecko = coingecko
        self.registry = registry or ChainRegistry()
        self.cache = cache
        self.concentration = ConcentrationEngine()
        self.manipulable = ManipulableWhaleEngine()
        self.risk = RiskScoringEngine()

    def resolve_contract(self, scanner_input: ScannerInput) -> tuple[TokenMarketData, str, str]:
        chain = self.registry.normalize_key(scanner_input.chain)
        if scanner_input.coin_id:
            if self.coingecko is None:
                raise ValueError("CoinGecko lookup is disabled; provide a contract address and chain.")
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
            if not contract:
                raise ValueError(f"No supported Ethereum/BNB Chain contract found for CoinGecko ID {scanner_input.coin_id}.")
            return market, chain, contract
        if scanner_input.contract_address:
            adapter = self.registry.get(chain)
            try:
                market = ExplorerClient(adapter).fetch_token_metadata(
                    scanner_input.contract_address,
                    fallback_symbol=scanner_input.symbol,
                )
            except Exception:
                market = TokenMarketData(
                    coin_id=f"{chain}:{scanner_input.contract_address.lower()}",
                    name=scanner_input.symbol.upper() if scanner_input.symbol else scanner_input.contract_address[:10],
                    symbol=scanner_input.symbol.upper(),
                    platforms={adapter.coingecko_platform: scanner_input.contract_address},
                    canonical_chain=chain,
                )
            return (market, chain, scanner_input.contract_address)
        if scanner_input.symbol:
            raise ValueError("Symbol-only lookup is disabled; provide a contract address and chain.")
        raise ValueError("Provide a contract address and chain.")

    def scan(
        self,
        scanner_input: ScannerInput,
        *,
        overrides: list[ManualOverride] | None = None,
        perp_context: PerpMarketContext | None = None,
    ) -> TokenScanResult:
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
            perp_context=perp_context,
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
        perp_context: PerpMarketContext | None = None,
    ) -> TokenScanResult:
        market = self._with_perp_market_data(market, perp_context or PerpMarketContext())
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
        perp = self._with_adjusted_float_context(perp_context or PerpMarketContext(), market=market, metrics=metrics)
        control = contract_control or ContractControlStats()
        thin = self.risk.compute_thin_float_stats(market, metrics)
        manipulable_metrics, wallet_forensics, wallet_clusters = self.manipulable.compute(
            classified,
            adjusted_float_supply=metrics.adjusted_float_supply,
        )
        representation = self.risk.representation_guardrail(inspected_chain=chain, market=market, metrics=metrics)
        if representation.wrapped_representation_warning:
            manipulable_metrics = ManipulableWhaleMetrics(
                cex_storage_supply_pct=manipulable_metrics.cex_storage_supply_pct,
                protocol_storage_supply_pct=manipulable_metrics.protocol_storage_supply_pct,
                treasury_storage_supply_pct=manipulable_metrics.treasury_storage_supply_pct,
                vesting_lockup_supply_pct=manipulable_metrics.vesting_lockup_supply_pct,
                bridge_wrapper_supply_pct=max(manipulable_metrics.bridge_wrapper_supply_pct, metrics.raw_top_100_pct),
                key_forensic_flags=["wrapped_representation_guardrail"],
                evidence_confidence="low",
                evidence_summary="Wrapped or chain-specific holder data is not treated as global manipulable-whale evidence without native-chain confirmation.",
            )
            wallet_clusters = []
        flags = self.risk.compute_flags(holders=classified, metrics=metrics, market=market, thin=thin, manipulable=manipulable_metrics)
        scores = self.risk.compute_scores(metrics=metrics, contract=control, thin=thin, flags=flags, manipulable=manipulable_metrics)
        master = self.risk.compute_master_score(
            metrics=metrics,
            manipulable=manipulable_metrics,
            thin=thin,
            scores=scores,
            flags=flags,
            perp=perp,
        )
        key_flags = self.risk.key_flags(flags, representation)
        status = ScannerStatus(
            last_market_data_fetch_at=market_fetch_at,
            last_holder_fetch_at=holder_fetch_at,
            last_classification_at=classification_at,
            scanner_status="partial" if scanner_error or partial else "complete",
            scanner_error=scanner_error,
        )
        summary = self.risk.summary(flags=flags, representation=representation, token_name=market.name or market.symbol, manipulable=manipulable_metrics)
        result = TokenScanResult(
            token=market,
            chain=chain,
            contract_address=contract,
            holders=classified,
            concentration=metrics,
            contract_control=control,
            representation=representation,
            manipulable=manipulable_metrics,
            wallet_forensics=wallet_forensics,
            wallet_clusters=wallet_clusters,
            thin_float=thin,
            scores=scores,
            flags=flags,
            status=status,
            summary=summary,
            key_flags=key_flags,
            perp_context=perp,
            master_score=master,
        )
        if self.cache is not None:
            self.cache.upsert_result(result)
        return result

    def _with_adjusted_float_context(
        self,
        context: PerpMarketContext,
        *,
        market: TokenMarketData,
        metrics: ConcentrationMetrics,
    ) -> PerpMarketContext:
        market_cap = market.market_cap
        adjusted_float_market_cap = (
            market_cap * metrics.adjusted_float_pct_total_supply / 100.0
            if market_cap is not None and metrics.adjusted_float_pct_total_supply > 0
            else None
        )
        return PerpMarketContext(
            **{
                **context.__dict__,
                "spot_volume_24h": context.spot_volume_24h if context.spot_volume_24h is not None else market.volume_24h,
                "volume_to_market_cap_ratio": self._ratio(context.perp_volume_24h or market.volume_24h, market_cap),
                "volume_to_adjusted_float_market_cap": self._ratio(context.perp_volume_24h or market.volume_24h, adjusted_float_market_cap),
                "oi_to_adjusted_float_market_cap_ratio": self._ratio(context.open_interest_notional, adjusted_float_market_cap),
            }
        )

    @staticmethod
    def _ratio(numerator: float | None, denominator: float | None) -> float | None:
        if numerator is None or denominator is None or denominator <= 0:
            return None
        return numerator / denominator

    def prioritized_universe(self, *, category: str = "", limit: int = 100) -> list[dict[str, Any]]:
        if self.coingecko is None:
            return []
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

    def _with_perp_market_data(self, market: TokenMarketData, context: PerpMarketContext) -> TokenMarketData:
        current_price = market.current_price if market.current_price is not None else context.current_price
        quoted_supply_value = (
            current_price * market.total_supply
            if current_price is not None and market.total_supply is not None
            else None
        )
        return replace(
            market,
            current_price=current_price,
            market_cap=market.market_cap if market.market_cap is not None else quoted_supply_value,
            fully_diluted_valuation=(
                market.fully_diluted_valuation
                if market.fully_diluted_valuation is not None
                else quoted_supply_value
            ),
            volume_24h=market.volume_24h if market.volume_24h is not None else context.perp_volume_24h,
            price_change_24h=market.price_change_24h if market.price_change_24h is not None else context.price_change_24h,
            price_change_7d=market.price_change_7d if market.price_change_7d is not None else context.price_change_7d,
            price_change_30d=market.price_change_30d if market.price_change_30d is not None else context.price_change_30d,
        )
