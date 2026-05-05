from __future__ import annotations

import json
from typing import Any

import pandas as pd

from .models import TokenScanResult


def result_to_row(result: TokenScanResult) -> dict[str, Any]:
    top_1 = result.holders[0] if result.holders else None
    return {
        "token": result.token.name,
        "symbol": result.token.symbol,
        "chain": result.chain,
        "contract": result.contract_address,
        "price": result.token.current_price,
        "market_cap": result.token.market_cap,
        "fdv": result.token.fully_diluted_valuation,
        "FDV": result.token.fully_diluted_valuation,
        "volume_24h": result.token.volume_24h,
        "price_change_24h": result.token.price_change_24h,
        "price_change_7d": result.token.price_change_7d,
        "price_change_30d": result.token.price_change_30d,
        "binance_symbol": result.perp_context.binance_symbol,
        "perp_volume_24h": result.perp_context.perp_volume_24h,
        "spot_volume_24h": result.perp_context.spot_volume_24h,
        "futures_to_spot_volume_ratio": result.perp_context.futures_to_spot_volume_ratio,
        "open_interest_notional": result.perp_context.open_interest_notional,
        "oi_to_market_cap_ratio": result.perp_context.oi_to_market_cap_ratio,
        "oi_to_adjusted_float_market_cap_ratio": result.perp_context.oi_to_adjusted_float_market_cap_ratio,
        "volume_to_adjusted_float_market_cap": result.perp_context.volume_to_adjusted_float_market_cap,
        "master_score": result.master_score.master_score,
        "pre_pump_risk_score": result.master_score.pre_pump_risk_score,
        "controlled_float_squeeze_score": result.master_score.controlled_float_squeeze_score,
        "insider_whale_concentration_score": result.master_score.insider_whale_concentration_score,
        "master_label": result.master_score.master_label,
        "master_reasons": ", ".join(result.master_score.ranked_reasons),
        "current_price": result.token.current_price,
        "all_time_low_price": result.token.all_time_low_price,
        "all_time_high_price": result.token.all_time_high_price,
        "ath_multiple_from_atl": result.thin_float.ath_multiple_from_atl,
        "current_drawdown_from_ath_pct": result.thin_float.current_drawdown_from_ath_pct,
        "current_market_cap": result.thin_float.current_market_cap,
        "peak_market_cap": result.thin_float.peak_market_cap,
        "current_fdv": result.thin_float.current_fdv,
        "peak_fdv": result.thin_float.peak_fdv,
        "circulating_supply_pct": result.thin_float.circulating_to_total_supply_pct,
        "raw_top_1_pct": result.concentration.raw_top_1_pct,
        "raw_top_5_pct": result.concentration.raw_top_5_pct,
        "raw_top_10_pct": result.concentration.raw_top_10_pct,
        "raw_top_100_pct": result.concentration.raw_top_100_pct,
        "adjusted_top_1_pct": result.concentration.adjusted_top_1_pct,
        "adjusted_top_5_pct": result.concentration.adjusted_top_5_pct,
        "adjusted_top_10_pct": result.concentration.adjusted_top_10_pct,
        "largest_unexplained_holder_pct": result.concentration.largest_unexplained_holder_pct,
        "top_1_label": top_1.label if top_1 else "",
        "top_1_category": top_1.holder_category if top_1 else "",
        "top_1_confidence": top_1.evidence_confidence if top_1 else "",
        "excluded_supply_pct": result.concentration.excluded_supply_pct,
        "estimated_non_top100_float_pct": result.thin_float.estimated_non_top100_float_pct,
        "estimated_non_top10_float_pct": result.thin_float.estimated_non_top10_float_pct,
        "peak_value_of_non_top100_float": result.thin_float.peak_value_of_non_top100_float,
        "top_1_wallet_peak_value": result.thin_float.top_1_wallet_peak_value,
        "top_5_wallet_peak_value": result.thin_float.top_5_wallet_peak_value,
        "gini": result.concentration.concentration_gini,
        "holder_hhi_index": result.concentration.holder_hhi_index,
        "whale_concentration_pct": result.concentration.whale_concentration_pct,
        "ravedao_archetype_score": result.scores.ravedao_archetype_score,
        "manipulable_whale_score": result.scores.manipulable_whale_score,
        "custody_concentration_score": result.scores.custody_concentration_score,
        "protocol_storage_score": result.scores.protocol_storage_score,
        "supply_overhang_score": result.scores.supply_overhang_score,
        "adjusted_score_after_custody_filter": result.scores.adjusted_score_after_custody_filter,
        "largest_manipulable_holder_pct": result.manipulable.largest_manipulable_holder_pct,
        "largest_manipulable_holder_address": result.manipulable.largest_manipulable_holder_address,
        "largest_manipulable_holder_category": result.manipulable.largest_manipulable_holder_category,
        "largest_manipulable_holder_score": result.manipulable.largest_manipulable_holder_score,
        "filtered_top_5_manipulable_pct": result.manipulable.filtered_top_5_manipulable_pct,
        "filtered_top_10_manipulable_pct": result.manipulable.filtered_top_10_manipulable_pct,
        "cluster_manipulable_supply_pct": result.manipulable.cluster_manipulable_supply_pct,
        "cluster_confidence": result.manipulable.cluster_confidence,
        "cex_storage_supply_pct": result.manipulable.cex_storage_supply_pct,
        "treasury_storage_supply_pct": result.manipulable.treasury_storage_supply_pct,
        "vesting_lockup_supply_pct": result.manipulable.vesting_lockup_supply_pct,
        "key_forensic_flags": ", ".join(result.manipulable.key_forensic_flags),
        "wrapped_representation_warning": result.representation.wrapped_representation_warning,
        "holder_table_not_global_supply": result.representation.holder_table_not_global_supply,
        "risk_score": result.scores.composite_structural_manipulation_risk_score,
        "risk_label": result.scores.risk_label,
        "confidence": result.scores.confidence,
        "key_flags": ", ".join(result.key_flags),
        "summary": result.summary,
        "scanner_status": result.status.scanner_status,
        "scanner_error": result.status.scanner_error,
    }


def results_to_frame(results: list[TokenScanResult]) -> pd.DataFrame:
    rows = [result_to_row(result) for result in results]
    return pd.DataFrame(rows)


def cache_rows_to_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    parsed: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row.get("payload_json", "{}"))
        except Exception:
            payload = {}
        token = payload.get("token", {})
        concentration = payload.get("concentration", {})
        scores = payload.get("scores", {})
        manipulable = payload.get("manipulable", {})
        thin = payload.get("thin_float", {})
        holders = payload.get("holders", [])
        perp = payload.get("perp_context", {})
        master = payload.get("master_score", {})
        top_1 = holders[0] if holders else {}
        representation = payload.get("representation", {})
        parsed.append(
            {
                "token": token.get("name") or row.get("token_name"),
                "symbol": token.get("symbol") or row.get("symbol"),
                "chain": row.get("chain"),
                "contract": row.get("contract_address"),
                "price": token.get("current_price"),
                "current_price": token.get("current_price"),
                "market_cap": token.get("market_cap"),
                "fdv": token.get("fully_diluted_valuation"),
                "FDV": token.get("fully_diluted_valuation"),
                "volume_24h": token.get("volume_24h"),
                "price_change_24h": token.get("price_change_24h"),
                "price_change_7d": token.get("price_change_7d"),
                "price_change_30d": token.get("price_change_30d"),
                "binance_symbol": perp.get("binance_symbol"),
                "perp_volume_24h": perp.get("perp_volume_24h"),
                "spot_volume_24h": perp.get("spot_volume_24h"),
                "futures_to_spot_volume_ratio": perp.get("futures_to_spot_volume_ratio"),
                "open_interest_notional": perp.get("open_interest_notional"),
                "oi_to_market_cap_ratio": perp.get("oi_to_market_cap_ratio"),
                "oi_to_adjusted_float_market_cap_ratio": perp.get("oi_to_adjusted_float_market_cap_ratio"),
                "volume_to_adjusted_float_market_cap": perp.get("volume_to_adjusted_float_market_cap"),
                "master_score": master.get("master_score"),
                "pre_pump_risk_score": master.get("pre_pump_risk_score"),
                "controlled_float_squeeze_score": master.get("controlled_float_squeeze_score"),
                "insider_whale_concentration_score": master.get("insider_whale_concentration_score"),
                "master_label": master.get("master_label"),
                "master_reasons": ", ".join(master.get("ranked_reasons", [])),
                "all_time_low_price": token.get("all_time_low_price"),
                "all_time_high_price": token.get("all_time_high_price"),
                "ath_multiple_from_atl": thin.get("ath_multiple_from_atl"),
                "current_drawdown_from_ath_pct": thin.get("current_drawdown_from_ath_pct"),
                "current_market_cap": thin.get("current_market_cap"),
                "peak_market_cap": thin.get("peak_market_cap"),
                "current_fdv": thin.get("current_fdv"),
                "peak_fdv": thin.get("peak_fdv"),
                "circulating_supply_pct": thin.get("circulating_to_total_supply_pct"),
                "raw_top_1_pct": concentration.get("raw_top_1_pct"),
                "raw_top_5_pct": concentration.get("raw_top_5_pct"),
                "raw_top_10_pct": concentration.get("raw_top_10_pct"),
                "raw_top_100_pct": concentration.get("raw_top_100_pct"),
                "adjusted_top_1_pct": concentration.get("adjusted_top_1_pct"),
                "adjusted_top_5_pct": concentration.get("adjusted_top_5_pct"),
                "adjusted_top_10_pct": concentration.get("adjusted_top_10_pct"),
                "largest_unexplained_holder_pct": concentration.get("largest_unexplained_holder_pct"),
                "top_1_label": top_1.get("label", ""),
                "top_1_category": top_1.get("holder_category", ""),
                "top_1_confidence": top_1.get("evidence_confidence", ""),
                "excluded_supply_pct": concentration.get("excluded_supply_pct"),
                "estimated_non_top100_float_pct": thin.get("estimated_non_top100_float_pct"),
                "estimated_non_top10_float_pct": thin.get("estimated_non_top10_float_pct"),
                "peak_value_of_non_top100_float": thin.get("peak_value_of_non_top100_float"),
                "top_1_wallet_peak_value": thin.get("top_1_wallet_peak_value"),
                "top_5_wallet_peak_value": thin.get("top_5_wallet_peak_value"),
                "gini": concentration.get("concentration_gini"),
                "holder_hhi_index": concentration.get("holder_hhi_index"),
                "whale_concentration_pct": concentration.get("whale_concentration_pct"),
                "ravedao_archetype_score": scores.get("ravedao_archetype_score") or row.get("ravedao_score"),
                "manipulable_whale_score": scores.get("manipulable_whale_score"),
                "custody_concentration_score": scores.get("custody_concentration_score"),
                "protocol_storage_score": scores.get("protocol_storage_score"),
                "supply_overhang_score": scores.get("supply_overhang_score"),
                "adjusted_score_after_custody_filter": scores.get("adjusted_score_after_custody_filter"),
                "largest_manipulable_holder_pct": manipulable.get("largest_manipulable_holder_pct"),
                "largest_manipulable_holder_address": manipulable.get("largest_manipulable_holder_address"),
                "largest_manipulable_holder_category": manipulable.get("largest_manipulable_holder_category"),
                "largest_manipulable_holder_score": manipulable.get("largest_manipulable_holder_score"),
                "filtered_top_5_manipulable_pct": manipulable.get("filtered_top_5_manipulable_pct"),
                "filtered_top_10_manipulable_pct": manipulable.get("filtered_top_10_manipulable_pct"),
                "cluster_manipulable_supply_pct": manipulable.get("cluster_manipulable_supply_pct"),
                "cluster_confidence": manipulable.get("cluster_confidence"),
                "cex_storage_supply_pct": manipulable.get("cex_storage_supply_pct"),
                "treasury_storage_supply_pct": manipulable.get("treasury_storage_supply_pct"),
                "vesting_lockup_supply_pct": manipulable.get("vesting_lockup_supply_pct"),
                "key_forensic_flags": ", ".join(manipulable.get("key_forensic_flags", [])),
                "wrapped_representation_warning": representation.get("wrapped_representation_warning"),
                "holder_table_not_global_supply": representation.get("holder_table_not_global_supply"),
                "risk_score": scores.get("composite_structural_manipulation_risk_score") or row.get("risk_score"),
                "risk_label": scores.get("risk_label") or row.get("risk_label"),
                "key_flags": ", ".join(payload.get("key_flags", [])),
                "summary": payload.get("summary", ""),
                "updated_at": row.get("updated_at"),
            }
        )
    return pd.DataFrame(parsed)
