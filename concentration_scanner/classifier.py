from __future__ import annotations

from dataclasses import dataclass

from .models import ClassifiedHolder, HolderRecord


EXCHANGE_KEYWORDS = (
    "binance",
    "bitget",
    "gate",
    "gate.io",
    "mexc",
    "okx",
    "kucoin",
    "coinbase",
    "kraken",
    "bybit",
    "htx",
    "huobi",
    "bithumb",
    "upbit",
    "bitfinex",
    "crypto.com",
    "etoro",
)

OWNER_RELATED_CATEGORIES = {"deployer", "owner", "admin", "proxy_admin", "possible_insider"}
PROTOCOL_RELATED_CATEGORIES = {"treasury", "dao_multisig", "protocol_contract", "vesting", "staking"}
DEFAULT_EXCLUDED_CATEGORIES = {
    "exchange",
    "liquidity_pool",
    "bridge",
    "burn",
    "staking",
    "vesting",
    "treasury",
    "protocol_contract",
}
DEAD_ADDRESSES = {
    "0x0000000000000000000000000000000000000000",
    "0x000000000000000000000000000000000000dead",
    "0x000000000000000000000000000000000000dEaD".lower(),
}


@dataclass(frozen=True)
class ManualOverride:
    address: str
    holder_category: str | None = None
    owner_relation: str | None = None
    excluded_from_adjusted_float: bool | None = None
    evidence_notes: str = "Manual override"


class HolderClassifier:
    def __init__(
        self,
        *,
        token_name: str = "",
        token_symbol: str = "",
        deployer_address: str = "",
        owner_address: str = "",
        admin_addresses: set[str] | None = None,
        proxy_admin_address: str = "",
    ) -> None:
        self.token_name = token_name.lower().strip()
        self.token_symbol = token_symbol.lower().strip()
        self.deployer_address = deployer_address.lower().strip()
        self.owner_address = owner_address.lower().strip()
        self.admin_addresses = {address.lower() for address in (admin_addresses or set()) if address}
        self.proxy_admin_address = proxy_admin_address.lower().strip()

    def classify_all(
        self,
        holders: list[HolderRecord],
        *,
        overrides: list[ManualOverride] | None = None,
    ) -> list[ClassifiedHolder]:
        classified = [self.classify(holder) for holder in holders]
        override_map = {override.address.lower(): override for override in overrides or []}
        if override_map:
            classified = [self.apply_override(holder, override_map.get(holder.address.lower())) for holder in classified]
        return classified

    def classify(self, holder: HolderRecord) -> ClassifiedHolder:
        label = holder.label.lower()
        address = holder.address.lower()
        category = "unknown_contract" if holder.is_contract else "unknown_wallet"
        relation = "unknown"
        confidence = "low"
        notes: list[str] = []

        if address in DEAD_ADDRESSES or "burn" in label or "dead" in label:
            category = "burn"
            confidence = "high"
            notes.append("Burn/dead address indicator")
        elif any(keyword in label for keyword in EXCHANGE_KEYWORDS):
            category = "exchange"
            confidence = "high"
            notes.append("Explorer label contains exchange keyword")
        elif "treasury" in label:
            category = "treasury"
            confidence = "high"
            notes.append("Explorer label contains treasury")
        elif "vesting" in label or "lockup" in label or "lock-up" in label:
            category = "vesting"
            confidence = "high"
            notes.append("Explorer label contains vesting/lockup")
        elif "staking" in label:
            category = "staking"
            confidence = "high"
            notes.append("Explorer label contains staking")
        elif "bridge" in label:
            category = "bridge"
            confidence = "high"
            notes.append("Explorer label contains bridge")
        elif any(word in label for word in ("liquidity", "pair", "pool", "uniswap", "pancakeswap")):
            category = "liquidity_pool"
            confidence = "high"
            notes.append("Explorer label contains liquidity pool keyword")
        elif any(word in label for word in ("gnosis safe", "safe proxy", "multisig", "multi-sig")):
            category = "dao_multisig"
            confidence = "high"
            notes.append("Explorer label contains multisig/safe keyword")
        elif self._looks_like_protocol_contract(label):
            category = "protocol_contract"
            confidence = "medium"
            notes.append("Label resembles project protocol/vault/voting contract")

        if self.deployer_address and address == self.deployer_address:
            category = "deployer"
            relation = "deployer"
            confidence = "high"
            notes.append("Matches deployer address")
        elif self.owner_address and address == self.owner_address:
            category = "owner"
            relation = "direct_owner"
            confidence = "high"
            notes.append("Matches owner address")
        elif self.proxy_admin_address and address == self.proxy_admin_address:
            category = "proxy_admin"
            relation = "proxy_admin"
            confidence = "high"
            notes.append("Matches proxy admin address")
        elif address in self.admin_addresses:
            category = "admin"
            relation = "admin_role_holder"
            confidence = "high"
            notes.append("Matches admin role holder")

        if category in {"unknown_wallet", "unknown_contract"} and holder.pct_total_supply > 5:
            category = "unexplained_whale"
            confidence = "medium" if holder.pct_total_supply <= 20 else "medium"
            notes.append("Unlabelled holder above 5% of supply")
        if self._funding_relation(holder):
            category = "possible_insider"
            relation = "same_funding_source"
            confidence = "medium"
            notes.append("Funding/source relation to owner/deployer/admin")

        round_allocation = self.is_round_allocation(holder)
        if round_allocation:
            notes.append("Clean round-number allocation in top 20")

        excluded = category in DEFAULT_EXCLUDED_CATEGORIES
        return ClassifiedHolder(
            **holder.__dict__,
            holder_category=category,
            owner_relation=relation if relation != "unknown" else "no_known_relation",
            is_owner_related=category in OWNER_RELATED_CATEGORIES,
            is_protocol_related=category in PROTOCOL_RELATED_CATEGORIES,
            is_unexplained_large_holder=category == "unexplained_whale",
            is_exchange_inventory=category == "exchange",
            is_round_allocation=round_allocation,
            evidence_confidence=confidence,
            evidence_notes="; ".join(notes) if notes else "No strong label or relationship evidence",
            excluded_from_adjusted_float=excluded,
        )

    def apply_override(self, holder: ClassifiedHolder, override: ManualOverride | None) -> ClassifiedHolder:
        if override is None:
            return holder
        category = override.holder_category or holder.holder_category
        relation = override.owner_relation or holder.owner_relation
        excluded = (
            override.excluded_from_adjusted_float
            if override.excluded_from_adjusted_float is not None
            else category in DEFAULT_EXCLUDED_CATEGORIES
        )
        return ClassifiedHolder(
            **{
                **holder.__dict__,
                "holder_category": category,
                "owner_relation": relation,
                "is_owner_related": category in OWNER_RELATED_CATEGORIES,
                "is_protocol_related": category in PROTOCOL_RELATED_CATEGORIES,
                "is_unexplained_large_holder": category == "unexplained_whale",
                "is_exchange_inventory": category == "exchange",
                "evidence_confidence": "high",
                "evidence_notes": override.evidence_notes or "Manual override",
                "excluded_from_adjusted_float": bool(excluded),
            }
        )

    def _looks_like_protocol_contract(self, label: str) -> bool:
        if not label:
            return False
        project_match = bool(self.token_name and self.token_name in label) or bool(self.token_symbol and self.token_symbol in label)
        return project_match and any(word in label for word in (" ve", "voting", "vault", "token", "protocol"))

    def _funding_relation(self, holder: HolderRecord) -> bool:
        related = {self.deployer_address, self.owner_address, self.proxy_admin_address, *self.admin_addresses}
        related = {item for item in related if item}
        sources = {holder.gas_funder.lower(), holder.token_source.lower(), holder.funding_source.lower()}
        return bool(related & sources)

    @staticmethod
    def is_round_allocation(holder: HolderRecord) -> bool:
        if holder.rank > 20 or holder.balance_decimal <= 0:
            return False
        value = abs(holder.balance_decimal)
        if value < 1_000:
            return float(value).is_integer()
        for step in (1_000_000_000, 100_000_000, 10_000_000, 1_000_000, 100_000, 10_000, 1_000):
            if value >= step and abs(value % step) < 1e-9:
                return True
        return False
