from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from binance_futures import BinanceFuturesPublic, FuturesSymbol

from .chains import ChainRegistry
from .clients import ExplorerClient
from .models import PerpMarketContext


MAJOR_BASES = {"BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "TRX", "LINK", "LTC", "BCH", "DOT", "AVAX"}
STABLE_BASES = {"USDC", "FDUSD", "BUSD", "TUSD", "USDP", "USDE", "DAI"}
DEFAULT_SEED_PATH = Path(os.environ.get("TOKEN_CONTRACT_SEED_FILE", r"C:\Users\PC\Downloads\eth_bnb_contract_addresses_seed.txt"))
DEFAULT_SEED_CACHE_PATH = Path("data") / "contract_seed_metadata_cache.json"
ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}")


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def base_symbol_candidates(base_asset: str) -> list[str]:
    base = str(base_asset).upper().strip()
    candidates = [base]
    for prefix in ("1000000", "100000", "10000", "1000"):
        if base.startswith(prefix) and len(base) > len(prefix):
            candidates.append(base[len(prefix) :])
    if base.startswith("1M") and len(base) > 2:
        candidates.append(base[2:])
    return list(dict.fromkeys(candidates))


def load_seed_addresses(seed_path: str | Path | None = None) -> list[str]:
    path = Path(seed_path) if seed_path else DEFAULT_SEED_PATH
    if not path.exists():
        return []
    addresses = ADDRESS_RE.findall(path.read_text(encoding="utf-8", errors="ignore"))
    return list(dict.fromkeys(addresses))


@dataclass(frozen=True)
class SeedContract:
    chain: str
    contract_address: str
    token_symbol: str
    token_name: str = ""
    total_supply: float | None = None
    current_price: float | None = None
    metadata_source: str = "seed_explorer"

    @property
    def normalized_symbol(self) -> str:
        return self.token_symbol.upper().strip()


@dataclass(frozen=True)
class PerpUniverseCandidate:
    symbol: str
    base_asset: str
    quote_asset: str = "USDT"
    underlying_type: str = ""
    chain: str = ""
    contract_address: str = ""
    contract_source: str = ""
    coingecko_id: str = ""
    token_name: str = ""
    token_symbol: str = ""
    current_price: float | None = None
    market_cap: float | None = None
    fully_diluted_valuation: float | None = None
    spot_volume_24h: float | None = None
    perp_volume_24h: float | None = None
    futures_to_spot_volume_ratio: float | None = None
    price_change_24h: float | None = None
    price_change_7d: float | None = None
    price_change_30d: float | None = None
    open_interest: float | None = None
    open_interest_notional: float | None = None
    oi_to_market_cap_ratio: float | None = None
    match_confidence: str = "none"
    skip_reason: str = ""

    def context(self) -> PerpMarketContext:
        return PerpMarketContext(
            binance_symbol=self.symbol,
            base_asset=self.base_asset,
            current_price=self.current_price,
            perp_volume_24h=self.perp_volume_24h,
            spot_volume_24h=self.spot_volume_24h,
            futures_to_spot_volume_ratio=self.futures_to_spot_volume_ratio,
            open_interest=self.open_interest,
            open_interest_notional=self.open_interest_notional,
            oi_to_market_cap_ratio=self.oi_to_market_cap_ratio,
            price_change_24h=self.price_change_24h,
            price_change_7d=self.price_change_7d,
            price_change_30d=self.price_change_30d,
            is_pre_ignition_price_action=(
                (self.price_change_7d is not None and 20 <= self.price_change_7d <= 100)
                or (self.price_change_30d is not None and 50 <= self.price_change_30d <= 300)
            ),
            perps_bigger_than_spot=(self.futures_to_spot_volume_ratio or 0.0) > 5,
            oi_pressure_flag=(self.oi_to_market_cap_ratio or 0.0) > 0.20,
            liquidity_churn_flag=_ratio(self.perp_volume_24h, self.market_cap) is not None and (_ratio(self.perp_volume_24h, self.market_cap) or 0.0) > 1,
        )


class BinanceSpotPublic:
    def __init__(self, *, base_url: str = "https://api.binance.com", timeout: int = 12) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = int(timeout)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "crime-pump-concentration-scanner/1.0"})

    def ticker_24hr(self) -> list[dict[str, Any]]:
        try:
            response = self.session.get(f"{self.base_url}/api/v3/ticker/24hr", timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else []
        except Exception:
            return []


class BinancePerpUniverseBuilder:
    def __init__(
        self,
        *,
        binance: BinanceFuturesPublic | None = None,
        spot: BinanceSpotPublic | None = None,
        registry: ChainRegistry | None = None,
        seed_contracts: list[SeedContract] | None = None,
        seed_cache_path: str | Path | None = None,
    ) -> None:
        self.binance = binance or BinanceFuturesPublic(requests_per_second=3.0)
        self.spot = spot or BinanceSpotPublic()
        self.registry = registry or ChainRegistry()
        self.seed_contracts = seed_contracts
        self.seed_cache_path = Path(seed_cache_path) if seed_cache_path else DEFAULT_SEED_CACHE_PATH

    def build_candidates(
        self,
        *,
        seed_path: str | Path | None = None,
        include_majors: bool = True,
        include_stables: bool = True,
        enrich_open_interest_top_n: int = 25,
    ) -> list[PerpUniverseCandidate]:
        symbols = self.binance.perpetual_usdt_symbols()
        futures_tickers = {str(row.get("symbol", "")).upper(): row for row in self.binance.ticker_24hr()}
        spot_tickers = {str(row.get("symbol", "")).upper(): row for row in self.spot.ticker_24hr()}
        contracts_by_symbol = self._contracts_by_symbol(seed_path)

        candidates: list[PerpUniverseCandidate] = []
        for futures_symbol in symbols:
            if not include_majors and futures_symbol.base_asset in MAJOR_BASES:
                continue
            if not include_stables and futures_symbol.base_asset in STABLE_BASES:
                continue
            ticker = futures_tickers.get(futures_symbol.symbol, {})
            spot_ticker = spot_tickers.get(futures_symbol.symbol, {})
            contract = self._match_contract(futures_symbol, contracts_by_symbol)
            candidates.append(self._candidate_from_rows(futures_symbol, ticker, spot_ticker, contract))

        candidates = sorted(
            candidates,
            key=lambda item: (
                1 if item.contract_address else 0,
                item.futures_to_spot_volume_ratio or 0.0,
                item.perp_volume_24h or 0.0,
                item.market_cap or 0.0,
            ),
            reverse=True,
        )
        if enrich_open_interest_top_n > 0:
            candidates = self._with_open_interest(candidates, limit=enrich_open_interest_top_n)
        return candidates

    def _contracts_by_symbol(self, seed_path: str | Path | None) -> dict[str, list[SeedContract]]:
        contracts = self.seed_contracts if self.seed_contracts is not None else self._load_or_build_seed_contracts(seed_path)
        by_symbol: dict[str, list[SeedContract]] = {}
        for contract in contracts:
            if not contract.normalized_symbol:
                continue
            by_symbol.setdefault(contract.normalized_symbol, []).append(contract)
        for rows in by_symbol.values():
            rows.sort(key=lambda item: (item.chain == "bsc", item.total_supply or 0.0), reverse=True)
        return by_symbol

    def _load_or_build_seed_contracts(self, seed_path: str | Path | None) -> list[SeedContract]:
        addresses = load_seed_addresses(seed_path)
        if not addresses:
            return []
        cached = self._load_seed_cache()
        contracts: list[SeedContract] = []
        changed = False
        adapters = self.registry.supported()
        explorers = {adapter.key: ExplorerClient(adapter, requests_per_second=1.25) for adapter in adapters}
        for address in addresses:
            key_prefix = address.lower()
            cached_rows = [row for key, row in cached.items() if key.endswith(f":{key_prefix}")]
            cached_successes = [row for row in cached_rows if row.get("token_symbol")]
            if cached_successes:
                contracts.extend(self._contract_from_cache(row) for row in cached_successes)
                continue
            for adapter in adapters:
                cache_key = f"{adapter.key}:{key_prefix}"
                try:
                    meta = explorers[adapter.key].fetch_token_metadata(address)
                except Exception as exc:
                    cached[cache_key] = {"chain": adapter.key, "contract_address": address, "token_symbol": "", "error": str(exc)}
                    changed = True
                    continue
                if not meta.symbol:
                    cached[cache_key] = {"chain": adapter.key, "contract_address": address, "token_symbol": "", "error": "missing ERC20 symbol"}
                    changed = True
                    continue
                contract = SeedContract(
                    chain=adapter.key,
                    contract_address=address,
                    token_symbol=meta.symbol,
                    token_name=meta.name,
                    total_supply=meta.total_supply,
                )
                cached[cache_key] = contract.__dict__
                contracts.append(contract)
                changed = True
        if changed:
            self._save_seed_cache(cached)
        return contracts

    def _load_seed_cache(self) -> dict[str, dict[str, Any]]:
        if not self.seed_cache_path.exists():
            return {}
        try:
            data = json.loads(self.seed_cache_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_seed_cache(self, payload: dict[str, dict[str, Any]]) -> None:
        self.seed_cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.seed_cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _contract_from_cache(self, row: dict[str, Any]) -> SeedContract:
        return SeedContract(
            chain=str(row.get("chain", "")),
            contract_address=str(row.get("contract_address", "")),
            token_symbol=str(row.get("token_symbol", "")),
            token_name=str(row.get("token_name", "")),
            total_supply=_to_float(row.get("total_supply")),
            metadata_source=str(row.get("metadata_source", "seed_explorer")),
        )

    def _match_contract(self, futures_symbol: FuturesSymbol, by_symbol: dict[str, list[SeedContract]]) -> SeedContract | None:
        for candidate_symbol in base_symbol_candidates(futures_symbol.base_asset):
            rows = by_symbol.get(candidate_symbol)
            if rows:
                return rows[0]
        return None

    def _candidate_from_rows(
        self,
        futures_symbol: FuturesSymbol,
        ticker: dict[str, Any],
        spot_ticker: dict[str, Any],
        contract: SeedContract | None,
    ) -> PerpUniverseCandidate:
        perp_volume = _to_float(ticker.get("quoteVolume"))
        spot_volume = _to_float(spot_ticker.get("quoteVolume"))
        current_price = _to_float(ticker.get("lastPrice") or ticker.get("weightedAvgPrice") or ticker.get("markPrice"))
        total_supply = contract.total_supply if contract else None
        quoted_supply_value = current_price * total_supply if current_price is not None and total_supply is not None else None
        match_confidence = "seed_symbol" if contract else "none"
        return PerpUniverseCandidate(
            symbol=futures_symbol.symbol,
            base_asset=futures_symbol.base_asset,
            quote_asset=futures_symbol.quote_asset,
            underlying_type=futures_symbol.underlying_type,
            chain=contract.chain if contract else "",
            contract_address=contract.contract_address if contract else "",
            contract_source=contract.metadata_source if contract else "",
            token_name=contract.token_name if contract else futures_symbol.base_asset,
            token_symbol=contract.token_symbol if contract else futures_symbol.base_asset,
            current_price=current_price,
            market_cap=quoted_supply_value,
            fully_diluted_valuation=quoted_supply_value,
            spot_volume_24h=spot_volume,
            perp_volume_24h=perp_volume,
            futures_to_spot_volume_ratio=_ratio(perp_volume, spot_volume),
            price_change_24h=_to_float(ticker.get("priceChangePercent")),
            match_confidence=match_confidence,
            skip_reason="" if contract else "No matching Ethereum/BNB/ARB contract in local seed index",
        )

    def _with_open_interest(self, candidates: list[PerpUniverseCandidate], *, limit: int) -> list[PerpUniverseCandidate]:
        enriched: list[PerpUniverseCandidate] = []
        for index, candidate in enumerate(candidates):
            if index >= limit:
                enriched.append(candidate)
                continue
            try:
                raw = self.binance.open_interest(candidate.symbol)
            except Exception:
                enriched.append(candidate)
                continue
            oi = _to_float(raw.get("openInterest"))
            notional = oi * candidate.current_price if oi is not None and candidate.current_price is not None else None
            enriched.append(
                PerpUniverseCandidate(
                    **{
                        **candidate.__dict__,
                        "open_interest": oi,
                        "open_interest_notional": notional,
                        "oi_to_market_cap_ratio": _ratio(notional, candidate.market_cap),
                    }
                )
            )
        return enriched
