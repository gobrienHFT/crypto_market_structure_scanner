from __future__ import annotations

from collections import defaultdict

from .models import ClassifiedHolder, ManipulableWhaleMetrics, WalletCluster, WalletForensics
from .risk import cap_score


BENIGN_STORAGE_CATEGORIES = {
    "exchange",
    "bridge",
    "wrapper",
    "liquidity_pool",
    "burn",
    "staking",
    "vesting",
    "treasury",
    "treasury_reserve",
    "dao_multisig_reserve",
    "protocol_contract",
    "protocol_storage",
    "claim_distribution_reserve",
}
MANIPULABLE_CATEGORIES = {
    "unexplained_whale",
    "unknown_wallet",
    "unknown_contract",
    "possible_insider",
    "owner",
    "deployer",
    "admin",
    "proxy_admin",
    "market_maker",
    "dao_multisig",
}
CEX_CATEGORIES = {"exchange"}
PROTOCOL_STORAGE_CATEGORIES = {"staking", "protocol_contract", "protocol_storage", "claim_distribution_reserve"}
TREASURY_STORAGE_CATEGORIES = {"treasury", "treasury_reserve", "dao_multisig_reserve"}
VESTING_LOCKUP_CATEGORIES = {"vesting"}
BRIDGE_WRAPPER_CATEGORIES = {"bridge", "wrapper"}


def manipulable_whale_label(score: float) -> str:
    if score >= 75:
        return "Extreme manipulable whale risk"
    if score >= 50:
        return "High manipulable whale risk"
    if score >= 25:
        return "Medium manipulable whale risk"
    return "Low manipulable whale risk"


class ManipulableWhaleEngine:
    def compute(self, holders: list[ClassifiedHolder], *, adjusted_float_supply: float = 0.0) -> tuple[ManipulableWhaleMetrics, list[WalletForensics], list[WalletCluster]]:
        sorted_holders = sorted(holders, key=lambda holder: holder.rank)
        round_allocations_top_20 = sum(1 for holder in sorted_holders[:20] if holder.is_round_allocation)
        forensics = [
            self._forensics_for_holder(holder, sorted_holders, round_allocations_top_20=round_allocations_top_20)
            for holder in sorted_holders[:20]
        ]
        score_by_address = {item.address.lower(): item.manipulable_whale_score for item in forensics}
        manipulable = [holder for holder in sorted_holders if self.is_manipulable_holder(holder)]
        manipulable_top_20 = [holder for holder in sorted_holders[:20] if self.is_manipulable_holder(holder)]
        manipulable_top_100 = [holder for holder in sorted_holders[:100] if self.is_manipulable_holder(holder)]
        largest = max(manipulable, key=lambda holder: holder.pct_total_supply, default=None)
        clusters = self._clusters(sorted_holders, forensics=forensics, adjusted_float_supply=adjusted_float_supply)
        largest_cluster = max(clusters, key=lambda cluster: cluster.cluster_manipulable_supply_pct, default=None)
        key_flags = sorted({flag for item in forensics for flag in item.forensic_flags})
        if largest_cluster:
            key_flags.extend(flag for flag in largest_cluster.cluster_reason_codes if flag not in key_flags)
        evidence = self._evidence_summary(sorted_holders, largest, largest_cluster)
        metrics = ManipulableWhaleMetrics(
            filtered_top_1_manipulable_pct=self._filtered_top(sorted_holders, 1),
            filtered_top_3_manipulable_pct=self._filtered_top(sorted_holders, 3),
            filtered_top_5_manipulable_pct=self._filtered_top(sorted_holders, 5),
            filtered_top_10_manipulable_pct=self._filtered_top(sorted_holders, 10),
            largest_manipulable_holder_pct=largest.pct_total_supply if largest else 0.0,
            largest_manipulable_holder_address=largest.address if largest else "",
            largest_manipulable_holder_category=largest.holder_category if largest else "",
            largest_manipulable_holder_score=score_by_address.get(largest.address.lower(), 0.0) if largest else 0.0,
            manipulable_holder_count_top_20=len(manipulable_top_20),
            manipulable_holder_count_top_100=len(manipulable_top_100),
            manipulable_supply_pct_top_20=sum(holder.pct_total_supply for holder in manipulable_top_20),
            manipulable_supply_pct_top_100=sum(holder.pct_total_supply for holder in manipulable_top_100),
            cex_storage_supply_pct=sum(holder.pct_total_supply for holder in sorted_holders[:100] if holder.holder_category in CEX_CATEGORIES),
            protocol_storage_supply_pct=sum(holder.pct_total_supply for holder in sorted_holders[:100] if holder.holder_category in PROTOCOL_STORAGE_CATEGORIES),
            treasury_storage_supply_pct=sum(holder.pct_total_supply for holder in sorted_holders[:100] if holder.holder_category in TREASURY_STORAGE_CATEGORIES),
            vesting_lockup_supply_pct=sum(holder.pct_total_supply for holder in sorted_holders[:100] if holder.holder_category in VESTING_LOCKUP_CATEGORIES),
            bridge_wrapper_supply_pct=sum(holder.pct_total_supply for holder in sorted_holders[:100] if holder.holder_category in BRIDGE_WRAPPER_CATEGORIES),
            cluster_manipulable_supply_pct=largest_cluster.cluster_manipulable_supply_pct if largest_cluster else 0.0,
            cluster_adjusted_float_pct=largest_cluster.cluster_adjusted_float_pct if largest_cluster else 0.0,
            cluster_confidence=largest_cluster.cluster_confidence if largest_cluster else "low",
            cex_outflow_7d=sum(item.cex_deposit_outflow_7d for item in forensics),
            suspicious_timing_score=max((item.suspicious_timing_score for item in forensics), default=0.0),
            key_forensic_flags=key_flags,
            evidence_confidence="medium" if any(item.forensic_flags for item in forensics) else "low",
            evidence_summary=evidence,
        )
        return metrics, forensics, clusters

    def is_manipulable_holder(self, holder: ClassifiedHolder) -> bool:
        if holder.holder_category in BENIGN_STORAGE_CATEGORIES:
            return False
        if holder.holder_category in MANIPULABLE_CATEGORIES:
            return True
        return not holder.excluded_from_adjusted_float

    def _filtered_top(self, holders: list[ClassifiedHolder], n: int) -> float:
        return sum(holder.pct_total_supply for holder in holders[:n] if self.is_manipulable_holder(holder))

    def _forensics_for_holder(
        self,
        holder: ClassifiedHolder,
        holders: list[ClassifiedHolder],
        *,
        round_allocations_top_20: int,
    ) -> WalletForensics:
        score = 0.0
        flags: list[str] = []
        category = holder.holder_category
        label = holder.label.lower()
        benign_storage = category in BENIGN_STORAGE_CATEGORIES
        if category == "unexplained_whale" and not holder.is_contract:
            score += 35
            flags.append("unexplained_eoa_whale")
        elif category == "unknown_contract" or (category == "unexplained_whale" and holder.is_contract):
            score += 25
            flags.append("unexplained_contract_wallet")
        elif category == "possible_insider":
            score += 25
            flags.append("possible_insider")
        elif category == "market_maker":
            score += 20
            flags.append("unclear_market_maker")
        elif category == "dao_multisig":
            score += 10
            flags.append("unclear_safe_or_multisig")
        elif category == "exchange":
            score -= 40
            flags.append("confirmed_cex_storage")
        elif category in {"bridge", "wrapper"}:
            score -= 35
            flags.append("confirmed_bridge_wrapper_storage")
        elif category == "vesting":
            score -= 35
            flags.append("confirmed_vesting_lockup")
        elif category == "burn":
            score -= 30
            flags.append("burn_address")
        elif category == "liquidity_pool":
            score -= 25
            flags.append("lp_pool")
        elif category in PROTOCOL_STORAGE_CATEGORIES:
            score -= 25
            flags.append("protocol_storage")
        elif category in TREASURY_STORAGE_CATEGORIES:
            score -= 20
            flags.append("treasury_or_reserve_storage")

        relation = holder.owner_relation
        source_text = " ".join([holder.token_source, holder.funding_source, holder.gas_funder, holder.evidence_notes]).lower()
        top_5_manipulable = sum(item.pct_total_supply for item in holders[:5] if self.is_manipulable_holder(item))
        if not benign_storage:
            score += self._supply_control_points(holder.pct_total_supply)
            if top_5_manipulable > 70:
                score += 60
                flags.append("top5_manipulable_over_70")
            elif top_5_manipulable > 50:
                score += 45
                flags.append("top5_manipulable_over_50")
            elif top_5_manipulable > 30:
                score += 25
                flags.append("top5_manipulable_over_30")
            if relation in {"deployer", "deployer_funded", "same_token_distribution_source"} or "deployer" in source_text:
                score += 35
                flags.append("deployer_funded")
            if relation in {"owner_funded", "admin_role_holder", "proxy_admin"} or "owner" in source_text or "admin" in source_text:
                score += 35
                flags.append("owner_admin_funded")
            if "treasury" in source_text and category not in TREASURY_STORAGE_CATEGORIES:
                score += 25
                flags.append("treasury_source_unlabeled_wallet")
            if holder.gas_funder and sum(1 for item in holders[:20] if item.gas_funder and item.gas_funder == holder.gas_funder) > 1:
                score += 20
                flags.append("same_gas_funder")
            if holder.token_source and sum(1 for item in holders[:20] if item.token_source and item.token_source == holder.token_source) > 1:
                score += 20
                flags.append("same_token_source")
            if holder.is_round_allocation and holder.pct_total_supply >= 5:
                score += 15
                flags.append("round_allocation")
            if round_allocations_top_20 >= 3 and top_5_manipulable > 30:
                score += 25
                flags.append("round_allocation_cluster")
            if round_allocations_top_20 >= 5 and holder.rank <= 5 and top_5_manipulable > 30:
                score += 30
                flags.append("top5_round_allocation_cluster")
            if (holder.net_balance_change_7d or 0.0) < 0:
                score += 25
                flags.append("balance_decreased_after_price_expansion")
        evidence_text = f"{holder.evidence_notes} {source_text}".lower()
        if any(keyword in evidence_text for keyword in ("cex", "mexc", "gate", "binance", "bitget", "deposit")):
            score += 35
            flags.append("cex_distribution_after_pump")
        if "dex" in evidence_text or "router" in evidence_text:
            score += 20
            flags.append("dex_router_interaction")
        if "fresh" in evidence_text or "purpose-built" in evidence_text:
            score += 15
            flags.append("purpose_built_wallet")

        return WalletForensics(
            address=holder.address,
            is_eoa=not holder.is_contract,
            is_contract=holder.is_contract,
            contract_name=holder.label,
            safe_multisig_detected=category in {"dao_multisig", "dao_multisig_reserve"},
            first_bnb_or_eth_funder=holder.gas_funder,
            first_token_source=holder.token_source,
            token_source_category=holder.owner_relation,
            gas_funder_category="shared" if "same_gas_funder" in flags else "unknown",
            deployer_relation=holder.owner_relation if "deployer" in holder.owner_relation else "unknown",
            owner_admin_relation=holder.owner_relation if "owner" in holder.owner_relation or "admin" in holder.owner_relation else "unknown",
            shared_gas_cluster_id=f"gas:{holder.gas_funder.lower()}" if holder.gas_funder else "",
            shared_token_source_cluster_id=f"source:{holder.token_source.lower()}" if holder.token_source else "",
            current_balance=holder.balance_decimal,
            net_balance_change_24h=holder.net_balance_change_24h,
            net_balance_change_7d=holder.net_balance_change_7d,
            cex_deposit_outflow_7d=abs(holder.net_balance_change_7d or 0.0) if "cex_distribution_after_pump" in flags else 0.0,
            wallet_purity_score=60.0 if "purpose_built_wallet" in flags else (40.0 if holder.rank <= 20 and not label else 0.0),
            suspicious_timing_score=80.0 if "cex_distribution_after_pump" in flags else (50.0 if (holder.net_balance_change_7d or 0.0) < 0 else 0.0),
            manipulable_whale_score=cap_score(score),
            forensic_flags=flags,
            evidence_notes=", ".join(flags) if flags else holder.evidence_notes,
        )

    def _supply_control_points(self, pct: float) -> float:
        if pct > 75:
            return 60
        if pct > 50:
            return 50
        if pct > 20:
            return 35
        if pct > 10:
            return 20
        return 0

    def _clusters(
        self,
        holders: list[ClassifiedHolder],
        *,
        forensics: list[WalletForensics],
        adjusted_float_supply: float,
    ) -> list[WalletCluster]:
        clusters: list[WalletCluster] = []
        by_reason: dict[str, list[ClassifiedHolder]] = defaultdict(list)
        for holder in holders[:20]:
            if holder.gas_funder:
                by_reason[f"same_gas_funder:{holder.gas_funder.lower()}"].append(holder)
            if holder.token_source:
                by_reason[f"same_token_source:{holder.token_source.lower()}"].append(holder)
        round_cluster = [holder for holder in holders[:20] if holder.is_round_allocation and self.is_manipulable_holder(holder)]
        if len(round_cluster) >= 3:
            by_reason["round_allocation_cluster:top20"].extend(round_cluster)
        forensic_by_address = {item.address.lower(): item for item in forensics}
        for reason, members in by_reason.items():
            unique = {member.address.lower(): member for member in members if self.is_manipulable_holder(member)}
            if len(unique) < 2:
                continue
            cluster_members = list(unique.values())
            supply = sum(member.pct_total_supply for member in cluster_members)
            balance = sum(member.balance_decimal for member in cluster_members)
            reason_code = reason.split(":", 1)[0]
            cex_outflow_7d = sum(forensic_by_address.get(member.address.lower(), WalletForensics(address=member.address)).cex_deposit_outflow_7d for member in cluster_members)
            confidence = "high" if reason_code in {"same_gas_funder", "same_token_source"} else "medium"
            clusters.append(
                WalletCluster(
                    cluster_id=reason,
                    addresses=[member.address for member in cluster_members],
                    cluster_reason_codes=[reason_code],
                    cluster_confidence=confidence,
                    cluster_total_supply_pct=supply,
                    cluster_adjusted_float_pct=balance / adjusted_float_supply * 100.0 if adjusted_float_supply > 0 else 0.0,
                    cluster_manipulable_supply_pct=supply,
                    cluster_largest_holder_pct=max(member.pct_total_supply for member in cluster_members),
                    cluster_cex_outflow_7d=cex_outflow_7d,
                    cluster_forensic_summary=f"{len(cluster_members)} top holders linked by {reason_code}; combined manipulable supply {supply:.2f}%.",
                    deployer_funded_cluster=any(member.owner_relation in {"deployer", "deployer_funded"} for member in cluster_members),
                    same_gas_funder_cluster=reason_code == "same_gas_funder",
                    same_token_source_cluster=reason_code == "same_token_source",
                    round_allocation_cluster=reason_code == "round_allocation_cluster",
                    cex_distribution_cluster=cex_outflow_7d > 0,
                )
            )
        return sorted(clusters, key=lambda item: item.cluster_manipulable_supply_pct, reverse=True)

    def _evidence_summary(
        self,
        holders: list[ClassifiedHolder],
        largest: ClassifiedHolder | None,
        largest_cluster: WalletCluster | None,
    ) -> str:
        if not holders:
            return "No holder data was available, so manipulable-whale analysis is incomplete."
        top = holders[0]
        if top.holder_category in BENIGN_STORAGE_CATEGORIES:
            return (
                f"Raw top-1 concentration is {top.pct_total_supply:.2f}%, but the top holder is classified as {top.holder_category}. "
                "It is treated as custody/storage rather than an anonymous tradable-float whale unless later forensic evidence shows active distribution."
            )
        if largest:
            cluster_text = (
                f" The largest linked cluster controls {largest_cluster.cluster_manipulable_supply_pct:.2f}% of supply."
                if largest_cluster and largest_cluster.cluster_manipulable_supply_pct > 0
                else ""
            )
            return (
                f"After excluding CEX, LP, burn, bridge, wrapper, vesting, lockup, and confirmed reserve/storage addresses, "
                f"the largest remaining holder is {largest.holder_category} at {largest.pct_total_supply:.2f}% of supply.{cluster_text}"
            )
        return "After custody/storage filters, no large manipulable holder remains in the current top-holder sample."
