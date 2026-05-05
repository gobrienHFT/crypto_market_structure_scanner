from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from binance_futures import BinanceFuturesPublic, FuturesSymbol

from .clients import CoinGeckoClient
from .models import PerpMarketContext


MAJOR_BASES = {"BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "TRX", "LINK", "LTC", "BCH", "DOT", "AVAX"}
STABLE_BASES = {"USDC", "FDUSD", "BUSD", "TUSD", "USDP", "USDE", "DAI"}


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


@dataclass(frozen=True)
class PerpUniverseCandidate:
    symbol: str
    base_asset: str
    quote_asset: str = "USDT"
    underlying_type: str = ""
    coingecko_id: str = ""
    token_name: str = ""
    token_symbol: str = ""
    current_price: float | None = None
    market_cap: float | None = None
    fully_diluted_valuation: float | None = None
    spot_volume_24h: float | None = None
    perp_volume_24h: float | None = None
    futures_to_spot_volume_ratio: float | None = None
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
            perp_volume_24h=self.perp_volume_24h,
            spot_volume_24h=self.spot_volume_24h,
            futures_to_spot_volume_ratio=self.futures_to_spot_volume_ratio,
            open_interest=self.open_interest,
            open_interest_notional=self.open_interest_notional,
            oi_to_market_cap_ratio=self.oi_to_market_cap_ratio,
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


class BinancePerpUniverseBuilder:
    def __init__(
        self,
        *,
        binance: BinanceFuturesPublic | None = None,
        coingecko: CoinGeckoClient | None = None,
    ) -> None:
        self.binance = binance or BinanceFuturesPublic(requests_per_second=3.0)
        self.coingecko = coingecko or CoinGeckoClient(requests_per_second=2.0)

    def build_candidates(
        self,
        *,
        coingecko_pages: int = 4,
        include_majors: bool = True,
        include_stables: bool = True,
        enrich_open_interest_top_n: int = 25,
    ) -> list[PerpUniverseCandidate]:
        symbols = self.binance.perpetual_usdt_symbols()
        tickers = {str(row.get("symbol", "")).upper(): row for row in self.binance.ticker_24hr()}
        markets = self._coingecko_market_rows(pages=coingecko_pages)
        by_symbol = self._markets_by_symbol(markets)

        candidates: list[PerpUniverseCandidate] = []
        for futures_symbol in symbols:
            if not include_majors and futures_symbol.base_asset in MAJOR_BASES:
                continue
            if not include_stables and futures_symbol.base_asset in STABLE_BASES:
                continue
            ticker = tickers.get(futures_symbol.symbol, {})
            market = self._match_market(futures_symbol, by_symbol)
            candidates.append(self._candidate_from_rows(futures_symbol, ticker, market))

        candidates = sorted(
            candidates,
            key=lambda item: (
                item.futures_to_spot_volume_ratio or 0.0,
                item.perp_volume_24h or 0.0,
                item.market_cap or 0.0,
            ),
            reverse=True,
        )
        if enrich_open_interest_top_n > 0:
            candidates = self._with_open_interest(candidates, limit=enrich_open_interest_top_n)
        return candidates

    def _coingecko_market_rows(self, *, pages: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for page in range(1, max(1, int(pages)) + 1):
            rows.extend(self.coingecko.markets(order="volume_desc", per_page=250, page=page))
        return rows

    def _markets_by_symbol(self, rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        by_symbol: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            symbol = str(row.get("symbol", "")).upper()
            if not symbol:
                continue
            by_symbol.setdefault(symbol, []).append(row)
        for symbol_rows in by_symbol.values():
            symbol_rows.sort(key=lambda row: float(row.get("market_cap") or row.get("total_volume") or 0.0), reverse=True)
        return by_symbol

    def _match_market(self, futures_symbol: FuturesSymbol, by_symbol: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        for candidate_symbol in base_symbol_candidates(futures_symbol.base_asset):
            rows = by_symbol.get(candidate_symbol)
            if rows:
                return rows[0]
        return {}

    def _candidate_from_rows(
        self,
        futures_symbol: FuturesSymbol,
        ticker: dict[str, Any],
        market: dict[str, Any],
    ) -> PerpUniverseCandidate:
        perp_volume = _to_float(ticker.get("quoteVolume"))
        spot_volume = _to_float(market.get("total_volume"))
        market_cap = _to_float(market.get("market_cap"))
        return PerpUniverseCandidate(
            symbol=futures_symbol.symbol,
            base_asset=futures_symbol.base_asset,
            quote_asset=futures_symbol.quote_asset,
            underlying_type=futures_symbol.underlying_type,
            coingecko_id=str(market.get("id", "")),
            token_name=str(market.get("name", "")),
            token_symbol=str(market.get("symbol", "")).upper(),
            current_price=_to_float(market.get("current_price")),
            market_cap=market_cap,
            fully_diluted_valuation=_to_float(market.get("fully_diluted_valuation")),
            spot_volume_24h=spot_volume,
            perp_volume_24h=perp_volume,
            futures_to_spot_volume_ratio=_ratio(perp_volume, spot_volume),
            price_change_7d=_to_float(market.get("price_change_percentage_7d_in_currency")),
            price_change_30d=_to_float(market.get("price_change_percentage_30d_in_currency")),
            match_confidence="symbol" if market else "none",
            skip_reason="" if market else "CoinGecko market match missing",
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
