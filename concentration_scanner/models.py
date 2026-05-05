from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def serialise_value(value: Any) -> Any:
    if is_dataclass(value):
        return {key: serialise_value(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [serialise_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): serialise_value(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class TokenMarketData:
    coin_id: str = ""
    name: str = ""
    symbol: str = ""
    platforms: dict[str, str] = field(default_factory=dict)
    current_price: float | None = None
    market_cap: float | None = None
    fully_diluted_valuation: float | None = None
    circulating_supply: float | None = None
    total_supply: float | None = None
    max_supply: float | None = None
    volume_24h: float | None = None
    price_change_1h: float | None = None
    price_change_24h: float | None = None
    price_change_7d: float | None = None
    price_change_14d: float | None = None
    price_change_30d: float | None = None
    all_time_low_price: float | None = None
    all_time_high_price: float | None = None
    atl_date: str = ""
    ath_date: str = ""
    peak_market_cap: float | None = None
    peak_fdv: float | None = None
    peak_volume_24h: float | None = None
    max_24h_price_change: float | None = None
    max_7d_price_change: float | None = None
    max_30d_price_change: float | None = None
    canonical_chain: str = ""
    is_native_asset: bool = False


@dataclass(frozen=True)
class HolderRecord:
    rank: int
    address: str
    label: str = ""
    balance_raw: str = ""
    balance_decimal: float = 0.0
    pct_total_supply: float = 0.0
    value_usd: float | None = None
    is_contract: bool = False
    explorer_url: str = ""
    first_seen_token_transfer: str = ""
    last_seen_token_transfer: str = ""
    recent_inflows: float | None = None
    recent_outflows: float | None = None
    net_balance_change_24h: float | None = None
    net_balance_change_7d: float | None = None
    gas_funder: str = ""
    token_source: str = ""
    funding_source: str = ""


@dataclass(frozen=True)
class ClassifiedHolder(HolderRecord):
    holder_category: str = "unknown_wallet"
    owner_relation: str = "unknown"
    is_owner_related: bool = False
    is_protocol_related: bool = False
    is_unexplained_large_holder: bool = False
    is_exchange_inventory: bool = False
    is_round_allocation: bool = False
    evidence_confidence: str = "low"
    evidence_notes: str = ""
    excluded_from_adjusted_float: bool = False


@dataclass(frozen=True)
class ContractControlStats:
    contract_verified: bool = False
    is_proxy: bool = False
    implementation_address: str = ""
    owner_address: str = ""
    get_owner_address: str = ""
    proxy_admin_address: str = ""
    default_admin_role_holders: list[str] = field(default_factory=list)
    has_mint_function: bool = False
    has_pause_function: bool = False
    has_blacklist_function: bool = False
    has_whitelist_function: bool = False
    has_fee_setter: bool = False
    has_transfer_restrictions: bool = False
    has_max_wallet_control: bool = False
    has_trading_gate: bool = False
    ownership_renounced: bool = False
    admin_privilege_score: float = 0.0
    contract_control_flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ConcentrationMetrics:
    raw_top_1_pct: float = 0.0
    raw_top_3_pct: float = 0.0
    raw_top_5_pct: float = 0.0
    raw_top_10_pct: float = 0.0
    raw_top_20_pct: float = 0.0
    raw_top_50_pct: float = 0.0
    raw_top_100_pct: float = 0.0
    whale_concentration_pct: float = 0.0
    holder_count: int = 0
    whale_count: int = 0
    concentration_gini: float = 0.0
    holder_hhi_index: float = 0.0
    adjusted_float_supply: float = 0.0
    adjusted_float_pct_total_supply: float = 0.0
    excluded_supply_pct: float = 0.0
    adjusted_top_1_pct: float = 0.0
    adjusted_top_5_pct: float = 0.0
    adjusted_top_10_pct: float = 0.0
    adjusted_top_20_pct: float = 0.0
    adjusted_top_50_pct: float = 0.0
    adjusted_top_100_pct: float = 0.0
    largest_unexplained_holder_pct: float = 0.0
    unexplained_top_5_pct: float = 0.0
    unexplained_top_10_pct: float = 0.0
    top_5_real_wallets_pct_adjusted_float: float = 0.0
    top_10_real_wallets_pct_adjusted_float: float = 0.0
    protocol_related_supply_pct: float = 0.0
    owner_related_cluster_pct: float = 0.0
    owner_related_adjusted_float_pct: float = 0.0
    exchange_supply_pct_top_100: float = 0.0
    largest_exchange_holder_pct_total_supply: float = 0.0
    largest_exchange_holder_rank: int | None = None
    round_allocation_supply_pct_top_20: float = 0.0
    data_confidence: str = "low"
    partial_result: bool = False


@dataclass(frozen=True)
class ManipulableWhaleMetrics:
    filtered_top_1_manipulable_pct: float = 0.0
    filtered_top_3_manipulable_pct: float = 0.0
    filtered_top_5_manipulable_pct: float = 0.0
    filtered_top_10_manipulable_pct: float = 0.0
    largest_manipulable_holder_pct: float = 0.0
    largest_manipulable_holder_address: str = ""
    largest_manipulable_holder_category: str = ""
    largest_manipulable_holder_score: float = 0.0
    manipulable_holder_count_top_20: int = 0
    manipulable_holder_count_top_100: int = 0
    manipulable_supply_pct_top_20: float = 0.0
    manipulable_supply_pct_top_100: float = 0.0
    cex_storage_supply_pct: float = 0.0
    protocol_storage_supply_pct: float = 0.0
    treasury_storage_supply_pct: float = 0.0
    vesting_lockup_supply_pct: float = 0.0
    bridge_wrapper_supply_pct: float = 0.0
    cluster_manipulable_supply_pct: float = 0.0
    cluster_adjusted_float_pct: float = 0.0
    cluster_confidence: str = "low"
    cex_outflow_7d: float = 0.0
    suspicious_timing_score: float = 0.0
    key_forensic_flags: list[str] = field(default_factory=list)
    evidence_confidence: str = "low"
    evidence_summary: str = ""


@dataclass(frozen=True)
class WalletForensics:
    address: str
    is_eoa: bool = True
    is_contract: bool = False
    contract_name: str = ""
    contract_verified: bool = False
    safe_multisig_detected: bool = False
    safe_owners: list[str] = field(default_factory=list)
    safe_threshold: int | None = None
    first_seen_at: str = ""
    wallet_age_days: float | None = None
    first_bnb_or_eth_funder: str = ""
    first_token_source: str = ""
    token_source_category: str = "unknown"
    gas_funder_category: str = "unknown"
    deployer_relation: str = "unknown"
    owner_admin_relation: str = "unknown"
    shared_gas_cluster_id: str = ""
    shared_token_source_cluster_id: str = ""
    total_token_in: float = 0.0
    total_token_out: float = 0.0
    current_balance: float = 0.0
    net_balance_change_24h: float | None = None
    net_balance_change_7d: float | None = None
    net_balance_change_30d: float | None = None
    cex_deposit_outflow_24h: float = 0.0
    cex_deposit_outflow_7d: float = 0.0
    cex_deposit_outflow_30d: float = 0.0
    dex_router_interactions: int = 0
    lp_interactions: int = 0
    number_of_unique_counterparties: int = 0
    wallet_purity_score: float = 0.0
    suspicious_timing_score: float = 0.0
    manipulable_whale_score: float = 0.0
    forensic_flags: list[str] = field(default_factory=list)
    evidence_notes: str = ""


@dataclass(frozen=True)
class WalletCluster:
    cluster_id: str
    addresses: list[str] = field(default_factory=list)
    cluster_reason_codes: list[str] = field(default_factory=list)
    cluster_confidence: str = "low"
    cluster_total_supply_pct: float = 0.0
    cluster_adjusted_float_pct: float = 0.0
    cluster_manipulable_supply_pct: float = 0.0
    cluster_largest_holder_pct: float = 0.0
    cluster_cex_outflow_24h: float = 0.0
    cluster_cex_outflow_7d: float = 0.0
    cluster_cex_outflow_30d: float = 0.0
    cluster_forensic_summary: str = ""
    deployer_funded_cluster: bool = False
    same_gas_funder_cluster: bool = False
    same_token_source_cluster: bool = False
    round_allocation_cluster: bool = False
    cex_distribution_cluster: bool = False
    inactive_then_moved_cluster: bool = False
    multi_token_pump_wallet_cluster: bool = False


@dataclass(frozen=True)
class RepresentationStats:
    inspected_chain: str = ""
    canonical_chain: str = ""
    is_native_asset: bool = False
    is_wrapped_or_bridged_representation: bool = False
    holder_table_represents_global_supply: bool = True
    representation_confidence: str = "high"
    wrapper_supply_pct_of_global_supply: float | None = None
    wrapper_concentration_score: float = 0.0
    global_concentration_score: float = 0.0
    concentration_score_confidence: str = "high"
    wrapped_representation_warning: bool = False
    holder_table_not_global_supply: bool = False
    cex_custody_dominated_wrapper: bool = False
    bridge_or_wrapper_concentration: bool = False
    native_chain_data_required: bool = False
    false_positive_concentration_risk: bool = False


@dataclass(frozen=True)
class RiskScores:
    concentration_score: float = 0.0
    unexplained_whale_score: float = 0.0
    owner_related_score: float = 0.0
    protocol_control_score: float = 0.0
    exchange_inventory_score: float = 0.0
    contract_admin_score: float = 0.0
    distribution_risk_score: float = 0.0
    controlled_float_score: float = 0.0
    ravedao_archetype_score: float = 0.0
    manipulable_whale_score: float = 0.0
    custody_concentration_score: float = 0.0
    protocol_storage_score: float = 0.0
    supply_overhang_score: float = 0.0
    adjusted_score_after_custody_filter: float = 0.0
    composite_structural_manipulation_risk_score: float = 0.0
    risk_label: str = "Low"
    confidence: str = "low"


@dataclass(frozen=True)
class RiskFlags:
    dominant_holder_warning: bool = False
    extreme_dominant_holder: bool = False
    nuclear_dominant_holder: bool = False
    unresolved_dominant_holder: bool = False
    adjusted_dominant_holder_extreme: bool = False
    adjusted_top5_extreme: bool = False
    adjusted_top10_extreme: bool = False
    fake_float_structure: bool = False
    cap_table_token: bool = False
    one_wallet_market: bool = False
    dominant_unexplained_holder: bool = False
    protocol_multisig_concentration: bool = False
    high_protocol_control: bool = False
    high_unexplained_whale_control: bool = False
    possible_distribution_wallets: bool = False
    low_float: bool = False
    extreme_low_float: bool = False
    fdv_overhang: bool = False
    extreme_fdv_overhang: bool = False
    top_100_supply_capture: bool = False
    extreme_top_100_supply_capture: bool = False
    exchange_inventory_dominance: bool = False
    cex_rank_1_wallet: bool = False
    bitget_rank_1_inventory_dominance: bool = False
    round_allocation_cluster: bool = False
    controlled_float_squeeze_structure: bool = False
    extreme_controlled_float_squeeze_structure: bool = False
    ravedao_archetype: bool = False
    extreme_ravedao_archetype: bool = False
    one_wallet_mark_to_market: bool = False
    cap_table_marked_to_market: bool = False
    tiny_public_float_marked_to_large_market_cap: bool = False
    historical_pump_with_dominant_holder: bool = False
    collapsed_after_concentrated_pump: bool = False
    billion_dollar_thin_float_print: bool = False
    unresolved_dominant_holder_after_pump: bool = False
    fake_headline_market_cap_risk: bool = False
    thin_float_mark_to_market: bool = False
    peak_valuation_distortion: bool = False
    cex_false_positive_risk: bool = False
    custody_dominated_holder_table: bool = False
    storage_dominated_holder_table: bool = False
    top_holder_is_benign_storage: bool = False
    top_holder_requires_manual_review: bool = False
    deployer_funded_cluster: bool = False
    same_gas_funder_cluster: bool = False
    same_token_source_cluster: bool = False
    cex_distribution_cluster: bool = False
    inactive_then_moved_cluster: bool = False
    multi_token_pump_wallet_cluster: bool = False
    manipulable_float_perp_squeeze_risk: bool = False


@dataclass(frozen=True)
class ThinFloatStats:
    circulating_to_total_supply_pct: float | None = None
    fdv_to_market_cap_ratio: float | None = None
    volume_to_market_cap_ratio: float | None = None
    volume_to_float_market_cap_ratio: float | None = None
    recent_pump_score: float = 0.0
    squeeze_proxy_score: float = 0.0
    ath_multiple_from_atl: float | None = None
    current_drawdown_from_ath_pct: float | None = None
    peak_market_cap: float | None = None
    current_market_cap: float | None = None
    peak_fdv: float | None = None
    current_fdv: float | None = None
    peak_volume_24h: float | None = None
    max_24h_price_change: float | None = None
    max_7d_price_change: float | None = None
    max_30d_price_change: float | None = None
    peak_volume_to_market_cap_ratio: float | None = None
    peak_volume_to_float_market_cap_ratio: float | None = None
    estimated_non_top100_float_pct: float = 0.0
    estimated_non_top10_float_pct: float = 0.0
    peak_value_of_non_top100_float: float | None = None
    peak_value_of_non_top10_float: float | None = None
    top_1_wallet_peak_value: float | None = None
    top_5_wallet_peak_value: float | None = None


@dataclass(frozen=True)
class PerpMarketContext:
    binance_symbol: str = ""
    base_asset: str = ""
    current_price: float | None = None
    perp_volume_24h: float | None = None
    spot_volume_24h: float | None = None
    futures_to_spot_volume_ratio: float | None = None
    open_interest: float | None = None
    open_interest_notional: float | None = None
    oi_to_market_cap_ratio: float | None = None
    oi_to_adjusted_float_market_cap_ratio: float | None = None
    volume_to_adjusted_float_market_cap: float | None = None
    volume_to_market_cap_ratio: float | None = None
    price_change_24h: float | None = None
    price_change_7d: float | None = None
    price_change_30d: float | None = None
    is_pre_ignition_price_action: bool = False
    perps_bigger_than_spot: bool = False
    oi_pressure_flag: bool = False
    liquidity_churn_flag: bool = False
    context_error: str = ""


@dataclass(frozen=True)
class MasterSqueezeScore:
    controlled_float_squeeze_score: float = 0.0
    pre_pump_risk_score: float = 0.0
    insider_whale_concentration_score: float = 0.0
    master_score: float = 0.0
    master_label: str = "Low"
    ranked_reasons: list[str] = field(default_factory=list)
    one_line_mission_match: bool = False


@dataclass(frozen=True)
class ScannerStatus:
    last_market_data_fetch_at: str = ""
    last_holder_fetch_at: str = ""
    last_classification_at: str = ""
    data_staleness_seconds: float | None = None
    scanner_status: str = "new"
    scanner_error: str = ""


@dataclass(frozen=True)
class TokenScanResult:
    token: TokenMarketData
    chain: str
    contract_address: str
    holders: list[ClassifiedHolder]
    concentration: ConcentrationMetrics
    contract_control: ContractControlStats
    representation: RepresentationStats
    thin_float: ThinFloatStats
    scores: RiskScores
    flags: RiskFlags
    status: ScannerStatus
    summary: str
    key_flags: list[str] = field(default_factory=list)
    manipulable: ManipulableWhaleMetrics = field(default_factory=ManipulableWhaleMetrics)
    wallet_forensics: list[WalletForensics] = field(default_factory=list)
    wallet_clusters: list[WalletCluster] = field(default_factory=list)
    perp_context: PerpMarketContext = field(default_factory=PerpMarketContext)
    master_score: MasterSqueezeScore = field(default_factory=MasterSqueezeScore)

    def to_dict(self) -> dict[str, Any]:
        return serialise_value(self)
