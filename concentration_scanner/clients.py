from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import requests

from .chains import ChainAdapter
from .models import ContractControlStats, HolderRecord, TokenMarketData


class ApiClientError(RuntimeError):
    pass


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _decode_eth_call_string(value: Any) -> str:
    text = str(value or "")
    if not text.startswith("0x") or text == "0x":
        return ""
    raw = text[2:]
    try:
        data = bytes.fromhex(raw)
    except ValueError:
        return ""
    if not data:
        return ""

    # ABI dynamic string: offset word, length word, then UTF-8 bytes.
    if len(data) >= 64:
        try:
            offset = int.from_bytes(data[:32], "big")
            length = int.from_bytes(data[offset : offset + 32], "big")
            if offset + 32 + length <= len(data):
                return data[offset + 32 : offset + 32 + length].decode("utf-8", errors="ignore").strip("\x00 ")
        except Exception:
            pass

    # Common bytes32 symbol/name fallback.
    return data.rstrip(b"\x00").decode("utf-8", errors="ignore").strip("\x00 ")


def _decode_eth_call_uint(value: Any) -> int | None:
    text = str(value or "")
    if not text.startswith("0x") or text == "0x":
        return None
    try:
        return int(text, 16)
    except ValueError:
        return None


class CoinGeckoClient:
    def __init__(
        self,
        *,
        base_url: str = "https://api.coingecko.com/api/v3",
        api_key: str | None = None,
        timeout: int = 15,
        requests_per_second: float = 2.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("COINGECKO_API_KEY", "")
        self.timeout = int(timeout)
        self.min_gap = 1.0 / max(0.2, float(requests_per_second))
        self._last_at = 0.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "crime-pump-concentration-scanner/1.0"})
        if self.api_key:
            self.session.headers.update({"x-cg-demo-api-key": self.api_key, "x-cg-pro-api-key": self.api_key})

    def _pace(self) -> None:
        gap = time.monotonic() - self._last_at
        if gap < self.min_gap:
            time.sleep(self.min_gap - gap)
        self._last_at = time.monotonic()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self._pace()
        response = self.session.get(f"{self.base_url}{path}", params=params or {}, timeout=self.timeout)
        if response.status_code != 200:
            raise ApiClientError(f"CoinGecko HTTP {response.status_code}: {response.text[:250]}")
        return response.json()

    def fetch_coin(self, coin_id: str) -> dict[str, Any]:
        return self._get(
            f"/coins/{coin_id}",
            {
                "localization": "false",
                "tickers": "false",
                "market_data": "true",
                "community_data": "false",
                "developer_data": "false",
                "sparkline": "false",
            },
        )

    def search(self, query: str) -> dict[str, Any]:
        return self._get("/search", {"query": query})

    def markets(
        self,
        *,
        category: str | None = None,
        order: str = "volume_desc",
        per_page: int = 100,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "vs_currency": "usd",
            "order": order,
            "per_page": int(per_page),
            "page": int(page),
            "price_change_percentage": "1h,24h,7d,14d,30d",
        }
        if category:
            params["category"] = category
        data = self._get("/coins/markets", params)
        return data if isinstance(data, list) else []

    def trending(self) -> list[dict[str, Any]]:
        data = self._get("/search/trending")
        coins = data.get("coins", []) if isinstance(data, dict) else []
        return [row.get("item", {}) for row in coins if isinstance(row, dict)]

    def parse_market_data(self, raw: dict[str, Any]) -> TokenMarketData:
        market = raw.get("market_data", {}) if isinstance(raw.get("market_data"), dict) else {}
        current_price = market.get("current_price", {}).get("usd") if isinstance(market.get("current_price"), dict) else raw.get("current_price")
        market_cap = market.get("market_cap", {}).get("usd") if isinstance(market.get("market_cap"), dict) else raw.get("market_cap")
        fdv = (
            market.get("fully_diluted_valuation", {}).get("usd")
            if isinstance(market.get("fully_diluted_valuation"), dict)
            else raw.get("fully_diluted_valuation")
        )
        total_volume = market.get("total_volume", {}).get("usd") if isinstance(market.get("total_volume"), dict) else raw.get("total_volume")
        atl = market.get("atl", {}).get("usd") if isinstance(market.get("atl"), dict) else raw.get("atl")
        ath = market.get("ath", {}).get("usd") if isinstance(market.get("ath"), dict) else raw.get("ath")
        return TokenMarketData(
            coin_id=str(raw.get("id", "")),
            name=str(raw.get("name", "")),
            symbol=str(raw.get("symbol", "")).upper(),
            platforms={str(k): str(v) for k, v in (raw.get("platforms") or {}).items() if v},
            current_price=_to_float(current_price),
            market_cap=_to_float(market_cap),
            fully_diluted_valuation=_to_float(fdv),
            circulating_supply=_to_float(market.get("circulating_supply", raw.get("circulating_supply"))),
            total_supply=_to_float(market.get("total_supply", raw.get("total_supply"))),
            max_supply=_to_float(market.get("max_supply", raw.get("max_supply"))),
            volume_24h=_to_float(total_volume),
            price_change_1h=_to_float(raw.get("price_change_percentage_1h_in_currency")),
            price_change_24h=_to_float(market.get("price_change_percentage_24h", raw.get("price_change_percentage_24h"))),
            price_change_7d=_to_float(raw.get("price_change_percentage_7d_in_currency")),
            price_change_14d=_to_float(raw.get("price_change_percentage_14d_in_currency")),
            price_change_30d=_to_float(raw.get("price_change_percentage_30d_in_currency")),
            all_time_low_price=_to_float(atl),
            all_time_high_price=_to_float(ath),
            atl_date=str(market.get("atl_date", {}).get("usd", raw.get("atl_date", "")) if isinstance(market.get("atl_date"), dict) else raw.get("atl_date", "")),
            ath_date=str(market.get("ath_date", {}).get("usd", raw.get("ath_date", "")) if isinstance(market.get("ath_date"), dict) else raw.get("ath_date", "")),
            peak_market_cap=_to_float(raw.get("peak_market_cap")),
            peak_fdv=_to_float(raw.get("peak_fdv")),
            peak_volume_24h=_to_float(raw.get("peak_volume_24h")),
            max_24h_price_change=_to_float(raw.get("max_24h_price_change")),
            max_7d_price_change=_to_float(raw.get("max_7d_price_change")),
            max_30d_price_change=_to_float(raw.get("max_30d_price_change")),
            canonical_chain=str(raw.get("asset_platform_id", "")),
            is_native_asset=not bool(raw.get("platforms")),
        )


@dataclass(frozen=True)
class ExplorerFetchResult:
    holders: list[HolderRecord]
    error: str = ""
    partial: bool = False


EXPLORER_API_KEY_FALLBACK_ENVS: dict[str, tuple[str, ...]] = {
    "ETHERSCAN_API_KEY": ("ETHERSCAN_API_KEY", "ETHERSCAN_V2_API_KEY"),
    "BSCSCAN_API_KEY": ("BSCSCAN_API_KEY", "ETHERSCAN_API_KEY", "ETHERSCAN_V2_API_KEY"),
    "ARBISCAN_API_KEY": ("ARBISCAN_API_KEY", "ARBSCAN_API_KEY", "ETHERSCAN_API_KEY", "ETHERSCAN_V2_API_KEY"),
}


def _explorer_api_key(primary_env: str) -> str:
    for env_name in EXPLORER_API_KEY_FALLBACK_ENVS.get(primary_env, (primary_env,)):
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    return ""


class ExplorerClient:
    """Etherscan-family explorer client.

    Some Etherscan-compatible deployments expose token holder endpoints, some do
    not. Missing endpoints are returned as partial results instead of crashing
    the dashboard.
    """

    def __init__(
        self,
        adapter: ChainAdapter,
        *,
        api_key: str | None = None,
        timeout: int = 15,
        requests_per_second: float = 2.0,
    ) -> None:
        self.adapter = adapter
        self.api_key = api_key if api_key is not None else _explorer_api_key(adapter.api_key_env)
        self.timeout = int(timeout)
        self.min_gap = 1.0 / max(0.2, float(requests_per_second))
        self._last_at = 0.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "crime-pump-concentration-scanner/1.0"})

    def _pace(self) -> None:
        gap = time.monotonic() - self._last_at
        if gap < self.min_gap:
            time.sleep(self.min_gap - gap)
        self._last_at = time.monotonic()

    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        req = dict(params)
        if self.api_key:
            req["apikey"] = self.api_key
        self._pace()
        response = self.session.get(self.adapter.explorer_api_url, params=req, timeout=self.timeout)
        if response.status_code != 200:
            raise ApiClientError(f"{self.adapter.explorer_name} HTTP {response.status_code}: {response.text[:250]}")
        data = response.json()
        return data if isinstance(data, dict) else {}

    def _proxy_eth_call(self, contract_address: str, selector: str) -> Any:
        data = self._get(
            {
                "module": "proxy",
                "action": "eth_call",
                "to": contract_address,
                "data": selector,
                "tag": "latest",
            }
        )
        return data.get("result")

    def fetch_token_metadata(self, contract_address: str, *, fallback_symbol: str = "") -> TokenMarketData:
        token_info = self._fetch_token_info(contract_address)
        symbol = str(token_info.get("symbol") or token_info.get("tokenSymbol") or "").upper()
        name = str(token_info.get("tokenName") or token_info.get("name") or "")
        decimals = _to_float(token_info.get("divisor") or token_info.get("decimals"))
        raw_supply = _to_float(token_info.get("totalSupply") or token_info.get("total_supply"))

        if not symbol:
            try:
                symbol = _decode_eth_call_string(self._proxy_eth_call(contract_address, "0x95d89b41")).upper()
            except Exception:
                symbol = ""
        if not name:
            try:
                name = _decode_eth_call_string(self._proxy_eth_call(contract_address, "0x06fdde03"))
            except Exception:
                name = ""
        if decimals is None:
            try:
                decimals_uint = _decode_eth_call_uint(self._proxy_eth_call(contract_address, "0x313ce567"))
                decimals = float(decimals_uint) if decimals_uint is not None else None
            except Exception:
                decimals = None
        if raw_supply is None:
            try:
                raw_supply_uint = _decode_eth_call_uint(self._proxy_eth_call(contract_address, "0x18160ddd"))
                raw_supply = float(raw_supply_uint) if raw_supply_uint is not None else None
            except Exception:
                raw_supply = None

        total_supply = raw_supply
        if raw_supply is not None and decimals is not None and decimals >= 0:
            scale = 10 ** int(decimals)
            total_supply = raw_supply / scale if raw_supply >= scale else raw_supply

        symbol = symbol or fallback_symbol.upper()
        return TokenMarketData(
            coin_id=f"{self.adapter.key}:{contract_address.lower()}",
            name=name or symbol or contract_address[:10],
            symbol=symbol,
            platforms={self.adapter.coingecko_platform: contract_address},
            total_supply=total_supply,
            max_supply=total_supply,
            canonical_chain=self.adapter.key,
            is_native_asset=False,
        )

    def _fetch_token_info(self, contract_address: str) -> dict[str, Any]:
        try:
            data = self._get({"module": "token", "action": "tokeninfo", "contractaddress": contract_address})
        except Exception:
            return {}
        result = data.get("result")
        if isinstance(result, list) and result and isinstance(result[0], dict):
            return result[0]
        if isinstance(result, dict):
            return result
        return {}

    def fetch_top_holders(self, contract_address: str, *, limit: int = 100) -> ExplorerFetchResult:
        endpoint_attempts = [
            {"module": "token", "action": "tokenholderlist", "contractaddress": contract_address, "page": 1, "offset": limit},
            {"module": "token", "action": "tokenholderlist", "contractAddress": contract_address, "page": 1, "offset": limit},
        ]
        errors: list[str] = []
        for params in endpoint_attempts:
            try:
                data = self._get(params)
            except Exception as exc:
                errors.append(str(exc))
                continue
            result = data.get("result")
            if isinstance(result, list):
                holders = self._parse_holder_rows(result, contract_address=contract_address)
                return ExplorerFetchResult(holders=holders[:limit], partial=len(holders) < min(100, limit))
            errors.append(str(data.get("message") or data.get("result") or "holder endpoint unavailable"))
        return ExplorerFetchResult(holders=[], error="; ".join(errors), partial=True)

    def _parse_holder_rows(self, rows: list[dict[str, Any]], *, contract_address: str) -> list[HolderRecord]:
        holders: list[HolderRecord] = []
        for index, row in enumerate(rows, start=1):
            address = str(row.get("TokenHolderAddress") or row.get("HolderAddress") or row.get("address") or "")
            if not address:
                continue
            balance = _to_float(row.get("TokenHolderQuantity") or row.get("balance") or row.get("Balance")) or 0.0
            pct = _to_float(row.get("percentage") or row.get("pct_total_supply") or row.get("share")) or 0.0
            holders.append(
                HolderRecord(
                    rank=int(row.get("rank", index) or index),
                    address=address,
                    label=str(row.get("label", "")),
                    balance_raw=str(row.get("TokenHolderQuantity") or row.get("balance") or ""),
                    balance_decimal=balance,
                    pct_total_supply=pct,
                    is_contract=bool(row.get("is_contract", False)),
                    explorer_url=self.adapter.address_url(address),
                )
            )
        return holders

    def fetch_contract_control(self, contract_address: str, holder_addresses: set[str] | None = None) -> ContractControlStats:
        try:
            data = self._get({"module": "contract", "action": "getsourcecode", "address": contract_address})
        except Exception:
            return ContractControlStats()
        result = data.get("result")
        if not isinstance(result, list) or not result:
            return ContractControlStats()
        source = result[0] if isinstance(result[0], dict) else {}
        abi_text = str(source.get("ABI", ""))
        source_text = str(source.get("SourceCode", ""))
        combined = f"{abi_text}\n{source_text}".lower()
        contract_verified = bool(source_text.strip()) or abi_text not in ("", "Contract source code not verified")
        is_proxy = str(source.get("Proxy", "")).lower() in ("1", "true") or "proxy" in combined
        implementation = str(source.get("Implementation", ""))
        owner = ""
        flags: list[str] = []

        def has_any(*needles: str) -> bool:
            return any(needle.lower() in combined for needle in needles)

        has_mint = has_any("function mint", '"name":"mint"', " minter_role")
        has_pause = has_any("pausable", "function pause", '"name":"pause"', '"name":"unpause"')
        has_blacklist = has_any("blacklist", "blocklist", "denylist")
        has_whitelist = has_any("whitelist", "allowlist")
        has_fee = has_any("setfee", "settax", "taxfee", "marketingfee", "liquidityfee")
        has_limits = has_any("maxwallet", "maxtx", "maxtransaction", "transferlimit")
        has_gate = has_any("tradingenabled", "enabletrading", "tradingopen")
        has_transfer_restrictions = has_any("beforetokentransfer", "_transfer", "transferrestriction") and (
            has_blacklist or has_whitelist or has_limits or has_gate
        )

        admin_score = 0.0
        if contract_verified and not has_any("renounceownership", "owner = address(0)", "owner: 0x0000000000000000000000000000000000000000"):
            admin_score += 20
            flags.append("owner/admin controls may exist")
        if is_proxy:
            admin_score += 20
            flags.append("upgradeable proxy")
        if has_mint:
            admin_score += 25
            flags.append("mint function")
        if has_pause:
            admin_score += 20
            flags.append("pause function")
        if has_blacklist or has_whitelist:
            admin_score += 25
            flags.append("blacklist/whitelist control")
        if has_fee:
            admin_score += 15
            flags.append("fee/tax setter")
        if has_limits or has_transfer_restrictions:
            admin_score += 15
            flags.append("transfer/max-wallet control")
        if owner and holder_addresses and owner.lower() in {item.lower() for item in holder_addresses}:
            admin_score += 20
            flags.append("owner/admin is top holder")

        return ContractControlStats(
            contract_verified=contract_verified,
            is_proxy=is_proxy,
            implementation_address=implementation,
            owner_address=owner,
            has_mint_function=has_mint,
            has_pause_function=has_pause,
            has_blacklist_function=has_blacklist,
            has_whitelist_function=has_whitelist,
            has_fee_setter=has_fee,
            has_transfer_restrictions=has_transfer_restrictions,
            has_max_wallet_control=has_limits,
            has_trading_gate=has_gate,
            ownership_renounced=has_any("owner = address(0)", "0x0000000000000000000000000000000000000000"),
            admin_privilege_score=min(100.0, admin_score),
            contract_control_flags=flags,
        )


def parse_json_env(name: str) -> Any:
    value = os.environ.get(name, "")
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None
