from __future__ import annotations

from .models import ClassifiedHolder, ConcentrationMetrics


def _sum_top(holders: list[ClassifiedHolder], n: int) -> float:
    return sum(max(0.0, holder.pct_total_supply) for holder in holders[:n])


def _gini(values: list[float]) -> float:
    positive = sorted(value for value in values if value >= 0)
    count = len(positive)
    if count == 0:
        return 0.0
    total = sum(positive)
    if total <= 0:
        return 0.0
    weighted = sum((index + 1) * value for index, value in enumerate(positive))
    return max(0.0, min(1.0, (2 * weighted) / (count * total) - (count + 1) / count))


def _hhi(shares_pct: list[float]) -> float:
    return sum((max(0.0, share) / 100.0) ** 2 for share in shares_pct) * 10_000.0


class ConcentrationEngine:
    def compute(
        self,
        holders: list[ClassifiedHolder],
        *,
        total_supply: float | None,
        circulating_supply: float | None = None,
    ) -> ConcentrationMetrics:
        sorted_holders = sorted(holders, key=lambda holder: holder.rank)
        supply = total_supply if total_supply and total_supply > 0 else circulating_supply
        partial = not bool(total_supply and total_supply > 0)
        if not supply or supply <= 0:
            observed = sum(holder.balance_decimal for holder in sorted_holders)
            supply = observed if observed > 0 else 0.0
            partial = True

        def pct(balance: float) -> float:
            return balance / supply * 100.0 if supply > 0 else 0.0

        excluded_balance = sum(holder.balance_decimal for holder in sorted_holders if holder.excluded_from_adjusted_float)
        adjusted_float = max(0.0, supply - excluded_balance)
        included = [holder for holder in sorted_holders if not holder.excluded_from_adjusted_float]
        included_by_balance = sorted(included, key=lambda holder: holder.balance_decimal, reverse=True)
        unexplained = [holder for holder in sorted_holders if holder.holder_category in {"unexplained_whale", "possible_insider", "unknown_wallet", "unknown_contract"}]
        real_wallets = [holder for holder in included_by_balance if holder.holder_category in {"real_wallet", "unknown_wallet", "unexplained_whale", "possible_insider"}]
        exchanges = [holder for holder in sorted_holders[:100] if holder.holder_category == "exchange"]

        def adjusted_top(n: int) -> float:
            if adjusted_float <= 0:
                return 0.0
            return sum(holder.balance_decimal for holder in included_by_balance[:n]) / adjusted_float * 100.0

        def adjusted_wallet_top(records: list[ClassifiedHolder], n: int) -> float:
            if adjusted_float <= 0:
                return 0.0
            return sum(holder.balance_decimal for holder in records[:n]) / adjusted_float * 100.0

        protocol_supply = sum(holder.pct_total_supply for holder in sorted_holders if holder.is_protocol_related)
        owner_supply = sum(holder.pct_total_supply for holder in sorted_holders if holder.is_owner_related)
        owner_adjusted = (
            sum(holder.balance_decimal for holder in sorted_holders if holder.is_owner_related) / adjusted_float * 100.0
            if adjusted_float > 0
            else 0.0
        )
        exchange_supply = sum(holder.pct_total_supply for holder in exchanges)
        largest_exchange = max(exchanges, key=lambda holder: holder.pct_total_supply, default=None)
        round_supply = sum(holder.pct_total_supply for holder in sorted_holders[:20] if holder.is_round_allocation)

        return ConcentrationMetrics(
            raw_top_1_pct=_sum_top(sorted_holders, 1),
            raw_top_3_pct=_sum_top(sorted_holders, 3),
            raw_top_5_pct=_sum_top(sorted_holders, 5),
            raw_top_10_pct=_sum_top(sorted_holders, 10),
            raw_top_20_pct=_sum_top(sorted_holders, 20),
            raw_top_50_pct=_sum_top(sorted_holders, 50),
            raw_top_100_pct=_sum_top(sorted_holders, 100),
            whale_concentration_pct=sum(holder.pct_total_supply for holder in sorted_holders if holder.pct_total_supply >= 1.0),
            holder_count=len(sorted_holders),
            whale_count=sum(1 for holder in sorted_holders if holder.pct_total_supply >= 1.0),
            concentration_gini=_gini([holder.balance_decimal for holder in sorted_holders]),
            holder_hhi_index=_hhi([holder.pct_total_supply for holder in sorted_holders]),
            adjusted_float_supply=adjusted_float,
            adjusted_float_pct_total_supply=pct(adjusted_float),
            excluded_supply_pct=pct(excluded_balance),
            adjusted_top_1_pct=adjusted_top(1),
            adjusted_top_5_pct=adjusted_top(5),
            adjusted_top_10_pct=adjusted_top(10),
            adjusted_top_20_pct=adjusted_top(20),
            adjusted_top_50_pct=adjusted_top(50),
            adjusted_top_100_pct=adjusted_top(100),
            largest_unexplained_holder_pct=max((holder.pct_total_supply for holder in unexplained), default=0.0),
            unexplained_top_5_pct=sum(holder.pct_total_supply for holder in unexplained[:5]),
            unexplained_top_10_pct=sum(holder.pct_total_supply for holder in unexplained[:10]),
            top_5_real_wallets_pct_adjusted_float=adjusted_wallet_top(real_wallets, 5),
            top_10_real_wallets_pct_adjusted_float=adjusted_wallet_top(real_wallets, 10),
            protocol_related_supply_pct=protocol_supply,
            owner_related_cluster_pct=owner_supply,
            owner_related_adjusted_float_pct=owner_adjusted,
            exchange_supply_pct_top_100=exchange_supply,
            largest_exchange_holder_pct_total_supply=largest_exchange.pct_total_supply if largest_exchange else 0.0,
            largest_exchange_holder_rank=largest_exchange.rank if largest_exchange else None,
            round_allocation_supply_pct_top_20=round_supply,
            data_confidence="low" if partial else "medium",
            partial_result=partial,
        )

    def recompute_with_overrides(
        self,
        holders: list[ClassifiedHolder],
        *,
        total_supply: float | None,
        circulating_supply: float | None = None,
    ) -> ConcentrationMetrics:
        return self.compute(holders, total_supply=total_supply, circulating_supply=circulating_supply)
