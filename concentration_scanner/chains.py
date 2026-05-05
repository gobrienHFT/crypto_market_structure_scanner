from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChainAdapter:
    key: str
    name: str
    coingecko_platform: str
    explorer_name: str
    explorer_api_url: str
    explorer_base_url: str
    api_key_env: str
    native_symbol: str

    def address_url(self, address: str) -> str:
        return f"{self.explorer_base_url.rstrip('/')}/address/{address}"

    def token_url(self, contract: str) -> str:
        return f"{self.explorer_base_url.rstrip('/')}/token/{contract}"


class ChainRegistry:
    """Known EVM chain adapters.

    The first two adapters are active. The remaining names are reserved so the
    scanner can grow without changing the public UI shape.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, ChainAdapter] = {
            "ethereum": ChainAdapter(
                key="ethereum",
                name="Ethereum",
                coingecko_platform="ethereum",
                explorer_name="Etherscan",
                explorer_api_url="https://api.etherscan.io/api",
                explorer_base_url="https://etherscan.io",
                api_key_env="ETHERSCAN_API_KEY",
                native_symbol="ETH",
            ),
            "bsc": ChainAdapter(
                key="bsc",
                name="BNB Chain",
                coingecko_platform="binance-smart-chain",
                explorer_name="BscScan",
                explorer_api_url="https://api.bscscan.com/api",
                explorer_base_url="https://bscscan.com",
                api_key_env="BSCSCAN_API_KEY",
                native_symbol="BNB",
            ),
        }
        self.reserved_adapters = (
            "base",
            "arbitrum",
            "polygon",
            "optimism",
            "moralis",
            "bitquery",
            "covalent",
            "alchemy",
            "custom_indexer",
        )

    def get(self, chain: str) -> ChainAdapter:
        key = self.normalize_key(chain)
        if key not in self._adapters:
            raise KeyError(f"Unsupported chain adapter: {chain}")
        return self._adapters[key]

    def supported(self) -> list[ChainAdapter]:
        return list(self._adapters.values())

    def platform_to_chain(self, platform: str) -> str | None:
        wanted = platform.lower().strip()
        for adapter in self._adapters.values():
            if adapter.coingecko_platform == wanted or adapter.key == wanted:
                return adapter.key
        return None

    def normalize_key(self, chain: str) -> str:
        value = chain.lower().strip()
        aliases = {
            "eth": "ethereum",
            "ethereum mainnet": "ethereum",
            "binance-smart-chain": "bsc",
            "bnb": "bsc",
            "bnb chain": "bsc",
            "bscscan": "bsc",
        }
        return aliases.get(value, value)
