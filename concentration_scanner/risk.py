from __future__ import annotations

from .models import (
    ClassifiedHolder,
    ConcentrationMetrics,
    ContractControlStats,
    RepresentationStats,
    RiskFlags,
    RiskScores,
    ThinFloatStats,
    TokenMarketData,
)


def cap_score(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def risk_label(score: float) -> str:
    if score >= 75:
        return "Extreme"
    if score >= 50:
        return "High"
    if score >= 25:
        return "Medium"
    return "Low"


def _points(value: float | None, thresholds: list[tuple[float, float]]) -> float:
    if value is None:
        return 0.0
    score = 0.0
    for threshold, points in thresholds:
        if value > threshold:
            score = max(score, points)
    return score


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


class RiskScoringEngine:
    unresolved_categories = {"unknown_wallet", "unknown_contract", "unexplained_whale", "possible_insider"}

    def compute_thin_float_stats(self, market: TokenMarketData, metrics: ConcentrationMetrics) -> ThinFloatStats:
        circulating_to_total = _ratio(market.circulating_supply, market.total_supply)
        fdv_to_mcap = _ratio(market.fully_diluted_valuation, market.market_cap)
        volume_to_mcap = _ratio(market.volume_24h, market.market_cap)
        float_mcap = market.market_cap * ((100.0 - metrics.raw_top_100_pct) / 100.0) if market.market_cap else None
        volume_to_float_mcap = _ratio(market.volume_24h, float_mcap)
        ath_multiple = _ratio(market.all_time_high_price, market.all_time_low_price)
        drawdown = (
            (market.all_time_high_price - market.current_price) / market.all_time_high_price * 100.0
            if market.all_time_high_price and market.current_price and market.all_time_high_price > 0
            else None
        )
        peak_market_cap = market.peak_market_cap or market.market_cap
        peak_fdv = market.peak_fdv or market.fully_diluted_valuation
        non_top100 = max(0.0, 100.0 - metrics.raw_top_100_pct)
        non_top10 = max(0.0, 100.0 - metrics.raw_top_10_pct)
        return ThinFloatStats(
            circulating_to_total_supply_pct=circulating_to_total * 100.0 if circulating_to_total is not None else None,
            fdv_to_market_cap_ratio=fdv_to_mcap,
            volume_to_market_cap_ratio=volume_to_mcap,
            volume_to_float_market_cap_ratio=volume_to_float_mcap,
            recent_pump_score=cap_score(max(market.price_change_24h or 0.0, market.price_change_7d or 0.0, market.price_change_30d or 0.0) / 5.0),
            squeeze_proxy_score=cap_score((volume_to_mcap or 0.0) * 30.0 + _points(circulating_to_total * 100.0 if circulating_to_total is not None else None, [(0, 0)]) ),
            ath_multiple_from_atl=ath_multiple,
            current_drawdown_from_ath_pct=drawdown,
            peak_market_cap=peak_market_cap,
            current_market_cap=market.market_cap,
            peak_fdv=peak_fdv,
            current_fdv=market.fully_diluted_valuation,
            peak_volume_24h=market.peak_volume_24h or market.volume_24h,
            max_24h_price_change=market.max_24h_price_change,
            max_7d_price_change=market.max_7d_price_change,
            max_30d_price_change=market.max_30d_price_change,
            peak_volume_to_market_cap_ratio=_ratio(market.peak_volume_24h or market.volume_24h, peak_market_cap),
            peak_volume_to_float_market_cap_ratio=_ratio(market.peak_volume_24h or market.volume_24h, peak_market_cap * (non_top100 / 100.0) if peak_market_cap else None),
            estimated_non_top100_float_pct=non_top100,
            estimated_non_top10_float_pct=non_top10,
            peak_value_of_non_top100_float=peak_market_cap * non_top100 / 100.0 if peak_market_cap is not None else None,
            peak_value_of_non_top10_float=peak_market_cap * non_top10 / 100.0 if peak_market_cap is not None else None,
            top_1_wallet_peak_value=peak_market_cap * metrics.raw_top_1_pct / 100.0 if peak_market_cap is not None else None,
            top_5_wallet_peak_value=peak_market_cap * metrics.raw_top_5_pct / 100.0 if peak_market_cap is not None else None,
        )

    def compute_flags(
        self,
        *,
        holders: list[ClassifiedHolder],
        metrics: ConcentrationMetrics,
        market: TokenMarketData,
        thin: ThinFloatStats,
    ) -> RiskFlags:
        top_1_category = holders[0].holder_category if holders else "unknown_wallet"
        circulating_pct = thin.circulating_to_total_supply_pct
        fdv_ratio = thin.fdv_to_market_cap_ratio
        volume_mcap = thin.volume_to_market_cap_ratio
        bitget_rank_1 = bool(holders and holders[0].holder_category == "exchange" and "bitget" in holders[0].label.lower())
        controlled = (
            (circulating_pct is not None and circulating_pct < 10)
            and metrics.raw_top_100_pct > 95
            and metrics.raw_top_5_pct > 60
            and (any(holder.holder_category == "exchange" and holder.rank <= 5 for holder in holders) or metrics.exchange_supply_pct_top_100 > 10)
            and ((market.price_change_30d or 0.0) > 300 or (volume_mcap or 0.0) > 1)
        )
        extreme_controlled = (
            (circulating_pct is not None and circulating_pct < 10)
            and metrics.raw_top_100_pct > 99
            and metrics.raw_top_5_pct > 80
            and metrics.largest_exchange_holder_pct_total_supply > 20
            and metrics.round_allocation_supply_pct_top_20 > 50
            and (market.price_change_30d or 0.0) > 500
        )
        ravedao = (
            (thin.ath_multiple_from_atl or 0.0) > 20
            and metrics.raw_top_5_pct > 80
            and metrics.raw_top_100_pct > 99
            and metrics.largest_unexplained_holder_pct > 20
        )
        extreme_ravedao = (
            (thin.ath_multiple_from_atl or 0.0) > 50
            and metrics.raw_top_1_pct > 50
            and metrics.raw_top_5_pct > 90
            and metrics.raw_top_100_pct > 99
            and ((thin.peak_market_cap or 0.0) > 1_000_000_000 or (thin.current_drawdown_from_ath_pct or 0.0) > 70)
        )
        return RiskFlags(
            dominant_holder_warning=metrics.raw_top_1_pct > 20,
            extreme_dominant_holder=metrics.raw_top_1_pct > 50,
            nuclear_dominant_holder=metrics.raw_top_1_pct > 75,
            unresolved_dominant_holder=metrics.raw_top_1_pct > 20 and top_1_category in self.unresolved_categories,
            adjusted_dominant_holder_extreme=metrics.adjusted_top_1_pct > 30,
            adjusted_top5_extreme=metrics.adjusted_top_5_pct > 60,
            adjusted_top10_extreme=metrics.adjusted_top_10_pct > 80,
            fake_float_structure=metrics.raw_top_100_pct > 95 and metrics.adjusted_float_pct_total_supply < 10,
            cap_table_token=metrics.raw_top_5_pct > 90 or metrics.raw_top_1_pct > 50,
            one_wallet_market=metrics.raw_top_1_pct > 75,
            dominant_unexplained_holder=metrics.largest_unexplained_holder_pct > 30,
            protocol_multisig_concentration=metrics.protocol_related_supply_pct > 20
            or any(holder.holder_category == "dao_multisig" and holder.rank <= 5 and holder.pct_total_supply > 10 for holder in holders),
            high_protocol_control=metrics.protocol_related_supply_pct > 40,
            high_unexplained_whale_control=metrics.unexplained_top_5_pct > 30,
            possible_distribution_wallets=any((holder.net_balance_change_24h or 0.0) < 0 and holder.rank <= 20 for holder in holders),
            low_float=circulating_pct is not None and circulating_pct < 10,
            extreme_low_float=circulating_pct is not None and circulating_pct < 5,
            fdv_overhang=fdv_ratio is not None and fdv_ratio > 5,
            extreme_fdv_overhang=fdv_ratio is not None and fdv_ratio > 10,
            top_100_supply_capture=metrics.raw_top_100_pct > 95,
            extreme_top_100_supply_capture=metrics.raw_top_100_pct > 99,
            exchange_inventory_dominance=metrics.exchange_supply_pct_top_100 > 10,
            cex_rank_1_wallet=bool(holders and holders[0].holder_category == "exchange"),
            bitget_rank_1_inventory_dominance=bitget_rank_1 and metrics.raw_top_1_pct > 20,
            round_allocation_cluster=sum(1 for holder in holders[:20] if holder.is_round_allocation) >= 3,
            controlled_float_squeeze_structure=controlled,
            extreme_controlled_float_squeeze_structure=extreme_controlled,
            ravedao_archetype=ravedao,
            extreme_ravedao_archetype=extreme_ravedao,
            one_wallet_mark_to_market=metrics.raw_top_1_pct > 50 and (thin.peak_market_cap or 0.0) > 500_000_000,
            cap_table_marked_to_market=metrics.raw_top_5_pct > 90 and (thin.peak_market_cap or 0.0) > 500_000_000,
            tiny_public_float_marked_to_large_market_cap=thin.estimated_non_top100_float_pct < 1 and (thin.peak_market_cap or 0.0) > 500_000_000,
            historical_pump_with_dominant_holder=(thin.ath_multiple_from_atl or 0.0) > 20 and metrics.raw_top_1_pct > 20,
            collapsed_after_concentrated_pump=(thin.ath_multiple_from_atl or 0.0) > 20 and (thin.current_drawdown_from_ath_pct or 0.0) > 70 and metrics.raw_top_5_pct > 80,
            billion_dollar_thin_float_print=(thin.peak_market_cap or 0.0) > 1_000_000_000 and metrics.raw_top_100_pct > 99 and thin.estimated_non_top100_float_pct < 1,
            unresolved_dominant_holder_after_pump=(thin.ath_multiple_from_atl or 0.0) > 20 and metrics.raw_top_1_pct > 20 and top_1_category in self.unresolved_categories,
            fake_headline_market_cap_risk=thin.estimated_non_top100_float_pct < 1 and metrics.raw_top_100_pct > 99,
            thin_float_mark_to_market=thin.estimated_non_top100_float_pct < 5 and (thin.peak_market_cap or 0.0) > 100_000_000,
            peak_valuation_distortion=thin.estimated_non_top100_float_pct < 1 and (thin.peak_market_cap or 0.0) > 1_000_000_000,
        )

    def compute_scores(
        self,
        *,
        metrics: ConcentrationMetrics,
        contract: ContractControlStats,
        thin: ThinFloatStats,
        flags: RiskFlags,
    ) -> RiskScores:
        concentration = cap_score(
            _points(metrics.raw_top_5_pct, [(50, 20), (60, 35), (80, 50)])
            + _points(metrics.raw_top_10_pct, [(70, 20), (85, 35)])
            + _points(metrics.raw_top_100_pct, [(99, 30)])
        )
        unexplained = cap_score(_points(metrics.largest_unexplained_holder_pct, [(5, 20), (10, 35), (20, 60), (30, 75)]))
        owner = cap_score(
            _points(metrics.owner_related_cluster_pct, [(10, 25), (20, 45)])
            + _points(metrics.owner_related_adjusted_float_pct, [(25, 60)])
        )
        protocol = cap_score(_points(metrics.protocol_related_supply_pct, [(20, 15), (40, 30), (60, 45)]))
        exchange = cap_score(
            _points(metrics.exchange_supply_pct_top_100, [(10, 15), (20, 30)])
            + (20 if metrics.largest_exchange_holder_rank is not None and metrics.largest_exchange_holder_rank <= 5 else 0)
        )
        controlled_float = cap_score(
            _points(thin.circulating_to_total_supply_pct, [(0, 0)])  # placeholder for type stability
            + (25 if thin.circulating_to_total_supply_pct is not None and thin.circulating_to_total_supply_pct < 10 else 0)
            + (40 if thin.circulating_to_total_supply_pct is not None and thin.circulating_to_total_supply_pct < 5 else 0)
            + (20 if thin.fdv_to_market_cap_ratio is not None and thin.fdv_to_market_cap_ratio > 5 else 0)
            + (35 if thin.fdv_to_market_cap_ratio is not None and thin.fdv_to_market_cap_ratio > 10 else 0)
            + (30 if metrics.raw_top_100_pct > 99 else 0)
        )
        distribution = cap_score(
            (20 if flags.possible_distribution_wallets else 0)
            + (35 if flags.high_unexplained_whale_control and flags.possible_distribution_wallets else 0)
        )
        ravedao = self.ravedao_score(metrics=metrics, thin=thin)
        composite = cap_score(
            concentration * 0.20
            + unexplained * 0.20
            + owner * 0.15
            + protocol * 0.10
            + exchange * 0.10
            + contract.admin_privilege_score * 0.10
            + controlled_float * 0.10
            + distribution * 0.05
        )
        if flags.dominant_unexplained_holder and metrics.raw_top_5_pct > 60:
            composite = max(composite, 50.0)
        if flags.controlled_float_squeeze_structure:
            composite = max(composite, 75.0 if flags.extreme_controlled_float_squeeze_structure else 50.0)
        confidence = "high" if not metrics.partial_result and contract.contract_verified else ("medium" if not metrics.partial_result else "low")
        return RiskScores(
            concentration_score=concentration,
            unexplained_whale_score=unexplained,
            owner_related_score=owner,
            protocol_control_score=protocol,
            exchange_inventory_score=exchange,
            contract_admin_score=contract.admin_privilege_score,
            distribution_risk_score=distribution,
            controlled_float_score=controlled_float,
            ravedao_archetype_score=ravedao,
            composite_structural_manipulation_risk_score=composite,
            risk_label=risk_label(max(composite, ravedao if ravedao >= 75 else composite)),
            confidence=confidence,
        )

    def ravedao_score(self, *, metrics: ConcentrationMetrics, thin: ThinFloatStats) -> float:
        score = 0.0
        score += _points(thin.ath_multiple_from_atl, [(20, 20), (50, 35), (100, 50)])
        score += _points(metrics.raw_top_1_pct, [(30, 20), (50, 40), (75, 60)])
        score += _points(metrics.raw_top_5_pct, [(80, 30), (90, 50)])
        score += 30 if metrics.raw_top_100_pct > 99 else 0
        score += 30 if metrics.concentration_gini > 0.99 else 0
        score += _points(metrics.largest_unexplained_holder_pct, [(20, 40), (50, 60)])
        score += _points(thin.current_drawdown_from_ath_pct, [(70, 30), (90, 50)])
        score += _points(thin.peak_market_cap, [(1_000_000_000, 25), (5_000_000_000, 40)])
        score += 50 if thin.estimated_non_top100_float_pct < 1 else 0
        return cap_score(score)

    def representation_guardrail(
        self,
        *,
        inspected_chain: str,
        market: TokenMarketData,
        metrics: ConcentrationMetrics,
    ) -> RepresentationStats:
        canonical = market.canonical_chain or inspected_chain
        wrapped = bool(market.is_native_asset and inspected_chain != canonical) or bool(canonical and inspected_chain and canonical != inspected_chain)
        wrapper_score = risk_label(metrics.raw_top_100_pct if metrics.raw_top_100_pct <= 100 else 100)
        exchange_dominated = metrics.exchange_supply_pct_top_100 > 10
        return RepresentationStats(
            inspected_chain=inspected_chain,
            canonical_chain=canonical,
            is_native_asset=market.is_native_asset,
            is_wrapped_or_bridged_representation=wrapped,
            holder_table_represents_global_supply=not wrapped,
            representation_confidence="low" if wrapped else "high",
            wrapper_concentration_score=100.0 if metrics.raw_top_100_pct > 95 else cap_score(metrics.raw_top_100_pct),
            global_concentration_score=0.0 if wrapped else cap_score(metrics.raw_top_100_pct),
            concentration_score_confidence="low" if wrapped else metrics.data_confidence,
            wrapped_representation_warning=wrapped,
            holder_table_not_global_supply=wrapped,
            cex_custody_dominated_wrapper=wrapped and exchange_dominated,
            bridge_or_wrapper_concentration=wrapped and metrics.raw_top_100_pct > 95,
            native_chain_data_required=wrapped,
            false_positive_concentration_risk=wrapped,
        )

    def key_flags(self, flags: RiskFlags, representation: RepresentationStats) -> list[str]:
        labels: list[str] = []
        mapping = {
            "RaveDAO-Type Extreme": flags.extreme_ravedao_archetype,
            "RaveDAO-Type Structure": flags.ravedao_archetype,
            "dominant-holder risk": flags.dominant_holder_warning,
            "unresolved dominant holder": flags.unresolved_dominant_holder,
            "controlled-float squeeze structure": flags.controlled_float_squeeze_structure,
            "extreme controlled-float squeeze": flags.extreme_controlled_float_squeeze_structure,
            "thin-float market-cap risk": flags.fake_headline_market_cap_risk,
            "wrapped representation warning": representation.wrapped_representation_warning,
            "Bitget rank-1 inventory dominance": flags.bitget_rank_1_inventory_dominance,
            "round allocation cluster": flags.round_allocation_cluster,
        }
        for label, enabled in mapping.items():
            if enabled:
                labels.append(label)
        return labels

    def summary(self, *, flags: RiskFlags, representation: RepresentationStats, token_name: str) -> str:
        name = token_name or "This token"
        if representation.wrapped_representation_warning:
            return (
                "This holder table appears to represent a wrapped or chain-specific version of the asset, not necessarily global ownership. "
                "Concentration is extreme within this representation, but global manipulation risk should not be inferred without native-chain holder/staking data."
            )
        if flags.extreme_ravedao_archetype or flags.ravedao_archetype:
            return (
                f"{name} matches the RaveDAO archetype: extreme historical price expansion, extreme holder concentration, "
                "and likely thin-float market-cap distortion. One unresolved holder controls a dominant share of supply, "
                "while the top 100 holders control nearly all supply. This does not prove manipulation, but it indicates "
                "severe float-control, distribution-overhang, and fake headline market-cap risk."
            )
        if flags.extreme_controlled_float_squeeze_structure or flags.controlled_float_squeeze_structure:
            return (
                f"{name} has a controlled-float squeeze structure: low circulating supply, high top-holder concentration, "
                "visible exchange inventory, round-allocation patterns, and recent price expansion. This does not prove manipulation, "
                "but it indicates high float-control, liquidation-cascade, and distribution risk."
            )
        if flags.dominant_unexplained_holder or flags.unresolved_dominant_holder:
            return (
                f"{name} has high structural concentration risk because one unresolved wallet controls a large share of supply. "
                "This does not prove manipulation, but the unresolved top-holder identity creates high float-control and distribution risk."
            )
        return (
            f"{name} shows measurable holder concentration and distribution risk signals. This does not prove manipulation; "
            "wallet identity investigation is required before drawing stronger conclusions."
        )
