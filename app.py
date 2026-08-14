from __future__ import annotations

import hashlib
import math
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import streamlit as st

from archetype_scoring import ARCHETYPE_SCORE_COLUMNS, apply_archetype_model
from binance_futures import BinanceHTTPError, BinanceFuturesPublic
from breakouts import BreakoutRow, levels_from_klines, recent_pump_stats_from_klines
from cmc_movers import fetch_cmc_movers
from concentration_scanner import HolderRecord, ManualOverride, ScanCache, ScannerInput, TokenConcentrationScanner
from concentration_scanner.fixtures import acceptance_fixture_results
from concentration_scanner.perp_universe import DEFAULT_SEED_PATH, BinancePerpUniverseBuilder, PerpUniverseCandidate
from concentration_scanner.presentation import cache_rows_to_frame
from convexity_scoring import CONVEXITY_SCORE_COLUMNS, apply_convexity_model
from cex_flow_scanner import CEX_DEPOSIT_FLOW_COLUMNS, build_cex_flow_discord_block, enrich_cex_deposit_flows
from crypto_market_structure.reflexivity import (
    SIGNAL_VERSION as REFLEXIVITY_SIGNAL_VERSION,
)
from crypto_market_structure.reporting import project_reflexivity_assessments
from discord_flag_formatter import (
    DISCORD_EMBED_DESCRIPTION_LIMIT,
    DISCORD_FOOTER,
    DISCORD_PRODUCT_IDENTITY,
    build_discord_flag_card,
    join_discord_flag_cards,
)
from early_pump_radar import EARLY_PUMP_RADAR_COLUMNS, apply_early_pump_radar
from event_study import EVENT_STUDY_COLUMNS, build_case_study_event_frame
from external_markets import (
    fetch_coinbase_spot_bases,
    fetch_dwf_labs_portfolio_members,
    fetch_external_crime_metrics,
    normalize_base_asset,
)
from holder_composition import (
    fetch_holder_composition,
    format_holder_composition_for_discord,
    resolve_contract_hint,
)
from market_structure_scoring import LIFECYCLE_SCORE_COLUMNS, apply_lifecycle_model
from mechanism_engine import MECHANISM_SCORE_COLUMNS, apply_mechanism_model
from pnl import PnLDashboardResult, build_pnl_dashboard_data
from pre_activity_radar import PRE_ACTIVITY_RADAR_COLUMNS, apply_pre_activity_radar
from proof_engine import archive_alerts
from short_account_roc import short_account_history_stats
from short_squeeze_scoring import SHORT_SQUEEZE_SCORE_COLUMNS, apply_short_squeeze_model
from squeeze_radar import (
    SQUEEZE_RADAR_PROFILES,
    attach_squeeze_history_features,
    oi_history_stats,
    score_squeeze_radar,
    select_squeeze_candidates,
)
from screener import ScreenerData, build_screener_data
from terminal_engine import TERMINAL_SCORE_COLUMNS, apply_terminal_model, build_setup_dossier
from timing_engine import TIMING_SCORE_COLUMNS, apply_timing_model, build_timing_card
from venue_gate import (
    binance_bitget_venue_mask,
    effective_top10_holder_pct,
    holder_concentration_mask,
    holder_evidence_mask,
    no_recent_pump_proof_mask,
    apply_thesis_alert_gate,
    thesis_alert_header,
)
from volume_metrics import closed_daily_anchored_vwap_metrics, closed_hour_volume_metrics

APP_DIR = Path(__file__).resolve().parent
IMPORT_ONLY = os.environ.get("CRYPTO_SCANNER_IMPORT_ONLY") == "1"
USD_LIKE_ASSETS = {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP"}
RANGE_PRESETS = ("7D", "30D", "90D", "YTD", "1Y", "3Y", "ITD", "Custom")
TRADFI_ALWAYS_INCLUDE_TYPES = {
    "COMMODITY",
    "EQUITY",
    "HK_EQUITY",
    "KR_EQUITY",
    "INDEX",
    "PREMARKET",
}
DEFAULT_CRIME_EXCLUDED_BASES = (
    "BTC,ETH,XRP,BNB,SOL,DOGE,ADA,TRX,LINK,LTC,BCH,DOT,AVAX,TON,SHIB,HBAR,XLM,ETC,ICP,NEAR,APT,ARB,OP"
)
DEFAULT_CRIME_FORCE_SYMBOLS = "RAVEUSDT,FIGHTUSDT,CHIPUSDT,SIRENUSDT,STOUSDT,HIGHUSDT,RIVERUSDT,PIPPINUSDT"
THESIS_HOLDER_CHAIN_OPTIONS = ("ethereum", "bsc", "arbitrum")
THESIS_HOLDER_CHAIN_LABEL = "ETH/BNB/ARB"
MM_PROXIMITY_COLUMNS = [
    "mm_proximity_score",
    "mm_proximity_maker",
    "mm_proximity_note",
    "mm_proximity_source",
]
MM_PROXIMITY_TEXT_COLUMNS = {"mm_proximity_maker", "mm_proximity_note", "mm_proximity_source"}
INVENTORY_TRANSFER_COLUMNS = [
    "spot_volume_to_mcap_pct",
    "perp_volume_to_mcap_pct",
    "oi_to_market_cap_pct",
    "inventory_sponsor_mismatch_score",
    "inventory_transfer_risk_score",
    "inventory_transfer_risk_flag",
    "inventory_transfer_note",
]
INVENTORY_TRANSFER_TEXT_COLUMNS = {"inventory_transfer_note"}
RAVE_LAB_SETUP_COLUMNS = [
    "insider_team_holder_pct",
    "centralized_ownership_score",
    "low_float_score",
    "short_account_build_score",
    "short_dominance_score",
    "low_volatility_coil_score",
    "pre_pump_short_fuse_score",
    "pre_pump_compression_score",
    "short_trap_score",
    "silent_oi_accumulation_score",
    "dormant_short_fuse_score",
    "price_volume_ignition_score",
    "target_cex_volume_share_pct",
    "target_cex_flow_score",
    "target_cex_share_change_pp",
    "cex_lane_wakeup_score",
    "oi_value_change_since_scan_pct",
    "ask_depth_1pct_change_pct",
    "ask_depth_withdrawal_score",
    "thin_ask_trap_score",
    "rave_lab_convex_fuel_score",
    "rave_lab_late_penalty_score",
    "no_chase_penalty_score",
    "pre_pump_precision_score",
    "rave_lab_setup_score",
    "snapshot_seen_before",
    "prior_scan_age_minutes",
    "dormant_short_fuse_flag",
    "pre_pump_precision_flag",
    "no_chase_ok_flag",
    "rave_lab_watch_flag",
    "rave_lab_setup_flag",
    "rave_lab_extreme_flag",
    "pre_pump_precision_note",
    "dormant_short_fuse_note",
    "rave_lab_setup_note",
]
RAVE_LAB_TEXT_COLUMNS = {"pre_pump_precision_note", "dormant_short_fuse_note", "rave_lab_setup_note"}
RAVE_LAB_BOOL_COLUMNS = {
    "snapshot_seen_before",
    "dormant_short_fuse_flag",
    "pre_pump_precision_flag",
    "no_chase_ok_flag",
    "rave_lab_watch_flag",
    "rave_lab_setup_flag",
    "rave_lab_extreme_flag",
}
CMC_MOVER_COLUMNS = [
    "cmc_name",
    "cmc_rank_1h",
    "cmc_rank_24h",
    "cmc_pct_1h",
    "cmc_pct_24h",
    "cmc_market_cap_usd",
    "cmc_volume_24h",
    "cmc_volume_to_mcap_pct",
    "cmc_mover_score",
    "cmc_mover_label",
]
CMC_MOVER_TEXT_COLUMNS = {"cmc_name", "cmc_mover_label"}
CEX_FLOW_WHALE_SENDER_COLUMNS = [
    "cex_deposit_24h_whale_sender_count",
    "cex_deposit_24h_whale_sender_token_amount",
    "cex_deposit_24h_whale_sender_max_amount",
    "cex_deposit_24h_top_sender_rank",
    "cex_deposit_24h_top_sender_pct",
    "cex_deposit_24h_top_sender_address",
]
CEX_FLOW_DASHBOARD_COLUMNS = [
    "symbol",
    "base_asset",
    "terminal_edge_score",
    "trade_bucket_score",
    "cex_deposit_flow_score",
    "cex_deposit_inventory_stress_score",
    "cex_deposit_flow_risk_level",
    "cex_deposit_flow_flag",
    "cex_deposit_24h_count",
    "cex_deposit_24h_token_amount",
    "cex_deposit_24h_max_amount",
    *CEX_FLOW_WHALE_SENDER_COLUMNS,
    "cex_deposit_24h_notional_usd",
    "cex_deposit_24h_max_notional_usd",
    "cex_deposit_24h_total_pct_supply",
    "cex_deposit_24h_max_pct_supply",
    "cex_deposit_24h_notional_to_ask_depth_pct",
    "cex_deposit_24h_max_notional_to_ask_depth_pct",
    "cex_deposit_24h_notional_to_volume_pct",
    "cex_deposit_inventory_stress_note",
    "cex_deposit_24h_target_exchanges",
    "cex_deposit_concentration_gate",
    "cex_deposit_flow_evidence_summary",
    "cex_deposit_flow_interpretation",
    "cex_deposit_flow_next_check",
    "cex_deposit_flow_note",
    "cex_deposit_flow_alert_line",
    "cex_deposit_flow_error",
    "cex_deposit_flow_source",
    "cex_deposit_24h_source_url",
    "top10_holder_pct",
    "top100_holder_pct",
    "centralized_ownership_score",
    "low_float_score",
    "short_account_pct",
    "long_account_pct",
    "oi_delta_pct",
    "daily_quote_volume_multiple",
    "day_return_pct",
    "broke_high_20d",
    "broke_high_90d",
    "broke_high_180d",
]
CEX_FLOW_DIAGNOSTIC_COLUMNS = [
    "symbol",
    "base_asset",
    "cex_deposit_concentration_gate",
    "cex_deposit_flow_risk_level",
    "cex_deposit_24h_count",
    "cex_deposit_24h_token_amount",
    "cex_deposit_24h_max_amount",
    *CEX_FLOW_WHALE_SENDER_COLUMNS,
    "cex_deposit_flow_evidence_summary",
    "cex_deposit_flow_next_check",
    "cex_deposit_flow_note",
    "cex_deposit_flow_error",
    "cex_deposit_flow_source",
    "cex_deposit_24h_source_url",
    "top10_holder_pct",
    "top100_holder_pct",
    "token_platform",
    "token_contract",
]
DWF_LABS_CATEGORY_URL = "https://www.coingecko.com/en/categories/dwf-labs-portfolio"
DWF_LABS_PORTFOLIO_COLUMNS = [
    "dwf_labs_portfolio",
    "dwf_labs_portfolio_score",
    "dwf_labs_portfolio_rank",
    "dwf_labs_portfolio_note",
]


def _load_local_env() -> None:
    env_path = APP_DIR / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


def _env_value(*names: str, default: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value not in (None, ""):
            return value
    return default


def _parse_positive_ints(raw_value: str, *, default: tuple[int, ...]) -> tuple[int, ...]:
    parsed: list[int] = []
    for raw_item in str(raw_value or "").split(","):
        try:
            item = int(raw_item.strip())
        except Exception:
            continue
        if item > 0:
            parsed.append(item)
    return tuple(dict.fromkeys(parsed)) or default


def _parse_env_int(raw_value: str, *, default: int, minimum: int | None = None) -> int:
    try:
        parsed = int(str(raw_value).strip())
    except Exception:
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    return parsed


def _parse_env_float(raw_value: str, *, default: float, minimum: float | None = None) -> float:
    try:
        parsed = float(str(raw_value).strip())
    except Exception:
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    return parsed


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _key_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_usd(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _format_pct(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value):,.2f}%"


def _format_pnl(value: float, currency: str | None) -> str:
    if currency in (None, "USD-like"):
        return _format_usd(value)
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value):,.2f} {currency}"


def _display_frame(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Return only available display columns so optional enrichments cannot crash a table."""
    source = df.loc[:, ~df.columns.duplicated()].copy()
    requested = list(columns)
    if "hour_volume_roc_1h_pct" in source.columns and "hour_volume_roc_1h_pct" not in requested:
        insert_after = "hour_quote_volume" if "hour_quote_volume" in requested else "symbol"
        insert_at = requested.index(insert_after) + 1 if insert_after in requested else 0
        requested.insert(insert_at, "hour_volume_roc_1h_pct")
    if {"long_account_pct", "short_account_pct"}.issubset(source.columns) and "symbol" in requested:
        missing_account_cols = [
            column for column in ("long_account_pct", "short_account_pct")
            if column not in requested
        ]
        if missing_account_cols:
            insert_after = "long_short_account_ratio"
            if insert_after not in requested:
                insert_after = "trade_bucket_score" if "trade_bucket_score" in requested else "symbol"
            insert_at = requested.index(insert_after) + 1
            requested[insert_at:insert_at] = missing_account_cols
    existing_columns: list[str] = []
    seen: set[str] = set()
    for column in requested:
        if column in source.columns and column not in seen:
            existing_columns.append(column)
            seen.add(column)
    if not existing_columns:
        return source
    return source.loc[:, existing_columns].copy()


def _period_label(label: str, complete: bool) -> str:
    return label if complete else f"{label}*"


def _open_position_count(account: dict[str, Any]) -> int:
    count = 0
    for position in account.get("positions", []):
        if abs(_safe_float(position.get("positionAmt"))) > 0:
            count += 1
    return count


def _client(*, api_key: str = "", api_secret: str = "") -> BinanceFuturesPublic:
    return BinanceFuturesPublic(
        base_url=BASE_URL,
        timeout=TIMEOUT,
        requests_per_second=REQUESTS_PER_SECOND,
        retries=RETRIES,
        api_key=api_key,
        api_secret=api_secret,
        recv_window=BINANCE_RECV_WINDOW,
    )


def _period_complete(result: PnLDashboardResult, start_dt: datetime) -> bool:
    if result.coverage_start is None:
        return False
    return result.coverage_start.to_pydatetime() <= start_dt


def _range_bounds(
    preset: str,
    *,
    coverage_start: pd.Timestamp,
    coverage_end: pd.Timestamp,
) -> tuple[datetime, datetime]:
    end_dt = coverage_end.to_pydatetime()
    if preset == "7D":
        return end_dt - timedelta(days=6), end_dt
    if preset == "30D":
        return end_dt - timedelta(days=29), end_dt
    if preset == "90D":
        return end_dt - timedelta(days=89), end_dt
    if preset == "YTD":
        return datetime(end_dt.year, 1, 1, tzinfo=timezone.utc), end_dt
    if preset == "1Y":
        return end_dt - timedelta(days=365), end_dt
    if preset == "3Y":
        return end_dt - timedelta(days=365 * 3), end_dt
    if preset == "ITD":
        return coverage_start.to_pydatetime(), end_dt
    return coverage_start.to_pydatetime(), end_dt


def _to_utc_date(dt: datetime | pd.Timestamp) -> date:
    if isinstance(dt, pd.Timestamp):
        dt = dt.to_pydatetime()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date()


def _date_to_utc(dt: date, *, end_of_day: bool = False) -> datetime:
    if end_of_day:
        return datetime(dt.year, dt.month, dt.day, 23, 59, 59, tzinfo=timezone.utc)
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def _filter_income_frame(df: pd.DataFrame, start_dt: datetime, end_dt: datetime) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    mask = (df["time"] >= pd.Timestamp(start_dt)) & (df["time"] <= pd.Timestamp(end_dt))
    return df.loc[mask].copy()


def _filter_daily_frame(df: pd.DataFrame, start_dt: datetime, end_dt: datetime) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    mask = (df["date"] >= pd.Timestamp(start_dt).normalize()) & (df["date"] <= pd.Timestamp(end_dt).normalize())
    return df.loc[mask].copy()


def _complete_daily_frame(df: pd.DataFrame, start_dt: datetime, end_dt: datetime) -> pd.DataFrame:
    idx = pd.date_range(
        pd.Timestamp(start_dt).normalize(),
        pd.Timestamp(end_dt).normalize(),
        freq="D",
        tz="UTC",
    )
    if df.empty:
        filled = pd.DataFrame({"date": idx})
        filled["net_pnl"] = 0.0
        filled["positive_pnl"] = 0.0
        filled["negative_pnl"] = 0.0
        filled["events"] = 0
        filled["cumulative_pnl"] = 0.0
        return filled

    reindexed = df.set_index("date").reindex(idx, fill_value=0.0)
    reindexed.index.name = "date"
    filled = reindexed.reset_index()
    filled["events"] = filled["events"].astype(int)
    filled["cumulative_pnl"] = filled["net_pnl"].cumsum()
    return filled


def _metric_period_total(daily_df: pd.DataFrame, start_dt: datetime) -> float:
    if daily_df.empty:
        return 0.0
    mask = daily_df["date"] >= pd.Timestamp(start_dt).normalize()
    return float(daily_df.loc[mask, "net_pnl"].sum())


def _baseline_balance(result: PnLDashboardResult) -> float:
    balances = result.current_balances_df
    if balances.empty:
        return max(abs(_safe_float(result.account.get("totalWalletBalance"))), 1.0)
    if result.headline_currency in (None, "USD-like"):
        usd_like = balances[balances["asset"].isin(USD_LIKE_ASSETS)]
        if not usd_like.empty:
            return max(abs(float(usd_like["wallet_balance"].sum())), 1.0)
    if result.headline_currency and result.headline_currency != "USD-like":
        match = balances[balances["asset"] == result.headline_currency]
        if not match.empty:
            return max(abs(float(match["wallet_balance"].sum())), 1.0)
    return max(abs(_safe_float(result.account.get("totalWalletBalance"))), 1.0)


def _build_period_stats(
    income_df: pd.DataFrame,
    daily_df: pd.DataFrame,
    *,
    baseline_balance: float,
) -> dict[str, float]:
    net_pnl = float(income_df["income"].sum()) if not income_df.empty else 0.0
    total_profit = float(income_df.loc[income_df["income"] > 0, "income"].sum()) if not income_df.empty else 0.0
    total_loss = abs(float(income_df.loc[income_df["income"] < 0, "income"].sum())) if not income_df.empty else 0.0
    winning_days = int((daily_df["net_pnl"] > 0).sum()) if not daily_df.empty else 0
    losing_days = int((daily_df["net_pnl"] < 0).sum()) if not daily_df.empty else 0
    breakeven_days = int((daily_df["net_pnl"] == 0).sum()) if not daily_df.empty else 0
    avg_profit = total_profit / winning_days if winning_days else 0.0
    avg_loss = total_loss / losing_days if losing_days else 0.0
    profit_loss_ratio = avg_profit / avg_loss if avg_loss else 0.0
    best_day = float(daily_df["net_pnl"].max()) if not daily_df.empty else 0.0
    worst_day = float(daily_df["net_pnl"].min()) if not daily_df.empty else 0.0
    event_count = int(len(income_df))
    active_assets = int(income_df["asset"].nunique()) if not income_df.empty else 0
    active_symbols = int(income_df.loc[income_df["symbol"] != "", "symbol"].nunique()) if not income_df.empty else 0
    return_pct = (net_pnl / baseline_balance * 100.0) if baseline_balance else 0.0
    max_drawdown = 0.0
    if not daily_df.empty:
        cumulative = daily_df["cumulative_pnl"]
        drawdown = cumulative - cumulative.cummax()
        max_drawdown = abs(float(drawdown.min()))

    return {
        "net_pnl": net_pnl,
        "total_profit": total_profit,
        "total_loss": total_loss,
        "winning_days": winning_days,
        "losing_days": losing_days,
        "breakeven_days": breakeven_days,
        "avg_profit": avg_profit,
        "avg_loss": avg_loss,
        "profit_loss_ratio": profit_loss_ratio,
        "best_day": best_day,
        "worst_day": worst_day,
        "event_count": event_count,
        "active_assets": active_assets,
        "active_symbols": active_symbols,
        "return_pct": return_pct,
        "max_drawdown": max_drawdown,
    }


def _credential_diagnostics(api_key: str, api_secret: str) -> list[str]:
    notes: list[str] = []
    if not api_key:
        notes.append("`BINANCE_API_KEY` is empty.")
    if not api_secret:
        notes.append("`BINANCE_API_SECRET` is empty.")
    if api_key and len(api_key) < 32:
        notes.append("The API key length looks unusually short.")
    if api_secret and len(api_secret) not in (64, 128):
        notes.append(f"The API secret length is {len(api_secret)}, which is unusual for a Binance HMAC secret.")
    return notes


def _render_stat_grid(stats: dict[str, float], currency: str | None) -> None:
    row_one = st.columns(4)
    row_one[0].metric("Selected net PnL", _format_pnl(stats["net_pnl"], currency))
    row_one[1].metric("Selected return", _format_pct(stats["return_pct"]))
    row_one[2].metric("Winning days", str(int(stats["winning_days"])))
    row_one[3].metric("Losing days", str(int(stats["losing_days"])))

    row_two = st.columns(4)
    row_two[0].metric("Total profit", _format_pnl(stats["total_profit"], currency))
    row_two[1].metric("Total loss", _format_pnl(-stats["total_loss"], currency))
    row_two[2].metric("Avg profit day", _format_pnl(stats["avg_profit"], currency))
    row_two[3].metric("Avg loss day", _format_pnl(-stats["avg_loss"], currency))

    row_three = st.columns(4)
    row_three[0].metric("Best day", _format_pnl(stats["best_day"], currency))
    row_three[1].metric("Worst day", _format_pnl(stats["worst_day"], currency))
    row_three[2].metric("Profit/loss ratio", f"{stats['profit_loss_ratio']:.2f}")
    row_three[3].metric("Max drawdown", _format_pnl(-stats["max_drawdown"], currency))

    row_four = st.columns(4)
    row_four[0].metric("Breakeven days", str(int(stats["breakeven_days"])))
    row_four[1].metric("Income events", str(int(stats["event_count"])))
    row_four[2].metric("Active assets", str(int(stats["active_assets"])))
    row_four[3].metric("Active symbols", str(int(stats["active_symbols"])))


def _closed_daily_close_series(klines: list[list[Any]]) -> pd.Series:
    if len(klines) < 2:
        return pd.Series(dtype=float)

    frame = pd.DataFrame(klines[:-1], columns=list(range(len(klines[0]))))
    close_series = pd.Series(
        pd.to_numeric(frame[4], errors="coerce").values,
        index=pd.to_datetime(frame[0], unit="ms", utc=True),
    ).dropna()
    close_series = close_series[~close_series.index.duplicated(keep="last")]
    return close_series.sort_index()


def _latest_btc_correlation(symbol: str, symbol_klines: list[list[Any]], btc_klines: list[list[Any]]) -> tuple[float, int]:
    if symbol.upper() == "BTCUSDT":
        btc_close = _closed_daily_close_series(btc_klines)
        btc_returns = btc_close.pct_change().dropna()
        return 1.0, min(180, len(btc_returns))

    symbol_close = _closed_daily_close_series(symbol_klines)
    btc_close = _closed_daily_close_series(btc_klines)
    if symbol_close.empty or btc_close.empty:
        return float("nan"), 0

    returns = pd.concat(
        [
            symbol_close.rename("symbol").pct_change(),
            btc_close.rename("btc").pct_change(),
        ],
        axis=1,
        join="inner",
    ).dropna()

    if len(returns) < 2:
        return float("nan"), int(len(returns))

    window_days = min(180, int(len(returns)))
    rolling_corr = returns["symbol"].rolling(window_days).corr(returns["btc"]).dropna()
    if rolling_corr.empty:
        return float("nan"), window_days
    return float(rolling_corr.iloc[-1]), window_days


def _funding_rate_to_pct(value: Any) -> float:
    try:
        rate = float(value)
    except Exception:
        return float("nan")
    if math.isnan(rate):
        return float("nan")
    return rate * 100.0


def _annualized_funding_pct(value: Any, *, interval_hours: int = 8) -> float:
    try:
        rate = float(value)
    except Exception:
        return float("nan")
    if math.isnan(rate):
        return float("nan")
    periods_per_day = 24.0 / max(1.0, float(interval_hours))
    return rate * periods_per_day * 365.0 * 100.0


def _share_to_pct(value: Any) -> float:
    try:
        share = float(value)
    except Exception:
        return float("nan")
    if math.isnan(share):
        return float("nan")
    return share * 100.0


def _float_nan(value: Any) -> float:
    try:
        parsed = float(value)
    except Exception:
        return float("nan")
    return parsed if not math.isnan(parsed) else float("nan")


def _pct_change(current: Any, previous: Any) -> float:
    current_f = _float_nan(current)
    previous_f = _float_nan(previous)
    if math.isnan(current_f) or math.isnan(previous_f) or abs(previous_f) < 1e-12:
        return float("nan")
    return (current_f / previous_f - 1.0) * 100.0


def _short_account_history_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return short_account_history_stats(rows, windows=tuple(SHORT_ACCOUNT_CHANGE_WINDOWS))


def _hourly_market_stats(klines: list[list[Any]]) -> dict[str, float]:
    if len(klines) < 4:
        return {
            "hour_return_pct": float("nan"),
            "hour_return_z": float("nan"),
            "day_return_pct": float("nan"),
            "hour_quote_volume": float("nan"),
            "hour_quote_volume_previous_1h": float("nan"),
            "hour_volume_roc_1h_pct": float("nan"),
            "hour_volume_multiple": float("nan"),
            "hour_trade_count_multiple": float("nan"),
            "hour_upper_wick_pct": float("nan"),
            "hour_close_location_pct": float("nan"),
        }

    closed_only = klines[:-1]
    opens = [_float_nan(row[1]) for row in closed_only if len(row) > 8]
    closes = [_float_nan(row[4]) for row in closed_only if len(row) > 7]
    highs = [_float_nan(row[2]) for row in closed_only if len(row) > 8]
    lows = [_float_nan(row[3]) for row in closed_only if len(row) > 8]
    quote_volumes = [_float_nan(row[7]) for row in closed_only if len(row) > 7]
    trade_counts = [_float_nan(row[8]) for row in closed_only if len(row) > 8]
    if len(closes) < 3 or len(quote_volumes) < 2 or len(trade_counts) < 2:
        return {
            "hour_return_pct": float("nan"),
            "hour_return_z": float("nan"),
            "day_return_pct": float("nan"),
            "hour_quote_volume": float("nan"),
            "hour_quote_volume_previous_1h": float("nan"),
            "hour_volume_roc_1h_pct": float("nan"),
            "hour_volume_multiple": float("nan"),
            "hour_trade_count_multiple": float("nan"),
            "hour_upper_wick_pct": float("nan"),
            "hour_close_location_pct": float("nan"),
        }

    return_series = pd.Series(closes, dtype="float64").pct_change().dropna()
    if return_series.empty:
        hour_return_pct = float("nan")
        hour_return_z = float("nan")
    else:
        latest_return = float(return_series.iloc[-1])
        baseline_returns = return_series.iloc[:-1].tail(48)
        if baseline_returns.empty:
            baseline_returns = return_series.tail(48)
        baseline_mean = float(baseline_returns.mean()) if not baseline_returns.empty else 0.0
        baseline_std = float(baseline_returns.std(ddof=0)) if len(baseline_returns) > 1 else float("nan")
        hour_return_pct = latest_return * 100.0
        if math.isnan(baseline_std) or baseline_std < 1e-12:
            hour_return_z = float("nan")
        else:
            hour_return_z = (latest_return - baseline_mean) / baseline_std

    if len(closes) >= 25 and not math.isnan(closes[-1]) and not math.isnan(closes[-25]) and abs(closes[-25]) >= 1e-12:
        day_return_pct = (closes[-1] / closes[-25] - 1.0) * 100.0
    else:
        day_return_pct = float("nan")

    latest_hour_quote_volume = quote_volumes[-1]
    hour_volume_roc = closed_hour_volume_metrics(klines, bars_per_hour=1)
    volume_baseline = pd.Series(quote_volumes[:-1], dtype="float64").tail(24)
    baseline_avg_quote_volume = float(volume_baseline.mean()) if not volume_baseline.empty else float("nan")
    if math.isnan(latest_hour_quote_volume) or math.isnan(baseline_avg_quote_volume) or baseline_avg_quote_volume < 1e-12:
        hour_volume_multiple = float("nan")
    else:
        hour_volume_multiple = latest_hour_quote_volume / baseline_avg_quote_volume

    latest_trade_count = trade_counts[-1]
    trade_baseline = pd.Series(trade_counts[:-1], dtype="float64").tail(24)
    baseline_avg_trade_count = float(trade_baseline.mean()) if not trade_baseline.empty else float("nan")
    if math.isnan(latest_trade_count) or math.isnan(baseline_avg_trade_count) or baseline_avg_trade_count < 1e-12:
        hour_trade_count_multiple = float("nan")
    else:
        hour_trade_count_multiple = latest_trade_count / baseline_avg_trade_count

    latest_open = opens[-1] if opens else float("nan")
    latest_high = highs[-1] if highs else float("nan")
    latest_low = lows[-1] if lows else float("nan")
    latest_close = closes[-1]
    hour_range = latest_high - latest_low if not math.isnan(latest_high) and not math.isnan(latest_low) else float("nan")
    if math.isnan(hour_range) or hour_range < 1e-12:
        hour_upper_wick_pct = float("nan")
        hour_close_location_pct = float("nan")
    else:
        hour_upper_wick_pct = max(0.0, (latest_high - latest_close) / hour_range * 100.0)
        hour_close_location_pct = min(100.0, max(0.0, (latest_close - latest_low) / hour_range * 100.0))

    return {
        "hour_return_pct": hour_return_pct,
        "hour_return_z": hour_return_z,
        "day_return_pct": day_return_pct,
        "hour_quote_volume": latest_hour_quote_volume,
        "hour_quote_volume_previous_1h": hour_volume_roc["hour_quote_volume_previous_1h"],
        "hour_volume_roc_1h_pct": hour_volume_roc["hour_volume_roc_1h_pct"],
        "hour_volume_multiple": hour_volume_multiple,
        "hour_trade_count_multiple": hour_trade_count_multiple,
        "hour_upper_wick_pct": hour_upper_wick_pct,
        "hour_close_location_pct": hour_close_location_pct,
    }


def _daily_quote_volume_multiple(klines: list[list[Any]], quote_volume_24h: float) -> float:
    """Compare current 24h perp volume with the recent closed daily baseline."""
    current_volume = _float_nan(quote_volume_24h)
    if math.isnan(current_volume) or current_volume <= 0:
        return float("nan")

    closed_only = klines[:-1] if len(klines) > 1 else []
    quote_volumes: list[float] = []
    for row in closed_only:
        if len(row) <= 7:
            continue
        quote_volume = _float_nan(row[7])
        if not math.isnan(quote_volume) and quote_volume > 0:
            quote_volumes.append(quote_volume)
    if len(quote_volumes) < 5:
        return float("nan")

    baseline = pd.Series(quote_volumes[-20:], dtype="float64").median()
    if math.isnan(float(baseline)) or float(baseline) <= 0:
        return float("nan")
    return current_volume / float(baseline)


def _daily_quote_volume_30d_context(klines: list[list[Any]], quote_volume_24h: float) -> dict[str, float | int]:
    """Compare rolling 24h quote volume with up to 30 completed UTC daily candles."""
    closed_only = klines[:-1] if len(klines) > 1 else []
    quote_volumes: list[float] = []
    for row in closed_only:
        if len(row) <= 7:
            continue
        quote_volume = _float_nan(row[7])
        if not math.isnan(quote_volume) and quote_volume >= 0:
            quote_volumes.append(quote_volume)

    sample = quote_volumes[-30:]
    prior_total = float(sum(sample)) if sample else float("nan")
    prior_average = prior_total / len(sample) if sample else float("nan")
    current_volume = _float_nan(quote_volume_24h)
    ratio = (
        current_volume / prior_average
        if not math.isnan(current_volume) and not math.isnan(prior_average) and prior_average > 0
        else float("nan")
    )
    return {
        "quote_volume_prior_30d_total": prior_total,
        "quote_volume_prior_30d_daily_avg": prior_average,
        "quote_volume_prior_30d_days": len(sample),
        "quote_volume_24h_vs_prior_30d_avg_ratio": ratio,
    }


def _distance_to_level_pct(level: float, last_price: float) -> float:
    if math.isnan(level) or last_price <= 0:
        return float("nan")
    return max(0.0, (level / last_price - 1.0) * 100.0)


def _depth_stress(depth_snapshot: dict[str, Any], quote_volume_24h: float) -> dict[str, float]:
    bids = depth_snapshot.get("bids", []) if isinstance(depth_snapshot, dict) else []
    asks = depth_snapshot.get("asks", []) if isinstance(depth_snapshot, dict) else []
    if not bids or not asks:
        return {
            "ask_depth_1pct_usdt": float("nan"),
            "ask_depth_to_24h_volume_pct": float("nan"),
        }

    try:
        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
    except Exception:
        return {
            "ask_depth_1pct_usdt": float("nan"),
            "ask_depth_to_24h_volume_pct": float("nan"),
        }
    if best_bid <= 0 or best_ask <= 0:
        return {
            "ask_depth_1pct_usdt": float("nan"),
            "ask_depth_to_24h_volume_pct": float("nan"),
        }

    mid_price = (best_bid + best_ask) / 2.0
    ask_limit = mid_price * 1.01
    ask_depth_1pct_usdt = 0.0
    for row in asks:
        try:
            price = float(row[0])
            qty = float(row[1])
        except Exception:
            continue
        if price > ask_limit:
            break
        ask_depth_1pct_usdt += price * qty

    if quote_volume_24h <= 0:
        ask_depth_to_24h_volume_pct = float("nan")
    else:
        ask_depth_to_24h_volume_pct = ask_depth_1pct_usdt / quote_volume_24h * 100.0

    return {
        "ask_depth_1pct_usdt": ask_depth_1pct_usdt,
        "ask_depth_to_24h_volume_pct": ask_depth_to_24h_volume_pct,
    }


def _percentile_score(series: pd.Series, *, ascending: bool = True, positive_only: bool = False) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if positive_only:
        numeric = numeric.where(numeric > 0)
    valid = numeric.dropna()
    if valid.empty:
        return pd.Series(0.0, index=series.index)
    if positive_only and float(valid.max()) <= 0:
        return pd.Series(0.0, index=series.index)
    if float(valid.max()) - float(valid.min()) < 1e-12:
        if positive_only:
            return numeric.notna().astype(float).reindex(series.index).fillna(0.0) * 100.0
        return pd.Series(0.0, index=series.index)
    ranked = valid.rank(pct=True, ascending=ascending) * 100.0
    return ranked.reindex(series.index).fillna(0.0)


def _linear_score(series: pd.Series, *, low: float, high: float, invert: bool = False) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if high <= low:
        return pd.Series(0.0, index=series.index)
    scaled = ((numeric - low) / (high - low) * 100.0).clip(lower=0.0, upper=100.0)
    if invert:
        scaled = 100.0 - scaled
    return scaled.fillna(0.0)


def _log_ratio_score(series: pd.Series, *, low: float = 2.0, high: float = 80.0) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce").where(lambda values: values > 0)
    low_log = math.log10(max(low, 1e-12))
    high_log = math.log10(max(high, low + 1e-12))
    scored = ((numeric.map(math.log10) - low_log) / (high_log - low_log) * 100.0).clip(lower=0.0, upper=100.0)
    return scored.fillna(0.0)


def _band_score(series: pd.Series, *, low: float, sweet_low: float, sweet_high: float, high: float) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if sweet_low <= low or high <= sweet_high:
        return pd.Series(0.0, index=series.index)
    left = ((numeric - low) / (sweet_low - low) * 100.0).clip(lower=0.0, upper=100.0)
    right = ((high - numeric) / (high - sweet_high) * 100.0).clip(lower=0.0, upper=100.0)
    scored = pd.Series(100.0, index=series.index)
    scored = scored.where(numeric >= sweet_low, other=left)
    scored = scored.where(numeric <= sweet_high, other=right)
    return scored.fillna(0.0).clip(lower=0.0, upper=100.0)


def _apply_crime_pump_scores(all_df: pd.DataFrame) -> pd.DataFrame:
    if all_df.empty:
        return all_df

    velocity_score = _percentile_score(all_df["hour_return_z"], positive_only=True)
    day_momo_score = _percentile_score(all_df["day_return_pct"], positive_only=True)
    volume_score = _percentile_score(all_df["hour_volume_multiple"], positive_only=True)
    trade_count_score = _percentile_score(all_df["hour_trade_count_multiple"], positive_only=True)
    oi_score = _percentile_score(all_df["oi_delta_pct"], positive_only=True)
    oi_turnover_score = _percentile_score(all_df["oi_to_24h_volume_pct"], positive_only=True)
    oi_fade_score = _percentile_score(-pd.to_numeric(all_df["oi_delta_pct"], errors="coerce"), positive_only=True)
    funding_score = _percentile_score(all_df["carry_funding_pct"], positive_only=True)
    premium_score = _percentile_score(all_df["premium_index_pct"], positive_only=True)
    basis_score = _percentile_score(all_df["basis_rate_pct"], positive_only=True)
    taker_score = _percentile_score(all_df["taker_buy_sell_ratio"], positive_only=True)
    divergence_score = _percentile_score(all_df["crowd_top_position_divergence_pct"], positive_only=True)
    account_divergence_score = _percentile_score(all_df["crowd_top_account_divergence_pct"], positive_only=True)
    thinness_score = _percentile_score(all_df["ask_depth_to_24h_volume_pct"], ascending=False, positive_only=True)
    low_quote_volume_score = _percentile_score(all_df["quote_volume_24h"], ascending=False, positive_only=True)
    low_abs_depth_score = _percentile_score(all_df["ask_depth_1pct_usdt"], ascending=False, positive_only=True)
    high_quote_volume_score = _percentile_score(all_df["quote_volume_24h"], positive_only=True)
    high_abs_depth_score = _percentile_score(all_df["ask_depth_1pct_usdt"], positive_only=True)
    coinbase_spot_score = _percentile_score(all_df["coinbase_to_perp_volume_pct"], positive_only=True)
    coinbase_share_score = _percentile_score(all_df["coinbase_volume_share_pct"], positive_only=True)
    spot_support_score = _percentile_score(all_df["spot_to_perp_volume_pct"], positive_only=True)
    venue_concentration_rank_score = _percentile_score(all_df["venue_concentration_score"], positive_only=True)
    venue_hhi_score = pd.to_numeric(
        all_df.get("venue_hhi_score", pd.Series(0.0, index=all_df.index)),
        errors="coerce",
    ).fillna(0.0).clip(lower=0.0, upper=100.0)
    trio_lane_score = pd.to_numeric(
        all_df.get("binance_bitget_gate_share_score", pd.Series(0.0, index=all_df.index)),
        errors="coerce",
    ).fillna(0.0).clip(lower=0.0, upper=100.0)
    emfx_lane_score = pd.to_numeric(
        all_df.get("emfx_lane_score", pd.Series(0.0, index=all_df.index)),
        errors="coerce",
    ).fillna(0.0).clip(lower=0.0, upper=100.0)
    cb_depth_volume_score = _linear_score(all_df["coinbase_depth_to_volume_pct"], low=0.0, high=1.0)
    cb_depth_perp_score = _linear_score(all_df["coinbase_depth_to_perp_volume_pct"], low=0.0, high=0.75)
    cb_tight_spread_score = _linear_score(all_df["coinbase_bid_ask_spread_pct"], low=0.0, high=0.60, invert=True)
    cb_share_direct_score = _linear_score(all_df["coinbase_volume_share_pct"], low=0.0, high=30.0)
    binance_share_direct_score = _linear_score(
        all_df.get("binance_volume_share_pct", pd.Series(float("nan"), index=all_df.index)),
        low=5.0,
        high=45.0,
    )
    bitget_share_direct_score = _linear_score(
        all_df.get("bitget_volume_share_pct", pd.Series(float("nan"), index=all_df.index)),
        low=3.0,
        high=35.0,
    )
    gate_share_direct_score = _linear_score(
        all_df.get("gate_volume_share_pct", pd.Series(float("nan"), index=all_df.index)),
        low=2.0,
        high=25.0,
    )
    krw_share_direct_score = _linear_score(
        all_df.get("krw_volume_share_pct", pd.Series(float("nan"), index=all_df.index)),
        low=2.0,
        high=35.0,
    )
    try_share_direct_score = _linear_score(
        all_df.get("try_volume_share_pct", pd.Series(float("nan"), index=all_df.index)),
        low=1.0,
        high=20.0,
    )
    spot_mcap_score = _linear_score(all_df["spot_volume_to_mcap_pct"], low=25.0, high=250.0)
    perp_mcap_score = _linear_score(all_df["perp_volume_to_mcap_pct"], low=50.0, high=500.0)
    oi_mcap_score = _linear_score(all_df["oi_to_market_cap_pct"], low=3.0, high=40.0)
    cmc_mover_score = pd.to_numeric(
        all_df.get("cmc_mover_score", pd.Series(0.0, index=all_df.index)),
        errors="coerce",
    ).fillna(0.0).clip(lower=0.0, upper=100.0)
    cmc_volume_mcap_score = _linear_score(
        all_df.get("cmc_volume_to_mcap_pct", pd.Series(float("nan"), index=all_df.index)),
        low=25.0,
        high=300.0,
    )
    cex_dex_score = pd.to_numeric(
        all_df.get("cex_dex_volume_ratio_score", pd.Series(0.0, index=all_df.index)),
        errors="coerce",
    ).fillna(0.0).clip(lower=0.0, upper=100.0)
    cex_share_direct_score = _linear_score(
        all_df.get("cex_volume_share_pct", pd.Series(float("nan"), index=all_df.index)),
        low=60.0,
        high=98.0,
    )
    locked_supply_score = _percentile_score(all_df["locked_supply_pct"], positive_only=True)
    fdv_float_gap_score = _percentile_score(all_df["fdv_to_market_cap"], positive_only=True)
    holder_concentration_score = _percentile_score(all_df["holder_concentration_score"], positive_only=True)
    low_holder_count_score = _percentile_score(all_df["holder_count"], ascending=False, positive_only=True)
    close_near_high_score = _percentile_score(all_df["hour_close_location_pct"], positive_only=True)
    upper_wick_score = _percentile_score(all_df["hour_upper_wick_pct"], positive_only=True)
    major_excluded = all_df["crime_excluded_major"].fillna(False).astype(bool)
    mm_proximity_score = pd.to_numeric(all_df["mm_proximity_score"], errors="coerce").fillna(0.0).clip(
        lower=0.0,
        upper=100.0,
    )
    dwf_portfolio_score = pd.to_numeric(
        all_df.get("dwf_labs_portfolio_score", pd.Series(0.0, index=all_df.index)),
        errors="coerce",
    ).fillna(0.0).clip(lower=0.0, upper=100.0)
    coinbase_listed_score = all_df["coinbase_spot_listed"].fillna(False).astype(bool).astype(float) * 100.0
    cb_imbalance = pd.to_numeric(all_df["coinbase_book_imbalance_pct"], errors="coerce")
    cb_book_balance_score = (100.0 - (cb_imbalance - 50.0).abs() * 2.0).clip(lower=0.0, upper=100.0).fillna(0.0)
    cb_bid_skew_score = ((cb_imbalance - 50.0) * 2.0).clip(lower=0.0, upper=100.0).fillna(0.0)
    cb_ask_skew_score = ((50.0 - cb_imbalance) * 2.0).clip(lower=0.0, upper=100.0).fillna(0.0)
    cb_depth_gap_score = _linear_score(all_df["coinbase_depth_to_perp_volume_pct"], low=0.0, high=0.25, invert=True).where(
        all_df["coinbase_spot_listed"].astype(bool),
        other=0.0,
    )

    all_df["crime_carry_stress_score"] = (funding_score + premium_score + basis_score) / 3.0
    all_df["crime_microstructure_score"] = low_quote_volume_score * 0.55 + low_abs_depth_score * 0.45
    all_df["crime_largecap_penalty_score"] = high_quote_volume_score * 0.60 + high_abs_depth_score * 0.40
    all_df["crime_coinbase_lane_score"] = (
        coinbase_spot_score * 0.42
        + coinbase_share_score * 0.42
        + all_df["coinbase_spot_listed"].astype(bool).astype(float) * 16.0
    ).clip(lower=0.0, upper=100.0)
    all_df["crime_owner_circle_score"] = (
        holder_concentration_score * 0.34
        + locked_supply_score * 0.24
        + fdv_float_gap_score * 0.18
        + low_holder_count_score * 0.10
        + venue_concentration_rank_score * 0.09
        + venue_hhi_score * 0.05
    ).clip(lower=0.0, upper=100.0)
    all_df["crime_spot_impulse_score"] = (
        spot_support_score * 0.55
        + all_df["crime_coinbase_lane_score"] * 0.35
        + venue_concentration_rank_score * 0.08
        + cex_dex_score * 0.12
        + trio_lane_score * 0.16
        + emfx_lane_score * 0.10
        + venue_hhi_score * 0.08
        + krw_share_direct_score * 0.04
        + try_share_direct_score * 0.03
        + cmc_volume_mcap_score * 0.08
        + cmc_mover_score * 0.04
    ).clip(lower=0.0, upper=100.0)
    all_df["crime_supply_control_score"] = (
        all_df["crime_owner_circle_score"]
    )
    all_df["mm_presence_score"] = (
        coinbase_listed_score * 0.10
        + cb_depth_volume_score * 0.27
        + cb_depth_perp_score * 0.20
        + cb_tight_spread_score * 0.18
        + cb_book_balance_score * 0.13
        + cb_share_direct_score * 0.07
        + all_df["crime_coinbase_lane_score"] * 0.05
        + mm_proximity_score * 0.08
        + dwf_portfolio_score * 0.06
    ).clip(lower=0.0, upper=100.0)
    all_df["mm_bid_support_score"] = (
        coinbase_listed_score * 0.08
        + cb_depth_volume_score * 0.24
        + cb_depth_perp_score * 0.22
        + cb_tight_spread_score * 0.10
        + cb_bid_skew_score * 0.24
        + all_df["crime_coinbase_lane_score"] * 0.12
        + mm_proximity_score * 0.06
        + dwf_portfolio_score * 0.04
    ).clip(lower=0.0, upper=100.0)
    all_df["mm_withdrawal_risk_score"] = (
        (100.0 - all_df["mm_presence_score"]) * 0.30
        + cb_ask_skew_score * 0.08
        + all_df["crime_owner_circle_score"] * 0.23
        + venue_concentration_rank_score * 0.14
        + upper_wick_score * 0.10
        + oi_fade_score * 0.08
        + all_df["crime_carry_stress_score"] * 0.07
    ).where(all_df["coinbase_spot_listed"].astype(bool), other=0.0).clip(lower=0.0, upper=100.0)
    all_df["inventory_sponsor_mismatch_score"] = (
        all_df["crime_coinbase_lane_score"] * 0.20
        + spot_mcap_score * 0.18
        + perp_mcap_score * 0.18
        + cb_depth_gap_score * 0.16
        + cex_dex_score * 0.12
        + mm_proximity_score * 0.16
        + dwf_portfolio_score * 0.10
        + venue_concentration_rank_score * 0.08
        + trio_lane_score * 0.10
        + emfx_lane_score * 0.06
        + venue_hhi_score * 0.04
    ).clip(lower=0.0, upper=100.0)
    all_df["inventory_transfer_risk_score"] = (
        all_df["crime_owner_circle_score"] * 0.24
        + all_df["inventory_sponsor_mismatch_score"] * 0.18
        + mm_proximity_score * 0.18
        + dwf_portfolio_score * 0.12
        + spot_mcap_score * 0.12
        + perp_mcap_score * 0.10
        + holder_concentration_score * 0.08
        + locked_supply_score * 0.06
        + oi_mcap_score * 0.04
        + cex_dex_score * 0.06
        + trio_lane_score * 0.08
        + emfx_lane_score * 0.06
    ).where(~major_excluded, other=0.0).clip(lower=0.0, upper=100.0)
    all_df["inventory_transfer_risk_flag"] = (
        (all_df["inventory_transfer_risk_score"] >= 65.0)
        & (
            (mm_proximity_score >= 55.0)
            | (dwf_portfolio_score >= 70.0)
            | (all_df["crime_owner_circle_score"] >= 55.0)
            | (all_df["holder_concentration_score"] >= 60.0)
        )
        & (
            (all_df["inventory_sponsor_mismatch_score"] >= 55.0)
            | (spot_mcap_score >= 70.0)
            | (perp_mcap_score >= 70.0)
        )
    )
    all_df["crime_mechanics_score"] = (
        all_df["crime_microstructure_score"] * 0.20
        + all_df["crime_coinbase_lane_score"] * 0.15
        + all_df["crime_spot_impulse_score"] * 0.12
        + all_df["crime_owner_circle_score"] * 0.17
        + all_df["mm_presence_score"] * 0.10
        + all_df["mm_bid_support_score"] * 0.06
        + mm_proximity_score * 0.08
        + dwf_portfolio_score * 0.07
        + all_df["inventory_transfer_risk_score"] * 0.06
        + cex_dex_score * 0.06
        + trio_lane_score * 0.08
        + emfx_lane_score * 0.05
        + venue_hhi_score * 0.04
        + cmc_mover_score * 0.06
        + velocity_score * 0.12
        + day_momo_score * 0.10
        + oi_score * 0.10
        + taker_score * 0.04
        - all_df["crime_largecap_penalty_score"] * 0.24
        - all_df["mm_withdrawal_risk_score"] * 0.05
    ).clip(lower=0.0, upper=100.0)
    all_df["crime_pump_score"] = (
        velocity_score * 0.14
        + day_momo_score * 0.12
        + volume_score * 0.10
        + trade_count_score * 0.08
        + oi_score * 0.14
        + all_df["crime_carry_stress_score"] * 0.11
        + taker_score * 0.10
        + divergence_score * 0.06
        + account_divergence_score * 0.03
        + thinness_score * 0.06
        + all_df["crime_microstructure_score"] * 0.07
        + all_df["crime_spot_impulse_score"] * 0.04
        + all_df["crime_supply_control_score"] * 0.03
        + all_df["mm_presence_score"] * 0.04
        + cex_share_direct_score * 0.02
        + trio_lane_score * 0.05
        + emfx_lane_score * 0.03
        + mm_proximity_score * 0.03
        + dwf_portfolio_score * 0.03
        + all_df["inventory_transfer_risk_score"] * 0.03
        + cmc_mover_score * 0.04
        + close_near_high_score * 0.04
        - all_df["crime_largecap_penalty_score"] * 0.18
    ).clip(lower=0.0, upper=100.0)
    all_df["crime_ignition_score"] = (
        velocity_score * 0.17
        + day_momo_score * 0.15
        + volume_score * 0.14
        + trade_count_score * 0.12
        + oi_score * 0.15
        + taker_score * 0.10
        + close_near_high_score * 0.09
        + thinness_score * 0.04
        + all_df["crime_microstructure_score"] * 0.06
        + all_df["crime_spot_impulse_score"] * 0.03
        + all_df["mm_bid_support_score"] * 0.03
        + cex_dex_score * 0.04
        + trio_lane_score * 0.04
        + emfx_lane_score * 0.03
        + mm_proximity_score * 0.03
        + dwf_portfolio_score * 0.03
        + cmc_mover_score * 0.06
        - all_df["crime_largecap_penalty_score"] * 0.14
    ).clip(lower=0.0, upper=100.0)
    all_df["crime_exhaustion_score"] = (
        upper_wick_score * 0.24
        + all_df["crime_carry_stress_score"] * 0.22
        + divergence_score * 0.12
        + account_divergence_score * 0.08
        + oi_fade_score * 0.14
        + volume_score * 0.08
        + day_momo_score * 0.06
        + oi_turnover_score * 0.06
    )
    all_df["crime_eligible"] = (
        ~major_excluded
        & (
            (all_df["crime_microstructure_score"] >= 45.0)
            | (all_df["crime_mechanics_score"] >= 50.0)
            | (
                (all_df["crime_coinbase_lane_score"] >= 55.0)
                & (all_df["crime_owner_circle_score"] >= 45.0)
            )
            | (
                (all_df["crime_spot_impulse_score"] >= 55.0)
                & (all_df["day_return_pct"] >= 8.0)
            )
            | (
                (all_df["mm_presence_score"] >= 55.0)
                & (all_df["crime_owner_circle_score"] >= 35.0)
                & (all_df["day_return_pct"] >= 5.0)
            )
            | (
                (all_df["mm_bid_support_score"] >= 60.0)
                & (all_df["crime_spot_impulse_score"] >= 40.0)
            )
            | (
                (mm_proximity_score >= 70.0)
                & (all_df["coinbase_spot_listed"].astype(bool))
                & (all_df["day_return_pct"] >= 3.0)
            )
            | (
                (dwf_portfolio_score >= 70.0)
                & (
                    (all_df["day_return_pct"] >= 1.5)
                    | (all_df["convexity_seed_score"] >= 35.0)
                    | (all_df["crime_spot_impulse_score"] >= 35.0)
                )
            )
            | (
                (all_df["inventory_transfer_risk_score"] >= 68.0)
                & (all_df["day_return_pct"] >= 3.0)
            )
            | (
                (cex_dex_score >= 65.0)
                & (
                    (all_df["day_return_pct"] >= 3.0)
                    | (spot_mcap_score >= 45.0)
                    | (perp_mcap_score >= 45.0)
                )
            )
            | (
                (trio_lane_score >= 60.0)
                & (cex_dex_score >= 55.0)
                & (
                    (all_df["day_return_pct"] >= 3.0)
                    | (spot_mcap_score >= 45.0)
                    | (all_df["crime_spot_impulse_score"] >= 45.0)
                )
            )
            | (
                (emfx_lane_score >= 55.0)
                & (
                    (all_df["day_return_pct"] >= 3.0)
                    | (spot_mcap_score >= 45.0)
                    | (all_df["crime_mechanics_score"] >= 45.0)
                )
            )
            | (
                (venue_hhi_score >= 65.0)
                & (cex_dex_score >= 55.0)
                & (
                    (all_df["crime_spot_impulse_score"] >= 45.0)
                    | (all_df["crime_mechanics_score"] >= 45.0)
                )
            )
            | (
                (cmc_mover_score >= 55.0)
                & (
                    (low_quote_volume_score >= 25.0)
                    | (all_df["crime_largecap_penalty_score"] <= 65.0)
                )
            )
            | (
                (low_quote_volume_score >= 35.0)
                & (low_abs_depth_score >= 35.0)
            )
        )
    )

    all_df["crime_pump_flag"] = (
        all_df["crime_eligible"]
        & (all_df["crime_pump_score"] >= 70.0)
        & (all_df["hour_return_pct"] >= 4.0)
        & (all_df["oi_delta_pct"] >= 2.0)
        & (all_df["taker_buy_sell_ratio"] >= 1.15)
    )
    all_df["squeeze_risk_flag"] = (
        all_df["crime_eligible"]
        & (all_df["hour_return_pct"] >= 3.0)
        & (all_df["oi_delta_pct"] >= 3.0)
        & (all_df["taker_buy_sell_ratio"] >= 1.20)
        & (all_df["long_short_account_ratio"] >= 1.10)
        & (all_df["crowd_top_position_divergence_pct"] >= 5.0)
    )
    all_df["ignition_setup_flag"] = (
        all_df["crime_eligible"]
        & (all_df["crime_ignition_score"] >= 68.0)
        & (all_df["hour_return_pct"] >= 3.0)
        & (all_df["day_return_pct"] >= 12.0)
        & (all_df["oi_delta_pct"] >= 2.0)
        & (all_df["taker_buy_sell_ratio"] >= 1.05)
        & (all_df["hour_trade_count_multiple"] >= 1.40)
        & (all_df["hour_close_location_pct"] >= 65.0)
    )
    all_df["exhaustion_flag"] = (
        (all_df["crime_exhaustion_score"] >= 68.0)
        & (all_df["hour_upper_wick_pct"] >= 30.0)
        & ((all_df["oi_delta_pct"] <= 0.0) | (all_df["carry_funding_pct"] >= 0.02))
    )
    all_df["blowoff_risk_flag"] = (
        all_df["crime_eligible"]
        & (all_df["crime_exhaustion_score"] >= 75.0)
        & (all_df["hour_volume_multiple"] >= 2.5)
        & ((all_df["carry_funding_pct"] >= 0.02) | (all_df["basis_rate_pct"] >= 0.10))
        & (all_df["ask_depth_to_24h_volume_pct"] <= 0.60)
    )

    def _inventory_transfer_note(row: pd.Series) -> str:
        triggers: list[str] = []
        if _safe_float(row.get("mm_proximity_score")) >= 70.0:
            maker = str(row.get("mm_proximity_maker", "")).strip()
            triggers.append(f"{maker} proximity" if maker else "MM proximity")
        if bool(row.get("dwf_labs_portfolio")):
            triggers.append("DWF Labs portfolio")
        if _safe_float(row.get("crime_owner_circle_score")) >= 55.0:
            triggers.append("controlled holder/float proxy")
        if _safe_float(row.get("inventory_sponsor_mismatch_score")) >= 60.0:
            triggers.append("sponsor/depth mismatch")
        if _safe_float(row.get("spot_volume_to_mcap_pct")) >= 100.0:
            triggers.append("spot volume > market cap")
        if _safe_float(row.get("cex_to_dex_volume_ratio")) >= 10.0:
            triggers.append("CEX volume dominates DEX")
        if _safe_float(row.get("binance_bitget_gate_share_pct")) >= 50.0:
            triggers.append("Binance/Bitget/Gate lane dominates")
        if _safe_float(row.get("emfx_volume_share_pct")) >= 12.0:
            triggers.append("EMFX quote lane active")
        if _safe_float(row.get("try_volume_share_pct")) >= 4.0:
            triggers.append("TRY quote lane active")
        if _safe_float(row.get("perp_volume_to_mcap_pct")) >= 250.0:
            triggers.append("perp volume extreme vs mcap")
        if _safe_float(row.get("oi_to_market_cap_pct")) >= 20.0:
            triggers.append("OI large vs mcap")
        if _safe_float(row.get("top_venue_volume_share_pct")) >= 45.0:
            triggers.append("single venue dominates volume")
        if _safe_float(row.get("venue_hhi_score")) >= 65.0:
            triggers.append("venue concentration extreme")
        if _safe_float(row.get("coinbase_depth_to_perp_volume_pct")) > 0 and _safe_float(row.get("coinbase_depth_to_perp_volume_pct")) <= 0.05:
            triggers.append("tiny visible CB depth vs perp flow")
        if not triggers:
            return "No strong OTC/inventory-transfer fingerprint."
        return " | ".join(triggers[:5])

    all_df["inventory_transfer_note"] = all_df.apply(_inventory_transfer_note, axis=1)
    return all_df


def _apply_rave_lab_setup_scores(all_df: pd.DataFrame) -> pd.DataFrame:
    """Rank controlled-float upside setups without making claims about intent."""
    if all_df.empty:
        for col in RAVE_LAB_SETUP_COLUMNS:
            dtype = "object" if col in RAVE_LAB_TEXT_COLUMNS else "bool" if col in RAVE_LAB_BOOL_COLUMNS else "float64"
            all_df[col] = pd.Series(dtype=dtype)
        return all_df

    all_df = all_df.copy()
    index = all_df.index

    def _num(col: str, default: float = 0.0) -> pd.Series:
        if col in all_df.columns:
            values = pd.to_numeric(all_df[col], errors="coerce")
        else:
            values = pd.Series(default, index=index)
        return values.fillna(default)

    def _raw_num(col: str, default: float = float("nan")) -> pd.Series:
        if col in all_df.columns:
            return pd.to_numeric(all_df[col], errors="coerce")
        return pd.Series(default, index=index)

    owner_holder = _num("owner_holder_pct")
    creator_holder = _num("creator_holder_pct")
    top10_holder = _num("top10_holder_pct")
    holder_count = _raw_num("holder_count")
    insider_team_holder = (owner_holder + creator_holder).clip(lower=0.0, upper=100.0)

    insider_score = _linear_score(insider_team_holder, low=2.0, high=35.0)
    top10_score = _linear_score(top10_holder, low=18.0, high=70.0)
    holder_count_score = _linear_score(holder_count, low=500.0, high=25_000.0, invert=True)
    holder_concentration_score = _num("holder_concentration_score").clip(lower=0.0, upper=100.0)
    owner_circle_score = _num("crime_owner_circle_score").clip(lower=0.0, upper=100.0)
    centralised_ownership = (
        holder_concentration_score * 0.28
        + top10_score * 0.24
        + insider_score * 0.22
        + owner_circle_score * 0.18
        + holder_count_score * 0.08
    ).clip(lower=0.0, upper=100.0)

    circulating_pct = _raw_num("circulating_supply_pct")
    locked_pct = _num("locked_supply_pct")
    fdv_to_market_cap = _raw_num("fdv_to_market_cap")
    low_circulating_score = _linear_score(circulating_pct, low=3.0, high=35.0, invert=True)
    locked_supply_score = _linear_score(locked_pct, low=15.0, high=85.0)
    fdv_gap_score = _log_ratio_score(fdv_to_market_cap, low=1.8, high=18.0)
    low_float_score = (
        low_circulating_score * 0.31
        + locked_supply_score * 0.25
        + fdv_gap_score * 0.20
        + _num("float_trap_score").clip(lower=0.0, upper=100.0) * 0.14
        + _num("valuation_trap_score").clip(lower=0.0, upper=100.0) * 0.10
    ).clip(lower=0.0, upper=100.0)

    short_account_pct = _raw_num("short_account_pct")
    long_short_ratio = _raw_num("long_short_account_ratio")
    short_change_pct = _num("short_account_change_max_pct")
    short_change_pp = _num("short_account_change_max_pp")
    oi_delta = _raw_num("oi_delta_pct")
    taker_buy_share = _raw_num("taker_buy_share_pct")
    short_dominance_score = (
        _linear_score(short_account_pct, low=50.0, high=76.0) * 0.42
        + _linear_score(long_short_ratio, low=0.30, high=0.95, invert=True) * 0.28
        + _num("short_crowding_score").clip(lower=0.0, upper=100.0) * 0.13
        + _linear_score(short_change_pct, low=0.5, high=8.0) * 0.09
        + _linear_score(short_change_pp, low=0.25, high=4.0) * 0.08
    ).clip(lower=0.0, upper=100.0)
    short_account_build_score = (
        _linear_score(short_account_pct, low=48.0, high=72.0) * 0.26
        + _linear_score(long_short_ratio, low=0.35, high=1.0, invert=True) * 0.20
        + _linear_score(short_change_pct, low=1.0, high=12.0) * 0.22
        + _linear_score(short_change_pp, low=0.35, high=6.0) * 0.16
        + _num("crowd_skew_confluence_score").clip(lower=0.0, upper=100.0) * 0.16
    ).clip(lower=0.0, upper=100.0)

    day_return = _raw_num("day_return_pct")
    abs_day_return = day_return.abs()
    abs_hour_return = _raw_num("hour_return_pct").abs()
    range_24h = _raw_num("range_24h_pct")
    quiet_range_score = _linear_score(range_24h, low=2.0, high=18.0, invert=True)
    quiet_return_score = (
        _linear_score(abs_day_return, low=1.0, high=18.0, invert=True) * 0.62
        + _linear_score(abs_hour_return, low=0.2, high=5.5, invert=True) * 0.38
    ).clip(lower=0.0, upper=100.0)
    gentle_wake_score = (
        _band_score(_raw_num("daily_quote_volume_multiple"), low=0.75, sweet_low=1.05, sweet_high=2.60, high=8.0) * 0.46
        + _band_score(_raw_num("hour_volume_multiple"), low=0.70, sweet_low=1.05, sweet_high=2.80, high=8.0) * 0.34
        + _band_score(_raw_num("hour_trade_count_multiple"), low=0.70, sweet_low=1.05, sweet_high=2.50, high=7.0) * 0.20
    ).clip(lower=0.0, upper=100.0)
    low_volatility_coil_score = (
        quiet_range_score * 0.42
        + quiet_return_score * 0.38
        + gentle_wake_score * 0.20
    ).clip(lower=0.0, upper=100.0)
    oi_growth_score = _linear_score(oi_delta, low=0.15, high=5.0)
    price_not_falling_score = _band_score(day_return, low=-4.0, sweet_low=-0.5, sweet_high=8.0, high=35.0)
    pre_pump_compression_score = (
        low_volatility_coil_score * 0.44
        + gentle_wake_score * 0.20
        + oi_growth_score * 0.18
        + price_not_falling_score * 0.12
        + _linear_score(_raw_num("distance_to_high_20d_pct"), low=-18.0, high=6.0, invert=True) * 0.06
    ).clip(lower=0.0, upper=100.0)
    short_trap_score = (
        short_dominance_score * 0.36
        + oi_growth_score * 0.24
        + price_not_falling_score * 0.18
        + _linear_score(taker_buy_share, low=48.0, high=62.0) * 0.10
        + _linear_score(short_change_pp, low=0.4, high=4.5) * 0.12
    ).clip(lower=0.0, upper=100.0)
    silent_oi_accumulation_score = (
        low_volatility_coil_score * 0.34
        + oi_growth_score * 0.34
        + short_dominance_score * 0.16
        + gentle_wake_score * 0.10
        + _linear_score(_raw_num("oi_to_24h_volume_pct"), low=2.0, high=16.0) * 0.06
    ).clip(lower=0.0, upper=100.0)
    pre_pump_short_fuse_score = (
        pre_pump_compression_score * 0.28
        + short_trap_score * 0.24
        + silent_oi_accumulation_score * 0.16
        + low_float_score * 0.18
        + centralised_ownership * 0.16
    ).clip(lower=0.0, upper=100.0)
    price_volume_ignition_score = (
        _band_score(day_return, low=1.0, sweet_low=8.0, sweet_high=120.0, high=450.0) * 0.18
        + _linear_score(_raw_num("hour_return_pct"), low=0.5, high=14.0) * 0.14
        + _log_ratio_score(_raw_num("daily_quote_volume_multiple"), low=1.08, high=12.0) * 0.18
        + _log_ratio_score(_raw_num("hour_volume_multiple"), low=1.10, high=9.0) * 0.16
        + _log_ratio_score(_raw_num("hour_trade_count_multiple"), low=1.10, high=7.0) * 0.11
        + _num("breakout_pressure_score").clip(lower=0.0, upper=100.0) * 0.13
        + _num("cmc_mover_score").clip(lower=0.0, upper=100.0) * 0.10
    ).clip(lower=0.0, upper=100.0)

    target_cex_share = (
        _num("binance_volume_share_pct")
        + _num("bitget_volume_share_pct")
        + _num("gate_volume_share_pct")
        + _num("okx_volume_share_pct")
        + _num("okex_volume_share_pct")
    ).clip(lower=0.0, upper=100.0)
    target_cex_flow_score = (
        _linear_score(target_cex_share, low=18.0, high=85.0) * 0.31
        + _num("cex_dex_volume_ratio_score").clip(lower=0.0, upper=100.0) * 0.22
        + _num("inventory_transfer_risk_score").clip(lower=0.0, upper=100.0) * 0.27
        + _num("venue_hhi_score").clip(lower=0.0, upper=100.0) * 0.12
        + all_df.get("inventory_transfer_risk_flag", pd.Series(False, index=index)).fillna(False).astype(bool).astype(float) * 8.0
    ).clip(lower=0.0, upper=100.0)

    convex_fuel = pd.concat(
        [
            _num("clean_convex_setup_score"),
            _num("forced_buying_setup_score"),
            _num("squeeze_machine_score"),
            _num("convexity_entry_score"),
            _num("short_liquidation_fuel_score"),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0).clip(lower=0.0, upper=100.0)
    late_penalty = (
        _num("crime_exhaustion_score").clip(lower=0.0, upper=100.0) * 0.28
        + _num("convexity_late_penalty").clip(lower=0.0, upper=100.0) * 0.30
        + _num("exit_fragility_score").clip(lower=0.0, upper=100.0) * 0.18
        + _linear_score(day_return, low=130.0, high=650.0) * 0.16
        + _num("crime_largecap_penalty_score").clip(lower=0.0, upper=100.0) * 0.08
    ).clip(lower=0.0, upper=100.0)
    no_chase_penalty_score = (
        _linear_score(day_return, low=55.0, high=260.0) * 0.22
        + _linear_score(_raw_num("hour_return_pct"), low=12.0, high=42.0) * 0.14
        + _linear_score(range_24h, low=18.0, high=80.0) * 0.12
        + _num("crime_exhaustion_score").clip(lower=0.0, upper=100.0) * 0.18
        + _num("convexity_late_penalty").clip(lower=0.0, upper=100.0) * 0.16
        + _num("exit_fragility_score").clip(lower=0.0, upper=100.0) * 0.10
        + _linear_score(_raw_num("carry_funding_pct"), low=0.015, high=0.12) * 0.08
    ).clip(lower=0.0, upper=100.0)
    dormant_short_fuse_score = (
        pre_pump_short_fuse_score * 0.76
        + target_cex_flow_score * 0.08
        + convex_fuel * 0.08
        + oi_growth_score * 0.08
        - no_chase_penalty_score * 0.16
    ).clip(lower=0.0, upper=100.0)
    timing_score = pd.concat(
        [price_volume_ignition_score, dormant_short_fuse_score],
        axis=1,
    ).max(axis=1).fillna(0.0).clip(lower=0.0, upper=100.0)

    raw_score = (
        centralised_ownership * 0.22
        + low_float_score * 0.20
        + short_account_build_score * 0.11
        + short_dominance_score * 0.07
        + timing_score * 0.20
        + target_cex_flow_score * 0.11
        + convex_fuel * 0.09
        - late_penalty * 0.16
        - _num("crime_largecap_penalty_score").clip(lower=0.0, upper=100.0) * 0.08
    ).clip(lower=0.0, upper=100.0)
    major_excluded = all_df.get("crime_excluded_major", pd.Series(False, index=index)).fillna(False).astype(bool)
    setup_score = raw_score.where(~major_excluded, other=0.0).clip(lower=0.0, upper=100.0)

    all_df["insider_team_holder_pct"] = insider_team_holder
    all_df["centralized_ownership_score"] = centralised_ownership
    all_df["low_float_score"] = low_float_score
    all_df["short_account_build_score"] = short_account_build_score
    all_df["short_dominance_score"] = short_dominance_score
    all_df["low_volatility_coil_score"] = low_volatility_coil_score
    all_df["pre_pump_compression_score"] = pre_pump_compression_score
    all_df["short_trap_score"] = short_trap_score
    all_df["silent_oi_accumulation_score"] = silent_oi_accumulation_score
    all_df["pre_pump_short_fuse_score"] = pre_pump_short_fuse_score
    all_df["dormant_short_fuse_score"] = dormant_short_fuse_score
    all_df["price_volume_ignition_score"] = price_volume_ignition_score
    all_df["target_cex_volume_share_pct"] = target_cex_share
    all_df["target_cex_flow_score"] = target_cex_flow_score
    all_df["rave_lab_convex_fuel_score"] = convex_fuel
    all_df["rave_lab_late_penalty_score"] = late_penalty
    all_df["no_chase_penalty_score"] = no_chase_penalty_score
    all_df["no_chase_ok_flag"] = (no_chase_penalty_score < 60.0) & (~major_excluded)
    all_df["pre_pump_precision_score"] = (
        pre_pump_compression_score * 0.24
        + short_trap_score * 0.24
        + silent_oi_accumulation_score * 0.18
        + low_float_score * 0.14
        + centralised_ownership * 0.12
        + target_cex_flow_score * 0.08
        - no_chase_penalty_score * 0.16
    ).where(~major_excluded, other=0.0).clip(lower=0.0, upper=100.0)
    all_df["rave_lab_setup_score"] = setup_score
    all_df["dormant_short_fuse_flag"] = (
        (dormant_short_fuse_score >= 58.0)
        & (low_volatility_coil_score >= 52.0)
        & (short_dominance_score >= 50.0)
        & ((low_float_score >= 38.0) | (centralised_ownership >= 45.0))
        & (no_chase_penalty_score < 62.0)
        & (~major_excluded)
    )
    all_df["pre_pump_precision_flag"] = (
        (all_df["pre_pump_precision_score"] >= 62.0)
        & (pre_pump_compression_score >= 45.0)
        & (short_trap_score >= 45.0)
        & ((low_float_score >= 38.0) | (centralised_ownership >= 44.0))
        & (no_chase_penalty_score < 60.0)
        & (~major_excluded)
    )
    all_df["rave_lab_watch_flag"] = (setup_score >= 50.0) & (~major_excluded)
    all_df["rave_lab_setup_flag"] = (
        (setup_score >= 62.0)
        & (centralised_ownership >= 42.0)
        & (low_float_score >= 35.0)
        & (
            (short_account_build_score >= 38.0)
            | (price_volume_ignition_score >= 55.0)
            | (dormant_short_fuse_score >= 58.0)
        )
        & (~major_excluded)
    )
    all_df["rave_lab_extreme_flag"] = (
        (setup_score >= 76.0)
        & (centralised_ownership >= 55.0)
        & (low_float_score >= 48.0)
        & (price_volume_ignition_score >= 45.0)
        & (no_chase_penalty_score < 66.0)
        & (~major_excluded)
    )

    def _short_fuse_note(row: pd.Series) -> str:
        if bool(row.get("crime_excluded_major")):
            return "Major/liquid tape excluded from the low-vol short-fuse radar."
        factors: list[str] = []
        if _safe_float(row.get("low_volatility_coil_score")) >= 55.0:
            factors.append(f"quiet 24h range {_safe_float(row.get('range_24h_pct')):.1f}%")
        if _safe_float(row.get("short_dominance_score")) >= 55.0:
            factors.append(f"short accounts {_safe_float(row.get('short_account_pct')):.1f}%")
        if _safe_float(row.get("short_account_change_max_pp")) >= 1.0:
            window = str(row.get("short_account_change_max_window", "")).strip()
            suffix = f" over {window}" if window else ""
            factors.append(f"short share +{_safe_float(row.get('short_account_change_max_pp')):.1f}pp{suffix}")
        if _safe_float(row.get("low_float_score")) >= 45.0:
            factors.append("low float / FDV gap")
        if _safe_float(row.get("centralized_ownership_score")) >= 45.0:
            factors.append("centralized holder proxy")
        if _safe_float(row.get("target_cex_flow_score")) >= 50.0:
            factors.append("target CEX-flow lane")
        if _safe_float(row.get("rave_lab_late_penalty_score")) >= 68.0:
            factors.append("late heat offset")
        if not factors:
            return "No quiet short-fuse pattern in this scan."
        return " | ".join(factors[:6])

    def _precision_note(row: pd.Series) -> str:
        if bool(row.get("crime_excluded_major")):
            return "Major/liquid tape excluded from the pre-ignition precision radar."
        factors: list[str] = []
        if _safe_float(row.get("pre_pump_compression_score")) >= 55.0:
            factors.append("compression")
        if _safe_float(row.get("short_trap_score")) >= 55.0:
            factors.append("short trap")
        if _safe_float(row.get("silent_oi_accumulation_score")) >= 55.0:
            factors.append("silent OI build")
        if _safe_float(row.get("low_float_score")) >= 45.0:
            factors.append("low float")
        if _safe_float(row.get("centralized_ownership_score")) >= 45.0:
            factors.append("centralized ownership")
        if _safe_float(row.get("target_cex_flow_score")) >= 50.0:
            factors.append("target CEX lane")
        if _safe_float(row.get("no_chase_penalty_score")) >= 60.0:
            factors.append("no-chase blocked")
        if not factors:
            return "No high-precision pre-ignition pattern in this scan."
        return " | ".join(factors[:6])

    def _setup_note(row: pd.Series) -> str:
        if bool(row.get("crime_excluded_major")):
            return "Major/liquid tape excluded from this controlled-float upside radar."
        factors: list[str] = []
        if _safe_float(row.get("pre_pump_precision_score")) >= 62.0:
            factors.append("pre-ignition precision")
        if _safe_float(row.get("dormant_short_fuse_score")) >= 58.0:
            factors.append("low-vol short fuse")
        if _safe_float(row.get("centralized_ownership_score")) >= 55.0:
            factors.append("centralized holder/insider proxy")
        elif _safe_float(row.get("insider_team_holder_pct")) >= 8.0:
            factors.append(f"insider/team proxy {_safe_float(row.get('insider_team_holder_pct')):.1f}%")
        if _safe_float(row.get("low_float_score")) >= 55.0:
            factors.append("very low float / FDV gap")
        if _safe_float(row.get("short_account_build_score")) >= 55.0:
            window = str(row.get("short_account_change_max_window", "")).strip()
            suffix = f" over {window}" if window else ""
            factors.append(f"short accounts building{suffix}")
        elif _safe_float(row.get("short_account_pct")) >= 55.0:
            factors.append(f"short accounts {_safe_float(row.get('short_account_pct')):.1f}%")
        if _safe_float(row.get("price_volume_ignition_score")) >= 55.0:
            factors.append("price/volume ignition")
        if _safe_float(row.get("target_cex_flow_score")) >= 55.0:
            factors.append("Binance/Bitget/Gate/OKX lane or CEX-flow proxy")
        if _safe_float(row.get("rave_lab_convex_fuel_score")) >= 55.0:
            factors.append("convex forced-buying fuel")
        if _safe_float(row.get("rave_lab_late_penalty_score")) >= 70.0:
            factors.append("late-stage heat offset")
        if not factors:
            return "No strong RAVE/LAB-style setup in this scan."
        return " | ".join(factors[:6])

    all_df["dormant_short_fuse_note"] = all_df.apply(_short_fuse_note, axis=1)
    all_df["pre_pump_precision_note"] = all_df.apply(_precision_note, axis=1)
    all_df["rave_lab_setup_note"] = all_df.apply(_setup_note, axis=1)
    return all_df


PRE_PUMP_SNAPSHOT_COLUMNS = [
    "snapshot_ts",
    "symbol",
    "base_asset",
    "last_price",
    "quote_volume_24h",
    "range_24h_pct",
    "day_return_pct",
    "hour_return_pct",
    "daily_quote_volume_multiple",
    "hour_volume_multiple",
    "hour_trade_count_multiple",
    "oi_value_usdt",
    "oi_delta_pct",
    "ask_depth_1pct_usdt",
    "ask_depth_to_24h_volume_pct",
    "short_account_pct",
    "long_account_pct",
    "short_account_change_max_pp",
    "short_account_change_max_pct",
    "short_account_change_max_window",
    "target_cex_volume_share_pct",
    "centralized_ownership_score",
    "low_float_score",
    "pre_pump_compression_score",
    "short_trap_score",
    "silent_oi_accumulation_score",
    "cex_lane_wakeup_score",
    "thin_ask_trap_score",
    "no_chase_penalty_score",
    "pre_pump_precision_score",
    "dormant_short_fuse_score",
    "rave_lab_setup_score",
    "pre_pump_precision_flag",
    "dormant_short_fuse_flag",
    "rave_lab_setup_flag",
]


def _read_pre_pump_snapshot_history() -> pd.DataFrame:
    path = PRE_PUMP_SNAPSHOT_PATH
    if not path.exists():
        return pd.DataFrame(columns=PRE_PUMP_SNAPSHOT_COLUMNS)
    try:
        history = pd.read_csv(path)
    except Exception:
        return pd.DataFrame(columns=PRE_PUMP_SNAPSHOT_COLUMNS)
    if history.empty or "snapshot_ts" not in history.columns or "symbol" not in history.columns:
        return pd.DataFrame(columns=PRE_PUMP_SNAPSHOT_COLUMNS)
    history["snapshot_ts"] = pd.to_datetime(history["snapshot_ts"], errors="coerce", utc=True)
    history = history[history["snapshot_ts"].notna()].copy()
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=max(PRE_PUMP_SNAPSHOT_RETENTION_DAYS, 1))
    history = history[history["snapshot_ts"] >= cutoff].copy()
    history["symbol"] = history["symbol"].astype(str).str.upper()
    return history


def _append_pre_pump_snapshots(all_df: pd.DataFrame) -> None:
    if all_df.empty:
        return
    path = PRE_PUMP_SNAPSHOT_PATH
    snapshot = _display_frame(all_df, [col for col in PRE_PUMP_SNAPSHOT_COLUMNS if col != "snapshot_ts"])
    if snapshot.empty or "symbol" not in snapshot.columns:
        return
    snapshot = snapshot.copy()
    snapshot.insert(0, "snapshot_ts", pd.Timestamp.now(tz="UTC").isoformat())
    for col in PRE_PUMP_SNAPSHOT_COLUMNS:
        if col not in snapshot.columns:
            snapshot[col] = "" if col in {"base_asset", "short_account_change_max_window"} else float("nan")
    snapshot = snapshot[PRE_PUMP_SNAPSHOT_COLUMNS]
    try:
        history = _read_pre_pump_snapshot_history()
        combined = pd.concat([history, snapshot], ignore_index=True)
        combined["snapshot_ts"] = pd.to_datetime(combined["snapshot_ts"], errors="coerce", utc=True)
        combined = combined[combined["snapshot_ts"].notna()].copy()
        combined["symbol"] = combined["symbol"].astype(str).str.upper()
        combined = combined.drop_duplicates(subset=["snapshot_ts", "symbol"], keep="last")
        path.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(path, index=False)
    except Exception:
        return


def _apply_pre_pump_scan_memory(all_df: pd.DataFrame) -> pd.DataFrame:
    if all_df.empty:
        return all_df

    all_df = all_df.copy()
    index = all_df.index

    def _num(col: str, default: float = 0.0) -> pd.Series:
        if col in all_df.columns:
            values = pd.to_numeric(all_df[col], errors="coerce")
        else:
            values = pd.Series(default, index=index)
        return values.fillna(default)

    def _raw_num(col: str, default: float = float("nan")) -> pd.Series:
        if col in all_df.columns:
            return pd.to_numeric(all_df[col], errors="coerce")
        return pd.Series(default, index=index)

    defaults = {
        "snapshot_seen_before": False,
        "prior_scan_age_minutes": float("nan"),
        "target_cex_share_change_pp": float("nan"),
        "cex_lane_wakeup_score": 0.0,
        "oi_value_change_since_scan_pct": float("nan"),
        "ask_depth_1pct_change_pct": float("nan"),
        "ask_depth_withdrawal_score": 0.0,
        "thin_ask_trap_score": 0.0,
    }
    for col, default in defaults.items():
        all_df[col] = default

    history = _read_pre_pump_snapshot_history()
    if not history.empty:
        latest = history.sort_values("snapshot_ts").drop_duplicates(subset=["symbol"], keep="last").set_index("symbol")
        symbols = all_df["symbol"].astype(str).str.upper()
        prior_ts = symbols.map(latest["snapshot_ts"]) if "snapshot_ts" in latest.columns else pd.Series(pd.NaT, index=index)
        all_df["snapshot_seen_before"] = prior_ts.notna().to_numpy()
        now = pd.Timestamp.now(tz="UTC")
        prior_age = (now - prior_ts).dt.total_seconds() / 60.0
        all_df["prior_scan_age_minutes"] = prior_age

        def _mapped_numeric(column: str) -> pd.Series:
            if column not in latest.columns:
                return pd.Series(float("nan"), index=index)
            return pd.to_numeric(symbols.map(latest[column]), errors="coerce")

        prior_cex_share = _mapped_numeric("target_cex_volume_share_pct")
        prior_oi_value = _mapped_numeric("oi_value_usdt")
        prior_ask_depth = _mapped_numeric("ask_depth_1pct_usdt")
        current_cex_share = _raw_num("target_cex_volume_share_pct")
        current_oi_value = _raw_num("oi_value_usdt")
        current_ask_depth = _raw_num("ask_depth_1pct_usdt")

        all_df["target_cex_share_change_pp"] = current_cex_share - prior_cex_share
        valid_prior_oi = prior_oi_value > 0
        all_df["oi_value_change_since_scan_pct"] = ((current_oi_value / prior_oi_value - 1.0) * 100.0).where(
            valid_prior_oi,
            other=float("nan"),
        )
        valid_prior_depth = prior_ask_depth > 0
        all_df["ask_depth_1pct_change_pct"] = ((current_ask_depth / prior_ask_depth - 1.0) * 100.0).where(
            valid_prior_depth,
            other=float("nan"),
        )

    cex_share_change = _raw_num("target_cex_share_change_pp")
    depth_change = _raw_num("ask_depth_1pct_change_pct")
    ask_depth_to_volume = _raw_num("ask_depth_to_24h_volume_pct")
    cex_lane_wakeup_score = (
        _linear_score(cex_share_change, low=2.0, high=22.0) * 0.58
        + _num("target_cex_flow_score").clip(lower=0.0, upper=100.0) * 0.28
        + _linear_score(_raw_num("target_cex_volume_share_pct"), low=30.0, high=85.0) * 0.14
    ).clip(lower=0.0, upper=100.0)
    ask_depth_withdrawal_score = (
        _linear_score(-depth_change, low=12.0, high=70.0) * 0.58
        + _linear_score(ask_depth_to_volume, low=0.02, high=0.85, invert=True) * 0.28
        + _num("short_trap_score").clip(lower=0.0, upper=100.0) * 0.14
    ).clip(lower=0.0, upper=100.0)
    thin_ask_trap_score = (
        ask_depth_withdrawal_score * 0.38
        + _num("short_trap_score").clip(lower=0.0, upper=100.0) * 0.22
        + _num("low_float_score").clip(lower=0.0, upper=100.0) * 0.16
        + cex_lane_wakeup_score * 0.14
        + _num("silent_oi_accumulation_score").clip(lower=0.0, upper=100.0) * 0.10
    ).clip(lower=0.0, upper=100.0)
    all_df["cex_lane_wakeup_score"] = cex_lane_wakeup_score
    all_df["ask_depth_withdrawal_score"] = ask_depth_withdrawal_score
    all_df["thin_ask_trap_score"] = thin_ask_trap_score

    precision_score = (
        _num("pre_pump_precision_score").clip(lower=0.0, upper=100.0) * 0.68
        + cex_lane_wakeup_score * 0.09
        + thin_ask_trap_score * 0.11
        + ask_depth_withdrawal_score * 0.05
        + _linear_score(_raw_num("oi_value_change_since_scan_pct"), low=1.0, high=16.0) * 0.07
        - _num("no_chase_penalty_score").clip(lower=0.0, upper=100.0) * 0.06
    ).clip(lower=0.0, upper=100.0)
    major_excluded = all_df.get("crime_excluded_major", pd.Series(False, index=index)).fillna(False).astype(bool)
    all_df["pre_pump_precision_score"] = precision_score.where(~major_excluded, other=0.0)
    all_df["pre_pump_precision_flag"] = (
        (all_df["pre_pump_precision_score"] >= 64.0)
        & (_num("pre_pump_compression_score") >= 45.0)
        & (_num("short_trap_score") >= 45.0)
        & ((_num("low_float_score") >= 38.0) | (_num("centralized_ownership_score") >= 44.0))
        & (_num("no_chase_penalty_score") < 60.0)
        & (~major_excluded)
    )

    def _memory_note(row: pd.Series) -> str:
        factors: list[str] = []
        if _safe_float(row.get("pre_pump_compression_score")) >= 55.0:
            factors.append("compression")
        if _safe_float(row.get("short_trap_score")) >= 55.0:
            factors.append("short trap")
        if _safe_float(row.get("silent_oi_accumulation_score")) >= 55.0:
            factors.append("silent OI")
        if _safe_float(row.get("cex_lane_wakeup_score")) >= 45.0:
            factors.append("CEX lane wake-up")
        if _safe_float(row.get("thin_ask_trap_score")) >= 45.0:
            factors.append("thin ask/depth withdrawal")
        if _safe_float(row.get("no_chase_penalty_score")) >= 60.0:
            factors.append("no-chase blocked")
        if not factors:
            return "No high-precision pre-ignition pattern in this scan."
        return " | ".join(factors[:6])

    all_df["pre_pump_precision_note"] = all_df.apply(_memory_note, axis=1)
    _append_pre_pump_snapshots(all_df)
    return all_df


def _pre_pump_label_events(history: pd.DataFrame, *, horizon_hours: int = 24, top_per_scan: int = 10) -> pd.DataFrame:
    if history.empty or "snapshot_ts" not in history.columns or "symbol" not in history.columns:
        return pd.DataFrame()
    data = history.copy()
    data["snapshot_ts"] = pd.to_datetime(data["snapshot_ts"], errors="coerce", utc=True)
    data = data[data["snapshot_ts"].notna()].copy()
    if data.empty:
        return pd.DataFrame()
    data["last_price"] = pd.to_numeric(
        data["last_price"] if "last_price" in data.columns else pd.Series(float("nan"), index=data.index),
        errors="coerce",
    )
    data["pre_pump_precision_score"] = pd.to_numeric(
        data["pre_pump_precision_score"]
        if "pre_pump_precision_score" in data.columns
        else pd.Series(0.0, index=data.index),
        errors="coerce",
    ).fillna(0.0)
    flag_values = (
        data["pre_pump_precision_flag"]
        if "pre_pump_precision_flag" in data.columns
        else pd.Series(False, index=data.index)
    )
    data["pre_pump_precision_flag"] = flag_values.fillna(False).astype(str).str.lower().isin(
        {"true", "1", "yes"}
    )
    events: list[dict[str, Any]] = []
    for snapshot_ts, group in data.groupby("snapshot_ts", sort=True):
        candidates = group[
            (group["pre_pump_precision_flag"])
            | (group["pre_pump_precision_score"] >= 60.0)
        ].sort_values("pre_pump_precision_score", ascending=False).head(top_per_scan)
        for _, event in candidates.iterrows():
            entry_price = _safe_float(event.get("last_price"))
            if not math.isfinite(entry_price) or entry_price <= 0:
                continue
            deadline = snapshot_ts + pd.Timedelta(hours=horizon_hours)
            future = data[
                (data["symbol"] == event["symbol"])
                & (data["snapshot_ts"] > snapshot_ts)
                & (data["snapshot_ts"] <= deadline)
            ]
            if future.empty:
                continue
            max_price = pd.to_numeric(future["last_price"], errors="coerce").max()
            if pd.isna(max_price):
                continue
            max_return = (float(max_price) / entry_price - 1.0) * 100.0
            events.append(
                {
                    "snapshot_ts": snapshot_ts,
                    "symbol": event["symbol"],
                    "entry_price": entry_price,
                    f"max_return_{horizon_hours}h_pct": max_return,
                    "hit_20pct": max_return >= 20.0,
                    "hit_50pct": max_return >= 50.0,
                    "hit_100pct": max_return >= 100.0,
                    "pre_pump_precision_score": event.get("pre_pump_precision_score"),
                    "dormant_short_fuse_score": event.get("dormant_short_fuse_score"),
                    "pre_pump_precision_note": event.get("pre_pump_precision_note", ""),
                }
            )
    return pd.DataFrame(events)


RANGE_BREAKOUT_COLUMNS = [
    "range_breakout_event",
    "range_breakout_side",
    "range_breakout_score",
    "range_high_break_count",
    "range_low_break_count",
]


def _apply_range_breakout_events(all_df: pd.DataFrame) -> pd.DataFrame:
    if all_df.empty:
        for column in RANGE_BREAKOUT_COLUMNS:
            all_df[column] = pd.Series(dtype="object" if column.endswith(("event", "side")) else "float64")
        return all_df

    out = all_df.copy()
    windows = (20, 90, 180)
    high_cols = [f"broke_high_{window}d" for window in windows]
    low_cols = [f"broke_low_{window}d" for window in windows]
    for column in high_cols + low_cols:
        if column not in out.columns:
            out[column] = False
        out[column] = out[column].fillna(False).astype(bool)

    high_count = sum(out[column].astype(int) for column in high_cols)
    low_count = sum(out[column].astype(int) for column in low_cols)
    out["range_high_break_count"] = high_count.astype("int64")
    out["range_low_break_count"] = low_count.astype("int64")
    out["range_breakout_score"] = (
        out["broke_high_20d"].astype(float) * 28.0
        + out["broke_high_90d"].astype(float) * 34.0
        + out["broke_high_180d"].astype(float) * 42.0
        + out["broke_low_20d"].astype(float) * 22.0
        + out["broke_low_90d"].astype(float) * 28.0
        + out["broke_low_180d"].astype(float) * 34.0
    ).clip(lower=0.0, upper=100.0)

    def _event(row: pd.Series) -> str:
        high_events = [f"{window}D high" for window in windows if bool(row.get(f"broke_high_{window}d"))]
        low_events = [f"{window}D low" for window in windows if bool(row.get(f"broke_low_{window}d"))]
        events = high_events + low_events
        return ", ".join(events) + " hit" if events else ""

    def _side(row: pd.Series) -> str:
        high_n = int(row.get("range_high_break_count", 0) or 0)
        low_n = int(row.get("range_low_break_count", 0) or 0)
        if high_n and low_n:
            return "both"
        if high_n:
            return "high"
        if low_n:
            return "low"
        return ""

    out["range_breakout_event"] = out.apply(_event, axis=1)
    out["range_breakout_side"] = out.apply(_side, axis=1)
    return out


CROWDED_SHORT_UPTREND_COLUMNS = [
    "crowded_short_uptrend_score",
    "crowded_short_uptrend_flag",
    "crowded_short_uptrend_note",
    "crowded_short_uptrend_funding_gate",
    "crowded_short_uptrend_short_gate",
    "crowded_short_uptrend_build_gate",
    "crowded_short_uptrend_trend_gate",
    "crowded_short_uptrend_effective_funding_pct",
    "crowded_short_uptrend_funding_score",
    "crowded_short_uptrend_short_score",
    "crowded_short_uptrend_build_score",
    "crowded_short_uptrend_trend_score",
    "crowded_short_uptrend_oi_score",
    "crowded_short_uptrend_late_heat_score",
]


def _crowded_short_uptrend_candidates(
    all_df: pd.DataFrame,
    *,
    min_short_pct: float = 50.0,
    min_short_roc_1h_pp: float = 0.25,
    min_funding_pct: float = 0.0,
    return_all: bool = False,
) -> pd.DataFrame:
    if all_df.empty:
        empty = all_df.copy()
        for column in CROWDED_SHORT_UPTREND_COLUMNS:
            empty[column] = pd.Series(dtype="object" if column.endswith("note") else "float64")
        return empty

    frame = all_df.copy()
    index = frame.index

    def _num_col(column: str, default: float = float("nan")) -> pd.Series:
        source = frame[column] if column in frame.columns else pd.Series(default, index=index)
        return pd.to_numeric(source, errors="coerce")

    def _bool_col(column: str) -> pd.Series:
        source = frame[column] if column in frame.columns else pd.Series(False, index=index)
        return source.fillna(False).astype(bool)

    carry_funding = _num_col("carry_funding_pct")
    predicted_funding = _num_col("predicted_funding_pct")
    effective_funding = pd.concat([carry_funding, predicted_funding], axis=1).max(axis=1, skipna=True)
    short_pct = _num_col("short_account_pct")
    short_roc_1h_pp = _num_col("short_account_roc_1h_pp").fillna(0.0)
    short_change_max_pp = _num_col("short_account_change_max_pp").fillna(0.0)
    short_change_max_pct = _num_col("short_account_change_max_pct").fillna(0.0)
    day_return = _num_col("day_return_pct")
    hour_return = _num_col("hour_return_pct")
    high_break_count = (
        _bool_col("broke_high_5d").astype(int)
        + _bool_col("broke_high_20d").astype(int)
        + _bool_col("broke_high_90d").astype(int)
        + _bool_col("broke_high_180d").astype(int)
    )
    low_break_count = (
        _bool_col("broke_low_5d").astype(int)
        + _bool_col("broke_low_20d").astype(int)
        + _bool_col("broke_low_90d").astype(int)
        + _bool_col("broke_low_180d").astype(int)
    )

    funding_score = _linear_score(effective_funding, low=0.0001, high=0.08)
    short_score = _linear_score(short_pct, low=50.0, high=70.0)
    build_score = pd.concat(
        [
            _linear_score(short_roc_1h_pp, low=0.25, high=3.0),
            _linear_score(short_change_max_pp, low=0.75, high=6.0),
            _linear_score(short_change_max_pct, low=2.0, high=12.0),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    high_break_score = (high_break_count.astype(float) * 28.0).clip(lower=0.0, upper=100.0)
    range_high_score = _linear_score(_num_col("range_high_break_count").fillna(0.0), low=0.5, high=3.0)
    trend_score = pd.concat(
        [
            high_break_score,
            range_high_score,
            _num_col("trend_confluence_score").fillna(0.0),
            _num_col("breakout_pressure_score").fillna(0.0),
            _linear_score(day_return, low=2.0, high=35.0),
            _linear_score(hour_return, low=0.5, high=10.0),
            _linear_score(_num_col("daily_quote_volume_multiple"), low=1.10, high=4.0),
            _linear_score(_num_col("hour_close_location_pct"), low=55.0, high=85.0),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    oi_score = pd.concat(
        [
            _linear_score(_num_col("oi_delta_pct"), low=0.5, high=8.0),
            _linear_score(_num_col("oi_to_24h_volume_pct"), low=2.0, high=25.0),
            _num_col("forced_buying_setup_score").fillna(0.0),
            _num_col("short_liquidation_fuel_score").fillna(0.0),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    late_heat_score = pd.concat(
        [
            _num_col("crime_exhaustion_score").fillna(0.0),
            _num_col("convexity_late_penalty").fillna(0.0),
            _num_col("terminal_risk_score").fillna(0.0),
            _num_col("exit_fragility_score").fillna(0.0),
            _bool_col("blowoff_risk_flag").astype(float) * 100.0,
            _bool_col("blowoff_watch_flag").astype(float) * 70.0,
            _bool_col("unwind_risk_flag").astype(float) * 65.0,
            low_break_count.astype(float) * 22.0,
            _linear_score(-day_return, low=4.0, high=20.0),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0).clip(lower=0.0, upper=100.0)

    score = (
        funding_score * 0.18
        + short_score * 0.23
        + build_score * 0.24
        + trend_score * 0.25
        + oi_score * 0.10
        - late_heat_score * 0.12
    ).clip(lower=0.0, upper=100.0)

    market_type = frame["market_type"].astype(str).str.upper() if "market_type" in frame.columns else pd.Series("", index=index)
    crypto_gate = ~market_type.isin(TRADFI_ALWAYS_INCLUDE_TYPES)
    funding_gate = effective_funding > float(min_funding_pct)
    short_gate = short_pct >= float(min_short_pct)
    build_gate = (
        (short_roc_1h_pp >= float(min_short_roc_1h_pp))
        | (short_change_max_pp >= 1.0)
        | (short_change_max_pct >= 2.5)
    )
    trend_gate = (high_break_count >= 1) | (trend_score >= 45.0)
    candidate_flag = crypto_gate & funding_gate & short_gate & build_gate & trend_gate & (score >= 35.0)

    out = frame.copy()
    out["crowded_short_uptrend_score"] = score
    out["crowded_short_uptrend_flag"] = candidate_flag.fillna(False).astype(bool)
    out["crowded_short_uptrend_funding_gate"] = funding_gate.fillna(False).astype(bool)
    out["crowded_short_uptrend_short_gate"] = short_gate.fillna(False).astype(bool)
    out["crowded_short_uptrend_build_gate"] = build_gate.fillna(False).astype(bool)
    out["crowded_short_uptrend_trend_gate"] = trend_gate.fillna(False).astype(bool)
    out["crowded_short_uptrend_effective_funding_pct"] = effective_funding
    out["crowded_short_uptrend_funding_score"] = funding_score
    out["crowded_short_uptrend_short_score"] = short_score
    out["crowded_short_uptrend_build_score"] = build_score
    out["crowded_short_uptrend_trend_score"] = trend_score
    out["crowded_short_uptrend_oi_score"] = oi_score
    out["crowded_short_uptrend_late_heat_score"] = late_heat_score

    def _note(row: pd.Series) -> str:
        factors: list[str] = []
        funding = _safe_float(row.get("crowded_short_uptrend_effective_funding_pct"))
        if math.isfinite(funding):
            factors.append(f"funding {funding:.4f}%")
        current_short = _safe_float(row.get("short_account_pct"))
        if math.isfinite(current_short):
            factors.append(f"shorts {current_short:.1f}%")
        roc = _safe_float(row.get("short_account_roc_1h_pp"))
        max_pp = _safe_float(row.get("short_account_change_max_pp"))
        if math.isfinite(roc) and roc > 0:
            factors.append(f"1h short +{roc:.2f}pp")
        elif math.isfinite(max_pp) and max_pp > 0:
            window = str(row.get("short_account_change_max_window", "") or "").strip()
            factors.append(f"short +{max_pp:.2f}pp{(' ' + window) if window else ''}")
        high_count_raw = _safe_float(row.get("range_high_break_count"))
        high_count = int(high_count_raw) if math.isfinite(high_count_raw) else 0
        if high_count > 0:
            factors.append(f"{high_count} high break windows")
        elif bool(row.get("broke_high_5d")):
            factors.append("5D high break")
        trend = _safe_float(row.get("crowded_short_uptrend_trend_score"))
        if math.isfinite(trend) and trend >= 55.0:
            factors.append(f"trend score {trend:.0f}")
        oi = _safe_float(row.get("oi_delta_pct"))
        if math.isfinite(oi) and oi > 0:
            factors.append(f"OI +{oi:.1f}%")
        heat = _safe_float(row.get("crowded_short_uptrend_late_heat_score"))
        if math.isfinite(heat) and heat >= 55.0:
            factors.append(f"late heat {heat:.0f}")
        return " | ".join(factors[:7]) if factors else "No crowded-short uptrend evidence in this scan."

    out["crowded_short_uptrend_note"] = out.apply(_note, axis=1)
    ranked = out[crypto_gate].copy() if return_all else out[out["crowded_short_uptrend_flag"]].copy()
    return ranked.sort_values(
        [
            "crowded_short_uptrend_score",
            "crowded_short_uptrend_build_score",
            "crowded_short_uptrend_short_score",
            "crowded_short_uptrend_trend_score",
            "quote_volume_24h" if "quote_volume_24h" in out.columns else "crowded_short_uptrend_oi_score",
            "symbol",
        ],
        ascending=[False, False, False, False, False, True],
    )


def _score_trade_buckets(all_df: pd.DataFrame) -> pd.DataFrame:
    if all_df.empty:
        all_df["trade_bucket"] = pd.Series(dtype="object")
        all_df["trade_bucket_score"] = pd.Series(dtype="float64")
        all_df["raw_convex_long_signal"] = pd.Series(dtype="bool")
        all_df["thesis_gate"] = pd.Series(dtype="bool")
        all_df["thesis_holder_gate"] = pd.Series(dtype="bool")
        all_df["thesis_holder_evidence_gate"] = pd.Series(dtype="bool")
        all_df["thesis_whale_concentration_gate"] = pd.Series(dtype="bool")
        all_df["thesis_venue_gate"] = pd.Series(dtype="bool")
        all_df["thesis_no_pump_gate"] = pd.Series(dtype="bool")
        all_df["thesis_base_gate"] = pd.Series(dtype="bool")
        all_df["thesis_float_gate"] = pd.Series(dtype="bool")
        all_df["thesis_short_squeeze_gate"] = pd.Series(dtype="bool")
        all_df["thesis_not_late_gate"] = pd.Series(dtype="bool")
        all_df["thesis_core_gate"] = pd.Series(dtype="bool")
        all_df["thesis_core_squeeze_fuel_score"] = pd.Series(dtype="float64")
        all_df["thesis_core_float_score"] = pd.Series(dtype="float64")
        all_df["thesis_gate_note"] = pd.Series(dtype="object")
        all_df["trade_bucket_note"] = pd.Series(dtype="object")
        return all_df

    # Several upstream enrichers add optional columns depending on scan mode.
    # Copy once here so bucket writes do not operate on a fragmented dataframe.
    all_df = all_df.copy()
    try:
        all_df._consolidate_inplace()
    except Exception:
        pass

    numeric_cols = [
        "crime_ignition_score",
        "crime_exhaustion_score",
        "oi_delta_pct",
        "hour_trade_count_multiple",
        "hour_volume_multiple",
        "taker_buy_sell_ratio",
        "hour_close_location_pct",
        "hour_upper_wick_pct",
        "carry_funding_pct",
        "crowd_top_position_divergence_pct",
        "day_return_pct",
        "basis_rate_pct",
        "crime_mechanics_score",
        "crime_pump_score",
        "crime_spot_impulse_score",
        "crime_owner_circle_score",
        "crime_supply_control_score",
        "mm_presence_score",
        "mm_bid_support_score",
        "mm_withdrawal_risk_score",
        "mm_proximity_score",
        "inventory_transfer_risk_score",
        "inventory_sponsor_mismatch_score",
        "float_trap_score",
        "ignition_score_v2",
        "perp_pressure_score",
        "venue_support_score",
        "exit_fragility_score",
        "crime_pump_score_v2",
        "convexity_seed_score",
        "large_cap_stabilizer",
        "coinbase_volume_share_pct",
        "binance_volume_share_pct",
        "bitget_volume_share_pct",
        "gate_volume_share_pct",
        "okx_volume_share_pct",
        "upbit_volume_share_pct",
        "krw_volume_share_pct",
        "try_volume_share_pct",
        "emfx_volume_share_pct",
        "kraken_volume_share_pct",
        "perp_volume_to_mcap_pct",
        "oi_to_market_cap_pct",
        "hour_return_pct",
        "hour_return_z",
        "cmc_mover_score",
        "cmc_pct_1h",
        "cmc_pct_24h",
        "cmc_volume_to_mcap_pct",
        "cex_volume_share_pct",
        "cex_to_dex_volume_ratio",
        "cex_dex_volume_ratio_score",
        "binance_bitget_gate_share_pct",
        "binance_bitget_gate_share_score",
        "venue_hhi",
        "venue_hhi_score",
        "emfx_lane_score",
        "funding_flip_score",
        "short_crowding_score",
        "short_account_history_points",
        "short_account_change_1p_pct",
        "short_account_change_1p_pp",
        "short_account_change_3p_pct",
        "short_account_change_3p_pp",
        "short_account_change_6p_pct",
        "short_account_change_6p_pp",
        "short_account_change_12p_pct",
        "short_account_change_12p_pp",
        "short_account_change_24p_pct",
        "short_account_change_24p_pp",
        "short_account_change_max_pct",
        "short_account_change_max_pp",
        "short_account_change_min_pct",
        "short_account_change_min_pp",
        "breakout_pressure_score",
        "runway_score",
        "short_squeeze_score",
        "last_settled_funding_pct",
        "prior_settled_funding_pct",
        "funding_flip_delta_pct",
        "upside_to_ath_pct",
        "ath_price",
        "ath_multiple",
        "ath_upside_pct",
        "coingecko_ath_usd",
        "coingecko_ath_change_pct",
        "convexity_float_score",
        "convexity_sponsor_score",
        "convexity_preignition_score",
        "convexity_expansion_score",
        "convexity_squeeze_score",
        "convexity_runway_score",
        "convexity_late_penalty",
        "trend_confluence_score",
        "spot_flow_confluence_score",
        "perp_squeeze_confluence_score",
        "float_control_confluence_score",
        "mm_sponsor_confluence_score",
        "ath_runway_confluence_score",
        "convexity_confluence_score",
        "convexity_confluence_count",
        "dwf_labs_portfolio_score",
        "valuation_trap_score",
        "short_liquidation_fuel_score",
        "spot_control_score",
        "crowd_skew_confluence_score",
        "forced_buying_setup_score",
        "clean_convex_setup_score",
        "squeeze_machine_score",
        "convexity_entry_score",
        "convexity_score",
        "daily_quote_volume_multiple",
        "distance_to_high_5d_pct",
        "distance_to_high_20d_pct",
        "distance_to_high_90d_pct",
        "insider_team_holder_pct",
        "centralized_ownership_score",
        "low_float_score",
        "short_account_build_score",
        "short_dominance_score",
        "low_volatility_coil_score",
        "pre_pump_short_fuse_score",
        "pre_pump_compression_score",
        "short_trap_score",
        "silent_oi_accumulation_score",
        "dormant_short_fuse_score",
        "price_volume_ignition_score",
        "target_cex_volume_share_pct",
        "target_cex_flow_score",
        "target_cex_share_change_pp",
        "cex_lane_wakeup_score",
        "short_account_pct",
        "oi_value_change_since_scan_pct",
        "oi_to_24h_volume_pct",
        "ask_depth_1pct_change_pct",
        "ask_depth_withdrawal_score",
        "thin_ask_trap_score",
        "rave_lab_convex_fuel_score",
        "rave_lab_late_penalty_score",
        "no_chase_penalty_score",
        "pre_pump_precision_score",
        "rave_lab_setup_score",
        "range_breakout_score",
        "range_high_break_count",
        "range_low_break_count",
        "short_crowding_score",
        "accumulation_absorption_score",
        "fdv_to_market_cap",
        "locked_supply_pct",
        "terminal_float_score",
        "terminal_hidden_float_reflexivity_score",
        "terminal_short_pressure_score",
        "terminal_pre_ignition_quality_score",
        "timing_score",
        "timing_too_late_score",
    ]
    missing_numeric_cols = [col for col in numeric_cols if col not in all_df.columns]
    if missing_numeric_cols:
        all_df = pd.concat(
            [all_df, pd.DataFrame({col: float("nan") for col in missing_numeric_cols}, index=all_df.index)],
            axis=1,
        )
    for col in numeric_cols:
        all_df[col] = pd.to_numeric(all_df[col], errors="coerce")

    bool_cols = [
        "active_short_squeeze_flag",
        "active_squeeze_flag",
        "ath_runway_20x_flag",
        "ath_runway_confluence_flag",
        "blowoff_risk_flag",
        "blowoff_watch_flag",
        "broke_high_5d",
        "broke_high_20d",
        "broke_high_90d",
        "broke_high_180d",
        "broke_low_5d",
        "broke_low_20d",
        "broke_low_90d",
        "broke_low_180d",
        "clean_convex_setup_flag",
        "coinbase_lane_flag",
        "convexity_chase_risk_flag",
        "convexity_prime_flag",
        "convexity_too_late_flag",
        "crime_excluded_major",
        "crime_pump_flag",
        "dwf_labs_portfolio",
        "early_convexity_flag",
        "exhaustion_flag",
        "float_control_confluence_flag",
        "forced_buying_setup_flag",
        "fresh_flip_flag",
        "funding_flip_up_flag",
        "inventory_transfer_risk_flag",
        "mm_sponsor_confluence_flag",
        "owner_controlled_flag",
        "perp_heavy_flag",
        "perp_squeeze_confluence_flag",
        "pre_pump_candidate_flag",
        "setup_ready_flag",
        "spot_flow_confluence_flag",
        "squeeze_chase_flag",
        "squeeze_machine_flag",
        "squeeze_risk_flag",
        "trend_confluence_flag",
        "unwind_risk_flag",
    ]
    missing_bool_cols = [col for col in bool_cols if col not in all_df.columns]
    if missing_bool_cols:
        all_df = pd.concat(
            [all_df, pd.DataFrame({col: False for col in missing_bool_cols}, index=all_df.index)],
            axis=1,
        )
    for col in bool_cols:
        all_df[col] = all_df[col].fillna(False).astype(bool)

    thesis_whale_gate = holder_concentration_mask(all_df, min_whale_pct=90.0, require_holder_evidence=False)
    thesis_holder_evidence_gate = holder_evidence_mask(all_df)
    thesis_holder_gate = holder_concentration_mask(all_df, min_whale_pct=90.0, require_holder_evidence=True)
    thesis_venue_gate = binance_bitget_venue_mask(all_df, allow_cex_flow_targets=False)
    thesis_no_pump_gate = no_recent_pump_proof_mask(all_df)
    thesis_base_gate = thesis_holder_gate & thesis_venue_gate & thesis_no_pump_gate
    thesis_short_pct = all_df["short_account_pct"].fillna(0.0)
    thesis_short_crowd_gate = (
        thesis_short_pct.ge(50.0)
        | all_df["short_dominance_score"].fillna(0.0).ge(60.0)
        | all_df["short_crowding_score"].fillna(0.0).ge(55.0)
        | all_df["terminal_short_pressure_score"].fillna(0.0).ge(55.0)
    )
    thesis_squeeze_fuel_score = pd.concat(
        [
            all_df["short_account_build_score"].fillna(0.0),
            all_df["silent_oi_accumulation_score"].fillna(0.0),
            all_df["short_liquidation_fuel_score"].fillna(0.0),
            all_df["funding_flip_score"].fillna(0.0),
            all_df["fresh_flip_flag"].fillna(False).astype(bool).astype(float) * 100.0,
            all_df["forced_buying_setup_score"].fillna(0.0),
            all_df["perp_squeeze_confluence_score"].fillna(0.0),
            _linear_score(all_df["short_account_change_max_pp"].fillna(0.0), low=0.25, high=5.0),
            _linear_score(all_df["oi_delta_pct"].fillna(0.0), low=0.5, high=7.5),
            _linear_score(all_df["oi_to_24h_volume_pct"].fillna(0.0), low=2.0, high=18.0),
            _linear_score(all_df["oi_to_market_cap_pct"].fillna(0.0), low=2.0, high=35.0),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0).clip(lower=0.0, upper=100.0)
    thesis_short_squeeze_gate = (
        (thesis_short_crowd_gate & thesis_squeeze_fuel_score.ge(40.0))
        | thesis_squeeze_fuel_score.ge(75.0)
    )
    thesis_float_score = pd.concat(
        [
            all_df["low_float_score"].fillna(0.0),
            all_df["float_trap_score"].fillna(0.0),
            all_df["terminal_float_score"].fillna(0.0),
            all_df["terminal_hidden_float_reflexivity_score"].fillna(0.0),
            _linear_score(all_df["fdv_to_market_cap"].fillna(0.0), low=1.8, high=12.0),
            _linear_score(all_df["locked_supply_pct"].fillna(0.0), low=15.0, high=85.0),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0).clip(lower=0.0, upper=100.0)
    thesis_float_gate = (
        thesis_float_score.ge(55.0)
        | all_df["fdv_to_market_cap"].fillna(0.0).ge(4.0)
        | all_df["locked_supply_pct"].fillna(0.0).ge(45.0)
    )
    thesis_structure_score = pd.concat(
        [
            all_df["terminal_pre_ignition_quality_score"].fillna(0.0),
            all_df["timing_score"].fillna(0.0),
            all_df["dormant_short_fuse_score"].fillna(0.0),
            all_df["pre_pump_precision_score"].fillna(0.0),
            all_df["rave_lab_setup_score"].fillna(0.0),
            all_df["accumulation_absorption_score"].fillna(0.0),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    thesis_late_risk = pd.concat(
        [
            all_df["timing_too_late_score"].fillna(0.0),
            all_df["convexity_late_penalty"].fillna(0.0),
            all_df["no_chase_penalty_score"].fillna(0.0),
            all_df["exit_fragility_score"].fillna(0.0) * 0.7,
            all_df["crime_exhaustion_score"].fillna(0.0) * 0.7,
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    thesis_not_late_gate = thesis_structure_score.ge(35.0) & (100.0 - thesis_late_risk).clip(lower=0.0, upper=100.0).ge(45.0)
    thesis_core_gate = thesis_base_gate & thesis_float_gate & thesis_short_squeeze_gate & thesis_not_late_gate
    thesis_gate = thesis_core_gate

    def _thesis_gate_note(row: pd.Series) -> str:
        if bool(row.get("thesis_gate")):
            return "thesis pass: top10 >= 90%, holder evidence, Binance+Bitget, 60D no-pump, float/FDV, short crowd+fuel, early/not-late"
        missing: list[str] = []
        if not bool(row.get("thesis_whale_concentration_gate")):
            missing.append("top10 >= 90%")
        elif not bool(row.get("thesis_holder_evidence_gate")):
            missing.append("ETH/BNB/ARB holder evidence")
        if not bool(row.get("thesis_venue_gate")):
            missing.append("Binance+Bitget")
        if not bool(row.get("thesis_no_pump_gate")):
            missing.append("60D no-pump proof")
        if bool(row.get("thesis_base_gate")):
            if not bool(row.get("thesis_float_gate")):
                missing.append("low-float/FDV evidence")
            if not bool(row.get("thesis_short_squeeze_gate")):
                missing.append("short crowd+fuel")
            if not bool(row.get("thesis_not_late_gate")):
                missing.append("early/not-late structure")
        if not missing:
            missing.append("hard thesis proof")
        return "thesis blocked: missing " + ", ".join(missing)

    long_breakout = all_df["broke_high_20d"] | all_df["broke_high_5d"] | all_df["broke_high_90d"] | all_df["broke_high_180d"]
    short_breakout = all_df["broke_low_20d"] | all_df["broke_low_5d"] | all_df["broke_low_90d"] | all_df["broke_low_180d"]
    major_excluded = all_df["crime_excluded_major"].fillna(False).astype(bool)
    coinbase_lane = all_df["coinbase_lane_flag"].fillna(False).astype(bool)
    owner_controlled = all_df["owner_controlled_flag"].fillna(False).astype(bool)
    perp_heavy = all_df["perp_heavy_flag"].fillna(False).astype(bool)
    early_convexity = all_df["early_convexity_flag"].fillna(False).astype(bool)
    prime_convexity = all_df["convexity_prime_flag"].fillna(False).astype(bool)
    pre_pump_candidate = all_df["pre_pump_candidate_flag"].fillna(False).astype(bool)
    convexity_chase_risk = all_df["convexity_chase_risk_flag"].fillna(False).astype(bool)
    too_late_convexity = all_df["convexity_too_late_flag"].fillna(False).astype(bool)
    trend_confluence = all_df["trend_confluence_flag"].fillna(False).astype(bool)
    spot_flow_confluence = all_df["spot_flow_confluence_flag"].fillna(False).astype(bool)
    perp_squeeze_confluence = all_df["perp_squeeze_confluence_flag"].fillna(False).astype(bool)
    float_control_confluence = all_df["float_control_confluence_flag"].fillna(False).astype(bool)
    mm_sponsor_confluence = all_df["mm_sponsor_confluence_flag"].fillna(False).astype(bool)
    ath_runway_confluence = all_df["ath_runway_confluence_flag"].fillna(False).astype(bool)
    forced_buying_setup = all_df["forced_buying_setup_flag"].fillna(False).astype(bool)
    clean_convex_setup = all_df["clean_convex_setup_flag"].fillna(False).astype(bool)
    squeeze_machine = all_df["squeeze_machine_flag"].fillna(False).astype(bool)
    ath_runway_20x = all_df["ath_runway_20x_flag"].fillna(False).astype(bool)
    confluence_count = all_df["convexity_confluence_count"].fillna(0.0)
    confluence_score = all_df["convexity_confluence_score"].fillna(0.0)
    early_float_signal = (
        owner_controlled
        | float_control_confluence
        | (all_df["float_trap_score"] >= 42.0)
        | (all_df["crime_owner_circle_score"] >= 42.0)
        | (all_df["crime_supply_control_score"] >= 45.0)
        | (all_df["inventory_transfer_risk_score"] >= 45.0)
    )
    early_venue_signal = (
        coinbase_lane
        | spot_flow_confluence
        | mm_sponsor_confluence
        | (all_df["venue_support_score"] >= 32.0)
        | (all_df["mm_presence_score"] >= 45.0)
        | (all_df["mm_bid_support_score"] >= 42.0)
        | (all_df["mm_proximity_score"] >= 55.0)
        | (all_df["krw_volume_share_pct"] >= 12.0)
        | (all_df["upbit_volume_share_pct"] >= 12.0)
        | (all_df["kraken_volume_share_pct"] >= 8.0)
        | (all_df["cex_dex_volume_ratio_score"] >= 65.0)
        | (all_df["cex_to_dex_volume_ratio"] >= 10.0)
        | (all_df["binance_bitget_gate_share_pct"] >= 45.0)
        | (all_df["emfx_volume_share_pct"] >= 10.0)
        | (all_df["venue_hhi_score"] >= 60.0)
    )
    early_perp_signal = (
        perp_heavy
        | perp_squeeze_confluence
        | forced_buying_setup
        | (all_df["forced_buying_setup_score"] >= 50.0)
        | (all_df["perp_pressure_score"] >= 42.0)
        | (all_df["oi_delta_pct"] >= 1.0)
        | (all_df["perp_volume_to_mcap_pct"] >= 150.0)
        | (all_df["oi_to_market_cap_pct"] >= 8.0)
    )
    early_ignition_signal = (
        all_df["setup_ready_flag"].fillna(False).astype(bool)
        | trend_confluence
        | (all_df["ignition_score_v2"].between(18.0, 75.0, inclusive="both"))
        | (all_df["crime_pump_score_v2"].between(25.0, 72.0, inclusive="both"))
        | (all_df["day_return_pct"].between(3.0, 65.0, inclusive="both"))
        | (all_df["cmc_mover_score"] >= 45.0)
        | (all_df["cmc_pct_24h"].between(15.0, 160.0, inclusive="both"))
        | (all_df["convexity_seed_score"] >= 45.0)
        | (all_df["convexity_preignition_score"] >= 35.0)
        | ((confluence_score >= 45.0) & (confluence_count >= 3.0))
        | (all_df["daily_quote_volume_multiple"] >= 1.35)
        | long_breakout
    )
    not_late_stage = (
        (~all_df["blowoff_risk_flag"].fillna(False).astype(bool))
        & (
            (~all_df["blowoff_watch_flag"].fillna(False).astype(bool))
            | (all_df["exit_fragility_score"].fillna(0.0) < 60.0)
        )
        & (~all_df["unwind_risk_flag"].fillna(False).astype(bool))
        & (~all_df["exhaustion_flag"].fillna(False).astype(bool))
        & (all_df["exit_fragility_score"].fillna(0.0) < 78.0)
        & (all_df["crime_exhaustion_score"].fillna(0.0) < 74.0)
        & (all_df["large_cap_stabilizer"].fillna(0.0) <= 80.0)
        & (all_df["convexity_late_penalty"].fillna(0.0) < 72.0)
        & (~convexity_chase_risk | (all_df["convexity_late_penalty"].fillna(0.0) < 45.0))
    )

    raw_convex_long_signal = (
        (~major_excluded)
        & not_late_stage
        & (~too_late_convexity)
        & (
            pre_pump_candidate
            | prime_convexity
            | early_convexity
            | squeeze_machine
            | forced_buying_setup
            | clean_convex_setup
            | (
                (all_df["convexity_entry_score"] >= 54.0)
                & (all_df["convexity_sponsor_score"] >= 50.0)
                & (all_df["convexity_float_score"] >= 38.0)
                & (all_df["convexity_preignition_score"] >= 34.0)
            )
            | all_df["setup_ready_flag"].fillna(False).astype(bool)
            | (early_float_signal & early_venue_signal & early_ignition_signal)
            | (
                (all_df["inventory_transfer_risk_score"] >= 42.0)
                & early_venue_signal
                & (
                    (all_df["ignition_score_v2"] >= 15.0)
                    | (all_df["convexity_preignition_score"] >= 30.0)
                )
            )
            | (
                early_perp_signal
                & early_venue_signal
                & (early_float_signal | (all_df["float_trap_score"] >= 30.0))
                & (
                    (all_df["ignition_score_v2"] >= 15.0)
                    | (all_df["convexity_preignition_score"] >= 30.0)
                )
            )
            | (
                (confluence_count >= 3.0)
                & (confluence_score >= 45.0)
                & (early_ignition_signal | (all_df["convexity_preignition_score"] >= 28.0))
                & (early_float_signal | ath_runway_confluence | ath_runway_20x)
                & (early_venue_signal | early_perp_signal)
            )
        )
        & (
            all_df["carry_funding_pct"].isna()
            | (all_df["carry_funding_pct"] <= 0.04)
        )
        & (
            all_df["crowd_top_position_divergence_pct"].isna()
            | (all_df["crowd_top_position_divergence_pct"] <= 30.0)
        )
        & (
            all_df["mm_withdrawal_risk_score"].isna()
            | (all_df["mm_withdrawal_risk_score"] <= 72.0)
        )
    )
    convex_long_mask = raw_convex_long_signal & thesis_gate

    avoid_mask = (
        all_df["blowoff_risk_flag"]
        | all_df["exhaustion_flag"]
        | (
            (all_df["mm_withdrawal_risk_score"] >= 78.0)
            & (
                (all_df["crime_exhaustion_score"] >= 55.0)
                | (all_df["hour_upper_wick_pct"] >= 22.0)
                | (all_df["oi_delta_pct"] <= 0.0)
            )
        )
        | (
            (all_df["inventory_transfer_risk_score"] >= 78.0)
            & (all_df["mm_withdrawal_risk_score"] >= 65.0)
            & (
                (all_df["hour_upper_wick_pct"] >= 20.0)
                | (all_df["oi_delta_pct"] <= 0.0)
            )
        )
        | (
            (all_df["crime_exhaustion_score"] >= 72.0)
            & (
                (all_df["hour_upper_wick_pct"] >= 28.0)
                | (all_df["carry_funding_pct"] >= 0.02)
                | (all_df["basis_rate_pct"] >= 0.10)
            )
        )
        | too_late_convexity
        | (
            short_breakout
            & (all_df["oi_delta_pct"] <= 0.0)
        )
        | (
            convexity_chase_risk
            & (all_df["convexity_late_penalty"] >= 55.0)
        )
    )

    scalp_only_mask = (
        ~raw_convex_long_signal
        & ~avoid_mask
        & (
            all_df["crime_pump_flag"]
            | all_df["squeeze_risk_flag"]
            | all_df["inventory_transfer_risk_flag"]
            | all_df["setup_ready_flag"]
            | all_df["active_squeeze_flag"]
            | pre_pump_candidate
            | early_convexity
            | (all_df["crime_pump_score"] >= 65.0)
            | (all_df["crime_pump_score_v2"] >= 65.0)
            | (all_df["crime_ignition_score"] >= 65.0)
            | ((all_df["hour_return_pct"] >= 3.0) & (all_df["oi_delta_pct"] >= 2.0))
        )
    )

    trade_bucket = pd.Series("Watch", index=all_df.index, dtype="object")
    trade_bucket.loc[convex_long_mask] = "Convex Long"
    trade_bucket.loc[scalp_only_mask] = "Scalp Only"
    trade_bucket.loc[avoid_mask] = "Avoid"

    convex_score = (
        all_df["convexity_entry_score"].fillna(all_df["convexity_score"]).fillna(0.0) * 0.72
        + confluence_score * 0.16
        + confluence_count * 3.0
        + all_df["squeeze_machine_score"].fillna(0.0) * 0.18
        + all_df["short_liquidation_fuel_score"].fillna(0.0) * 0.06
        + all_df["spot_control_score"].fillna(0.0) * 0.05
        + all_df["clean_convex_setup_score"].fillna(0.0) * 0.12
        + all_df["forced_buying_setup_score"].fillna(0.0) * 0.08
        + all_df["crowd_skew_confluence_score"].fillna(0.0) * 0.05
        + all_df["crime_pump_score_v2"].fillna(0.0) * 0.18
        + all_df["short_squeeze_score"].fillna(0.0) * 0.06
        + all_df["inventory_transfer_risk_score"].fillna(0.0) * 0.06
        + all_df["cmc_mover_score"].fillna(0.0) * 0.05
        + all_df["convexity_preignition_score"].fillna(0.0) * 0.08
        + all_df["ath_runway_confluence_score"].fillna(0.0) * 0.05
        + all_df["ath_multiple"].clip(lower=0.0, upper=50.0).fillna(0.0) * 0.30
        + pre_pump_candidate.astype(float) * 10.0
        + prime_convexity.astype(float) * 12.0
        + early_convexity.astype(float) * 8.0
        + ath_runway_20x.astype(float) * 6.0
        + squeeze_machine.astype(float) * 12.0
        + forced_buying_setup.astype(float) * 5.0
        + clean_convex_setup.astype(float) * 7.0
        + coinbase_lane.astype(float) * 4.0
        + owner_controlled.astype(float) * 5.0
        + perp_heavy.astype(float) * 4.0
        - all_df["convexity_late_penalty"].fillna(0.0) * 0.18
        - convexity_chase_risk.astype(float) * 10.0
        - too_late_convexity.astype(float) * 25.0
    )
    scalp_score = (
        all_df["crime_pump_score"].fillna(0.0) * 0.35
        + all_df["crime_pump_score_v2"].fillna(0.0) * 0.12
        + all_df["crime_mechanics_score"].fillna(0.0) * 0.12
        + all_df["crime_ignition_score"].fillna(0.0) * 0.18
        + all_df["ignition_score_v2"].fillna(0.0) * 0.08
        + all_df["convexity_score"].fillna(0.0) * 0.12
        + all_df["convexity_preignition_score"].fillna(0.0) * 0.06
        + all_df["mm_presence_score"].fillna(0.0) * 0.05
        + all_df["inventory_transfer_risk_score"].fillna(0.0) * 0.05
        + all_df["cmc_mover_score"].fillna(0.0) * 0.06
        + all_df["cex_dex_volume_ratio_score"].fillna(0.0) * 0.05
        + all_df["binance_bitget_gate_share_score"].fillna(0.0) * 0.08
        + all_df["emfx_lane_score"].fillna(0.0) * 0.04
        + confluence_score * 0.08
        + early_convexity.astype(float) * 5.0
        + all_df["hour_return_z"].clip(lower=0.0).fillna(0.0) * 6.0
        + all_df["oi_delta_pct"].clip(lower=0.0).fillna(0.0) * 3.0
        + all_df["taker_buy_sell_ratio"].clip(lower=0.0).fillna(0.0) * 6.0
        - all_df["crime_exhaustion_score"].fillna(0.0) * 0.10
    )
    avoid_score = (
        all_df["crime_exhaustion_score"].fillna(0.0) * 0.45
        + all_df["exit_fragility_score"].fillna(0.0) * 0.18
        + all_df["convexity_late_penalty"].fillna(0.0) * 0.28
        + all_df["hour_upper_wick_pct"].clip(lower=0.0).fillna(0.0) * 0.55
        + all_df["carry_funding_pct"].clip(lower=0.0).fillna(0.0) * 250.0
        + all_df["basis_rate_pct"].clip(lower=0.0).fillna(0.0) * 40.0
        + all_df["crowd_top_position_divergence_pct"].clip(lower=0.0).fillna(0.0) * 1.7
        + (-all_df["oi_delta_pct"]).clip(lower=0.0).fillna(0.0) * 3.5
        + all_df["mm_withdrawal_risk_score"].fillna(0.0) * 0.18
        + short_breakout.astype(float) * 10.0
    )

    trade_bucket_score = pd.Series(0.0, index=all_df.index, dtype="float64")
    trade_bucket_score.loc[trade_bucket == "Convex Long"] = convex_score
    trade_bucket_score.loc[trade_bucket == "Scalp Only"] = scalp_score
    trade_bucket_score.loc[trade_bucket == "Avoid"] = avoid_score
    trade_bucket_score.loc[trade_bucket == "Watch"] = convex_score * 0.5
    bucket_frame = pd.DataFrame(
        {
            "trade_bucket": trade_bucket,
            "trade_bucket_score": trade_bucket_score,
            "raw_convex_long_signal": raw_convex_long_signal.fillna(False).astype(bool),
            "thesis_gate": thesis_gate.fillna(False).astype(bool),
            "thesis_holder_gate": thesis_holder_gate.fillna(False).astype(bool),
            "thesis_holder_evidence_gate": thesis_holder_evidence_gate.fillna(False).astype(bool),
            "thesis_whale_concentration_gate": thesis_whale_gate.fillna(False).astype(bool),
            "thesis_venue_gate": thesis_venue_gate.fillna(False).astype(bool),
            "thesis_no_pump_gate": thesis_no_pump_gate.fillna(False).astype(bool),
            "thesis_base_gate": thesis_base_gate.fillna(False).astype(bool),
            "thesis_float_gate": thesis_float_gate.fillna(False).astype(bool),
            "thesis_short_squeeze_gate": thesis_short_squeeze_gate.fillna(False).astype(bool),
            "thesis_not_late_gate": thesis_not_late_gate.fillna(False).astype(bool),
            "thesis_core_gate": thesis_core_gate.fillna(False).astype(bool),
            "thesis_core_squeeze_fuel_score": thesis_squeeze_fuel_score,
            "thesis_core_float_score": thesis_float_score,
        },
        index=all_df.index,
    )
    all_df = pd.concat(
        [
            all_df.drop(
                columns=[
                    "trade_bucket",
                    "trade_bucket_score",
                    "raw_convex_long_signal",
                    "thesis_gate",
                    "thesis_holder_gate",
                    "thesis_holder_evidence_gate",
                    "thesis_whale_concentration_gate",
                    "thesis_venue_gate",
                    "thesis_no_pump_gate",
                    "thesis_base_gate",
                    "thesis_float_gate",
                    "thesis_short_squeeze_gate",
                    "thesis_not_late_gate",
                    "thesis_core_gate",
                    "thesis_core_squeeze_fuel_score",
                    "thesis_core_float_score",
                    "thesis_gate_note",
                ],
                errors="ignore",
            ),
            bucket_frame,
        ],
        axis=1,
    ).copy()
    all_df["thesis_gate_note"] = all_df.apply(_thesis_gate_note, axis=1)

    def _bucket_note(row: pd.Series) -> str:
        bucket = str(row.get("trade_bucket", "Watch"))
        triggers: list[str] = []
        range_event = str(row.get("range_breakout_event", "") or "").strip()
        if range_event:
            triggers.append(range_event)
        elif bool(row.get("broke_high_180d")):
            triggers.append("180D high break")
        elif bool(row.get("broke_high_90d")):
            triggers.append("90D high break")
        elif bool(row.get("broke_high_20d")):
            triggers.append("20D breakout")
        elif bool(row.get("broke_high_5d")):
            triggers.append("5D breakout")
        if pd.notna(row.get("crime_ignition_score")) and float(row["crime_ignition_score"]) >= 68.0:
            triggers.append("high ignition")
        if pd.notna(row.get("oi_delta_pct")) and float(row["oi_delta_pct"]) >= 2.0:
            triggers.append("OI expanding")
        if pd.notna(row.get("hour_trade_count_multiple")) and float(row["hour_trade_count_multiple"]) >= 1.40:
            triggers.append("trade count spike")
        if pd.notna(row.get("taker_buy_sell_ratio")) and float(row["taker_buy_sell_ratio"]) >= 1.05:
            triggers.append("taker buyers in control")
        if pd.notna(row.get("hour_close_location_pct")) and float(row["hour_close_location_pct"]) >= 65.0:
            triggers.append("strong hourly close")
        if pd.notna(row.get("float_trap_score")) and float(row["float_trap_score"]) >= 45.0:
            triggers.append("float trap")
        if pd.notna(row.get("convexity_score")) and float(row["convexity_score"]) >= 55.0:
            triggers.append("early convexity")
        if pd.notna(row.get("convexity_confluence_count")) and float(row["convexity_confluence_count"]) >= 3.0:
            note = str(row.get("convexity_confluence_note", "")).strip()
            triggers.append(note if note and note != "No multi-mechanic confluence yet." else "multi-mechanic confluence")
        if pd.notna(row.get("convexity_confluence_score")) and float(row["convexity_confluence_score"]) >= 55.0:
            triggers.append("mechanics confluence")
        if bool(row.get("dwf_labs_portfolio")):
            triggers.append("DWF Labs portfolio")
        if pd.notna(row.get("squeeze_machine_score")) and float(row["squeeze_machine_score"]) >= 55.0:
            triggers.append("float-control/perp-squeeze machine")
        if bool(row.get("clean_convex_setup_flag")):
            triggers.append("clean convex setup")
        if bool(row.get("forced_buying_setup_flag")):
            triggers.append("forced-buying fuel")
        if pd.notna(row.get("crowd_skew_confluence_score")) and float(row["crowd_skew_confluence_score"]) >= 55.0:
            triggers.append("short-account skew")
        if pd.notna(row.get("short_liquidation_fuel_score")) and float(row["short_liquidation_fuel_score"]) >= 55.0:
            triggers.append("short liquidation fuel")
        if pd.notna(row.get("spot_control_score")) and float(row["spot_control_score"]) >= 55.0:
            triggers.append("spot control")
        if pd.notna(row.get("valuation_trap_score")) and float(row["valuation_trap_score"]) >= 55.0:
            triggers.append("valuation trap")
        if bool(row.get("pre_pump_candidate_flag")):
            triggers.append("pre-ignition signal")
        if bool(row.get("convexity_prime_flag")):
            triggers.append("convexity prime")
        if bool(row.get("early_convexity_flag")):
            triggers.append("convexity active")
        if pd.notna(row.get("convexity_preignition_score")) and float(row["convexity_preignition_score"]) >= 45.0:
            triggers.append("pre-ignition pressure")
        if pd.notna(row.get("daily_quote_volume_multiple")) and float(row["daily_quote_volume_multiple"]) >= 1.75:
            triggers.append("daily volume expanding")
        if pd.notna(row.get("venue_support_score")) and float(row["venue_support_score"]) >= 35.0:
            triggers.append("venue support")
        if pd.notna(row.get("convexity_sponsor_score")) and float(row["convexity_sponsor_score"]) >= 50.0:
            triggers.append("sponsored spot")
        if pd.notna(row.get("convexity_expansion_score")) and float(row["convexity_expansion_score"]) >= 45.0:
            triggers.append("expansion readiness")
        if pd.notna(row.get("perp_pressure_score")) and float(row["perp_pressure_score"]) >= 42.0:
            triggers.append("perp fuel")
        if pd.notna(row.get("convexity_runway_score")) and float(row["convexity_runway_score"]) >= 45.0:
            triggers.append("runway open")
        if pd.notna(row.get("ath_multiple")) and float(row["ath_multiple"]) >= 20.0:
            triggers.append(f"{float(row['ath_multiple']):.1f}x from ATH")
        if pd.notna(row.get("crime_pump_score_v2")) and float(row["crime_pump_score_v2"]) >= 30.0:
            triggers.append("early v2 setup")
        if pd.notna(row.get("cmc_mover_score")) and float(row["cmc_mover_score"]) >= 55.0:
            label = str(row.get("cmc_mover_label", "")).strip()
            triggers.append(label if label else "CMC top mover")
        if pd.notna(row.get("cmc_volume_to_mcap_pct")) and float(row["cmc_volume_to_mcap_pct"]) >= 100.0:
            triggers.append("CMC vol/mcap extreme")
        if pd.notna(row.get("cex_to_dex_volume_ratio")) and float(row["cex_to_dex_volume_ratio"]) >= 10.0:
            triggers.append("CEX >> DEX flow")
        elif pd.notna(row.get("cex_dex_volume_ratio_score")) and float(row["cex_dex_volume_ratio_score"]) >= 65.0:
            triggers.append("CEX/DEX skew")
        if pd.notna(row.get("binance_bitget_gate_share_pct")) and float(row["binance_bitget_gate_share_pct"]) >= 45.0:
            triggers.append("Binance/Bitget/Gate lane")
        if pd.notna(row.get("krw_volume_share_pct")) and float(row["krw_volume_share_pct"]) >= 12.0:
            triggers.append("KRW spot lane")
        if pd.notna(row.get("try_volume_share_pct")) and float(row["try_volume_share_pct"]) >= 4.0:
            triggers.append("TRY spot lane")
        if pd.notna(row.get("emfx_volume_share_pct")) and float(row["emfx_volume_share_pct"]) >= 10.0:
            triggers.append("EMFX lane")
        if pd.notna(row.get("venue_hhi_score")) and float(row["venue_hhi_score"]) >= 60.0:
            triggers.append("venue concentration extreme")
        if pd.notna(row.get("mm_presence_score")) and float(row["mm_presence_score"]) >= 55.0:
            triggers.append("MM present on CB spot")
        if pd.notna(row.get("mm_bid_support_score")) and float(row["mm_bid_support_score"]) >= 55.0:
            triggers.append("CB bid support")
        if pd.notna(row.get("mm_withdrawal_risk_score")) and float(row["mm_withdrawal_risk_score"]) >= 72.0:
            triggers.append("MM pull-risk")
        if pd.notna(row.get("mm_proximity_score")) and float(row["mm_proximity_score"]) >= 70.0:
            maker = str(row.get("mm_proximity_maker", "")).strip()
            triggers.append(f"{maker} proximity" if maker else "MM proximity")
        if pd.notna(row.get("inventory_transfer_risk_score")) and float(row["inventory_transfer_risk_score"]) >= 65.0:
            triggers.append("OTC inventory-transfer risk")
        if bool(row.get("setup_ready_flag")):
            triggers.append("setup ready")
        if bool(row.get("funding_flip_up_flag")):
            triggers.append("funding flipped up")
        if bool(row.get("fresh_flip_flag")):
            triggers.append("fresh short squeeze")
        if bool(row.get("active_short_squeeze_flag")):
            triggers.append("active short squeeze")
        if bool(row.get("squeeze_chase_flag")):
            triggers.append("squeeze chase risk")
        if pd.notna(row.get("short_squeeze_score")) and float(row["short_squeeze_score"]) >= 65.0:
            triggers.append("short squeeze")
        if pd.notna(row.get("upside_to_ath_pct")) and float(row["upside_to_ath_pct"]) >= 50.0:
            triggers.append("ATH runway")
        if bool(row.get("active_squeeze_flag")):
            triggers.append("active squeeze")
        if bool(row.get("blowoff_watch_flag")):
            triggers.append("blowoff watch")
        if bool(row.get("unwind_risk_flag")):
            triggers.append("unwind risk")
        if bool(row.get("convexity_too_late_flag")):
            triggers.append("too late")
        if bool(row.get("convexity_chase_risk_flag")):
            triggers.append("chase risk")
        if pd.notna(row.get("crime_exhaustion_score")) and float(row["crime_exhaustion_score"]) >= 68.0:
            triggers.append("exhaustion elevated")
        if pd.notna(row.get("hour_upper_wick_pct")) and float(row["hour_upper_wick_pct"]) >= 30.0:
            triggers.append("big upper wick")
        if pd.notna(row.get("carry_funding_pct")) and float(row["carry_funding_pct"]) >= 0.02:
            triggers.append("hot funding")
        if pd.notna(row.get("crowd_top_position_divergence_pct")) and float(row["crowd_top_position_divergence_pct"]) >= 5.0:
            triggers.append("crowd ahead of top traders")
        if bool(row.get("blowoff_risk_flag")):
            triggers.append("blowoff risk")
        if bool(row.get("squeeze_risk_flag")):
            triggers.append("crowded squeeze")

        thesis_note = str(row.get("thesis_gate_note", "") or "").strip()
        raw_signal = bool(row.get("raw_convex_long_signal", False))
        if bucket == "Convex Long":
            parts = [thesis_note or "thesis pass: hard gates cleared", *triggers[:3]]
            return " | ".join(part for part in parts if part)
        if raw_signal:
            parts = [thesis_note or "thesis blocked: hard gates unproven", *triggers[:3]]
            return " | ".join(part for part in parts if part)
        if not triggers:
            return "No strong classification signal yet."
        if bucket == "Scalp Only":
            return " | ".join(triggers[:5])
        if bucket == "Avoid":
            return " | ".join(triggers[:5])
        return " | ".join(triggers[:3])

    trade_bucket_note = all_df.apply(_bucket_note, axis=1)
    return pd.concat(
        [
            all_df.drop(columns=["trade_bucket_note"], errors="ignore"),
            pd.DataFrame({"trade_bucket_note": trade_bucket_note}, index=all_df.index),
        ],
        axis=1,
    ).copy()


def _coerce_funding_interval_hours(value: Any) -> int:
    try:
        hours = int(float(value))
    except Exception:
        return 8
    return max(1, hours)


def _funding_countdown_hours(next_funding_time_ms: Any) -> float:
    try:
        next_ms = int(float(next_funding_time_ms))
    except Exception:
        return float("nan")
    remaining_ms = next_ms - int(_utc_now().timestamp() * 1000)
    return max(0.0, remaining_ms / (1000.0 * 60.0 * 60.0))


def _latest_premium_index_rate(snapshot: dict[str, Any]) -> float:
    mark_price = _safe_float(snapshot.get("markPrice"))
    index_price = _safe_float(snapshot.get("indexPrice"))
    if math.isnan(mark_price) or math.isnan(index_price) or abs(index_price) < 1e-12:
        return float("nan")
    return (mark_price - index_price) / index_price


def _basis_from_mark_price_snapshot(snapshot: dict[str, Any]) -> tuple[float, float]:
    mark_price = _safe_float(snapshot.get("markPrice"))
    index_price = _safe_float(snapshot.get("indexPrice"))
    if math.isnan(mark_price) or math.isnan(index_price) or abs(index_price) < 1e-12:
        return float("nan"), float("nan")
    basis_usdt = mark_price - index_price
    basis_rate_pct = basis_usdt / index_price * 100.0
    return basis_rate_pct, basis_usdt


def _safe_public_fetch(default: Any, fn: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except Exception:
        return default


def _empty_hourly_stats() -> dict[str, float]:
    return {
        "hour_return_pct": float("nan"),
        "hour_return_z": float("nan"),
        "day_return_pct": float("nan"),
        "hour_quote_volume": float("nan"),
        "hour_quote_volume_previous_1h": float("nan"),
        "hour_volume_roc_1h_pct": float("nan"),
        "hour_volume_multiple": float("nan"),
        "hour_trade_count_multiple": float("nan"),
        "hour_upper_wick_pct": float("nan"),
        "hour_close_location_pct": float("nan"),
    }


def _clip_funding_rate(rate: float, cap_rate: float | None, floor_rate: float | None) -> float:
    if math.isnan(rate):
        return float("nan")
    if cap_rate is not None:
        rate = min(rate, cap_rate)
    if floor_rate is not None:
        rate = max(rate, floor_rate)
    return rate


def _kline_interval_ms(interval: str) -> int:
    lookup = {
        "1m": 60_000,
        "3m": 3 * 60_000,
        "5m": 5 * 60_000,
        "15m": 15 * 60_000,
        "30m": 30 * 60_000,
        "1h": 60 * 60_000,
        "2h": 2 * 60 * 60_000,
        "4h": 4 * 60 * 60_000,
    }
    return lookup.get(interval, 5 * 60_000)


def _select_premium_kline_interval(lookback_ms: int) -> str:
    for interval in ("5m", "15m", "30m", "1h", "2h", "4h"):
        if lookback_ms / _kline_interval_ms(interval) <= 1400:
            return interval
    return "4h"


def _premium_segments_from_klines(klines: list[list[Any]]) -> list[tuple[int, int, float]]:
    segments: list[tuple[int, int, float]] = []
    for row in klines:
        if len(row) < 7:
            continue
        try:
            start_ms = int(row[0])
            end_ms = int(row[6]) + 1
            rate = float(row[4])
        except Exception:
            continue
        if math.isnan(rate) or end_ms <= start_ms:
            continue
        segments.append((start_ms, end_ms, rate))
    return segments


def _weighted_premium_average(
    segments: list[tuple[int, int, float]],
    *,
    window_start_ms: int,
    window_end_ms: int,
    tail_rate: float | None = None,
    tail_start_ms: int | None = None,
    tail_end_ms: int | None = None,
) -> float:
    weighted_sum = 0.0
    weight_ms = 0

    for start_ms, end_ms, rate in segments:
        overlap_start = max(start_ms, window_start_ms)
        overlap_end = min(end_ms, window_end_ms)
        if overlap_end <= overlap_start:
            continue
        duration_ms = overlap_end - overlap_start
        weighted_sum += rate * duration_ms
        weight_ms += duration_ms

    if tail_rate is not None and tail_start_ms is not None and tail_end_ms is not None and not math.isnan(tail_rate):
        overlap_start = max(tail_start_ms, window_start_ms)
        overlap_end = min(tail_end_ms, window_end_ms)
        if overlap_end > overlap_start:
            duration_ms = overlap_end - overlap_start
            weighted_sum += tail_rate * duration_ms
            weight_ms += duration_ms

    if weight_ms <= 0:
        return float("nan")
    return weighted_sum / float(weight_ms)


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    if len(values) == 1:
        return float(values[0])
    q = min(max(q, 0.0), 1.0)
    ranked = sorted(values)
    position = q * (len(ranked) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(ranked[lower])
    blend = position - lower
    return float(ranked[lower] * (1.0 - blend) + ranked[upper] * blend)


def _estimate_next_funding_rate(
    *,
    funding_snapshot: dict[str, Any],
    interval_hours: int,
    cap_rate: float | None,
    floor_rate: float | None,
    funding_history: list[dict[str, Any]],
    premium_klines: list[list[Any]],
    websocket_snapshot: dict[str, Any] | None,
) -> dict[str, float]:
    try:
        next_funding_ms = int(float(funding_snapshot.get("nextFundingTime")))
    except Exception:
        return {
            "predicted_rate": float("nan"),
            "predicted_low_rate": float("nan"),
            "predicted_high_rate": float("nan"),
            "predicted_band_rate": float("nan"),
            "predicted_mae_rate": float("nan"),
            "latest_premium_rate": float("nan"),
            "window_elapsed_pct": float("nan"),
            "backtest_count": 0.0,
        }

    now_ms = int(_utc_now().timestamp() * 1000)
    interval_ms = max(1, int(interval_hours)) * 60 * 60 * 1000
    window_start_ms = max(0, next_funding_ms - interval_ms)
    elapsed_ms = min(max(0, now_ms - window_start_ms), interval_ms)
    window_elapsed_pct = elapsed_ms / interval_ms * 100.0 if interval_ms else float("nan")

    segments = _premium_segments_from_klines(premium_klines)
    latest_premium_rate = _latest_premium_index_rate(funding_snapshot)
    tail_rate = latest_premium_rate
    tail_end_ms = min(now_ms, next_funding_ms)
    last_closed_segment_end_ms = window_start_ms
    closed_segments = [segment for segment in segments if segment[1] <= tail_end_ms]
    if closed_segments:
        last_closed_segment_end_ms = max(end_ms for _, end_ms, _ in closed_segments)

    if websocket_snapshot:
        try:
            latest_ws_rate = float(websocket_snapshot.get("latest_premium_rate"))
            if not math.isnan(latest_ws_rate):
                latest_premium_rate = latest_ws_rate
        except Exception:
            pass
        try:
            avg_ws_rate = float(websocket_snapshot.get("avg_premium_rate"))
            if not math.isnan(avg_ws_rate):
                tail_rate = avg_ws_rate
        except Exception:
            tail_rate = latest_premium_rate

    try:
        interest_rate = float(funding_snapshot.get("interestRate"))
    except Exception:
        interest_rate = 0.0

    current_avg_premium_rate = _weighted_premium_average(
        closed_segments,
        window_start_ms=window_start_ms,
        window_end_ms=tail_end_ms,
        tail_rate=tail_rate,
        tail_start_ms=max(window_start_ms, last_closed_segment_end_ms),
        tail_end_ms=tail_end_ms,
    )
    raw_rate = _clip_funding_rate(current_avg_premium_rate + interest_rate, cap_rate, floor_rate)

    errors: list[float] = []
    for item in funding_history:
        try:
            funding_time_ms = int(float(item.get("fundingTime")))
            actual_rate = float(item.get("fundingRate"))
        except Exception:
            continue
        historical_avg_premium = _weighted_premium_average(
            segments,
            window_start_ms=max(0, funding_time_ms - interval_ms),
            window_end_ms=funding_time_ms,
        )
        historical_pred_rate = _clip_funding_rate(historical_avg_premium + interest_rate, cap_rate, floor_rate)
        if math.isnan(historical_pred_rate):
            continue
        errors.append(actual_rate - historical_pred_rate)

    backtest_count = len(errors)
    if errors:
        bias_rate = float(sum(errors) / backtest_count)
        abs_errors = [abs(value) for value in errors]
        mae_rate = float(sum(abs_errors) / backtest_count)
        band_rate = max(mae_rate, _quantile(abs_errors, 0.80))
    else:
        bias_rate = 0.0
        mae_rate = float("nan")
        band_rate = float("nan")

    calibrated_rate = _clip_funding_rate(raw_rate + bias_rate, cap_rate, floor_rate)
    if math.isnan(calibrated_rate) or math.isnan(band_rate):
        low_rate = float("nan")
        high_rate = float("nan")
    else:
        low_rate = _clip_funding_rate(calibrated_rate - band_rate, cap_rate, floor_rate)
        high_rate = _clip_funding_rate(calibrated_rate + band_rate, cap_rate, floor_rate)

    return {
        "predicted_rate": calibrated_rate,
        "predicted_low_rate": low_rate,
        "predicted_high_rate": high_rate,
        "predicted_band_rate": band_rate,
        "predicted_mae_rate": mae_rate,
        "latest_premium_rate": latest_premium_rate,
        "window_elapsed_pct": window_elapsed_pct,
        "backtest_count": int(backtest_count),
    }


def _crossed_above(level: float, observed_high: float) -> bool:
    return not math.isnan(level) and observed_high > level


def _crossed_below(level: float, observed_low: float) -> bool:
    return not math.isnan(level) and observed_low < level


_load_local_env()

BASE_URL = _env_value("BINANCE_FAPI_BASE", default="https://fapi.binance.com")
TIMEOUT = int(_env_value("HTTP_TIMEOUT", default="12"))
REQUESTS_PER_SECOND = float(
    _env_value("REQUESTS_PER_SECOND", "REQUESTS_PER_SEC", "RATE_LIMIT_REQ_PER_SEC", default="4.0")
)
RETRIES = int(_env_value("HTTP_RETRIES", "RETRIES", default="2"))
MAX_SYMBOLS_TO_SCAN = int(_env_value("MAX_SYMBOLS_TO_SCAN", "LEVELS_MAX_SYMBOLS", default="18"))
FAST_MAX_SYMBOLS = int(_env_value("FAST_MAX_SYMBOLS", default="12"))
DEEP_MAX_TOTAL_SYMBOLS_TO_SCAN = int(_env_value("DEEP_MAX_TOTAL_SYMBOLS_TO_SCAN", default="28"))
CRIME_SYMBOLS_TO_SCAN = int(_env_value("MARKET_STRUCTURE_SYMBOLS_TO_SCAN", "CRIME_SYMBOLS_TO_SCAN", default="10"))
DAILY_KLINE_LIMIT = int(_env_value("DAILY_KLINE_LIMIT", default="1500"))
NO_LARGE_PUMP_LOOKBACK_DAYS = 60
NO_LARGE_PUMP_THRESHOLD_PCT = float(_env_value("NO_LARGE_PUMP_THRESHOLD_PCT", default="35.0"))
INCLUDE_TRADFI_BREAKOUTS = _env_value("INCLUDE_TRADFI_BREAKOUTS", default="0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ENABLE_MODELED_FUNDING = _env_value("ENABLE_MODELED_FUNDING", default="0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ALWAYS_SCAN_SYMBOLS = tuple(
    symbol.strip().upper()
    for symbol in _env_value(
        "ALWAYS_SCAN_SYMBOLS",
        "FORCE_SCAN_SYMBOLS",
        default="COPPERUSDT,XAUUSDT,XAGUSDT,XPTUSDT,XPDUSDT,CLUSDT,NATGASUSDT,NVDAUSDT,GOOGLUSDT,TSLAUSDT,INTCUSDT,HOODUSDT,MSTRUSDT,AMZNUSDT,CRCLUSDT,COINUSDT,PLTRUSDT,PAYPUSDT,METAUSDT,EWYUSDT,EWJUSDT",
    ).split(",")
    if symbol.strip()
)

BINANCE_API_KEY = _env_value("BINANCE_API_KEY", default="")
BINANCE_API_SECRET = _env_value("BINANCE_API_SECRET", default="")
BINANCE_RECV_WINDOW = int(_env_value("BINANCE_RECV_WINDOW", "BINANCE_RECV_WINDOW_MS", default="5000"))
PNL_RECENT_DAYS = int(_env_value("PNL_RECENT_DAYS", default="90"))
PNL_MAX_EXPORT_FETCHES = int(_env_value("PNL_EXPORT_MAX_FETCHES", "PNL_EXPORT_MAX_YEARS", default="5"))
PNL_CACHE_DIR = _env_value("PNL_CACHE_DIR", default=str(APP_DIR / ".cache" / "binance_income"))
PRE_PUMP_SNAPSHOT_PATH = Path(
    _env_value("PRE_PUMP_SNAPSHOT_PATH", default=str(APP_DIR / "data" / "pre_pump_scan_snapshots.csv"))
)
PRE_PUMP_SNAPSHOT_RETENTION_DAYS = int(_env_value("PRE_PUMP_SNAPSHOT_RETENTION_DAYS", default="21"))
PNL_BENCHMARKS = [s.strip().upper() for s in _env_value("PNL_BENCHMARKS", default="BTCUSDT,BNBUSDT").split(",") if s.strip()]
FUNDING_BACKTEST_WINDOWS = int(_env_value("FUNDING_BACKTEST_WINDOWS", default="4"))
FUNDING_STREAM_SAMPLE_SECONDS = float(_env_value("FUNDING_STREAM_SAMPLE_SECONDS", default="1.0"))
LONG_SHORT_RATIO_PERIOD = _env_value("LONG_SHORT_RATIO_PERIOD", default="1h")
ALL_CRYPTO_SHORTS_REQUESTS_PER_SECOND = float(
    _env_value("ALL_CRYPTO_SHORTS_REQUESTS_PER_SECOND", default="8.0")
)
SQUEEZE_RADAR_REQUESTS_PER_SECOND = _parse_env_float(
    _env_value("SQUEEZE_RADAR_REQUESTS_PER_SECOND", default="6.0"),
    default=6.0,
    minimum=1.0,
)
SQUEEZE_RADAR_DEFAULT_SYMBOLS = _parse_env_int(
    _env_value("SQUEEZE_RADAR_DEFAULT_SYMBOLS", default="24"),
    default=24,
    minimum=12,
)
SQUEEZE_RADAR_PREFILTER_SYMBOLS = _parse_env_int(
    _env_value("SQUEEZE_RADAR_PREFILTER_SYMBOLS", default="72"),
    default=72,
    minimum=24,
)
SQUEEZE_RADAR_LATEST_PATH = Path(
    _env_value(
        "SQUEEZE_RADAR_LATEST_PATH",
        default=str(APP_DIR / "data" / "squeeze_radar_latest.csv"),
    )
)
SQUEEZE_RADAR_HISTORY_PATH = Path(
    _env_value(
        "SQUEEZE_RADAR_HISTORY_PATH",
        default=str(APP_DIR / "data" / "squeeze_radar_history.csv"),
    )
)
SQUEEZE_RADAR_HISTORY_RETENTION_DAYS = _parse_env_int(
    _env_value("SQUEEZE_RADAR_HISTORY_RETENTION_DAYS", default="30"),
    default=30,
    minimum=7,
)
SQUEEZE_RADAR_STRUCTURAL_EVIDENCE_PATH = Path(
    _env_value(
        "SQUEEZE_RADAR_STRUCTURAL_EVIDENCE_PATH",
        default=str(APP_DIR / "data" / "squeeze_radar_structural_evidence.csv"),
    )
)
SQUEEZE_RADAR_STRUCTURAL_REFRESH_MAX_SYMBOLS = _parse_env_int(
    _env_value("SQUEEZE_RADAR_STRUCTURAL_REFRESH_MAX_SYMBOLS", default="4"),
    default=4,
    minimum=1,
)
SQUEEZE_RADAR_CROWD_DIAGNOSTIC_MAX_SYMBOLS = _parse_env_int(
    _env_value("SQUEEZE_RADAR_CROWD_DIAGNOSTIC_MAX_SYMBOLS", default="12"),
    default=12,
    minimum=0,
)
SQUEEZE_RADAR_SHORT_SEED_PATHS = (
    APP_DIR / "short_account_roc_output" / "short_account_roc_full_scan_latest.csv",
    APP_DIR / "data" / "latest_short_account_roc.csv",
    APP_DIR / "data" / "latest_short_account_trend.csv",
)
SHORT_ACCOUNT_CHANGE_WINDOWS = _parse_positive_ints(
    _env_value("SHORT_ACCOUNT_CHANGE_WINDOWS", default="1,3,4,6,12,24"),
    default=(1, 3, 4, 6, 12, 24),
)
LONG_SHORT_RATIO_HISTORY_LIMIT = max(
    int(_env_value("LONG_SHORT_RATIO_HISTORY_LIMIT", default="25")),
    max(SHORT_ACCOUNT_CHANGE_WINDOWS, default=1) + 1,
    2,
)
CRIME_PUMP_PERIOD = _env_value("MARKET_STRUCTURE_PERIOD", "CRIME_PUMP_PERIOD", default="1h")
CRIME_DEPTH_LIMIT = int(_env_value("MARKET_STRUCTURE_DEPTH_LIMIT", "CRIME_DEPTH_LIMIT", default="50"))
CRIME_HOURLY_LOOKBACK = int(_env_value("MARKET_STRUCTURE_HOURLY_LOOKBACK", "CRIME_HOURLY_LOOKBACK", default="50"))
CRIME_MIN_QUOTE_VOLUME = float(
    _env_value("MARKET_STRUCTURE_MIN_QUOTE_VOLUME", "CRIME_MIN_QUOTE_VOLUME", default="2500000")
)
CRIME_EXTERNAL_SYMBOLS_TO_SCAN = int(
    _env_value("MARKET_STRUCTURE_EXTERNAL_SYMBOLS_TO_SCAN", "CRIME_EXTERNAL_SYMBOLS_TO_SCAN", default="6")
)
DEEP_EXTERNAL_SYMBOLS_TO_SCAN = int(_env_value("DEEP_EXTERNAL_SYMBOLS_TO_SCAN", default="4"))
PRECONVEX_SYMBOLS_TO_SCAN = int(_env_value("PRECONVEX_SYMBOLS_TO_SCAN", default="8"))
ATH_RUNWAY_SYMBOLS_TO_SCAN = int(_env_value("ATH_RUNWAY_SYMBOLS_TO_SCAN", default="25"))
DEEP_ATH_SYMBOLS_TO_SCAN = int(_env_value("DEEP_ATH_SYMBOLS_TO_SCAN", default="4"))
FULL_ATH_MAX_SYMBOLS_TO_SCAN = int(_env_value("FULL_ATH_MAX_SYMBOLS_TO_SCAN", default="35"))
FULL_ATH_EXTERNAL_SYMBOLS_TO_SCAN = int(_env_value("FULL_ATH_EXTERNAL_SYMBOLS_TO_SCAN", default="4"))
CRIME_EXCLUDED_BASE_ASSETS = {
    item.strip().upper()
    for item in _env_value(
        "MARKET_STRUCTURE_EXCLUDED_BASE_ASSETS",
        "CRIME_EXCLUDED_BASE_ASSETS",
        default=DEFAULT_CRIME_EXCLUDED_BASES,
    ).split(",")
    if item.strip()
}
CRIME_FORCE_SYMBOLS = tuple(
    symbol.strip().upper()
    for symbol in _env_value("MARKET_STRUCTURE_FORCE_SYMBOLS", "CRIME_FORCE_SYMBOLS", default=DEFAULT_CRIME_FORCE_SYMBOLS).split(",")
    if symbol.strip()
)
CRIME_MM_PROXIMITY_PATH = _env_value(
    "MARKET_MAKER_PROXIMITY_PATH",
    "CRIME_MM_PROXIMITY_PATH",
    default=str(APP_DIR / "crypto_market_structure" / "fixtures" / "crime_mm_proximity.csv"),
)
CRIME_MM_PROXIMITY_SIGNALS = _env_value("MARKET_MAKER_PROXIMITY_SIGNALS", "CRIME_MM_PROXIMITY_SIGNALS", default="")
COINMARKETCAP_API_KEY = _env_value("COINMARKETCAP_API_KEY", "CMC_API_KEY", default="")
CMC_MOVERS_LIMIT = int(_env_value("CMC_MOVERS_LIMIT", default="200"))
CMC_MOVER_SYMBOLS_TO_SCAN = int(_env_value("CMC_MOVER_SYMBOLS_TO_SCAN", default="8"))
DWF_PORTFOLIO_SYMBOLS_TO_SCAN = int(_env_value("DWF_PORTFOLIO_SYMBOLS_TO_SCAN", default="8"))
DISCORD_WEBHOOK_URL = _env_value("DISCORD_WEBHOOK_URL", "CONVEX_LONG_DISCORD_WEBHOOK_URL", default="").strip()
DISCORD_CONVEX_ALERTS_ENABLED = _env_value("DISCORD_CONVEX_ALERTS_ENABLED", default="1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DISCORD_CONVEX_ALERT_TOP_N = _parse_env_int(
    _env_value("DISCORD_CONVEX_ALERT_TOP_N", default="10"),
    default=10,
    minimum=1,
)
DISCORD_CONVEX_ALERT_MIN_SCORE = _parse_env_float(
    _env_value("DISCORD_CONVEX_ALERT_MIN_SCORE", default="0"),
    default=0.0,
    minimum=0.0,
)
DISCORD_CONVEX_ALERT_COOLDOWN_MINUTES = _parse_env_int(
    _env_value("DISCORD_CONVEX_ALERT_COOLDOWN_MINUTES", default="240"),
    default=240,
    minimum=0,
)
DISCORD_CONVEX_ALERT_STATE_PATH = Path(
    _env_value(
        "DISCORD_CONVEX_ALERT_STATE_PATH",
        default=str(APP_DIR / "data" / "discord_convex_alert_state.csv"),
    )
)
DISCORD_CONVEX_CACHE_PATH = Path(
    _env_value(
        "DISCORD_CONVEX_CACHE_PATH",
        default=str(APP_DIR / "data" / "latest_convex_longs.csv"),
    )
)
DISCORD_HOLDER_CONTRACTS_FILE = Path(
    _env_value(
        "DISCORD_HOLDER_CONTRACTS_FILE",
        default=str(APP_DIR / "data" / "discord_holder_contracts.csv"),
    )
)
DISCORD_HOLDER_COMPOSITION_ENABLED = _env_value("DISCORD_HOLDER_COMPOSITION_ENABLED", default="1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DISCORD_HOLDER_COMPOSITION_SHOW_MISSING = _env_value(
    "DISCORD_HOLDER_COMPOSITION_SHOW_MISSING",
    default="0",
).strip().lower() in {"1", "true", "yes", "on"}
DISCORD_HOLDER_COMPOSITION_TIMEOUT_SECONDS = _parse_env_int(
    _env_value("DISCORD_HOLDER_COMPOSITION_TIMEOUT_SECONDS", default="12"),
    default=12,
    minimum=3,
)
DISCORD_HOLDER_COMPOSITION_MAX_HOLDERS = _parse_env_int(
    _env_value("DISCORD_HOLDER_COMPOSITION_MAX_HOLDERS", default="100"),
    default=100,
    minimum=10,
)
DISCORD_HOLDER_COMPOSITION_TOP_HOLDERS = _parse_env_int(
    _env_value("DISCORD_HOLDER_COMPOSITION_TOP_HOLDERS", default="0"),
    default=0,
    minimum=0,
)
DISCORD_HOLDER_COMPOSITION_MAX_CHARS = _parse_env_int(
    _env_value("DISCORD_HOLDER_COMPOSITION_MAX_CHARS", default="520"),
    default=520,
    minimum=200,
)
CEX_DEPOSIT_FLOW_ENABLED = _env_value("CEX_DEPOSIT_FLOW_ENABLED", default="1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
CEX_DEPOSIT_FLOW_MAX_SYMBOLS = _parse_env_int(
    _env_value("CEX_DEPOSIT_FLOW_MAX_SYMBOLS", default="0"),
    default=0,
    minimum=0,
)
CEX_DEPOSIT_FLOW_LOOKBACK_HOURS = _parse_env_int(
    _env_value("CEX_DEPOSIT_FLOW_LOOKBACK_HOURS", default="24"),
    default=24,
    minimum=1,
)
CEX_DEPOSIT_FLOW_MIN_TRANSFER_TOKENS = _parse_env_float(
    _env_value("CEX_DEPOSIT_FLOW_MIN_TRANSFER_TOKENS", default="500000"),
    default=500_000.0,
    minimum=0.0,
)
CEX_DEPOSIT_FLOW_MIN_TOP10_PCT = _parse_env_float(
    _env_value("CEX_DEPOSIT_FLOW_MIN_TOP10_PCT", default="90"),
    default=90.0,
    minimum=0.0,
)
CEX_DEPOSIT_FLOW_TIMEOUT_SECONDS = _parse_env_int(
    _env_value("CEX_DEPOSIT_FLOW_TIMEOUT_SECONDS", default="12"),
    default=12,
    minimum=3,
)

if not IMPORT_ONLY:
    st.set_page_config(page_title="Convex Squeeze Radar", layout="wide")
    st.markdown(
        """
        <style>
        :root {
            --radar-bg: #0d1014;
            --radar-panel: #151a20;
            --radar-panel-2: #1b2129;
            --radar-border: #303741;
            --radar-text: #f2f5f7;
            --radar-muted: #a8b0ba;
            --radar-cyan: #59c3d8;
            --radar-green: #4bc487;
            --radar-amber: #f0b44d;
            --radar-coral: #f06b67;
        }
        .stApp { background: var(--radar-bg); color: var(--radar-text); }
        .block-container { max-width: 1600px; padding-top: 1.35rem; padding-bottom: 3rem; }
        h1, h2, h3, p, label, .stMarkdown, .stCaption { color: var(--radar-text) !important; letter-spacing: 0 !important; }
        h1 { font-size: 2.15rem !important; line-height: 1.08 !important; margin-bottom: 0.2rem !important; }
        h2 { font-size: 1.35rem !important; margin-top: 1.35rem !important; }
        h3 { font-size: 1.05rem !important; }
        [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: var(--radar-muted) !important; }
        [data-testid="stMetric"] {
            background: var(--radar-panel);
            border: 1px solid var(--radar-border);
            border-radius: 6px;
            padding: 0.75rem 0.85rem;
            min-height: 96px;
        }
        [data-testid="stMetricLabel"] { color: var(--radar-muted) !important; }
        [data-testid="stMetricValue"] { color: var(--radar-text) !important; font-size: 1.55rem !important; }
        div[data-testid="stDataFrame"] { border: 1px solid var(--radar-border); border-radius: 6px; overflow: hidden; }
        .stTabs [data-baseweb="tab-list"] { gap: 0; border-bottom: 1px solid var(--radar-border); }
        .stTabs [data-baseweb="tab"] { border-radius: 0; padding-left: 1rem; padding-right: 1rem; }
        .stTabs [aria-selected="true"] { color: var(--radar-cyan) !important; border-bottom: 2px solid var(--radar-cyan); }
        .stButton button { border-radius: 6px !important; min-height: 2.6rem; }
        .stButton button[kind="primary"] { background: var(--radar-coral); border-color: var(--radar-coral); color: #111417; }
        .stButton button[kind="primary"]:hover { background: #ff817c; border-color: #ff817c; }
        button[data-testid="stBaseButton-segmented_control"] {
            background: var(--radar-panel) !important;
            border-color: var(--radar-border) !important;
        }
        button[data-testid="stBaseButton-segmented_control"] p { color: var(--radar-muted) !important; }
        button[data-testid="stBaseButton-segmented_controlActive"] {
            background: var(--radar-panel-2) !important;
            border-color: var(--radar-cyan) !important;
        }
        button[data-testid="stBaseButton-segmented_controlActive"] p { color: var(--radar-text) !important; }
        [data-testid="stAlert"] { border-radius: 6px; border-width: 1px; }
        div[data-baseweb="select"] > div, div[role="radiogroup"] { border-radius: 6px !important; }
        hr { border-color: var(--radar-border) !important; }
        .card { background: var(--radar-panel); border: 1px solid var(--radar-border); border-radius: 6px; padding: 12px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _cache_data(*cache_args: Any, **cache_kwargs: Any) -> Any:
    if IMPORT_ONLY:
        if cache_args and callable(cache_args[0]) and len(cache_args) == 1 and not cache_kwargs:
            return cache_args[0]

        def decorator(func: Any) -> Any:
            return func

        return decorator
    return st.cache_data(*cache_args, **cache_kwargs)


DISCORD_CONVEX_ALERT_STATE_COLUMNS = ["symbol", "last_notified_at", "last_score", "last_note"]


def _metric_value(row: pd.Series, columns: tuple[str, ...]) -> float | None:
    for column in columns:
        if column not in row.index:
            continue
        try:
            value = float(row.get(column))
        except Exception:
            continue
        if math.isfinite(value):
            return value
    return None


def _truthy_value(value: Any) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except Exception:
        pass
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _dashboard_bool_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame[column].astype("object").where(pd.notna(frame[column]), False).astype(str).str.strip().str.lower().isin(
        {"1", "true", "yes", "y", "on"}
    )


def _dashboard_num_series(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").fillna(default).astype("float64")


def _early_pump_dashboard_watch_mask(frame: pd.DataFrame, *, min_score: float = 55.0) -> pd.Series:
    if frame.empty:
        return pd.Series(False, index=frame.index)
    hard_gates = (
        _dashboard_bool_series(frame, "early_pump_holder_evidence_gate")
        & _dashboard_bool_series(frame, "early_pump_whale_gate")
        & _dashboard_bool_series(frame, "early_pump_binance_bitget_gate")
        & _dashboard_bool_series(frame, "early_pump_float_gate")
        & _dashboard_bool_series(frame, "early_pump_short_gate")
        & _dashboard_bool_series(frame, "early_pump_not_late_gate")
        & _dashboard_bool_series(frame, "early_pump_no_recent_pump_gate")
    )
    score_watch = _dashboard_num_series(frame, "early_pump_radar_score").ge(float(min_score))
    alert = _dashboard_bool_series(frame, "early_pump_alert_flag")
    return ((alert | score_watch) & hard_gates).fillna(False)


def _pre_activity_dashboard_watch_mask(frame: pd.DataFrame, *, min_score: float = 58.0) -> pd.Series:
    if frame.empty:
        return pd.Series(False, index=frame.index)
    hard_gates = (
        _dashboard_bool_series(frame, "pre_activity_holder_evidence_gate")
        & _dashboard_bool_series(frame, "pre_activity_whale_gate")
        & _dashboard_bool_series(frame, "pre_activity_binance_bitget_gate")
        & _dashboard_bool_series(frame, "pre_activity_float_gate")
        & _dashboard_bool_series(frame, "pre_activity_structure_gate")
        & _dashboard_bool_series(frame, "pre_activity_short_gate")
        & _dashboard_bool_series(frame, "pre_activity_behavior_gate")
        & _dashboard_bool_series(frame, "pre_activity_quiet_gate")
        & _dashboard_bool_series(frame, "pre_activity_no_recent_pump_gate")
    )
    score_watch = _dashboard_num_series(frame, "pre_activity_pump_score").ge(float(min_score))
    alert = _dashboard_bool_series(frame, "pre_activity_alert_flag")
    return ((alert | score_watch) & hard_gates).fillna(False)


def _single_row_gate_mask(row: pd.Series, fn: Any) -> bool:
    frame = pd.DataFrame([row.to_dict()]).loc[:, lambda data: ~data.columns.duplicated()].copy()
    try:
        mask = fn(frame)
    except Exception:
        return False
    if not isinstance(mask, pd.Series) or mask.empty:
        return False
    return _truthy_value(mask.iloc[0])


def _dashboard_alert_gate_line(row: pd.Series) -> str:
    core = _truthy_value(row.get("thesis_core_gate"))
    holder = _truthy_value(row.get("thesis_holder_gate")) or _single_row_gate_mask(
        row,
        lambda frame: holder_concentration_mask(frame, min_whale_pct=90.0, require_holder_evidence=True),
    )
    venue = _truthy_value(row.get("thesis_venue_gate")) or _single_row_gate_mask(
        row,
        lambda frame: binance_bitget_venue_mask(frame, allow_cex_flow_targets=False),
    )
    no_pump = _truthy_value(row.get("thesis_no_pump_gate")) or _single_row_gate_mask(row, no_recent_pump_proof_mask)
    top10 = _metric_value(row, ("filtered_top_10_manipulable_pct", "adjusted_top_10_pct", "top10_holder_pct", "raw_top_10_pct"))
    if top10 is None:
        try:
            top10_values = effective_top10_holder_pct(pd.DataFrame([row.to_dict()]))
            if not top10_values.empty:
                parsed_top10 = float(top10_values.iloc[0])
                top10 = parsed_top10 if math.isfinite(parsed_top10) else None
        except Exception:
            top10 = None
    short_pct = _metric_value(row, ("short_account_pct",))
    top10_text = f"{top10:.1f}%" if top10 is not None else "n/a"
    short_text = f"{short_pct:.1f}%" if short_pct is not None else "n/a"
    yes_no = lambda value: "Y" if bool(value) else "N"
    return (
        f"Dashboard gate: coreThesis {yes_no(core)} | holder {yes_no(holder)} top10 {top10_text} | "
        f"BnBg {yes_no(venue)} | noPump60 {yes_no(no_pump)} | shorts {short_text}"
    )


def _metric_fragment(
    row: pd.Series,
    label: str,
    columns: tuple[str, ...],
    *,
    suffix: str = "",
    decimals: int = 1,
) -> str:
    value = _metric_value(row, columns)
    if value is None:
        return ""
    return f"{label} {value:.{decimals}f}{suffix}"


def _read_discord_convex_alert_state() -> pd.DataFrame:
    if not DISCORD_CONVEX_ALERT_STATE_PATH.exists():
        return pd.DataFrame(columns=DISCORD_CONVEX_ALERT_STATE_COLUMNS)
    try:
        state = pd.read_csv(DISCORD_CONVEX_ALERT_STATE_PATH)
    except Exception:
        return pd.DataFrame(columns=DISCORD_CONVEX_ALERT_STATE_COLUMNS)
    for column in DISCORD_CONVEX_ALERT_STATE_COLUMNS:
        if column not in state.columns:
            state[column] = pd.NA
    state = state.loc[:, DISCORD_CONVEX_ALERT_STATE_COLUMNS].copy()
    state["symbol"] = state["symbol"].astype(str).str.upper().str.strip()
    state["last_notified_at"] = pd.to_datetime(state["last_notified_at"], errors="coerce", utc=True)
    state["last_score"] = pd.to_numeric(state["last_score"], errors="coerce")
    return state[state["symbol"].ne("")].drop_duplicates(subset=["symbol"], keep="last")


def _write_discord_convex_alert_state(state: pd.DataFrame) -> None:
    DISCORD_CONVEX_ALERT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = state.loc[:, DISCORD_CONVEX_ALERT_STATE_COLUMNS].copy()
    output["last_notified_at"] = pd.to_datetime(output["last_notified_at"], errors="coerce", utc=True).dt.strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    output.to_csv(DISCORD_CONVEX_ALERT_STATE_PATH, index=False)


def _discord_convex_candidates(all_df: pd.DataFrame) -> pd.DataFrame:
    if all_df.empty or "trade_bucket" not in all_df.columns:
        return pd.DataFrame()
    source = all_df.loc[:, ~all_df.columns.duplicated()].copy()
    source["_discord_bucket_score"] = pd.to_numeric(source.get("trade_bucket_score"), errors="coerce").fillna(0.0)
    candidates = source[
        source["trade_bucket"].astype(str).eq("Convex Long")
        & (source["_discord_bucket_score"] >= DISCORD_CONVEX_ALERT_MIN_SCORE)
    ].copy()
    if candidates.empty:
        return candidates
    candidates = apply_thesis_alert_gate(candidates, allow_cex_flow_targets=False)
    if candidates.empty:
        return candidates
    rescored = _score_trade_buckets(candidates)
    current_core = (
        rescored.get("trade_bucket", pd.Series("", index=rescored.index)).astype(str).eq("Convex Long")
        & rescored.get("thesis_core_gate", pd.Series(False, index=rescored.index)).fillna(False).astype(bool)
    )
    candidates = candidates.loc[current_core.reindex(candidates.index, fill_value=False)].copy()
    if candidates.empty:
        return candidates
    for column in (
        "trade_bucket",
        "trade_bucket_score",
        "raw_convex_long_signal",
        "thesis_gate",
        "thesis_base_gate",
        "thesis_float_gate",
        "thesis_short_squeeze_gate",
        "thesis_not_late_gate",
        "thesis_core_gate",
        "thesis_gate_note",
        "trade_bucket_note",
    ):
        if column in rescored.columns:
            candidates[column] = rescored.loc[candidates.index, column]
    return candidates.sort_values(["_discord_bucket_score", "symbol"], ascending=[False, True])


def _write_latest_convex_longs_cache(all_df: pd.DataFrame, *, scan_mode: str) -> None:
    columns = [
        "symbol",
        "base_asset",
        "coingecko_id",
        "binance_perp_universe",
        "token_platform",
        "token_contract",
        "top10_holder_pct",
        "owner_holder_pct",
        "creator_holder_pct",
        "holder_count",
        "holder_source",
        "trade_bucket",
        "trade_bucket_score",
        "raw_convex_long_signal",
        "thesis_gate",
        "thesis_holder_gate",
        "thesis_holder_evidence_gate",
        "thesis_whale_concentration_gate",
        "thesis_venue_gate",
        "thesis_no_pump_gate",
        "thesis_base_gate",
        "thesis_float_gate",
        "thesis_short_squeeze_gate",
        "thesis_not_late_gate",
        "thesis_core_gate",
        "thesis_core_squeeze_fuel_score",
        "thesis_core_float_score",
        "thesis_gate_note",
        "trade_bucket_note",
        *RANGE_BREAKOUT_COLUMNS,
        "broke_high_20d",
        "broke_high_90d",
        "broke_high_180d",
        "broke_low_20d",
        "broke_low_90d",
        "broke_low_180d",
        "recent_max_pump_60d_pct",
        "recent_pump_60d_days",
        "no_large_pump_60d_flag",
        "last_price",
        "price_change_24h_pct",
        "change_24h_pct",
        "day_change_pct",
        "bitget_or_gate_venue_flag",
        "binance_volume_share_pct",
        "bitget_volume_share_pct",
        "gate_volume_share_pct",
        "binance_bitget_gate_share_pct",
        "binance_bitget_gate_share_score",
        "top_venue",
        "short_account_pct",
        "long_account_pct",
        "long_short_account_ratio",
        "hour_quote_volume_previous_1h",
        "hour_quote_volume",
        "hour_volume_roc_1h_pct",
        "hour_volume_multiple",
        "oi_delta_pct",
        "oi_value_change_since_scan_pct",
        "convexity_entry_score",
        "convexity_score",
        "rave_lab_setup_score",
        "pre_pump_precision_score",
        "dormant_short_fuse_score",
        "accumulation_cvd_proxy_score",
        "accumulation_absorption_score",
        "accumulation_absorption_flag",
        "accumulation_absorption_note",
        "convexity_summary",
        "rave_lab_setup_note",
        "dormant_short_fuse_note",
        "pre_pump_precision_note",
        *CEX_DEPOSIT_FLOW_COLUMNS,
        *TERMINAL_SCORE_COLUMNS,
        *TIMING_SCORE_COLUMNS,
        *MECHANISM_SCORE_COLUMNS,
    ]
    cache_frame = _discord_convex_candidates(all_df).head(max(50, DISCORD_CONVEX_ALERT_TOP_N)).copy()
    if cache_frame.empty:
        cache_frame = pd.DataFrame(columns=columns)
    else:
        cache_frame = cache_frame[[column for column in columns if column in cache_frame.columns]].copy()
    cache_frame.insert(0, "scan_mode", str(scan_mode))
    cache_frame.insert(0, "scanned_at_utc", _now_utc())
    DISCORD_CONVEX_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cache_frame.to_csv(DISCORD_CONVEX_CACHE_PATH, index=False)


def _eligible_discord_convex_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return candidates
    if DISCORD_CONVEX_ALERT_COOLDOWN_MINUTES <= 0:
        return candidates
    state = _read_discord_convex_alert_state()
    last_by_symbol = dict(zip(state["symbol"], state["last_notified_at"]))
    now = pd.Timestamp.now(tz="UTC")
    cooldown = pd.Timedelta(minutes=DISCORD_CONVEX_ALERT_COOLDOWN_MINUTES)
    eligible_indices: list[Any] = []
    for index, row in candidates.iterrows():
        symbol = str(row.get("symbol", "")).upper().strip()
        last_sent = last_by_symbol.get(symbol)
        if last_sent is None or pd.isna(last_sent) or now - last_sent >= cooldown:
            eligible_indices.append(index)
    return candidates.loc[eligible_indices].copy()


def _discord_holder_composition_text(row: pd.Series) -> str:
    if not DISCORD_HOLDER_COMPOSITION_ENABLED:
        return ""
    try:
        composition = fetch_holder_composition(
            row.to_dict(),
            hints_path=DISCORD_HOLDER_CONTRACTS_FILE,
            timeout=DISCORD_HOLDER_COMPOSITION_TIMEOUT_SECONDS,
            max_holders=DISCORD_HOLDER_COMPOSITION_MAX_HOLDERS,
        )
    except Exception as exc:
        return f"Holder composition unavailable: {exc}"
    if composition.error == "no contract hint" and not DISCORD_HOLDER_COMPOSITION_SHOW_MISSING:
        return ""
    return format_holder_composition_for_discord(
        composition,
        include_top_holders=DISCORD_HOLDER_COMPOSITION_TOP_HOLDERS,
        max_chars=DISCORD_HOLDER_COMPOSITION_MAX_CHARS,
    )


def _discord_candidate_line(row: pd.Series) -> str:
    holder_text = _discord_holder_composition_text(row)
    return f"{_dashboard_alert_gate_line(row)}\n{build_discord_flag_card(row, holder_text=holder_text)}"


def _post_discord_convex_alert(candidates: pd.DataFrame, *, scan_mode: str) -> None:
    lines = [_discord_candidate_line(row) for _, row in candidates.iterrows()]
    alert_header = thesis_alert_header()
    description_prefix = f"{DISCORD_PRODUCT_IDENTITY}\n\n{alert_header}\n\n"
    card_budget = DISCORD_EMBED_DESCRIPTION_LIMIT - len(description_prefix)
    description = f"{description_prefix}{join_discord_flag_cards(lines, max_chars=card_budget)}"
    payload = {
        "username": "Convex Scanner",
        "embeds": [
            {
                "title": f"{len(candidates)} market-structure candidate{'s' if len(candidates) != 1 else ''}",
                "description": description,
                "color": 0x22C55E,
                "fields": [
                    {"name": "Scan mode", "value": str(scan_mode), "inline": True},
                    {"name": "Alert threshold", "value": f"{DISCORD_CONVEX_ALERT_MIN_SCORE:.1f}+", "inline": True},
                    {
                        "name": "Cooldown",
                        "value": f"{DISCORD_CONVEX_ALERT_COOLDOWN_MINUTES}m per symbol",
                        "inline": True,
                    },
                ],
                "footer": {
                    "text": DISCORD_FOOTER,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }
    response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
    if response.status_code >= 300:
        raise RuntimeError(f"Discord webhook HTTP {response.status_code}: {response.text[:180]}")
    archive_alerts(candidates, scan_mode=scan_mode)


def _record_discord_convex_alerts(candidates: pd.DataFrame) -> None:
    state = _read_discord_convex_alert_state()
    symbols = [str(symbol).upper().strip() for symbol in candidates["symbol"].tolist()]
    state = state[~state["symbol"].isin(symbols)].copy()
    now = pd.Timestamp.now(tz="UTC")
    new_rows = pd.DataFrame(
        [
            {
                "symbol": str(row.get("symbol", "")).upper().strip(),
                "last_notified_at": now,
                "last_score": _metric_value(row, ("_discord_bucket_score", "trade_bucket_score")),
                "last_note": str(row.get("trade_bucket_note", "")).strip()[:300],
            }
            for _, row in candidates.iterrows()
        ],
        columns=DISCORD_CONVEX_ALERT_STATE_COLUMNS,
    )
    _write_discord_convex_alert_state(pd.concat([state, new_rows], ignore_index=True))


def _maybe_notify_discord_convex_longs(all_df: pd.DataFrame, *, scan_key: str, scan_mode: str) -> str:
    if not DISCORD_CONVEX_ALERTS_ENABLED or not DISCORD_WEBHOOK_URL:
        return ""
    session_key = f"discord_convex_alert_sent::{scan_key}"
    if st.session_state.get(session_key):
        return ""
    st.session_state[session_key] = True

    candidates = _discord_convex_candidates(all_df)
    if candidates.empty:
        return "Discord alerts enabled: no Convex Long candidates met the current alert threshold."

    eligible = _eligible_discord_convex_candidates(candidates)
    if eligible.empty:
        return "Discord alerts enabled: Convex Long candidates are inside the per-symbol cooldown window."

    to_send = eligible.head(DISCORD_CONVEX_ALERT_TOP_N).copy()
    try:
        _post_discord_convex_alert(to_send, scan_mode=scan_mode)
        _record_discord_convex_alerts(to_send)
    except Exception as exc:
        return f"Discord alert failed: {exc}"
    return f"Discord alert sent for {len(to_send)} Convex Long candidate{'s' if len(to_send) != 1 else ''}."


@_cache_data(ttl=1800, show_spinner=False)
def load_benchmark_history(symbols: tuple[str, ...], start_ms: int, end_ms: int) -> pd.DataFrame:
    client = _client()
    day_ms = 24 * 60 * 60 * 1000
    frames: list[pd.DataFrame] = []

    for symbol in symbols:
        cursor = int(start_ms)
        rows: list[list[Any]] = []
        while cursor <= end_ms:
            batch = client.klines(
                symbol,
                interval="1d",
                limit=1500,
                start_time=cursor,
                end_time=end_ms,
            )
            if not batch:
                break
            rows.extend(batch)
            next_cursor = int(batch[-1][0]) + day_ms
            if next_cursor <= cursor or len(batch) < 1500:
                break
            cursor = next_cursor

        if not rows:
            continue

        frame = pd.DataFrame(rows, columns=list(range(len(rows[0]))))
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(frame[0], unit="ms", utc=True),
                symbol: pd.to_numeric(frame[4], errors="coerce"),
            }
        ).dropna()
        frames.append(frame.drop_duplicates(subset=["date"]).sort_values("date"))

    if not frames:
        return pd.DataFrame(columns=["date", *symbols])

    merged = frames[0]
    for frame in frames[1:]:
        merged = merged.merge(frame, on="date", how="outer")
    return merged.sort_values("date").reset_index(drop=True)


def _build_benchmark_comparison(
    result: PnLDashboardResult,
    daily_df: pd.DataFrame,
    *,
    benchmark_symbols: list[str],
) -> pd.DataFrame:
    if daily_df.empty or not benchmark_symbols:
        return pd.DataFrame(columns=["date", "Cumulative PnL %"])

    start_ms = int(daily_df["date"].min().timestamp() * 1000)
    end_ms = int(daily_df["date"].max().timestamp() * 1000)
    benchmark_df = load_benchmark_history(tuple(benchmark_symbols), start_ms, end_ms)
    baseline = _baseline_balance(result)
    compare_df = pd.DataFrame({"date": daily_df["date"], "Cumulative PnL %": daily_df["cumulative_pnl"] / baseline * 100.0})

    if benchmark_df.empty:
        return compare_df

    merged = compare_df.merge(benchmark_df, on="date", how="left").sort_values("date").ffill()
    for symbol in benchmark_symbols:
        if symbol not in merged.columns:
            continue
        first_valid = merged[symbol].dropna()
        if first_valid.empty:
            continue
        start_close = float(first_valid.iloc[0])
        if abs(start_close) < 1e-12:
            continue
        merged[f"{symbol} %"] = (merged[symbol] / start_close - 1.0) * 100.0

    keep_cols = ["date", "Cumulative PnL %"] + [f"{symbol} %" for symbol in benchmark_symbols if f"{symbol} %" in merged.columns]
    return merged[keep_cols]


EXTERNAL_CRIME_COLUMNS = [
    *DWF_LABS_PORTFOLIO_COLUMNS,
    "coinbase_spot_listed",
    "coinbase_spot_quote_volume_24h",
    "binance_spot_quote_volume_24h",
    "coingecko_total_volume_24h",
    "coingecko_coinbase_volume_24h",
    "coingecko_cex_volume_24h",
    "coingecko_dex_volume_24h",
    "kraken_spot_quote_volume_24h",
    "upbit_spot_quote_volume_24h",
    "upbit_krw_quote_volume_24h",
    "try_spot_quote_volume_24h",
    "emfx_spot_quote_volume_24h",
    "coinbase_volume_share_pct",
    "binance_volume_share_pct",
    "bitget_volume_share_pct",
    "gate_volume_share_pct",
    "okx_volume_share_pct",
    "cex_volume_share_pct",
    "kraken_volume_share_pct",
    "upbit_volume_share_pct",
    "krw_volume_share_pct",
    "try_volume_share_pct",
    "emfx_volume_share_pct",
    "dex_volume_share_pct",
    "cex_to_dex_volume_ratio",
    "cex_dex_volume_ratio_score",
    "binance_bitget_gate_share_pct",
    "binance_bitget_gate_share_score",
    "coinbase_bid_depth_2pct_usd",
    "coinbase_ask_depth_2pct_usd",
    "coinbase_total_depth_2pct_usd",
    "coinbase_book_imbalance_pct",
    "coinbase_depth_to_volume_pct",
    "coinbase_depth_to_perp_volume_pct",
    "top_venue",
    "top_venue_volume_24h",
    "top_venue_volume_share_pct",
    "top3_venue_volume_share_pct",
    "venue_hhi",
    "venue_hhi_score",
    "venue_count",
    "cex_venue_count",
    "dex_venue_count",
    "coinbase_bid_ask_spread_pct",
    "spot_external_quote_volume_24h",
    "spot_to_perp_volume_pct",
    "coinbase_to_perp_volume_pct",
    "coingecko_id",
    "coingecko_ath_usd",
    "coingecko_ath_change_pct",
    "coingecko_ath_date",
    "market_cap_usd",
    "fdv_usd",
    "fdv_to_market_cap",
    "circulating_supply_pct",
    "locked_supply_pct",
    "token_platform",
    "token_contract",
    "top10_holder_pct",
    "owner_holder_pct",
    "creator_holder_pct",
    "holder_count",
    "holder_source",
    "holder_concentration_score",
    "venue_concentration_score",
    "emfx_lane_score",
    "crime_coinbase_lane_score",
    "crime_owner_circle_score",
    "crime_spot_impulse_score",
    "crime_supply_control_score",
    *INVENTORY_TRANSFER_COLUMNS,
    "ath_price",
    "ath_multiple",
    "ath_upside_pct",
    "ath_source",
    "ath_runway_20x_flag",
]
EXTERNAL_CRIME_BOOL_COLUMNS = {
    "dwf_labs_portfolio",
    "coinbase_spot_listed",
    "inventory_transfer_risk_flag",
    "ath_runway_20x_flag",
}
EXTERNAL_CRIME_TEXT_COLUMNS = {
    "dwf_labs_portfolio_note",
    "coingecko_id",
    "coingecko_ath_date",
    "token_platform",
    "token_contract",
    "holder_source",
    "top_venue",
    "ath_source",
    *INVENTORY_TRANSFER_TEXT_COLUMNS,
}


@_cache_data(ttl=900, show_spinner=False)
def load_external_crime_metrics_cached(base_assets: tuple[str, ...]) -> pd.DataFrame:
    rows = fetch_external_crime_metrics(list(base_assets))
    if not rows:
        return pd.DataFrame(columns=["normalized_base_asset", *EXTERNAL_CRIME_COLUMNS])
    return pd.DataFrame([row.__dict__ for row in rows])


@_cache_data(ttl=1800, show_spinner=False)
def load_dwf_labs_portfolio_cached() -> pd.DataFrame:
    rows = fetch_dwf_labs_portfolio_members()
    if not rows:
        return pd.DataFrame(columns=["normalized_base_asset", *DWF_LABS_PORTFOLIO_COLUMNS])
    portfolio = pd.DataFrame(rows)
    if "normalized_base_asset" not in portfolio.columns:
        return pd.DataFrame(columns=["normalized_base_asset", *DWF_LABS_PORTFOLIO_COLUMNS])
    portfolio["normalized_base_asset"] = portfolio["normalized_base_asset"].map(normalize_base_asset)
    portfolio = portfolio[portfolio["normalized_base_asset"].astype(str).str.len() > 0].copy()
    portfolio["dwf_labs_portfolio"] = True
    portfolio["dwf_labs_portfolio_rank"] = pd.to_numeric(portfolio.get("rank"), errors="coerce")
    portfolio["dwf_labs_portfolio_score"] = (
        95.0 - portfolio["dwf_labs_portfolio_rank"].fillna(110.0).clip(lower=1.0, upper=150.0) * 0.12
    ).clip(lower=70.0, upper=95.0)
    portfolio["dwf_labs_portfolio_note"] = portfolio["dwf_labs_portfolio_rank"].apply(
        lambda rank: (
            f"DWF Labs CoinGecko portfolio member #{int(rank)} ({DWF_LABS_CATEGORY_URL})"
            if pd.notna(rank)
            else f"DWF Labs CoinGecko portfolio member ({DWF_LABS_CATEGORY_URL})"
        )
    )
    return (
        portfolio.sort_values(["dwf_labs_portfolio_rank", "normalized_base_asset"], ascending=[True, True])
        .drop_duplicates(subset=["normalized_base_asset"], keep="first")
        [["normalized_base_asset", *DWF_LABS_PORTFOLIO_COLUMNS]]
        .reset_index(drop=True)
    )


@_cache_data(ttl=900, show_spinner=False)
def load_coinbase_spot_bases_cached() -> set[str]:
    return fetch_coinbase_spot_bases()


@_cache_data(ttl=300, show_spinner=False)
def load_cmc_movers_cached(api_key_fingerprint: str, _api_key: str, limit: int) -> pd.DataFrame:
    # The fingerprint gives Streamlit a safe cache key without storing the raw CMC key in the hash.
    _ = api_key_fingerprint
    rows = fetch_cmc_movers(_api_key, limit=limit)
    if not rows:
        return pd.DataFrame(columns=["normalized_base_asset", *CMC_MOVER_COLUMNS])

    movers = pd.DataFrame([row.__dict__ for row in rows])
    movers["normalized_base_asset"] = movers["base_asset"].map(normalize_base_asset)
    movers = movers[movers["normalized_base_asset"].astype(str).str.len() > 0].copy()
    if movers.empty:
        return pd.DataFrame(columns=["normalized_base_asset", *CMC_MOVER_COLUMNS])

    movers["cmc_mover_score"] = pd.to_numeric(
        movers["cmc_mover_score"],
        errors="coerce",
    ).fillna(0.0).clip(lower=0.0, upper=100.0)
    for col in CMC_MOVER_COLUMNS:
        if col not in movers.columns:
            movers[col] = "" if col in CMC_MOVER_TEXT_COLUMNS else float("nan")

    return (
        movers.sort_values("cmc_mover_score", ascending=False)
        .drop_duplicates(subset=["normalized_base_asset"], keep="first")
        [["normalized_base_asset", *CMC_MOVER_COLUMNS]]
    )


def _load_cmc_movers_for_scan(deep_scan: bool) -> pd.DataFrame:
    if not deep_scan or not COINMARKETCAP_API_KEY:
        return pd.DataFrame(columns=["normalized_base_asset", *CMC_MOVER_COLUMNS])
    return load_cmc_movers_cached(
        _key_fingerprint(COINMARKETCAP_API_KEY),
        COINMARKETCAP_API_KEY,
        CMC_MOVERS_LIMIT,
    )


def _empty_cmc_mover_columns(all_df: pd.DataFrame) -> pd.DataFrame:
    for col in CMC_MOVER_COLUMNS:
        if col not in all_df.columns:
            if col in CMC_MOVER_TEXT_COLUMNS:
                all_df[col] = ""
            elif col == "cmc_mover_score":
                all_df[col] = 0.0
            else:
                all_df[col] = float("nan")
    return all_df


def _apply_cmc_mover_metrics(all_df: pd.DataFrame, cmc_movers_df: pd.DataFrame) -> pd.DataFrame:
    all_df = _empty_cmc_mover_columns(all_df)
    if all_df.empty or cmc_movers_df.empty or "normalized_base_asset" not in cmc_movers_df.columns:
        return all_df

    merge_cols = ["normalized_base_asset", *[col for col in CMC_MOVER_COLUMNS if col in cmc_movers_df.columns]]
    merged = all_df[["symbol", "normalized_base_asset"]].merge(
        cmc_movers_df[merge_cols],
        on="normalized_base_asset",
        how="left",
    )
    merged = merged.set_index("symbol")
    for col in CMC_MOVER_COLUMNS:
        if col not in merged.columns:
            continue
        mapped = all_df["symbol"].map(merged[col])
        if col in CMC_MOVER_TEXT_COLUMNS:
            mapped = mapped.fillna("").astype(str)
        elif col == "cmc_mover_score":
            mapped = pd.to_numeric(mapped, errors="coerce").fillna(0.0).clip(lower=0.0, upper=100.0)
        else:
            mapped = pd.to_numeric(mapped, errors="coerce")
        all_df[col] = mapped
    return all_df


def _empty_mm_proximity_columns(all_df: pd.DataFrame) -> pd.DataFrame:
    for col in MM_PROXIMITY_COLUMNS:
        if col not in all_df.columns:
            all_df[col] = "" if col in MM_PROXIMITY_TEXT_COLUMNS else 0.0
    return all_df


def _parse_mm_proximity_env(raw_signals: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for raw_entry in str(raw_signals or "").split(";"):
        entry = raw_entry.strip()
        if not entry:
            continue
        parts = [part.strip() for part in entry.split("|")]
        if not parts or not parts[0]:
            continue
        rows.append(
            {
                "base_asset": parts[0].upper(),
                "mm_proximity_maker": parts[1] if len(parts) > 1 else "",
                "mm_proximity_score": _safe_float(parts[2]) if len(parts) > 2 else 50.0,
                "mm_proximity_note": parts[3] if len(parts) > 3 else "Manual MM/social graph signal.",
                "mm_proximity_source": parts[4] if len(parts) > 4 else "",
            }
        )
    return pd.DataFrame(rows)


@_cache_data(ttl=300, show_spinner=False)
def load_mm_proximity_signals_cached(path: str, raw_signals: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    csv_path = Path(path)
    if csv_path.exists():
        try:
            frames.append(pd.read_csv(csv_path))
        except Exception:
            pass

    env_df = _parse_mm_proximity_env(raw_signals)
    if not env_df.empty:
        frames.append(env_df)

    if not frames:
        return pd.DataFrame(columns=["normalized_base_asset", *MM_PROXIMITY_COLUMNS])

    signals = pd.concat(frames, ignore_index=True)
    if "base_asset" not in signals.columns:
        return pd.DataFrame(columns=["normalized_base_asset", *MM_PROXIMITY_COLUMNS])

    signals["normalized_base_asset"] = signals["base_asset"].map(normalize_base_asset)
    rename_map = {
        "score": "mm_proximity_score",
        "maker": "mm_proximity_maker",
        "market_maker": "mm_proximity_maker",
        "note": "mm_proximity_note",
        "source": "mm_proximity_source",
        "source_url": "mm_proximity_source",
    }
    signals = signals.rename(columns={key: value for key, value in rename_map.items() if key in signals.columns})
    if "mm_proximity_score" not in signals.columns:
        signals["mm_proximity_score"] = 0.0
    signals["mm_proximity_score"] = pd.to_numeric(
        signals["mm_proximity_score"],
        errors="coerce",
    ).fillna(0.0).clip(lower=0.0, upper=100.0)
    for col in MM_PROXIMITY_TEXT_COLUMNS:
        if col not in signals.columns:
            signals[col] = ""
        signals[col] = signals[col].fillna("").astype(str)

    signals = signals[signals["normalized_base_asset"].astype(str).str.len() > 0].copy()
    if signals.empty:
        return pd.DataFrame(columns=["normalized_base_asset", *MM_PROXIMITY_COLUMNS])
    return (
        signals.sort_values("mm_proximity_score", ascending=False)
        .drop_duplicates(subset=["normalized_base_asset"], keep="first")
        [["normalized_base_asset", *MM_PROXIMITY_COLUMNS]]
    )


def _apply_mm_proximity_signals(all_df: pd.DataFrame) -> pd.DataFrame:
    all_df = _empty_mm_proximity_columns(all_df)
    if all_df.empty:
        return all_df

    signals = load_mm_proximity_signals_cached(CRIME_MM_PROXIMITY_PATH, CRIME_MM_PROXIMITY_SIGNALS)
    if signals.empty:
        return all_df

    merged = all_df[["symbol", "normalized_base_asset"]].merge(signals, on="normalized_base_asset", how="left")
    merged = merged.set_index("symbol")
    for col in MM_PROXIMITY_COLUMNS:
        mapped = all_df["symbol"].map(merged[col]) if col in merged.columns else None
        if mapped is None:
            continue
        if col in MM_PROXIMITY_TEXT_COLUMNS:
            all_df[col] = mapped.fillna("").astype(str)
        else:
            all_df[col] = pd.to_numeric(mapped, errors="coerce").fillna(0.0).clip(lower=0.0, upper=100.0)
    return all_df


def _apply_dwf_mm_proximity_signal(all_df: pd.DataFrame) -> pd.DataFrame:
    if all_df.empty or "dwf_labs_portfolio_score" not in all_df.columns:
        return all_df
    all_df = _empty_mm_proximity_columns(all_df)
    dwf_score = pd.to_numeric(all_df["dwf_labs_portfolio_score"], errors="coerce").fillna(0.0).clip(
        lower=0.0,
        upper=100.0,
    )
    existing_mm_score = pd.to_numeric(all_df["mm_proximity_score"], errors="coerce").fillna(0.0)
    dwf_better = dwf_score > existing_mm_score
    if not bool(dwf_better.any()):
        return all_df
    all_df.loc[dwf_better, "mm_proximity_score"] = dwf_score[dwf_better]
    all_df.loc[dwf_better, "mm_proximity_maker"] = "DWF Labs"
    all_df.loc[dwf_better, "mm_proximity_note"] = all_df.loc[dwf_better, "dwf_labs_portfolio_note"].fillna(
        "DWF Labs CoinGecko portfolio member."
    )
    all_df.loc[dwf_better, "mm_proximity_source"] = DWF_LABS_CATEGORY_URL
    return all_df


def _empty_external_crime_columns(all_df: pd.DataFrame) -> pd.DataFrame:
    missing = [col for col in EXTERNAL_CRIME_COLUMNS if col not in all_df.columns]
    if not missing:
        return all_df

    defaults: dict[str, Any] = {}
    for col in missing:
        if col in EXTERNAL_CRIME_BOOL_COLUMNS:
            defaults[col] = False
        elif col in EXTERNAL_CRIME_TEXT_COLUMNS:
            defaults[col] = ""
        else:
            defaults[col] = float("nan")

    # Add the sparse external-market schema in one concat to avoid fragmenting the
    # scan dataframe when public enrichment is skipped or only partly available.
    return pd.concat([all_df, pd.DataFrame(defaults, index=all_df.index)], axis=1).copy()


def _apply_external_crime_metrics(all_df: pd.DataFrame, crime_symbols: set[str]) -> pd.DataFrame:
    all_df = _empty_external_crime_columns(all_df)
    if all_df.empty or not crime_symbols:
        return all_df

    target_df = all_df[all_df["symbol"].isin(crime_symbols)].copy()
    base_assets = tuple(
        sorted(
            {
                str(base)
                for base in target_df["normalized_base_asset"].dropna().astype(str)
                if str(base).strip()
            }
        )
    )
    if not base_assets:
        return all_df

    external_df = load_external_crime_metrics_cached(base_assets)
    if external_df.empty or "normalized_base_asset" not in external_df.columns:
        return all_df

    merge_cols = ["normalized_base_asset", *[col for col in EXTERNAL_CRIME_COLUMNS if col in external_df.columns]]
    merged = target_df[["symbol", "normalized_base_asset", "quote_volume_24h"]].merge(
        external_df[merge_cols],
        on="normalized_base_asset",
        how="left",
    )
    merged = merged.set_index("symbol")
    for col in EXTERNAL_CRIME_COLUMNS:
        if col in merged.columns:
            mapped = all_df["symbol"].map(merged[col])
            if col in EXTERNAL_CRIME_BOOL_COLUMNS:
                mapped = mapped.where(mapped.notna(), False).astype(bool)
            elif col in EXTERNAL_CRIME_TEXT_COLUMNS:
                mapped = mapped.fillna("").astype(str)
            else:
                mapped = pd.to_numeric(mapped, errors="coerce")
            all_df.loc[all_df["symbol"].isin(merged.index), col] = mapped

    all_df = _apply_dwf_mm_proximity_signal(all_df)

    coinbase_direct = pd.to_numeric(all_df["coinbase_spot_quote_volume_24h"], errors="coerce")
    coinbase_cg = pd.to_numeric(all_df["coingecko_coinbase_volume_24h"], errors="coerce")
    coinbase = pd.concat([coinbase_direct, coinbase_cg], axis=1).max(axis=1)
    all_df["coinbase_spot_quote_volume_24h"] = coinbase
    binance_spot = pd.to_numeric(all_df["binance_spot_quote_volume_24h"], errors="coerce")
    coingecko_total = pd.to_numeric(all_df["coingecko_total_volume_24h"], errors="coerce")
    direct_sum = coinbase.fillna(0.0) + binance_spot.fillna(0.0)
    has_any_spot = coinbase.notna() | binance_spot.notna() | coingecko_total.notna()
    all_df["spot_external_quote_volume_24h"] = pd.concat([direct_sum, coingecko_total], axis=1).max(axis=1).where(
        has_any_spot,
        other=float("nan"),
    )

    perp_volume = pd.to_numeric(all_df["quote_volume_24h"], errors="coerce")
    valid_perp = perp_volume > 0
    all_df["spot_to_perp_volume_pct"] = (
        all_df["spot_external_quote_volume_24h"] / perp_volume * 100.0
    ).where(valid_perp, other=float("nan"))
    all_df["coinbase_to_perp_volume_pct"] = (coinbase / perp_volume * 100.0).where(valid_perp, other=float("nan"))
    cb_depth = pd.to_numeric(all_df["coinbase_total_depth_2pct_usd"], errors="coerce")
    all_df["coinbase_depth_to_perp_volume_pct"] = (cb_depth / perp_volume * 100.0).where(
        valid_perp,
        other=float("nan"),
    )
    cex_volume = pd.to_numeric(all_df["coingecko_cex_volume_24h"], errors="coerce")
    dex_volume = pd.to_numeric(all_df["coingecko_dex_volume_24h"], errors="coerce")
    cex_dex_total = cex_volume.fillna(0.0) + dex_volume.fillna(0.0)
    has_cex_dex_total = cex_dex_total > 0
    all_df["cex_volume_share_pct"] = (cex_volume / cex_dex_total * 100.0).where(
        has_cex_dex_total,
        other=float("nan"),
    )
    dex_denominator = dex_volume.where(dex_volume > 0)
    all_df["cex_to_dex_volume_ratio"] = (cex_volume / dex_denominator).where(
        cex_volume > 0,
        other=float("nan"),
    )
    all_df.loc[(cex_volume > 0) & ~(dex_volume > 0), "cex_to_dex_volume_ratio"] = 999.0
    ratio_score = _log_ratio_score(all_df["cex_to_dex_volume_ratio"], low=2.0, high=80.0)
    cex_share_score = _linear_score(all_df["cex_volume_share_pct"], low=60.0, high=98.0)
    all_df["cex_dex_volume_ratio_score"] = (
        ratio_score * 0.72
        + cex_share_score * 0.28
    ).where(has_cex_dex_total, other=0.0).clip(lower=0.0, upper=100.0)

    market_cap = pd.to_numeric(all_df["market_cap_usd"], errors="coerce")
    valid_market_cap = market_cap > 0
    all_df["spot_volume_to_mcap_pct"] = (
        all_df["spot_external_quote_volume_24h"] / market_cap * 100.0
    ).where(valid_market_cap, other=float("nan"))
    all_df["perp_volume_to_mcap_pct"] = (perp_volume / market_cap * 100.0).where(
        valid_market_cap,
        other=float("nan"),
    )
    oi_value = pd.to_numeric(all_df["oi_value_usdt"], errors="coerce")
    all_df["oi_to_market_cap_pct"] = (oi_value / market_cap * 100.0).where(valid_market_cap, other=float("nan"))

    top10 = pd.to_numeric(all_df["top10_holder_pct"], errors="coerce")
    owner = pd.to_numeric(all_df["owner_holder_pct"], errors="coerce")
    creator = pd.to_numeric(all_df["creator_holder_pct"], errors="coerce")
    all_df["holder_concentration_score"] = pd.concat(
        [
            top10.clip(lower=0.0, upper=100.0),
            owner.clip(lower=0.0, upper=100.0) * 1.5,
            creator.clip(lower=0.0, upper=100.0) * 1.5,
        ],
        axis=1,
    ).max(axis=1)
    all_df["venue_hhi_score"] = _linear_score(all_df["venue_hhi"], low=900.0, high=4_500.0)
    all_df["binance_bitget_gate_share_score"] = _linear_score(
        all_df["binance_bitget_gate_share_pct"],
        low=20.0,
        high=85.0,
    )
    bitget_share = pd.to_numeric(
        all_df.get("bitget_volume_share_pct", pd.Series(0.0, index=all_df.index)),
        errors="coerce",
    ).fillna(0.0)
    gate_share = pd.to_numeric(
        all_df.get("gate_volume_share_pct", pd.Series(0.0, index=all_df.index)),
        errors="coerce",
    ).fillna(0.0)
    all_df["bitget_or_gate_venue_flag"] = bitget_share.gt(0.0) | gate_share.gt(0.0)
    all_df["emfx_lane_score"] = (
        _linear_score(all_df["emfx_volume_share_pct"], low=4.0, high=40.0) * 0.62
        + _linear_score(all_df["krw_volume_share_pct"], low=3.0, high=35.0) * 0.23
        + _linear_score(all_df["try_volume_share_pct"], low=1.0, high=20.0) * 0.15
    ).clip(lower=0.0, upper=100.0)
    top_venue_share = pd.to_numeric(all_df["top_venue_volume_share_pct"], errors="coerce")
    top3_share = pd.to_numeric(all_df["top3_venue_volume_share_pct"], errors="coerce")
    all_df["venue_concentration_score"] = pd.concat(
        [
            top_venue_share,
            top3_share * 0.75,
            all_df["venue_hhi_score"],
            all_df["binance_bitget_gate_share_score"],
        ],
        axis=1,
    ).max(axis=1)
    return all_df


def _apply_ath_runway(all_df: pd.DataFrame) -> pd.DataFrame:
    if all_df.empty:
        return all_df

    for col in ("coingecko_ath_usd", "ath_scanned", "last_price", "upside_to_ath_pct"):
        if col not in all_df.columns:
            all_df[col] = float("nan")

    cg_ath = pd.to_numeric(all_df["coingecko_ath_usd"], errors="coerce")
    scanned_ath = pd.to_numeric(all_df["ath_scanned"], errors="coerce")
    last_price = pd.to_numeric(all_df["last_price"], errors="coerce")

    valid_cg = (cg_ath > 0) & (last_price > 0)
    valid_scanned = (scanned_ath > 0) & (last_price > 0)
    ath_price = cg_ath.where(valid_cg, other=scanned_ath.where(valid_scanned, other=float("nan")))
    ath_source = pd.Series("Unavailable", index=all_df.index, dtype="object")
    ath_source = ath_source.where(~valid_scanned, other="Binance scanned history")
    ath_source = ath_source.where(~valid_cg, other="CoinGecko")

    multiple = (ath_price / last_price).where((ath_price > 0) & (last_price > 0), other=float("nan"))
    upside_pct = ((multiple - 1.0) * 100.0).where(multiple.notna(), other=float("nan"))
    all_df["ath_price"] = ath_price
    all_df["ath_multiple"] = multiple
    all_df["ath_upside_pct"] = upside_pct
    all_df["ath_source"] = ath_source
    all_df["ath_runway_20x_flag"] = multiple >= 20.0

    # Prefer external lifetime ATH for runway scoring when available, but keep the
    # Binance scanned-history fallback so fast scans still remain useful.
    all_df["upside_to_ath_pct"] = upside_pct.where(upside_pct.notna(), other=all_df["upside_to_ath_pct"])
    return all_df


def _crypto_perp_ticker(ticker: pd.DataFrame, symbol_meta: dict[str, Any]) -> pd.DataFrame:
    if ticker.empty:
        return ticker.copy()
    market_types = ticker["symbol"].map(
        lambda symbol: str(getattr(symbol_meta.get(str(symbol).upper()), "underlying_type", "") or "").upper()
    )
    return (
        ticker[~market_types.isin(TRADFI_ALWAYS_INCLUDE_TYPES)]
        .sort_values(["quoteVolume", "symbol"], ascending=[False, True])
        .reset_index(drop=True)
    )


def _all_crypto_short_account_frame(client: BinanceFuturesPublic) -> pd.DataFrame:
    crypto_symbols = sorted(
        item.symbol
        for item in client.perpetual_usdt_symbols()
        if item.symbol and str(item.underlying_type or "").upper() not in TRADFI_ALWAYS_INCLUDE_TYPES
    )
    rows: list[dict[str, Any]] = []
    for symbol in crypto_symbols:
        ratio_rows = _safe_public_fetch(
            [],
            client.global_long_short_account_ratio,
            symbol,
            period=LONG_SHORT_RATIO_PERIOD,
            limit=1,
        )
        latest = ratio_rows[-1] if ratio_rows else {}
        rows.append(
            {
                "symbol": symbol,
                "short_account_pct": _share_to_pct(latest.get("shortAccount")),
            }
        )

    frame = pd.DataFrame(rows, columns=["symbol", "short_account_pct"])
    if frame.empty:
        return frame
    frame["short_account_pct"] = pd.to_numeric(frame["short_account_pct"], errors="coerce")
    return frame.sort_values(
        ["short_account_pct", "symbol"],
        ascending=[False, True],
        na_position="last",
    ).reset_index(drop=True)


@_cache_data(ttl=60)
def run_scan(refresh_nonce: int, scan_mode: str = "Fast") -> tuple[pd.DataFrame, pd.DataFrame]:
    _ = (refresh_nonce, scan_mode)
    normalized_scan_mode = str(scan_mode).strip().lower()
    all_crypto_scan = normalized_scan_mode in {
        "all short account %",
        "all short accounts",
        "all crypto perps",
        "all crypto",
        "all perps",
        "full universe",
    }
    full_ath_scan = normalized_scan_mode in {"full ath", "full ath runway", "ath"}
    deep_scan = normalized_scan_mode in {"deep", "full ath", "full ath runway", "ath"}
    if all_crypto_scan:
        census_client = BinanceFuturesPublic(
            base_url=BASE_URL,
            timeout=TIMEOUT,
            requests_per_second=ALL_CRYPTO_SHORTS_REQUESTS_PER_SECOND,
            retries=RETRIES,
        )
        return pd.DataFrame(), _all_crypto_short_account_frame(census_client)

    scan_max_symbols = FULL_ATH_MAX_SYMBOLS_TO_SCAN if full_ath_scan else MAX_SYMBOLS_TO_SCAN if deep_scan else FAST_MAX_SYMBOLS
    crime_symbol_limit = CRIME_SYMBOLS_TO_SCAN if deep_scan else 0
    modeled_funding_enabled = ENABLE_MODELED_FUNDING and deep_scan and not full_ath_scan
    client = _client()
    symbol_meta = {s.symbol: s for s in client.perpetual_usdt_symbols()}
    symbols = {symbol: meta.base_asset for symbol, meta in symbol_meta.items()}
    tradfi_symbols = {
        symbol for symbol, meta in symbol_meta.items() if meta.underlying_type in TRADFI_ALWAYS_INCLUDE_TYPES
    }
    ticker = pd.DataFrame(client.ticker_24hr())
    if ticker.empty:
        return pd.DataFrame(), pd.DataFrame()

    ticker["symbol"] = ticker["symbol"].astype(str).str.upper()
    ticker = ticker[ticker["symbol"].isin(symbols.keys())].copy()
    if not INCLUDE_TRADFI_BREAKOUTS:
        ticker = ticker[
            ticker["symbol"].map(
                lambda symbol: (symbol_meta.get(str(symbol)).underlying_type if symbol_meta.get(str(symbol)) else "")
                not in TRADFI_ALWAYS_INCLUDE_TYPES
            )
        ].copy()

    for col in ("lastPrice", "highPrice", "lowPrice", "quoteVolume", "priceChangePercent", "count"):
        ticker[col] = pd.to_numeric(ticker.get(col), errors="coerce")

    ticker = ticker.dropna(subset=["lastPrice", "highPrice", "lowPrice", "quoteVolume"])
    ticker["base_asset"] = ticker["symbol"].map(symbols)
    ticker["normalized_base_asset"] = ticker["base_asset"].map(normalize_base_asset)
    ticker["crime_excluded_major"] = ticker["normalized_base_asset"].isin(CRIME_EXCLUDED_BASE_ASSETS)
    cmc_movers_df = _load_cmc_movers_for_scan(deep_scan)
    if cmc_movers_df.empty:
        ticker["cmc_mover_seed_score"] = 0.0
    else:
        cmc_seed = cmc_movers_df.set_index("normalized_base_asset")["cmc_mover_score"]
        ticker["cmc_mover_seed_score"] = (
            ticker["normalized_base_asset"].map(cmc_seed).fillna(0.0).astype("float64")
        )
    dwf_portfolio_df = load_dwf_labs_portfolio_cached() if deep_scan else pd.DataFrame()
    if dwf_portfolio_df.empty:
        ticker["dwf_labs_portfolio_seed"] = False
        ticker["dwf_labs_portfolio_score_seed"] = 0.0
        ticker["dwf_labs_portfolio_rank_seed"] = float("nan")
        ticker["dwf_labs_portfolio_note_seed"] = ""
    else:
        dwf_index = dwf_portfolio_df.set_index("normalized_base_asset")
        ticker["dwf_labs_portfolio_seed"] = ticker["normalized_base_asset"].isin(dwf_index.index)
        ticker["dwf_labs_portfolio_score_seed"] = (
            ticker["normalized_base_asset"]
            .map(dwf_index["dwf_labs_portfolio_score"])
            .fillna(0.0)
            .astype("float64")
        )
        ticker["dwf_labs_portfolio_rank_seed"] = pd.to_numeric(
            ticker["normalized_base_asset"].map(dwf_index["dwf_labs_portfolio_rank"]),
            errors="coerce",
        )
        ticker["dwf_labs_portfolio_note_seed"] = (
            ticker["normalized_base_asset"].map(dwf_index["dwf_labs_portfolio_note"]).fillna("").astype(str)
        )
    coinbase_spot_bases = load_coinbase_spot_bases_cached() if deep_scan else set()
    ticker["coinbase_spot_seed"] = ticker["normalized_base_asset"].isin(coinbase_spot_bases)
    ticker["range_24h_pct"] = (ticker["highPrice"] / ticker["lowPrice"] - 1.0) * 100.0
    ticker["crime_seed_score"] = (
        _percentile_score(ticker["priceChangePercent"], positive_only=True) * 0.42
        + _percentile_score(ticker["range_24h_pct"], positive_only=True) * 0.22
        + _percentile_score(ticker["quoteVolume"], positive_only=True) * 0.18
        + _percentile_score(ticker["count"], positive_only=True) * 0.10
        + _percentile_score(ticker["quoteVolume"], ascending=False, positive_only=True) * 0.08
        + ticker["cmc_mover_seed_score"].fillna(0.0) * 0.16
        + ticker["dwf_labs_portfolio_score_seed"].fillna(0.0) * 0.12
        + ticker["coinbase_spot_seed"].astype(float) * 12.0
    )
    ticker["convexity_seed_score"] = (
        _band_score(ticker["priceChangePercent"], low=-8.0, sweet_low=2.0, sweet_high=45.0, high=120.0) * 0.30
        + _linear_score(ticker["range_24h_pct"], low=4.0, high=55.0) * 0.12
        + _percentile_score(ticker["quoteVolume"], positive_only=True) * 0.13
        + _percentile_score(ticker["count"], positive_only=True) * 0.13
        + _percentile_score(ticker["quoteVolume"], ascending=False, positive_only=True) * 0.08
        + ticker["cmc_mover_seed_score"].fillna(0.0) * 0.13
        + ticker["dwf_labs_portfolio_score_seed"].fillna(0.0) * 0.16
        + ticker["coinbase_spot_seed"].astype(float) * 11.0
    ).clip(lower=0.0, upper=100.0)
    ticker = ticker.sort_values("quoteVolume", ascending=False)
    available_crypto_ticker = _crypto_perp_ticker(ticker, symbol_meta)
    available_crypto_perp_count = len(available_crypto_ticker)

    top_ticker = ticker.head(scan_max_symbols)
    crime_pool = ticker[
        (~ticker["crime_excluded_major"])
        & (ticker["quoteVolume"] >= CRIME_MIN_QUOTE_VOLUME)
        & (
            (ticker["priceChangePercent"].fillna(0.0) > 0.0)
            | ticker["coinbase_spot_seed"]
            | (ticker["cmc_mover_seed_score"] >= 35.0)
            | ticker["dwf_labs_portfolio_seed"]
        )
    ].copy()
    crime_ticker = crime_pool.sort_values(
        ["crime_seed_score", "priceChangePercent", "quoteVolume", "symbol"],
        ascending=[False, False, False, True],
    ).head(crime_symbol_limit)
    preconvex_ticker = ticker[
        (~ticker["crime_excluded_major"])
        & (ticker["quoteVolume"] >= CRIME_MIN_QUOTE_VOLUME * 0.40)
        & (
            (ticker["convexity_seed_score"] >= 45.0)
            | ticker["coinbase_spot_seed"]
            | (ticker["cmc_mover_seed_score"] >= 35.0)
            | ticker["dwf_labs_portfolio_seed"]
        )
    ].sort_values(
        ["convexity_seed_score", "priceChangePercent", "quoteVolume", "symbol"],
        ascending=[False, False, False, True],
    ).head(max(0, PRECONVEX_SYMBOLS_TO_SCAN))
    forced_crime_ticker = ticker[
        ticker["symbol"].isin(CRIME_FORCE_SYMBOLS)
        & (~ticker["crime_excluded_major"])
    ].copy()
    dwf_ticker = ticker[
        ticker["dwf_labs_portfolio_seed"]
        & (~ticker["crime_excluded_major"])
    ].sort_values(
        ["convexity_seed_score", "crime_seed_score", "priceChangePercent", "quoteVolume", "dwf_labs_portfolio_score_seed", "symbol"],
        ascending=[False, False, False, False, False, True],
    ).head(max(0, DWF_PORTFOLIO_SYMBOLS_TO_SCAN))
    ath_runway_budget = (
        max(0, FULL_ATH_MAX_SYMBOLS_TO_SCAN)
        if full_ath_scan
        else max(0, min(ATH_RUNWAY_SYMBOLS_TO_SCAN, DEEP_ATH_SYMBOLS_TO_SCAN))
    )
    ath_external_budget = (
        max(0, FULL_ATH_EXTERNAL_SYMBOLS_TO_SCAN)
        if full_ath_scan
        else max(0, min(ATH_RUNWAY_SYMBOLS_TO_SCAN, DEEP_ATH_SYMBOLS_TO_SCAN))
    )
    ath_runway_ticker = ticker[(~ticker["crime_excluded_major"])].sort_values(
        ["convexity_seed_score", "quoteVolume", "symbol"],
        ascending=[False, False, True],
    ).head(ath_runway_budget)
    ath_external_ticker = ath_runway_ticker.head(ath_external_budget)
    cmc_crime_ticker = ticker[
        (ticker["cmc_mover_seed_score"] >= 45.0)
        & (~ticker["crime_excluded_major"])
    ].sort_values(
        ["cmc_mover_seed_score", "priceChangePercent", "quoteVolume", "symbol"],
        ascending=[False, False, False, True],
    ).head(max(0, CMC_MOVER_SYMBOLS_TO_SCAN))
    if not deep_scan:
        crime_ticker = ticker.iloc[0:0].copy()
        preconvex_ticker = ticker.iloc[0:0].copy()
        forced_crime_ticker = ticker.iloc[0:0].copy()
        dwf_ticker = ticker.iloc[0:0].copy()
        ath_runway_ticker = ticker.iloc[0:0].copy()
        ath_external_ticker = ticker.iloc[0:0].copy()
        cmc_crime_ticker = ticker.iloc[0:0].copy()
    forced_symbols = {
        symbol
        for symbol in set(ALWAYS_SCAN_SYMBOLS)
        if symbol in symbol_meta and (INCLUDE_TRADFI_BREAKOUTS or symbol_meta[symbol].underlying_type not in TRADFI_ALWAYS_INCLUDE_TYPES)
    }
    if BINANCE_API_KEY and BINANCE_API_SECRET:
        signed_client = _client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)
        open_positions = _safe_public_fetch([], signed_client.position_information_v3, None)
        forced_symbols |= {
            str(position.get("symbol") or "").upper()
            for position in open_positions
            if abs(_float_nan(position.get("positionAmt"))) > 0
            and str(position.get("symbol") or "").upper() in symbol_meta
            and symbol_meta[str(position.get("symbol") or "").upper()].underlying_type not in TRADFI_ALWAYS_INCLUDE_TYPES
        }
    if INCLUDE_TRADFI_BREAKOUTS:
        forced_symbols |= tradfi_symbols
    forced_ticker = ticker[ticker["symbol"].isin(forced_symbols)]
    selected_ticker = (
        pd.concat(
            [
                top_ticker,
                crime_ticker,
                preconvex_ticker,
                ath_runway_ticker,
                cmc_crime_ticker,
                dwf_ticker,
                forced_crime_ticker,
                forced_ticker,
            ],
            ignore_index=True,
        )
        .drop_duplicates(subset=["symbol"], keep="first")
    )
    if full_ath_scan:
        forced_full_mask = selected_ticker["symbol"].isin(set(CRIME_FORCE_SYMBOLS) | set(forced_symbols))
        forced_selected = selected_ticker[forced_full_mask].copy().head(max(0, FULL_ATH_MAX_SYMBOLS_TO_SCAN))
        remaining_budget = max(0, FULL_ATH_MAX_SYMBOLS_TO_SCAN - len(forced_selected))
        ranked_selected = selected_ticker[~forced_full_mask].sort_values(
            ["convexity_seed_score", "crime_seed_score", "dwf_labs_portfolio_score_seed", "quoteVolume", "symbol"],
            ascending=[False, False, False, False, True],
        ).head(remaining_budget)
        ticker = (
            pd.concat([forced_selected, ranked_selected], ignore_index=True)
            .drop_duplicates(subset=["symbol"], keep="first")
            .sort_values(["convexity_seed_score", "dwf_labs_portfolio_score_seed", "quoteVolume", "symbol"], ascending=[False, False, False, True])
            .reset_index(drop=True)
        )
    elif deep_scan:
        forced_deep_mask = selected_ticker["symbol"].isin(set(CRIME_FORCE_SYMBOLS) | set(forced_symbols))
        forced_selected = selected_ticker[forced_deep_mask].copy().head(max(0, DEEP_MAX_TOTAL_SYMBOLS_TO_SCAN))
        remaining_budget = max(0, DEEP_MAX_TOTAL_SYMBOLS_TO_SCAN - len(forced_selected))
        ranked_selected = selected_ticker[~forced_deep_mask].sort_values(
            ["crime_seed_score", "convexity_seed_score", "dwf_labs_portfolio_score_seed", "quoteVolume", "symbol"],
            ascending=[False, False, False, False, True],
        ).head(remaining_budget)
        ticker = (
            pd.concat([forced_selected, ranked_selected], ignore_index=True)
            .drop_duplicates(subset=["symbol"], keep="first")
            .sort_values(["crime_seed_score", "convexity_seed_score", "dwf_labs_portfolio_score_seed", "quoteVolume", "symbol"], ascending=[False, False, False, False, True])
            .reset_index(drop=True)
        )
    else:
        ticker = (
            selected_ticker.sort_values("quoteVolume", ascending=False)
            .reset_index(drop=True)
        )
    crime_symbols = set(
        pd.concat([crime_ticker, preconvex_ticker, cmc_crime_ticker, dwf_ticker, forced_crime_ticker], ignore_index=True)
        .drop_duplicates(subset=["symbol"], keep="first")
        .head(max(0, crime_symbol_limit + len(preconvex_ticker) + len(cmc_crime_ticker) + len(dwf_ticker) + len(forced_crime_ticker)))
        ["symbol"]
        .astype(str)
    )
    external_candidates = (
        pd.concat(
            [
                crime_ticker.head(max(0, CRIME_EXTERNAL_SYMBOLS_TO_SCAN)),
                preconvex_ticker.head(max(0, PRECONVEX_SYMBOLS_TO_SCAN)),
                ath_external_ticker,
                cmc_crime_ticker.head(max(0, CMC_MOVER_SYMBOLS_TO_SCAN)),
                dwf_ticker.head(max(0, DWF_PORTFOLIO_SYMBOLS_TO_SCAN)),
                forced_crime_ticker,
            ],
            ignore_index=True,
        )
        .drop_duplicates(subset=["symbol"], keep="first")
    )
    if full_ath_scan:
        forced_external_mask = external_candidates["symbol"].isin(set(CRIME_FORCE_SYMBOLS) | set(forced_symbols))
        forced_external = external_candidates[forced_external_mask].copy().head(max(0, FULL_ATH_EXTERNAL_SYMBOLS_TO_SCAN))
        external_remaining = max(0, FULL_ATH_EXTERNAL_SYMBOLS_TO_SCAN - len(forced_external))
        external_candidates = pd.concat(
            [
                forced_external,
                external_candidates[~forced_external_mask].head(external_remaining),
            ],
            ignore_index=True,
        ).drop_duplicates(subset=["symbol"], keep="first")
    elif deep_scan:
        forced_external_mask = external_candidates["symbol"].isin(set(CRIME_FORCE_SYMBOLS) | set(forced_symbols))
        forced_external = external_candidates[forced_external_mask].copy().head(max(0, DEEP_EXTERNAL_SYMBOLS_TO_SCAN))
        external_remaining = max(0, DEEP_EXTERNAL_SYMBOLS_TO_SCAN - len(forced_external))
        external_candidates = pd.concat(
            [
                forced_external,
                external_candidates[~forced_external_mask].head(external_remaining),
            ],
            ignore_index=True,
        ).drop_duplicates(subset=["symbol"], keep="first")
    external_crime_symbols = set(external_candidates["symbol"].astype(str))

    rows: list[BreakoutRow] = []
    now_ms = int(_utc_now().timestamp() * 1000)
    btc_klines = _safe_public_fetch([], client.klines_1d, "BTCUSDT", limit=DAILY_KLINE_LIMIT)
    websocket_snapshots = (
        _safe_public_fetch(
            {},
            client.mark_price_stream_snapshot,
            ticker["symbol"].astype(str).str.upper().tolist(),
            sample_seconds=FUNDING_STREAM_SAMPLE_SECONDS,
            update_speed="1s",
        )
        if modeled_funding_enabled
        else {}
    )
    funding_info_by_symbol = {
        str(item.get("symbol", "")).upper(): item
        for item in _safe_public_fetch([], client.funding_info)
        if str(item.get("symbol", "")).upper() in symbols
    }
    funding_by_symbol = {
        str(item.get("symbol", "")).upper(): item
        for item in _safe_public_fetch([], client.mark_price)
        if str(item.get("symbol", "")).upper() in symbols
    }
    for _, t in ticker.iterrows():
        symbol = str(t["symbol"])
        compute_crime_detail = symbol in crime_symbols
        klines = _safe_public_fetch([], client.klines_1d, symbol, limit=DAILY_KLINE_LIMIT)
        hourly_klines = _safe_public_fetch(
            [], client.klines, symbol, interval="1h", limit=max(10, CRIME_HOURLY_LOOKBACK)
        )
        levels = levels_from_klines(klines)
        recent_pump = recent_pump_stats_from_klines(klines, lookback_days=NO_LARGE_PUMP_LOOKBACK_DAYS)
        corr_to_btc, corr_window_days = _latest_btc_correlation(symbol, klines, btc_klines)
        funding_snapshot = funding_by_symbol.get(symbol, {})
        funding_info_snapshot = funding_info_by_symbol.get(symbol, {})
        interval_hours = _coerce_funding_interval_hours(funding_info_snapshot.get("fundingIntervalHours"))
        cap_rate = None
        floor_rate = None
        if "adjustedFundingRateCap" in funding_info_snapshot:
            try:
                cap_rate = float(funding_info_snapshot.get("adjustedFundingRateCap"))
            except Exception:
                cap_rate = None
        if "adjustedFundingRateFloor" in funding_info_snapshot:
            try:
                floor_rate = float(funding_info_snapshot.get("adjustedFundingRateFloor"))
            except Exception:
                floor_rate = None

        funding_pct = _funding_rate_to_pct(funding_snapshot.get("lastFundingRate"))
        annualized_funding_pct = _annualized_funding_pct(
            funding_snapshot.get("lastFundingRate"),
            interval_hours=interval_hours,
        )
        try:
            next_funding_ms = int(float(funding_snapshot.get("nextFundingTime")))
        except Exception:
            next_funding_ms = now_ms + interval_hours * 60 * 60 * 1000
        current_window_start_ms = max(0, next_funding_ms - interval_hours * 60 * 60 * 1000)
        elapsed_ms = min(max(0, now_ms - current_window_start_ms), interval_hours * 60 * 60 * 1000)
        window_elapsed_pct = (
            elapsed_ms / (interval_hours * 60 * 60 * 1000) * 100.0 if interval_hours > 0 else float("nan")
        )
        funding_history = _safe_public_fetch(
            [],
            client.funding_rate_history,
            symbol,
            limit=max(3, FUNDING_BACKTEST_WINDOWS if modeled_funding_enabled else 3),
        )
        last_settled_funding_pct = (
            _funding_rate_to_pct(funding_history[-1].get("fundingRate"))
            if funding_history
            else float("nan")
        )
        prior_settled_funding_pct = (
            _funding_rate_to_pct(funding_history[-2].get("fundingRate"))
            if len(funding_history) >= 2
            else float("nan")
        )
        if modeled_funding_enabled:
            history_window_start_ms = current_window_start_ms
            if funding_history:
                try:
                    history_window_start_ms = min(
                        current_window_start_ms,
                        int(float(funding_history[0].get("fundingTime"))) - interval_hours * 60 * 60 * 1000,
                    )
                except Exception:
                    history_window_start_ms = current_window_start_ms

            premium_lookback_ms = max(5 * 60 * 1000, now_ms - history_window_start_ms)
            premium_interval = _select_premium_kline_interval(premium_lookback_ms)
            premium_limit = max(
                50,
                min(1500, int(math.ceil(premium_lookback_ms / _kline_interval_ms(premium_interval))) + 5),
            )
            premium_klines = _safe_public_fetch(
                [],
                client.premium_index_klines,
                symbol,
                interval=premium_interval,
                limit=premium_limit,
                start_time=history_window_start_ms,
                end_time=now_ms,
            )
            funding_model = _estimate_next_funding_rate(
                funding_snapshot=funding_snapshot,
                interval_hours=interval_hours,
                cap_rate=cap_rate,
                floor_rate=floor_rate,
                funding_history=funding_history,
                premium_klines=premium_klines,
                websocket_snapshot=websocket_snapshots.get(symbol),
            )
            predicted_funding_rate = funding_model["predicted_rate"]
            predicted_funding_pct = _funding_rate_to_pct(predicted_funding_rate)
            predicted_annualized_funding_pct = _annualized_funding_pct(
                predicted_funding_rate,
                interval_hours=interval_hours,
            )
            predicted_low_pct = _funding_rate_to_pct(funding_model["predicted_low_rate"])
            predicted_high_pct = _funding_rate_to_pct(funding_model["predicted_high_rate"])
            predicted_band_pct = _funding_rate_to_pct(funding_model["predicted_band_rate"])
            predicted_mae_pct = _funding_rate_to_pct(funding_model["predicted_mae_rate"])
            funding_window_elapsed_pct = funding_model["window_elapsed_pct"]
            predicted_backtest_count = int(funding_model["backtest_count"])
            latest_premium_pct = _funding_rate_to_pct(funding_model["latest_premium_rate"])
        else:
            predicted_funding_pct = funding_pct
            predicted_annualized_funding_pct = annualized_funding_pct
            predicted_low_pct = float("nan")
            predicted_high_pct = float("nan")
            predicted_band_pct = float("nan")
            predicted_mae_pct = float("nan")
            funding_window_elapsed_pct = window_elapsed_pct
            predicted_backtest_count = 0
            latest_premium_pct = _funding_rate_to_pct(_latest_premium_index_rate(funding_snapshot))
        effective_funding_pct = predicted_funding_pct if not math.isnan(predicted_funding_pct) else funding_pct
        funding_flip_delta_pct = (
            effective_funding_pct - last_settled_funding_pct
            if not math.isnan(effective_funding_pct) and not math.isnan(last_settled_funding_pct)
            else float("nan")
        )
        long_short_rows = _safe_public_fetch(
            [],
            client.global_long_short_account_ratio,
            symbol,
            period=LONG_SHORT_RATIO_PERIOD,
            limit=LONG_SHORT_RATIO_HISTORY_LIMIT,
        )
        long_short_snapshot = long_short_rows[-1] if long_short_rows else {}
        try:
            long_short_account_ratio = float(long_short_snapshot.get("longShortRatio"))
        except Exception:
            long_short_account_ratio = float("nan")
        long_account_pct = _share_to_pct(long_short_snapshot.get("longAccount"))
        short_account_pct = _share_to_pct(long_short_snapshot.get("shortAccount"))
        short_account_history_stats = _short_account_history_stats(long_short_rows)
        hourly_stats = _hourly_market_stats(hourly_klines)

        oi_rows = (
            _safe_public_fetch(
                [],
                client.open_interest_statistics,
                symbol,
                period=CRIME_PUMP_PERIOD,
                limit=2,
            )
            if compute_crime_detail
            else []
        )
        latest_oi_row = oi_rows[-1] if oi_rows else {}
        previous_oi_row = oi_rows[-2] if len(oi_rows) >= 2 else {}
        oi_value_usdt = _float_nan(latest_oi_row.get("sumOpenInterestValue"))
        oi_delta_pct = _pct_change(
            latest_oi_row.get("sumOpenInterestValue"),
            previous_oi_row.get("sumOpenInterestValue"),
        )

        taker_rows = (
            _safe_public_fetch(
                [],
                client.taker_buy_sell_volume,
                symbol,
                period=CRIME_PUMP_PERIOD,
                limit=1,
            )
            if compute_crime_detail
            else []
        )
        taker_snapshot = taker_rows[-1] if taker_rows else {}
        taker_buy_sell_ratio = _float_nan(taker_snapshot.get("buySellRatio"))
        taker_buy_vol = _float_nan(taker_snapshot.get("buyVol"))
        taker_sell_vol = _float_nan(taker_snapshot.get("sellVol"))
        taker_total_vol = taker_buy_vol + taker_sell_vol
        if math.isnan(taker_buy_vol) or math.isnan(taker_sell_vol) or taker_total_vol <= 0:
            taker_buy_share_pct = float("nan")
        else:
            taker_buy_share_pct = taker_buy_vol / taker_total_vol * 100.0

        top_position_rows = (
            _safe_public_fetch(
                [],
                client.top_trader_long_short_position_ratio,
                symbol,
                period=CRIME_PUMP_PERIOD,
                limit=1,
            )
            if compute_crime_detail
            else []
        )
        top_position_snapshot = top_position_rows[-1] if top_position_rows else {}
        top_trader_position_ratio = _float_nan(top_position_snapshot.get("longShortRatio"))
        top_trader_long_position_pct = _share_to_pct(top_position_snapshot.get("longAccount"))
        top_trader_short_position_pct = _share_to_pct(top_position_snapshot.get("shortAccount"))

        top_account_rows = (
            _safe_public_fetch(
                [],
                client.top_trader_long_short_account_ratio,
                symbol,
                period=CRIME_PUMP_PERIOD,
                limit=1,
            )
            if compute_crime_detail
            else []
        )
        top_account_snapshot = top_account_rows[-1] if top_account_rows else {}
        top_trader_account_ratio = _float_nan(top_account_snapshot.get("longShortRatio"))
        top_trader_long_account_pct = _share_to_pct(top_account_snapshot.get("longAccount"))
        top_trader_short_account_pct = _share_to_pct(top_account_snapshot.get("shortAccount"))

        if math.isnan(long_account_pct) or math.isnan(top_trader_long_position_pct):
            crowd_top_position_divergence_pct = float("nan")
        else:
            crowd_top_position_divergence_pct = long_account_pct - top_trader_long_position_pct
        if math.isnan(long_account_pct) or math.isnan(top_trader_long_account_pct):
            crowd_top_account_divergence_pct = float("nan")
        else:
            crowd_top_account_divergence_pct = long_account_pct - top_trader_long_account_pct

        if compute_crime_detail:
            try:
                basis_rows = client.basis(
                    symbol,
                    contract_type="PERPETUAL",
                    period=CRIME_PUMP_PERIOD,
                    limit=1,
                )
                basis_snapshot = basis_rows[-1] if basis_rows else {}
                if basis_snapshot:
                    basis_rate_pct = _funding_rate_to_pct(basis_snapshot.get("basisRate"))
                    basis_usdt = _float_nan(basis_snapshot.get("basis"))
                else:
                    basis_rate_pct, basis_usdt = _basis_from_mark_price_snapshot(funding_snapshot)
            except BinanceHTTPError:
                basis_rate_pct, basis_usdt = _basis_from_mark_price_snapshot(funding_snapshot)
            except Exception:
                basis_rate_pct, basis_usdt = _basis_from_mark_price_snapshot(funding_snapshot)
            depth_snapshot = _safe_public_fetch({}, client.depth, symbol, limit=CRIME_DEPTH_LIMIT)
            depth_stats = _depth_stress(depth_snapshot, float(t["quoteVolume"]))
        else:
            basis_rate_pct, basis_usdt = _basis_from_mark_price_snapshot(funding_snapshot)
            depth_stats = {
                "ask_depth_1pct_usdt": float("nan"),
                "ask_depth_to_24h_volume_pct": float("nan"),
            }
        if math.isnan(oi_value_usdt) or float(t["quoteVolume"]) <= 0:
            oi_to_24h_volume_pct = float("nan")
        else:
            oi_to_24h_volume_pct = oi_value_usdt / float(t["quoteVolume"]) * 100.0

        high_24h = float(t["highPrice"])
        low_24h = float(t["lowPrice"])
        last_price = float(t["lastPrice"])
        quote_volume_24h = float(t["quoteVolume"])
        daily_quote_volume_multiple = _daily_quote_volume_multiple(klines, quote_volume_24h)
        volume_30d = _daily_quote_volume_30d_context(klines, quote_volume_24h)
        anchored_vwap_30d = closed_daily_anchored_vwap_metrics(
            klines,
            last_price=last_price,
            lookback_days=30,
        )
        upside_to_ath_pct = (
            max(0.0, levels.ath_scanned / last_price - 1.0) * 100.0
            if not math.isnan(levels.ath_scanned) and last_price > 0
            else float("nan")
        )
        distance_to_high_5d_pct = _distance_to_level_pct(levels.high_5d, last_price)
        distance_to_high_20d_pct = _distance_to_level_pct(levels.high_20d, last_price)
        distance_to_high_90d_pct = _distance_to_level_pct(levels.high_90d, last_price)
        rows.append(
            BreakoutRow(
                symbol=symbol,
                base_asset=symbols[symbol],
                market_type=symbol_meta[symbol].underlying_type or "CRYPTO",
                binance_perp_universe=True,
                last_price=last_price,
                quote_volume_24h=quote_volume_24h,
                quote_volume_prior_30d_total=float(volume_30d["quote_volume_prior_30d_total"]),
                quote_volume_prior_30d_daily_avg=float(volume_30d["quote_volume_prior_30d_daily_avg"]),
                quote_volume_prior_30d_days=int(volume_30d["quote_volume_prior_30d_days"]),
                quote_volume_24h_vs_prior_30d_avg_ratio=float(volume_30d["quote_volume_24h_vs_prior_30d_avg_ratio"]),
                anchored_vwap_30d=float(anchored_vwap_30d["anchored_vwap_30d"]),
                price_vs_anchored_vwap_30d_pct=float(
                    anchored_vwap_30d["price_vs_anchored_vwap_30d_pct"]
                ),
                anchored_vwap_30d_days=int(anchored_vwap_30d["anchored_vwap_30d_days"]),
                history_days=max(0, len(klines) - 1),
                recent_max_pump_60d_pct=recent_pump.max_pump_pct,
                recent_pump_60d_days=recent_pump.used_days,
                no_large_pump_60d_flag=(
                    recent_pump.used_days >= NO_LARGE_PUMP_LOOKBACK_DAYS
                    and not math.isnan(recent_pump.max_pump_pct)
                    and recent_pump.max_pump_pct < NO_LARGE_PUMP_THRESHOLD_PCT
                ),
                corr_to_btc_6m=corr_to_btc,
                corr_window_days=corr_window_days,
                high_24h=high_24h,
                low_24h=low_24h,
                carry_funding_pct=funding_pct,
                carry_funding_annualized_pct=annualized_funding_pct,
                long_carry_pct=-funding_pct,
                long_carry_annualized_pct=-annualized_funding_pct,
                funding_interval_hours=interval_hours,
                funding_countdown_hours=_funding_countdown_hours(funding_snapshot.get("nextFundingTime")),
                premium_index_pct=latest_premium_pct,
                predicted_funding_pct=predicted_funding_pct,
                predicted_funding_annualized_pct=predicted_annualized_funding_pct,
                predicted_long_carry_pct=-predicted_funding_pct,
                predicted_long_carry_annualized_pct=-predicted_annualized_funding_pct,
                predicted_funding_low_pct=predicted_low_pct,
                predicted_funding_high_pct=predicted_high_pct,
                predicted_funding_band_pct=predicted_band_pct,
                predicted_funding_backtest_mae_pct=predicted_mae_pct,
                predicted_funding_backtest_count=predicted_backtest_count,
                funding_window_elapsed_pct=funding_window_elapsed_pct,
                last_settled_funding_pct=last_settled_funding_pct,
                prior_settled_funding_pct=prior_settled_funding_pct,
                funding_flip_delta_pct=funding_flip_delta_pct,
                long_short_account_ratio=long_short_account_ratio,
                long_account_pct=long_account_pct,
                short_account_pct=short_account_pct,
                short_account_history_points=int(short_account_history_stats.get("short_account_history_points", 0) or 0),
                short_account_change_1p_pct=_float_nan(short_account_history_stats.get("short_account_change_1p_pct")),
                short_account_change_1p_pp=_float_nan(short_account_history_stats.get("short_account_change_1p_pp")),
                short_account_previous_1h_pct=_float_nan(short_account_history_stats.get("short_account_previous_1h_pct")),
                short_account_roc_1h_pct=_float_nan(short_account_history_stats.get("short_account_roc_1h_pct")),
                short_account_roc_1h_pp=_float_nan(short_account_history_stats.get("short_account_roc_1h_pp")),
                short_account_roc_1h_abs_pp=_float_nan(short_account_history_stats.get("short_account_roc_1h_abs_pp")),
                short_account_roc_1h_direction=str(short_account_history_stats.get("short_account_roc_1h_direction", "") or ""),
                short_account_roc_smoothed_3p_pp=_float_nan(
                    short_account_history_stats.get("short_account_roc_smoothed_3p_pp")
                ),
                short_account_roc_smoothed_3p_pct=_float_nan(
                    short_account_history_stats.get("short_account_roc_smoothed_3p_pct")
                ),
                short_account_acceleration_1h_pp=_float_nan(
                    short_account_history_stats.get("short_account_acceleration_1h_pp")
                ),
                short_account_acceleration_smoothed_3p_pp=_float_nan(
                    short_account_history_stats.get("short_account_acceleration_smoothed_3p_pp")
                ),
                short_account_roc_zscore=_float_nan(
                    short_account_history_stats.get("short_account_roc_zscore")
                ),
                short_account_direction_persistence=int(
                    short_account_history_stats.get("short_account_direction_persistence", 0) or 0
                ),
                short_account_change_3p_pct=_float_nan(short_account_history_stats.get("short_account_change_3p_pct")),
                short_account_change_3p_pp=_float_nan(short_account_history_stats.get("short_account_change_3p_pp")),
                short_account_change_4p_pct=_float_nan(short_account_history_stats.get("short_account_change_4p_pct")),
                short_account_change_4p_pp=_float_nan(short_account_history_stats.get("short_account_change_4p_pp")),
                short_account_change_6p_pct=_float_nan(short_account_history_stats.get("short_account_change_6p_pct")),
                short_account_change_6p_pp=_float_nan(short_account_history_stats.get("short_account_change_6p_pp")),
                short_account_change_12p_pct=_float_nan(short_account_history_stats.get("short_account_change_12p_pct")),
                short_account_change_12p_pp=_float_nan(short_account_history_stats.get("short_account_change_12p_pp")),
                short_account_change_24p_pct=_float_nan(short_account_history_stats.get("short_account_change_24p_pct")),
                short_account_change_24p_pp=_float_nan(short_account_history_stats.get("short_account_change_24p_pp")),
                short_account_change_max_pct=_float_nan(short_account_history_stats.get("short_account_change_max_pct")),
                short_account_change_max_pp=_float_nan(short_account_history_stats.get("short_account_change_max_pp")),
                short_account_change_max_window=str(short_account_history_stats.get("short_account_change_max_window", "") or ""),
                short_account_change_min_pct=_float_nan(short_account_history_stats.get("short_account_change_min_pct")),
                short_account_change_min_pp=_float_nan(short_account_history_stats.get("short_account_change_min_pp")),
                short_account_change_min_window=str(short_account_history_stats.get("short_account_change_min_window", "") or ""),
                hour_return_pct=hourly_stats["hour_return_pct"],
                hour_return_z=hourly_stats["hour_return_z"],
                day_return_pct=hourly_stats["day_return_pct"],
                daily_quote_volume_multiple=daily_quote_volume_multiple,
                hour_quote_volume=hourly_stats["hour_quote_volume"],
                hour_quote_volume_previous_1h=hourly_stats["hour_quote_volume_previous_1h"],
                hour_volume_roc_1h_pct=hourly_stats["hour_volume_roc_1h_pct"],
                hour_volume_multiple=hourly_stats["hour_volume_multiple"],
                hour_trade_count_multiple=hourly_stats["hour_trade_count_multiple"],
                hour_upper_wick_pct=hourly_stats["hour_upper_wick_pct"],
                hour_close_location_pct=hourly_stats["hour_close_location_pct"],
                oi_value_usdt=oi_value_usdt,
                oi_delta_pct=oi_delta_pct,
                oi_acceleration_1h_pct=_float_nan(oi_stats.get("oi_acceleration_1h_pct")),
                oi_to_24h_volume_pct=oi_to_24h_volume_pct,
                taker_buy_sell_ratio=taker_buy_sell_ratio,
                taker_buy_share_pct=taker_buy_share_pct,
                top_trader_position_ratio=top_trader_position_ratio,
                top_trader_long_position_pct=top_trader_long_position_pct,
                top_trader_short_position_pct=top_trader_short_position_pct,
                top_trader_account_ratio=top_trader_account_ratio,
                top_trader_long_account_pct=top_trader_long_account_pct,
                top_trader_short_account_pct=top_trader_short_account_pct,
                crowd_top_position_divergence_pct=crowd_top_position_divergence_pct,
                crowd_top_account_divergence_pct=crowd_top_account_divergence_pct,
                basis_rate_pct=basis_rate_pct,
                basis_usdt=basis_usdt,
                ask_depth_1pct_usdt=depth_stats["ask_depth_1pct_usdt"],
                ask_depth_to_24h_volume_pct=depth_stats["ask_depth_to_24h_volume_pct"],
                crime_carry_stress_score=float("nan"),
                crime_pump_score=float("nan"),
                crime_ignition_score=float("nan"),
                crime_exhaustion_score=float("nan"),
                crime_pump_flag=False,
                ignition_setup_flag=False,
                exhaustion_flag=False,
                squeeze_risk_flag=False,
                blowoff_risk_flag=False,
                high_5d=levels.high_5d,
                low_5d=levels.low_5d,
                high_20d=levels.high_20d,
                low_20d=levels.low_20d,
                high_90d=levels.high_90d,
                low_90d=levels.low_90d,
                high_180d=levels.high_180d,
                low_180d=levels.low_180d,
                ath_scanned=levels.ath_scanned,
                upside_to_ath_pct=upside_to_ath_pct,
                distance_to_high_5d_pct=distance_to_high_5d_pct,
                distance_to_high_20d_pct=distance_to_high_20d_pct,
                distance_to_high_90d_pct=distance_to_high_90d_pct,
                broke_high_5d=_crossed_above(levels.high_5d, high_24h),
                broke_low_5d=_crossed_below(levels.low_5d, low_24h),
                broke_high_20d=_crossed_above(levels.high_20d, high_24h),
                broke_low_20d=_crossed_below(levels.low_20d, low_24h),
                broke_high_90d=_crossed_above(levels.high_90d, high_24h),
                broke_high_180d=_crossed_above(levels.high_180d, high_24h),
                broke_low_90d=_crossed_below(levels.low_90d, low_24h),
                broke_low_180d=_crossed_below(levels.low_180d, low_24h),
            )
        )

    if not rows:
        empty_cols = list(BreakoutRow.__annotations__.keys())
        empty_cols.extend(
            [
                "normalized_base_asset",
                "crime_excluded_major",
                "crime_seed_score",
                "convexity_seed_score",
                "price_change_24h_pct",
                "range_24h_pct",
                "crime_microstructure_score",
                "crime_largecap_penalty_score",
                "crime_eligible",
                "crime_mechanics_score",
                *MM_PROXIMITY_COLUMNS,
                *CMC_MOVER_COLUMNS,
                "mm_presence_score",
                "mm_bid_support_score",
                "mm_withdrawal_risk_score",
                *EXTERNAL_CRIME_COLUMNS,
                *RANGE_BREAKOUT_COLUMNS,
                *LIFECYCLE_SCORE_COLUMNS,
                *CONVEXITY_SCORE_COLUMNS,
                *SHORT_SQUEEZE_SCORE_COLUMNS,
                *RAVE_LAB_SETUP_COLUMNS,
                *CEX_DEPOSIT_FLOW_COLUMNS,
                *ARCHETYPE_SCORE_COLUMNS,
                *EARLY_PUMP_RADAR_COLUMNS,
                *PRE_ACTIVITY_RADAR_COLUMNS,
                *MECHANISM_SCORE_COLUMNS,
                "trade_bucket",
                "trade_bucket_score",
                "raw_convex_long_signal",
                "thesis_gate",
                "thesis_holder_gate",
                "thesis_holder_evidence_gate",
                "thesis_whale_concentration_gate",
                "thesis_venue_gate",
                "thesis_no_pump_gate",
                "thesis_base_gate",
                "thesis_float_gate",
                "thesis_short_squeeze_gate",
                "thesis_not_late_gate",
                "thesis_core_gate",
                "thesis_core_squeeze_fuel_score",
                "thesis_core_float_score",
                "thesis_gate_note",
                "trade_bucket_note",
            ]
        )
        return pd.DataFrame(columns=empty_cols), pd.DataFrame(columns=empty_cols)

    all_df = pd.DataFrame([r.__dict__ for r in rows]).sort_values("symbol")
    all_df["scan_mode"] = str(scan_mode)
    all_df["available_crypto_perp_count"] = available_crypto_perp_count
    all_df["scanned_symbol_count"] = len(all_df)
    all_df["crypto_perp_coverage_pct"] = (
        len(all_df) / available_crypto_perp_count * 100.0 if available_crypto_perp_count else float("nan")
    )
    ticker_meta = ticker.set_index("symbol")
    all_df["normalized_base_asset"] = all_df["base_asset"].map(normalize_base_asset)
    all_df["crime_excluded_major"] = all_df["normalized_base_asset"].isin(CRIME_EXCLUDED_BASE_ASSETS)
    all_df["crime_seed_score"] = all_df["symbol"].map(ticker_meta["crime_seed_score"]).astype("float64")
    all_df["convexity_seed_score"] = all_df["symbol"].map(ticker_meta["convexity_seed_score"]).astype("float64")
    all_df["price_change_24h_pct"] = all_df["symbol"].map(ticker_meta["priceChangePercent"]).astype("float64")
    all_df["range_24h_pct"] = all_df["symbol"].map(ticker_meta["range_24h_pct"]).astype("float64")
    all_df["dwf_labs_portfolio"] = all_df["symbol"].map(ticker_meta["dwf_labs_portfolio_seed"]).fillna(False).astype(bool)
    all_df["dwf_labs_portfolio_score"] = (
        all_df["symbol"].map(ticker_meta["dwf_labs_portfolio_score_seed"]).fillna(0.0).astype("float64")
    )
    all_df["dwf_labs_portfolio_rank"] = pd.to_numeric(
        all_df["symbol"].map(ticker_meta["dwf_labs_portfolio_rank_seed"]),
        errors="coerce",
    )
    all_df["dwf_labs_portfolio_note"] = (
        all_df["symbol"].map(ticker_meta["dwf_labs_portfolio_note_seed"]).fillna("").astype(str)
    )
    all_df = _apply_mm_proximity_signals(all_df)
    all_df = _apply_dwf_mm_proximity_signal(all_df)
    all_df = _apply_cmc_mover_metrics(all_df, cmc_movers_df)
    all_df = _apply_external_crime_metrics(all_df, external_crime_symbols if deep_scan else set())
    all_df = _apply_range_breakout_events(all_df)
    all_df = _apply_ath_runway(all_df)
    all_df = _apply_crime_pump_scores(all_df)
    all_df = apply_lifecycle_model(all_df)
    all_df = apply_short_squeeze_model(all_df)
    all_df = apply_convexity_model(all_df)
    all_df = _apply_rave_lab_setup_scores(all_df)
    all_df = _apply_pre_pump_scan_memory(all_df)
    all_df = enrich_cex_deposit_flows(
        all_df,
        enabled=deep_scan and CEX_DEPOSIT_FLOW_ENABLED,
        hints_path=DISCORD_HOLDER_CONTRACTS_FILE,
        max_symbols=CEX_DEPOSIT_FLOW_MAX_SYMBOLS,
        timeout=CEX_DEPOSIT_FLOW_TIMEOUT_SECONDS,
        max_holders=DISCORD_HOLDER_COMPOSITION_MAX_HOLDERS,
        lookback_hours=CEX_DEPOSIT_FLOW_LOOKBACK_HOURS,
        min_transfer_tokens=CEX_DEPOSIT_FLOW_MIN_TRANSFER_TOKENS,
        min_top10_pct=CEX_DEPOSIT_FLOW_MIN_TOP10_PCT,
    )
    all_df = apply_terminal_model(all_df)
    all_df = apply_archetype_model(all_df)
    all_df = apply_timing_model(all_df)
    all_df = _score_trade_buckets(all_df)
    all_df = apply_early_pump_radar(all_df)
    all_df = apply_pre_activity_radar(all_df)
    all_df = apply_mechanism_model(all_df)
    range_events_df = all_df[pd.to_numeric(all_df["range_breakout_score"], errors="coerce").fillna(0.0) > 0.0].copy()
    range_events_df = range_events_df.sort_values(
        ["range_breakout_score", "range_high_break_count", "range_low_break_count", "carry_funding_pct", "symbol"],
        ascending=[False, False, False, False, True],
    )
    return range_events_df, all_df


@_cache_data(ttl=120, show_spinner=False)
def load_pnl_dashboard_cached(api_key_fingerprint: str, refresh_nonce: int) -> PnLDashboardResult:
    _ = (api_key_fingerprint, refresh_nonce)
    client = _client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)
    return build_pnl_dashboard_data(
        client=client,
        api_key=BINANCE_API_KEY,
        cache_root=PNL_CACHE_DIR,
        recent_lookback_days=PNL_RECENT_DAYS,
        max_export_year_fetches=PNL_MAX_EXPORT_FETCHES,
    )


@_cache_data(ttl=60, show_spinner=False)
def load_screener_cached(refresh_nonce: int) -> ScreenerData:
    _ = refresh_nonce
    return build_screener_data(_client())


def render_legacy_breakout_dashboard() -> None:
    st.title("Binance USDT Perp Breakout Dashboard")
    st.caption("Single-click scan for 5D/20D/90D/180D highs and lows plus funding/carry, crowding, and structural diagnostics.")
    scan_mode = st.radio(
        "Scan Mode",
        ("Fast", "Deep", "All Short Account %", "Full ATH"),
        horizontal=True,
        help=(
            "Fast scans the top crypto perps with Binance est funding and breakout data first. "
            "Deep adds heavier market-structure diagnostics. All Short Account % returns only each currently trading Binance USDT crypto pair "
            "and its latest global short-account percentage. Open signed-account positions are always forced into Fast and Deep scans. "
            "Full ATH scans a wider ranked non-major universe for 20x+ ATH runway, "
            f"capped at {FULL_ATH_MAX_SYMBOLS_TO_SCAN} symbols and {FULL_ATH_EXTERNAL_SYMBOLS_TO_SCAN} external enrichments to avoid hammering public APIs."
        ),
        key="breakout_scan_mode",
    )

    if st.button("Scan now", type="primary", key="scan_breakouts"):
        st.session_state["breakout_refresh_nonce"] = st.session_state.get("breakout_refresh_nonce", 0) + 1
        spinner_label = (
            "Loading the latest short-account percentage for every Binance USDT crypto perpetual..."
            if scan_mode == "All Short Account %"
            else
            "Running full ATH runway scan with throttled external enrichment..."
            if scan_mode == "Full ATH"
            else
            "Running deep Binance scan with market-structure diagnostics..."
            if scan_mode == "Deep"
            else "Running fast Binance scan with breakout and est-funding data..."
        )
        try:
            with st.spinner(spinner_label):
                highs_df, all_df = run_scan(st.session_state["breakout_refresh_nonce"], scan_mode)
        except Exception as exc:
            st.error(
                "Scan failed before results were available. This is usually a transient Binance/CoinGecko/GoPlus "
                "API issue or a column-shape regression; the app caught it instead of leaving the page stuck."
            )
            st.exception(exc)
            return

        if scan_mode == "All Short Account %":
            available_short_values = int(
                pd.to_numeric(all_df.get("short_account_pct"), errors="coerce").notna().sum()
            ) if not all_df.empty else 0
            st.caption(
                f"Latest Binance global account ratio ({LONG_SHORT_RATIO_PERIOD}) | "
                f"{len(all_df)} crypto perp pairs | {available_short_values} short-account values returned"
            )
            if all_df.empty:
                st.warning("Binance did not return any currently trading crypto perpetual pairs.")
                return
            st.dataframe(
                all_df.loc[:, ["symbol", "short_account_pct"]],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "symbol": st.column_config.TextColumn("Coin Pair"),
                    "short_account_pct": st.column_config.NumberColumn(
                        "Short Accounts",
                        format="%.2f%%",
                    ),
                },
            )
            return

        breakout_column_config = {
            "trade_bucket": st.column_config.TextColumn(
                "Setup Bucket",
                help="Fast trade-triage label derived from breakout, ignition, crowding, carry, and exhaustion signals.",
            ),
            "trade_bucket_score": st.column_config.NumberColumn(
                "Bucket Score",
                format="%.1f",
                help="Ranking score inside each bucket. Higher is better for Convex Long / Scalp Only; higher means more toxic for Avoid.",
            ),
            "raw_convex_long_signal": st.column_config.CheckboxColumn(
                "Raw Convex Signal",
                help="Soft pre-ignition structure signal before the hard thesis gates are applied.",
            ),
            "thesis_gate": st.column_config.CheckboxColumn(
                "Thesis Gate",
                help="Full hard gate: 90%+ top10 holder evidence, Binance+Bitget trading evidence, 60D no-pump proof, float/FDV evidence, short crowd plus squeeze fuel, and early/not-late structure.",
            ),
            "thesis_base_gate": st.column_config.CheckboxColumn(
                "Base Thesis",
                help="Base structural gate before float/FDV and squeeze-fuel checks: holder evidence, Binance+Bitget, and 60D no-pump proof.",
            ),
            "thesis_holder_gate": st.column_config.CheckboxColumn(
                "Holder Gate",
                help="Observed top10 holder concentration is at least 90% with eligible explorer evidence.",
            ),
            "thesis_venue_gate": st.column_config.CheckboxColumn(
                "Binance+Bitget",
                help="Requires Binance perp/share evidence and Bitget trading evidence. Gate.IO is supporting only.",
            ),
            "thesis_no_pump_gate": st.column_config.CheckboxColumn(
                "No Pump 60D",
                help="Requires enough recent history to prove no large pump over the 60D lookback.",
            ),
            "thesis_float_gate": st.column_config.CheckboxColumn(
                "Float/FDV Gate",
                help="Requires independent low-float, FDV/MC, locked-supply, or hidden-float evidence.",
            ),
            "thesis_short_squeeze_gate": st.column_config.CheckboxColumn(
                "Short+Fuel Gate",
                help="Requires short crowding paired with build/OI/liquidation/funding/forced-buying squeeze fuel.",
            ),
            "thesis_not_late_gate": st.column_config.CheckboxColumn(
                "Early Gate",
                help="Requires pre-ignition/timing structure without late/exhaustion risk.",
            ),
            "thesis_core_gate": st.column_config.CheckboxColumn(
                "Core Thesis",
                help="Same value as Thesis Gate; printed separately so exports can distinguish base and full core gates.",
            ),
            "thesis_core_squeeze_fuel_score": st.column_config.NumberColumn("Core Fuel", format="%.1f"),
            "thesis_core_float_score": st.column_config.NumberColumn("Core Float", format="%.1f"),
            "thesis_gate_note": st.column_config.TextColumn(
                "Thesis Gate Note",
                help="Shows which non-negotiable thesis prerequisite is still missing.",
            ),
            "trade_bucket_note": st.column_config.TextColumn(
                "Bucket Note",
                help="Short explanation of why the coin landed in that bucket.",
            ),
            "quote_volume_24h": st.column_config.NumberColumn(
                "24H Quote Vol",
                format="$%.0f",
                help="24-hour quote volume used as a rough size/liquidity proxy.",
            ),
            "quote_volume_prior_30d_total": st.column_config.NumberColumn(
                "Prior 30D Vol",
                format="$%.0f",
                help="Total Binance futures quote volume across up to 30 completed UTC daily candles.",
            ),
            "quote_volume_prior_30d_daily_avg": st.column_config.NumberColumn(
                "Prior 30D Avg",
                format="$%.0f",
                help="Average daily Binance futures quote volume across the completed prior-day sample.",
            ),
            "quote_volume_prior_30d_days": st.column_config.NumberColumn(
                "Prior Days",
                format="%d",
                help="Completed daily candles in the baseline, capped at 30.",
            ),
            "quote_volume_24h_vs_prior_30d_avg_ratio": st.column_config.NumberColumn(
                "24H / 30D Avg",
                format="%.2fx",
                help="Rolling 24-hour quote volume divided by the prior completed-day average.",
            ),
            "anchored_vwap_30d": st.column_config.NumberColumn(
                "30D AVWAP",
                format="%.8f",
                help="Perpetual-market VWAP anchored to the start of up to 30 completed UTC daily candles.",
            ),
            "price_vs_anchored_vwap_30d_pct": st.column_config.NumberColumn(
                "Price vs 30D AVWAP",
                format="%.2f%%",
                help="Current price distance above or below the completed-day 30D anchored VWAP.",
            ),
            "anchored_vwap_30d_days": st.column_config.NumberColumn(
                "AVWAP Days",
                format="%d",
                help="Completed daily candles used by the anchored VWAP calculation.",
            ),
            "crime_microstructure_score": st.column_config.NumberColumn(
                "Microstructure",
                format="%.1f",
                help="Higher means thinner/smaller tape and therefore more plausible as a structural squeeze candidate.",
            ),
            "crime_largecap_penalty_score": st.column_config.NumberColumn(
                "Large-Cap Penalty",
                format="%.1f",
                help="Higher means the symbol behaves more like a major liquid tape and should rank lower in structure-radar views.",
            ),
            "crime_eligible": st.column_config.CheckboxColumn(
                "Structure Eligible",
                help="Only thinner/smaller names should make the crime tape. Large liquid majors are filtered out here.",
            ),
            "crime_mechanics_score": st.column_config.NumberColumn(
                "Crime Mechanics",
                format="%.1f",
                help="Composite of thin tape, spot venue support, supply concentration proxies, velocity, OI expansion, and taker pressure.",
            ),
            "float_trap_score": st.column_config.NumberColumn(
                "Float Trap",
                format="%.1f",
                help="Controlled-float quality score from holder/supply concentration, FDV gap, holder count, sponsor mismatch, and OTC inventory-risk proxies.",
            ),
            "rave_lab_setup_score": st.column_config.NumberColumn(
                "RAVE/LAB Setup",
                format="%.1f",
                help="Combined controlled-float upside score: centralized ownership, low float, short-account build, price/volume ignition, target CEX-flow proxies, and convexity fuel. This is structural risk/upside, not proof of manipulation.",
            ),
            "rave_lab_watch_flag": st.column_config.CheckboxColumn(
                "RAVE/LAB Watch",
                help="True when the combined structure is worth watching but not necessarily strong enough for the clean setup flag.",
            ),
            "rave_lab_setup_flag": st.column_config.CheckboxColumn(
                "RAVE/LAB Setup",
                help="True when centralized ownership/float structure and either short build or ignition line up.",
            ),
            "rave_lab_extreme_flag": st.column_config.CheckboxColumn(
                "RAVE/LAB Extreme",
                help="Highest-conviction structural setup: strong ownership centralization, low float, active ignition, and not too much late-stage heat.",
            ),
            "rave_lab_setup_note": st.column_config.TextColumn(
                "RAVE/LAB Note",
                help="Short explanation of the factors driving the combined score.",
            ),
            "insider_team_holder_pct": st.column_config.NumberColumn(
                "Insider/Team %",
                format="%.1f%%",
                help="Owner plus creator holder percentage proxy when GoPlus-style holder data is available.",
            ),
            "centralized_ownership_score": st.column_config.NumberColumn(
                "Centralized Own.",
                format="%.1f",
                help="Scores holder concentration, owner/creator holdings, low holder count, and owner-circle proxies.",
            ),
            "low_float_score": st.column_config.NumberColumn(
                "Low Float",
                format="%.1f",
                help="Scores low circulating supply, locked supply, FDV/market-cap gap, float-trap, and valuation-trap structure.",
            ),
            "short_account_build_score": st.column_config.NumberColumn(
                "Short Build",
                format="%.1f",
                help="Scores current short-account skew and the largest recent increase in short-account share.",
            ),
            "short_dominance_score": st.column_config.NumberColumn(
                "Short Dom.",
                format="%.1f",
                help="Scores whether short accounts are already dominant, even if the coin has not started moving yet.",
            ),
            "low_volatility_coil_score": st.column_config.NumberColumn(
                "Low-Vol Coil",
                format="%.1f",
                help="Scores quiet 24h range and muted returns with a gentle volume/trade wake-up. Built for pre-breakout compression.",
            ),
            "pre_pump_short_fuse_score": st.column_config.NumberColumn(
                "Pre-Ignition Fuse",
                format="%.1f",
                help="Pre-breakout score combining low volatility, dominant shorts, low float, and centralized ownership.",
            ),
            "pre_pump_compression_score": st.column_config.NumberColumn(
                "Compression",
                format="%.1f",
                help="Low-volatility compression with muted returns, gentle volume wake-up, and early OI pressure.",
            ),
            "short_trap_score": st.column_config.NumberColumn(
                "Short Trap",
                format="%.1f",
                help="Shorts are dominant or building while price is not breaking down and OI is expanding.",
            ),
            "silent_oi_accumulation_score": st.column_config.NumberColumn(
                "Silent OI",
                format="%.1f",
                help="OI builds while realized range stays quiet. This is the preferred pre-candle pressure pattern.",
            ),
            "accumulation_cvd_proxy_score": st.column_config.NumberColumn(
                "CVD Proxy",
                format="%.1f",
                help="Proxy for aggressive taker demand being absorbed with muted price response, gated by float/holder concentration.",
            ),
            "accumulation_absorption_score": st.column_config.NumberColumn(
                "Accum. Absorption",
                format="%.1f",
                help="Structural absorption score: taker demand, muted price response, activity, OI hold, and float-control gate.",
            ),
            "accumulation_absorption_flag": st.column_config.CheckboxColumn(
                "Accum. Flag",
                help="True when concentrated-float names show aggressive taker demand with muted price response.",
            ),
            "accumulation_absorption_note": st.column_config.TextColumn(
                "Accum. Read",
                help="Neutral summary of the accumulation-like absorption pattern. This is a hypothesis requiring source/holder review.",
            ),
            "dormant_short_fuse_score": st.column_config.NumberColumn(
                "Dormant Short Fuse",
                format="%.1f",
                help="CHIP-style setup score: quiet tape, dominant shorts, owner/float concentration, small CEX-flow confirmation, and low late-stage heat.",
            ),
            "pre_pump_precision_score": st.column_config.NumberColumn(
                "Pre-Ignition Precision",
                format="%.1f",
                help="Highest-precision pre-ignition score combining compression, short trap, silent OI, float/owner concentration, CEX lane wake-up, depth withdrawal, and no-chase filters.",
            ),
            "pre_pump_precision_flag": st.column_config.CheckboxColumn(
                "Precision Flag",
                help="True when the pre-ignition pattern clears compression, short-trap, float/ownership, and no-chase gates.",
            ),
            "pre_pump_precision_note": st.column_config.TextColumn(
                "Precision Note",
                help="Short explanation of the precision pre-ignition pattern.",
            ),
            "cex_lane_wakeup_score": st.column_config.NumberColumn(
                "CEX Wake",
                format="%.1f",
                help="Scan-to-scan increase in Binance/Bitget/Gate/OKX venue share plus current CEX-flow strength.",
            ),
            "target_cex_share_change_pp": st.column_config.NumberColumn("CEX Share Chg", format="%.2fpp"),
            "oi_value_change_since_scan_pct": st.column_config.NumberColumn("OI Chg Scan", format="%.2f%%"),
            "ask_depth_1pct_change_pct": st.column_config.NumberColumn("Ask Depth Chg", format="%.2f%%"),
            "ask_depth_withdrawal_score": st.column_config.NumberColumn(
                "Depth Pull",
                format="%.1f",
                help="Flags ask-depth withdrawal or very thin visible ask depth while short pressure is present.",
            ),
            "thin_ask_trap_score": st.column_config.NumberColumn(
                "Thin Ask Trap",
                format="%.1f",
                help="Combines ask-depth withdrawal, short trap, low float, CEX wake-up, and silent OI accumulation.",
            ),
            "no_chase_penalty_score": st.column_config.NumberColumn(
                "No-Chase Penalty",
                format="%.1f",
                help="Penalty for already-late candles: big 1h/24h move, wide 24h range, hot funding, upper-wick/exhaustion, or exit fragility.",
            ),
            "no_chase_ok_flag": st.column_config.CheckboxColumn("No-Chase OK"),
            "dormant_short_fuse_flag": st.column_config.CheckboxColumn(
                "Short Fuse",
                help="True when a low-volatility coin has dominant shorts plus float/ownership concentration before the breakout.",
            ),
            "dormant_short_fuse_note": st.column_config.TextColumn(
                "Short Fuse Note",
                help="Short explanation of the quiet short-fuse setup.",
            ),
            "price_volume_ignition_score": st.column_config.NumberColumn(
                "PV Ignition",
                format="%.1f",
                help="Scores price action, hourly/daily volume expansion, trade-count acceleration, breakout pressure, and optional CMC mover signal.",
            ),
            "target_cex_volume_share_pct": st.column_config.NumberColumn(
                "Target CEX Share",
                format="%.1f%%",
                help="Share of visible venue volume on Binance, Bitget, Gate, and OKX/OKEx where available.",
            ),
            "target_cex_flow_score": st.column_config.NumberColumn(
                "Target CEX Flow",
                format="%.1f",
                help="Scores target CEX venue concentration plus CEX/DEX skew and inventory-transfer/CEX-flow proxies.",
            ),
            "rave_lab_convex_fuel_score": st.column_config.NumberColumn("Convex Fuel", format="%.1f"),
            "rave_lab_late_penalty_score": st.column_config.NumberColumn("Late Offset", format="%.1f"),
            "convexity_float_score": st.column_config.NumberColumn(
                "Convex Float",
                format="%.1f",
                help="Early convexity score for controlled float and bad float quality.",
            ),
            "convexity_sponsor_score": st.column_config.NumberColumn(
                "Convex Sponsor",
                format="%.1f",
                help="How strong the spot sponsorship looks from venue concentration, CEX-over-DEX, venue cluster dominance, and EMFX lanes.",
            ),
            "convexity_preignition_score": st.column_config.NumberColumn(
                "Pre-Ignition",
                format="%.1f",
                help="Entry-quality pressure before the move is fully obvious: daily volume lift, near-breakout structure, constructive returns, and early OI/trade expansion.",
            ),
            "convexity_expansion_score": st.column_config.NumberColumn(
                "Convex Expand",
                format="%.1f",
                help="Whether the tape is beginning to expand through volume, trade count, OI growth, and breakouts without already being too late.",
            ),
            "convexity_squeeze_score": st.column_config.NumberColumn(
                "Convex Squeeze",
                format="%.1f",
                help="Optional squeeze fuel score using crowding, funding flips, and OI structure while preferring cooler carry.",
            ),
            "convexity_runway_score": st.column_config.NumberColumn(
                "Convex Runway",
                format="%.1f",
                help="Remaining asymmetry from scanned ATH runway, listing age, and smaller-cap structure.",
            ),
            "convexity_late_penalty": st.column_config.NumberColumn(
                "Late Penalty",
                format="%.1f",
                help="Penalty for already-late structures: exhaustion, hot funding, upper wicks, blowoff behavior, and unwind risk.",
            ),
            "convexity_entry_score": st.column_config.NumberColumn(
                "Entry Score",
                format="%.1f",
                help="The main entry-quality convexity score. This is the score used to prefer early asymmetric setups over late heat.",
            ),
            "convexity_score": st.column_config.NumberColumn(
                "Convexity",
                format="%.1f",
                help="Early-phase convexity score prioritizing controlled float, sponsored spot, expansion readiness, squeeze optionality, and runway while penalizing late-stage heat.",
            ),
            "pre_pump_candidate_flag": st.column_config.CheckboxColumn(
                "Pre-Ignition",
                help="True when the setup has sponsor/float/pre-ignition confluence but is not yet in chase-risk territory.",
            ),
            "early_convexity_flag": st.column_config.CheckboxColumn(
                "Early Convex",
                help="True when the setup looks structurally sponsored and still early enough to matter.",
            ),
            "convexity_prime_flag": st.column_config.CheckboxColumn(
                "Convex Prime",
                help="Best-in-class early convexity signals before hard thesis gating.",
            ),
            "convexity_chase_risk_flag": st.column_config.CheckboxColumn(
                "Chase Risk",
                help="True when the same setup is likely too hot for clean early positioning.",
            ),
            "convexity_too_late_flag": st.column_config.CheckboxColumn(
                "Convex Too Late",
                help="Names whose convexity profile is already too stretched or too late.",
            ),
            "convexity_summary": st.column_config.TextColumn("Convex Summary"),
            "convexity_top_factors": st.column_config.TextColumn("Convex Factors"),
            "convexity_offsets": st.column_config.TextColumn("Convex Offsets"),
            "convexity_seed_score": st.column_config.NumberColumn("Convex Seed", format="%.1f"),
            "trend_confluence_score": st.column_config.NumberColumn(
                "Trend Conf.",
                format="%.1f",
                help="Breakout-stack, near-breakout, daily volume lift, hourly volume, and close-quality confluence.",
            ),
            "spot_flow_confluence_score": st.column_config.NumberColumn(
                "Spot Flow Conf.",
                format="%.1f",
                help="CEX/DEX skew, Binance/Bitget/Gate dominance, EMFX/KRW/TRY lanes, spot volume versus market cap, and venue concentration.",
            ),
            "perp_squeeze_confluence_score": st.column_config.NumberColumn(
                "Perp Sqz Conf.",
                format="%.1f",
                help="Funding-flip, short crowding, OI growth, OI versus market cap, taker buying, and cool carry confluence.",
            ),
            "float_control_confluence_score": st.column_config.NumberColumn(
                "Float Ctrl Conf.",
                format="%.1f",
                help="Controlled-float confluence from holder concentration, unreleased supply, FDV/MCap, low holders, and inventory-risk proxies.",
            ),
            "mm_sponsor_confluence_score": st.column_config.NumberColumn(
                "MM Sponsor Conf.",
                format="%.1f",
                help="Coinbase depth/spread/bid support plus manual MM-proximity hints. This is a liquidity-sponsor proxy, not proof of a specific desk.",
            ),
            "ath_runway_confluence_score": st.column_config.NumberColumn(
                "ATH Runway Conf.",
                format="%.1f",
                help="ATH multiple/runway confluence, preferring large remaining upside while avoiding mega-cap stabilization.",
            ),
            "convexity_confluence_score": st.column_config.NumberColumn(
                "Mechanics Conf.",
                format="%.1f",
                help="Weighted confluence score across trend, spot flow, perp squeeze, float control, MM/sponsor, and ATH runway mechanics.",
            ),
            "convexity_confluence_count": st.column_config.NumberColumn(
                "Conf. Count",
                format="%d",
                help="How many independent mechanics are active: trend, spot flow, perp squeeze, float control, MM/sponsor, ATH runway.",
            ),
            "valuation_trap_score": st.column_config.NumberColumn(
                "Valuation Trap",
                format="%.1f",
                help="Scores the 'obviously overvalued but tiny real float' setup using FDV/MCap, locked supply, holder concentration, and volume versus market cap.",
            ),
            "short_liquidation_fuel_score": st.column_config.NumberColumn(
                "Short Fuel",
                format="%.1f",
                help="Scores forced-buy fuel from short-account skew, funding flip, short-crowding, OI/MCap, OI growth, and perp pressure.",
            ),
            "spot_control_score": st.column_config.NumberColumn(
                "Spot Control",
                format="%.1f",
                help="Scores CEX/spot sponsorship and possible liquidity-control proxies from venue support, CEX/DEX skew, MM presence, venue concentration, and bid support.",
            ),
            "crowd_skew_confluence_score": st.column_config.NumberColumn(
                "Crowd Skew",
                format="%.1f",
                help="Scores whether account-positioning is skewed short while top-trader positioning and funding leave room for forced buying.",
            ),
            "forced_buying_setup_score": st.column_config.NumberColumn(
                "Forced Buying",
                format="%.1f",
                help="Scores short-account skew, OI expansion, funding flip, cool carry, perp pressure, and breakout confirmation.",
            ),
            "clean_convex_setup_score": st.column_config.NumberColumn(
                "Clean Convex",
                format="%.1f",
                help="Entry-quality score for setups with pre-ignition pressure, float/spot control, forced-buying fuel, runway, and low late-stage penalty.",
            ),
            "squeeze_machine_score": st.column_config.NumberColumn(
                "Squeeze Machine",
                format="%.1f",
                help="Lifecycle score for controlled float + CEX spot support + perp short fuel + early upward pressure, penalized for late/distribution risk.",
            ),
            "trend_confluence_flag": st.column_config.CheckboxColumn("Trend Conf."),
            "spot_flow_confluence_flag": st.column_config.CheckboxColumn("Spot Flow Conf."),
            "perp_squeeze_confluence_flag": st.column_config.CheckboxColumn("Perp Sqz Conf."),
            "float_control_confluence_flag": st.column_config.CheckboxColumn("Float Ctrl Conf."),
            "mm_sponsor_confluence_flag": st.column_config.CheckboxColumn("MM Sponsor Conf."),
            "ath_runway_confluence_flag": st.column_config.CheckboxColumn("ATH Runway Conf."),
            "forced_buying_setup_flag": st.column_config.CheckboxColumn("Forced Buying"),
            "clean_convex_setup_flag": st.column_config.CheckboxColumn("Clean Convex"),
            "squeeze_machine_flag": st.column_config.CheckboxColumn("Sqz Machine"),
            "convexity_confluence_note": st.column_config.TextColumn(
                "Confluence Note",
                help="Plain-English summary of which mechanics are lining up.",
            ),
            "daily_quote_volume_multiple": st.column_config.NumberColumn("Daily Vol x", format="%.2f"),
            "distance_to_high_5d_pct": st.column_config.NumberColumn("Dist 5D High", format="%.2f%%"),
            "distance_to_high_20d_pct": st.column_config.NumberColumn("Dist 20D High", format="%.2f%%"),
            "distance_to_high_90d_pct": st.column_config.NumberColumn("Dist 90D High", format="%.2f%%"),
            "ignition_score_v2": st.column_config.NumberColumn(
                "Ignition v2",
                format="%.1f",
                help="Lifecycle launch score from breakouts, return z-score, volume/trade-count expansion, taker pressure, OI expansion, and spot/MM support.",
            ),
            "perp_pressure_score": st.column_config.NumberColumn(
                "Perp Pressure",
                format="%.1f",
                help="Derivative crowding score from OI, funding, premium/basis, long-short crowding, and perp volume versus market cap.",
            ),
            "venue_support_score": st.column_config.NumberColumn(
                "Venue Support",
                format="%.1f",
                help="Spot/MM support score using Coinbase depth/spread/volume, venue breadth/concentration, Upbit/KRW, Kraken, and MM pull-risk as an offset.",
            ),
            "exit_fragility_score": st.column_config.NumberColumn(
                "Exit Fragility",
                format="%.1f",
                help="How violently the move can fail if support fades: MM pull risk, upper wick, weak close, thin ask depth, sponsor mismatch, OTC inventory risk, and exhaustion.",
            ),
            "crime_pump_score_v2": st.column_config.NumberColumn(
                "Structure Score v2",
                format="%.1f",
                help="Lifecycle score: Float Trap 27%, Ignition 23%, Perp Pressure 22%, Venue Support 16%, Exit Fragility 12%, minus Large-Cap Stabilizer 20%.",
            ),
            "funding_flip_up_flag": st.column_config.CheckboxColumn(
                "Funding Flipped",
                help="True when the most recent settled funding was negative and the live/model funding has flipped positive by a meaningful amount.",
            ),
            "fresh_flip_flag": st.column_config.CheckboxColumn("Fresh Flip"),
            "active_short_squeeze_flag": st.column_config.CheckboxColumn("Active Short Sqz"),
            "squeeze_chase_flag": st.column_config.CheckboxColumn("Short Sqz Chase"),
            "funding_flip_score": st.column_config.NumberColumn(
                "Funding Flip",
                format="%.1f",
                help="Scores how cleanly funding swung from negative to positive using the last settled funding, current estimated/model funding, premium, and basis.",
            ),
            "short_crowding_score": st.column_config.NumberColumn(
                "Short Crowding",
                format="%.1f",
                help="Scores whether there was still real short fuel in the tape using account ratios, short share, and OI crowding.",
            ),
            "breakout_pressure_score": st.column_config.NumberColumn(
                "Breakout Pressure",
                format="%.1f",
                help="Confirms the squeeze with breakout stack, returns, volume/trade expansion, taker aggression, and close quality.",
            ),
            "runway_score": st.column_config.NumberColumn(
                "ATH Runway",
                format="%.1f",
                help="Scores remaining upside to the max scanned daily high, plus listing age and size stabilization.",
            ),
            "short_squeeze_score": st.column_config.NumberColumn(
                "Short Squeeze",
                format="%.1f",
                help="Funding-flip / short-squeeze composite: funding flip, short crowding, breakout pressure, ATH runway, minus chase penalty.",
            ),
            "crowded_short_uptrend_score": st.column_config.NumberColumn(
                "Crowded Uptrend",
                format="%.1f",
                help="Ranks coins where positive funding, high/rising short accounts, and uptrend/breakout structure coexist.",
            ),
            "crowded_short_uptrend_flag": st.column_config.CheckboxColumn("Crowded Uptrend"),
            "crowded_short_uptrend_note": st.column_config.TextColumn("Crowded Uptrend Note"),
            "crowded_short_uptrend_funding_gate": st.column_config.CheckboxColumn("Funding > 0"),
            "crowded_short_uptrend_short_gate": st.column_config.CheckboxColumn("High Shorts"),
            "crowded_short_uptrend_build_gate": st.column_config.CheckboxColumn("Shorts Building"),
            "crowded_short_uptrend_trend_gate": st.column_config.CheckboxColumn("Uptrend Gate"),
            "crowded_short_uptrend_effective_funding_pct": st.column_config.NumberColumn(
                "Effective Funding",
                format="%.4f%%",
                help="Max of live estimated and modeled funding, used only as a positive-funding gate and score input.",
            ),
            "crowded_short_uptrend_funding_score": st.column_config.NumberColumn("Funding Score", format="%.1f"),
            "crowded_short_uptrend_short_score": st.column_config.NumberColumn("Short Level", format="%.1f"),
            "crowded_short_uptrend_build_score": st.column_config.NumberColumn("Short Build", format="%.1f"),
            "crowded_short_uptrend_trend_score": st.column_config.NumberColumn("Trend", format="%.1f"),
            "crowded_short_uptrend_oi_score": st.column_config.NumberColumn("OI/Fuel", format="%.1f"),
            "crowded_short_uptrend_late_heat_score": st.column_config.NumberColumn(
                "Late Heat",
                format="%.1f",
                help="Penalty from exhaustion, late-risk, blowoff/unwind flags, low breaks, or sharp downside tape.",
            ),
            "mechanism_score": st.column_config.NumberColumn(
                "Mechanism",
                format="%.1f",
                help="Best dominant reflexive-loop score across float, CEX inventory, short-uptrend, compression, and runway mechanisms.",
            ),
            "mechanism_primary": st.column_config.TextColumn("Primary Mechanism"),
            "mechanism_stage": st.column_config.TextColumn("Stage"),
            "mechanism_reflexivity_loop": st.column_config.TextColumn("Reflexivity Loop"),
            "mechanism_playbook_label": st.column_config.TextColumn("Playbook"),
            "mechanism_playbook_rule": st.column_config.TextColumn("Playbook Rule"),
            "mechanism_evidence_note": st.column_config.TextColumn("Mechanism Evidence"),
            "mechanism_next_check": st.column_config.TextColumn("Next Check"),
            "mechanism_invalidation": st.column_config.TextColumn("Invalidation"),
            "mechanism_hidden_float_score": st.column_config.NumberColumn("Hidden Float", format="%.1f"),
            "mechanism_inventory_squeeze_score": st.column_config.NumberColumn("CEX Inventory", format="%.1f"),
            "mechanism_crowded_short_uptrend_score": st.column_config.NumberColumn("Short Uptrend Loop", format="%.1f"),
            "mechanism_compression_ignition_score": st.column_config.NumberColumn("Compression Ignition", format="%.1f"),
            "mechanism_runway_breakout_score": st.column_config.NumberColumn("Runway Breakout", format="%.1f"),
            "mechanism_late_failure_score": st.column_config.NumberColumn("Late Failure", format="%.1f"),
            "local_snapshot_count": st.column_config.NumberColumn("Local Rows", format="%d"),
            "best_snapshot_file": st.column_config.TextColumn("Best Snapshot"),
            "best_snapshot_time": st.column_config.TextColumn("Snapshot Time"),
            "local_evidence_status": st.column_config.TextColumn("Evidence Status"),
            "observed_phase": st.column_config.TextColumn("Observed Phase"),
            "contract_hint_status": st.column_config.TextColumn("Contract Hint"),
            "contract_hint_chain": st.column_config.TextColumn("Contract Chain"),
            "contract_hint_address": st.column_config.TextColumn("Contract Address"),
            "price_path_status": st.column_config.TextColumn("Price Path"),
            "price_event_date": st.column_config.TextColumn("Price Date"),
            "price_event_date_source": st.column_config.TextColumn("Date Source"),
            "event_day_return_pct": st.column_config.NumberColumn("Event Day", format="%.1f%%"),
            "event_break_prior_20d_high": st.column_config.CheckboxColumn("Broke 20D High"),
            "post_7d_high_return_pct": st.column_config.NumberColumn("Post 7D High", format="%.1f%%"),
            "post_7d_low_drawdown_pct": st.column_config.NumberColumn("Post 7D Low", format="%.1f%%"),
            "mechanism_hypothesis": st.column_config.TextColumn("Mechanism Hypothesis"),
            "mechanism_read": st.column_config.TextColumn("Mechanism Read"),
            "mechanism_verdict": st.column_config.TextColumn("Mechanism Verdict"),
            "scanner_lesson": st.column_config.TextColumn("Scanner Lesson"),
            "evidence_gap_severity": st.column_config.TextColumn("Gap Severity"),
            "next_data_action": st.column_config.TextColumn("Next Data Action"),
            "evidence_gaps": st.column_config.TextColumn("Evidence Gaps"),
            "last_settled_funding_pct": st.column_config.NumberColumn(
                "Prev Funding",
                format="%.4f%%",
                help="Most recent settled Binance funding rate before the current live estimate/model.",
            ),
            "prior_settled_funding_pct": st.column_config.NumberColumn(
                "Prior Funding",
                format="%.4f%%",
                help="Funding rate from one settlement before Prev Funding.",
            ),
            "funding_flip_delta_pct": st.column_config.NumberColumn(
                "Flip Delta",
                format="%.4f%%",
                help="Current effective funding minus the most recent settled funding. Positive means the tape is repricing toward longs paying shorts.",
            ),
            "ath_scanned": st.column_config.NumberColumn(
                "Scanned ATH",
                format="%.6f",
                help="Maximum scanned daily high from the loaded Binance history window. This is a scanned-history proxy, not guaranteed full lifetime ATH.",
            ),
            "coingecko_ath_usd": st.column_config.NumberColumn(
                "CG ATH",
                format="$%.6f",
                help="CoinGecko lifetime ATH when the asset can be matched and enriched in Deep/Full ATH mode.",
            ),
            "coingecko_ath_change_pct": st.column_config.NumberColumn(
                "CG ATH Drawdown",
                format="%.1f%%",
                help="CoinGecko reported percent change from ATH. Negative means price is below ATH.",
            ),
            "coingecko_ath_date": st.column_config.TextColumn("CG ATH Date"),
            "ath_price": st.column_config.NumberColumn(
                "ATH Price",
                format="%.6f",
                help="Best available ATH price: CoinGecko lifetime ATH when present, otherwise Binance scanned-history ATH.",
            ),
            "ath_multiple": st.column_config.NumberColumn(
                "X to ATH",
                format="%.2fx",
                help="ATH Price divided by current last price. 20x means the coin is at least 20x below its ATH.",
            ),
            "ath_upside_pct": st.column_config.NumberColumn(
                "ATH Upside",
                format="%.1f%%",
                help="Remaining upside from last price to the best available ATH.",
            ),
            "ath_source": st.column_config.TextColumn(
                "ATH Source",
                help="CoinGecko when lifetime ATH is available; otherwise Binance scanned daily history.",
            ),
            "ath_runway_20x_flag": st.column_config.CheckboxColumn(
                "20x From ATH",
                help="True when current price is at least 20x below the best available ATH.",
            ),
            "upside_to_ath_pct": st.column_config.NumberColumn(
                "Upside to ATH",
                format="%.1f%%",
                help="Remaining upside from last price to the scanned ATH proxy.",
            ),
            "breakout_stack_count": st.column_config.NumberColumn(
                "Breakout Stack",
                format="%d",
                help="How many of the 5D, 20D, 90D, and 180D highs broke in the latest move.",
            ),
            "range_breakout_event": st.column_config.TextColumn(
                "Range Event",
                help="20D/90D/180D high or low events hit in the latest scan window.",
            ),
            "range_breakout_side": st.column_config.TextColumn("Range Side"),
            "range_breakout_score": st.column_config.NumberColumn(
                "Range Event Score",
                format="%.1f",
                help="Scores 20D/90D/180D high and low events, with longer-window breaks weighted more heavily.",
            ),
            "range_high_break_count": st.column_config.NumberColumn("High Breaks", format="%d"),
            "range_low_break_count": st.column_config.NumberColumn("Low Breaks", format="%d"),
            "short_squeeze_summary": st.column_config.TextColumn("Squeeze Summary"),
            "short_squeeze_top_factors": st.column_config.TextColumn("Squeeze Factors"),
            "short_squeeze_offsets": st.column_config.TextColumn("Squeeze Offsets"),
            "cmc_mover_score": st.column_config.NumberColumn(
                "CMC Mover",
                format="%.1f",
                help="Optional CoinMarketCap top-mover signal from 1H/24H rank, velocity, and volume-to-market-cap. Requires COINMARKETCAP_API_KEY or CMC_API_KEY.",
            ),
            "cmc_mover_label": st.column_config.TextColumn(
                "CMC Label",
                help="Why CMC ranked it: 1H rank, 24H rank, and extreme CMC volume-to-market-cap notes.",
            ),
            "cmc_rank_1h": st.column_config.NumberColumn("CMC 1H Rank", format="%.0f"),
            "cmc_rank_24h": st.column_config.NumberColumn("CMC 24H Rank", format="%.0f"),
            "cmc_pct_1h": st.column_config.NumberColumn("CMC 1H %", format="%.2f%%"),
            "cmc_pct_24h": st.column_config.NumberColumn("CMC 24H %", format="%.2f%%"),
            "cmc_market_cap_usd": st.column_config.NumberColumn("CMC Mkt Cap", format="$%.0f"),
            "cmc_volume_24h": st.column_config.NumberColumn("CMC 24H Vol", format="$%.0f"),
            "cmc_volume_to_mcap_pct": st.column_config.NumberColumn("CMC Vol/MCap", format="%.1f%%"),
            "cmc_name": st.column_config.TextColumn("CMC Name"),
            "setup_ready_flag": st.column_config.CheckboxColumn("Setup Ready"),
            "active_squeeze_flag": st.column_config.CheckboxColumn("Active Squeeze"),
            "blowoff_watch_flag": st.column_config.CheckboxColumn("Blowoff Watch"),
            "unwind_risk_flag": st.column_config.CheckboxColumn("Unwind Risk"),
            "coinbase_lane_flag": st.column_config.CheckboxColumn("Coinbase Lane"),
            "owner_controlled_flag": st.column_config.CheckboxColumn("Owner Controlled"),
            "perp_heavy_flag": st.column_config.CheckboxColumn("Perp Heavy"),
            "why_flagged_summary": st.column_config.TextColumn("Why Summary"),
            "why_flagged_top_factors": st.column_config.TextColumn("Top Factors"),
            "why_flagged_offsets": st.column_config.TextColumn("Offsets"),
            "crime_spot_impulse_score": st.column_config.NumberColumn(
                "Spot Impulse",
                format="%.1f",
                help="Scores external spot support, including Coinbase/Binance spot volume relative to Binance perp volume.",
            ),
            "crime_supply_control_score": st.column_config.NumberColumn(
                "Supply Control",
                format="%.1f",
                help="Proxy for float/holder concentration using CoinGecko supply data and GoPlus holder concentration when available.",
            ),
            "crime_coinbase_lane_score": st.column_config.NumberColumn(
                "Coinbase Lane",
                format="%.1f",
                help="Scores Coinbase-listed spot support, Coinbase volume share, and Coinbase spot volume versus Binance perp volume.",
            ),
            "crime_owner_circle_score": st.column_config.NumberColumn(
                "Owner-Circle",
                format="%.1f",
                help="Scores holder concentration, unreleased supply/FDV gap, low holder count, and venue concentration proxies.",
            ),
            "mm_presence_score": st.column_config.NumberColumn(
                "MM Presence",
                format="%.1f",
                help="Coinbase spot liquidity-sponsor proxy: tight spread, 2% order-book depth, balanced quoting, and Coinbase spot share.",
            ),
            "mm_bid_support_score": st.column_config.NumberColumn(
                "CB Bid Support",
                format="%.1f",
                help="Scores whether Coinbase spot bids are unusually supportive versus asks and volume. Useful for sponsored squeeze mechanics.",
            ),
            "mm_withdrawal_risk_score": st.column_config.NumberColumn(
                "MM Pull Risk",
                format="%.1f",
                help="Higher means the Coinbase liquidity sponsor looks weak, one-sided, or easier to pull while owner/venue concentration risk is high.",
            ),
            "mm_proximity_score": st.column_config.NumberColumn(
                "MM Proximity",
                format="%.1f",
                help="Manual social-graph / relationship signal. Use for founder/MM proximity, venue sponsorship, advisor links, or credible desk breadcrumbs.",
            ),
            "dwf_labs_portfolio": st.column_config.CheckboxColumn(
                "DWF Labs",
                help="True when CoinGecko currently lists the asset in the DWF Labs portfolio category.",
            ),
            "dwf_labs_portfolio_score": st.column_config.NumberColumn(
                "DWF Score",
                format="%.1f",
                help="Sponsor-proximity score from CoinGecko's DWF Labs portfolio category. Confluence, not proof of misconduct.",
            ),
            "dwf_labs_portfolio_rank": st.column_config.NumberColumn("DWF Rank", format="%.0f"),
            "dwf_labs_portfolio_note": st.column_config.TextColumn("DWF Note"),
            "mm_proximity_maker": st.column_config.TextColumn(
                "MM Hint",
                help="Market maker, venue, desk, or relationship label behind the manual proximity signal.",
            ),
            "mm_proximity_note": st.column_config.TextColumn(
                "MM Note",
                help="Human-readable note for the manual proximity signal. Treat as confluence, not proof.",
            ),
            "mm_proximity_source": st.column_config.TextColumn(
                "MM Source",
                help="Optional URL for the social graph / market maker relationship breadcrumb.",
            ),
            "inventory_transfer_risk_score": st.column_config.NumberColumn(
                "OTC Inv Risk",
                format="%.1f",
                help="Proxy for off-exchange inventory transfer risk: MM proximity, controlled float, venue concentration, volume-to-market-cap pressure, and visible-depth mismatch.",
            ),
            "inventory_sponsor_mismatch_score": st.column_config.NumberColumn(
                "Sponsor Mismatch",
                format="%.1f",
                help="Higher when spot/perp volume is huge versus market cap but public Coinbase depth looks small or concentrated.",
            ),
            "inventory_transfer_risk_flag": st.column_config.CheckboxColumn(
                "OTC Inv Flag",
                help="True when the off-exchange inventory-transfer fingerprint crosses the configured composite threshold.",
            ),
            "inventory_transfer_note": st.column_config.TextColumn(
                "OTC Inv Note",
                help="Short explanation of the inventory-transfer risk fingerprint. It is not proof of off-exchange token swaps.",
            ),
            "spot_volume_to_mcap_pct": st.column_config.NumberColumn(
                "Spot Vol/MCap",
                format="%.1f%%",
                help="External spot volume divided by CoinGecko market cap. Very high values can indicate aggressive inventory rotation.",
            ),
            "perp_volume_to_mcap_pct": st.column_config.NumberColumn(
                "Perp Vol/MCap",
                format="%.1f%%",
                help="Binance futures 24h volume divided by CoinGecko market cap.",
            ),
            "oi_to_market_cap_pct": st.column_config.NumberColumn(
                "OI/MCap",
                format="%.1f%%",
                help="Binance futures open interest notional divided by CoinGecko market cap.",
            ),
            "venue_concentration_score": st.column_config.NumberColumn(
                "Venue Conc.",
                format="%.1f",
                help="Higher when volume is dominated by one or a few venues.",
            ),
            "crime_excluded_major": st.column_config.CheckboxColumn(
                "Major Excluded",
                help="True when the base asset is in the configured major-exclusion list for structure scans.",
            ),
            "crime_seed_score": st.column_config.NumberColumn(
                "Structure Seed",
                format="%.1f",
                help="Pre-scan ranking score used to choose which non-major symbols receive the expensive structure diagnostics.",
            ),
            "spot_external_quote_volume_24h": st.column_config.NumberColumn(
                "Ext Spot Vol",
                format="$%.0f",
                help="Coinbase plus Binance spot quote volume where public endpoints have the pair.",
            ),
            "coinbase_spot_quote_volume_24h": st.column_config.NumberColumn(
                "Coinbase Spot Vol",
                format="$%.0f",
                help="Coinbase public 24h spot quote volume across USD/USDC/USDT pairs when listed.",
            ),
            "coingecko_total_volume_24h": st.column_config.NumberColumn("CG Total Vol", format="$%.0f"),
            "coingecko_cex_volume_24h": st.column_config.NumberColumn(
                "CEX Vol",
                format="$%.0f",
                help="CoinGecko ticker volume classified as centralized-exchange volume.",
            ),
            "coingecko_dex_volume_24h": st.column_config.NumberColumn("DEX Vol", format="$%.0f"),
            "kraken_spot_quote_volume_24h": st.column_config.NumberColumn("Kraken Vol", format="$%.0f"),
            "upbit_spot_quote_volume_24h": st.column_config.NumberColumn("Upbit Vol", format="$%.0f"),
            "upbit_krw_quote_volume_24h": st.column_config.NumberColumn("Upbit KRW Vol", format="$%.0f"),
            "try_spot_quote_volume_24h": st.column_config.NumberColumn("TRY Vol", format="$%.0f"),
            "emfx_spot_quote_volume_24h": st.column_config.NumberColumn(
                "EMFX Vol",
                format="$%.0f",
                help="CoinGecko ticker volume quoted in EMFX lanes such as KRW and TRY.",
            ),
            "coinbase_volume_share_pct": st.column_config.NumberColumn("CB Vol Share", format="%.1f%%"),
            "binance_volume_share_pct": st.column_config.NumberColumn("Binance Share", format="%.1f%%"),
            "bitget_volume_share_pct": st.column_config.NumberColumn("Bitget Share", format="%.1f%%"),
            "gate_volume_share_pct": st.column_config.NumberColumn("Gate Share", format="%.1f%%"),
            "okx_volume_share_pct": st.column_config.NumberColumn("OKX Share", format="%.1f%%"),
            "cex_volume_share_pct": st.column_config.NumberColumn(
                "CEX Share",
                format="%.1f%%",
                help="CEX volume divided by CEX plus DEX volume. High values mean spot activity is mostly centralized venues.",
            ),
            "cex_to_dex_volume_ratio": st.column_config.NumberColumn(
                "CEX/DEX",
                format="%.2f",
                help="CEX volume divided by DEX volume. Very high ratios can indicate venue-supported flow rather than organic on-chain liquidity.",
            ),
            "cex_dex_volume_ratio_score": st.column_config.NumberColumn(
                "CEX/DEX Score",
                format="%.1f",
                help="Log-scaled CEX/DEX dominance score. It is a market-structure / squeeze-risk anomaly signal, not proof of misconduct.",
            ),
            "kraken_volume_share_pct": st.column_config.NumberColumn("Kraken Share", format="%.1f%%"),
            "upbit_volume_share_pct": st.column_config.NumberColumn("Upbit Share", format="%.1f%%"),
            "krw_volume_share_pct": st.column_config.NumberColumn("KRW Share", format="%.1f%%"),
            "try_volume_share_pct": st.column_config.NumberColumn("TRY Share", format="%.1f%%"),
            "emfx_volume_share_pct": st.column_config.NumberColumn(
                "EMFX Share",
                format="%.1f%%",
                help="Share of spot volume quoted in EMFX lanes such as KRW and TRY. Useful for spotting non-USD lane sponsorship.",
            ),
            "dex_volume_share_pct": st.column_config.NumberColumn("DEX Vol Share", format="%.1f%%"),
            "binance_bitget_gate_share_pct": st.column_config.NumberColumn(
                "B/B/G Share",
                format="%.1f%%",
                help="Combined CoinGecko spot-volume share from Binance, Bitget, and Gate.io. High values mean a small venue cluster owns the tape.",
            ),
            "binance_bitget_gate_share_score": st.column_config.NumberColumn(
                "B/B/G Score",
                format="%.1f",
                help="Scaled version of the Binance+Bitget+Gate share, used as a venue-cluster anomaly signal.",
            ),
            "top_venue": st.column_config.TextColumn("Top Venue"),
            "top_venue_volume_share_pct": st.column_config.NumberColumn("Top Venue %", format="%.1f%%"),
            "top3_venue_volume_share_pct": st.column_config.NumberColumn("Top3 Venue %", format="%.1f%%"),
            "venue_hhi": st.column_config.NumberColumn(
                "Venue HHI",
                format="%.0f",
                help="Herfindahl-style venue concentration index computed from CoinGecko ticker shares. Higher means fewer venues dominate the flow.",
            ),
            "venue_hhi_score": st.column_config.NumberColumn(
                "Venue HHI Score",
                format="%.1f",
                help="Scaled venue concentration score derived from the spot-volume HHI.",
            ),
            "venue_count": st.column_config.NumberColumn("Venues", format="%d"),
            "emfx_lane_score": st.column_config.NumberColumn(
                "EMFX Lane",
                format="%.1f",
                help="Composite KRW/TRY/EMFX quote-lane score. High values mean the move is being carried in non-USD quote lanes.",
            ),
            "coinbase_bid_ask_spread_pct": st.column_config.NumberColumn("CB Spread", format="%.2f%%"),
            "coinbase_bid_depth_2pct_usd": st.column_config.NumberColumn("CB Bid Depth 2%", format="$%.0f"),
            "coinbase_ask_depth_2pct_usd": st.column_config.NumberColumn("CB Ask Depth 2%", format="$%.0f"),
            "coinbase_total_depth_2pct_usd": st.column_config.NumberColumn(
                "CB Depth 2%",
                format="$%.0f",
                help="Live Coinbase Exchange level-2 bid plus ask notional within 2% of mid across USD/USDC/USDT products.",
            ),
            "coinbase_book_imbalance_pct": st.column_config.NumberColumn(
                "CB Book Bid %",
                format="%.1f%%",
                help="Coinbase 2% book imbalance: bid depth divided by total bid+ask depth. Above 50% means bid-heavy.",
            ),
            "coinbase_depth_to_volume_pct": st.column_config.NumberColumn(
                "CB Depth/CB Vol",
                format="%.2f%%",
                help="Coinbase 2% depth divided by Coinbase 24h spot volume. Higher suggests stickier sponsor liquidity.",
            ),
            "coinbase_depth_to_perp_volume_pct": st.column_config.NumberColumn(
                "CB Depth/Perp Vol",
                format="%.2f%%",
                help="Coinbase 2% spot depth divided by Binance futures 24h quote volume.",
            ),
            "binance_spot_quote_volume_24h": st.column_config.NumberColumn(
                "Binance Spot Vol",
                format="$%.0f",
                help="Binance public spot 24h quote volume for the normalized base asset.",
            ),
            "spot_to_perp_volume_pct": st.column_config.NumberColumn(
                "Spot/Perp Vol",
                format="%.1f%%",
                help="External spot volume divided by Binance futures 24h quote volume. Higher can indicate real spot sponsorship.",
            ),
            "coinbase_to_perp_volume_pct": st.column_config.NumberColumn(
                "CB/Perp Vol",
                format="%.1f%%",
                help="Coinbase spot volume divided by Binance futures 24h quote volume.",
            ),
            "coinbase_spot_listed": st.column_config.CheckboxColumn(
                "Coinbase Spot",
                help="Whether Coinbase Exchange has an online USD/USDC/USDT spot market for this base.",
            ),
            "market_cap_usd": st.column_config.NumberColumn("Mkt Cap", format="$%.0f"),
            "fdv_usd": st.column_config.NumberColumn("FDV", format="$%.0f"),
            "fdv_to_market_cap": st.column_config.NumberColumn("FDV/MCap", format="%.2f"),
            "circulating_supply_pct": st.column_config.NumberColumn("Circ Supply", format="%.1f%%"),
            "locked_supply_pct": st.column_config.NumberColumn(
                "Locked/Unrel.",
                format="%.1f%%",
                help="100 minus circulating supply share using CoinGecko total/max supply. This is a float proxy, not exact insider ownership.",
            ),
            "top10_holder_pct": st.column_config.NumberColumn(
                "Top10 Holders",
                format="%.1f%%",
                help="GoPlus top-10 holder concentration when an EVM contract is available.",
            ),
            "owner_holder_pct": st.column_config.NumberColumn("Owner Hold", format="%.1f%%"),
            "creator_holder_pct": st.column_config.NumberColumn("Creator Hold", format="%.1f%%"),
            "holder_count": st.column_config.NumberColumn("Holders", format="%.0f"),
            "market_type": st.column_config.TextColumn("Market Type"),
            "history_days": st.column_config.NumberColumn("History (D)", format="%d"),
            "corr_window_days": st.column_config.NumberColumn("Corr Window (D)", format="%d"),
            "corr_to_btc_6m": st.column_config.NumberColumn("Corr to BTC (Max 180D)", format="%.3f"),
            "funding_interval_hours": st.column_config.NumberColumn("Funding Int. (H)", format="%d"),
            "funding_countdown_hours": st.column_config.NumberColumn(
                "Next Funding In",
                format="%.2f h",
                help="Hours remaining until the next Binance funding settlement.",
            ),
            "carry_funding_pct": st.column_config.NumberColumn(
                "Est. Funding",
                format="%.4f%%",
                help="Binance's live estimated funding rate from the mark-price snapshot. Positive means longs pay shorts; negative means shorts pay longs.",
            ),
            "carry_funding_annualized_pct": st.column_config.NumberColumn(
                "Est. Funding Ann.",
                format="%.2f%%",
                help="Binance's live estimated funding rate annualized using the symbol's current settlement interval.",
            ),
            "long_carry_pct": st.column_config.NumberColumn(
                "Long Carry (Est.)",
                format="%.4f%%",
                help="Binance estimated funding from the long-position perspective. Positive means a long would receive funding; negative means a long would pay funding.",
            ),
            "long_carry_annualized_pct": st.column_config.NumberColumn(
                "Long Carry Ann. (Est.)",
                format="%.2f%%",
                help="Binance estimated long carry annualized using the symbol's current settlement interval.",
            ),
            "premium_index_pct": st.column_config.NumberColumn(
                "Premium Idx",
                format="%.4f%%",
                help="Latest premium snapshot, refined by websocket when available.",
            ),
            "predicted_funding_pct": st.column_config.NumberColumn(
                "Modeled Funding",
                format="%.4f%%",
                help="Our custom modeled funding estimate using the current premium window, a short websocket refinement, and recent settled funding backtests. This is not Binance's official estimate.",
            ),
            "predicted_funding_annualized_pct": st.column_config.NumberColumn(
                "Modeled Funding Ann.",
                format="%.2f%%",
                help="Our custom modeled funding estimate annualized using the symbol's current settlement interval.",
            ),
            "predicted_long_carry_pct": st.column_config.NumberColumn(
                "Modeled Long Carry",
                format="%.4f%%",
                help="Modeled next funding from the long-position perspective. Positive means a long would receive; negative means a long would pay.",
            ),
            "predicted_long_carry_annualized_pct": st.column_config.NumberColumn(
                "Modeled Long Carry Ann.",
                format="%.2f%%",
                help="Predicted long carry annualized using the symbol's current settlement interval.",
            ),
            "predicted_funding_low_pct": st.column_config.NumberColumn(
                "Model Low",
                format="%.4f%%",
                help="Lower bound of the predicted funding band using recent model error.",
            ),
            "predicted_funding_high_pct": st.column_config.NumberColumn(
                "Model High",
                format="%.4f%%",
                help="Upper bound of the predicted funding band using recent model error.",
            ),
            "predicted_funding_band_pct": st.column_config.NumberColumn(
                "Model Band +/-",
                format="%.4f%%",
                help="Radius of the displayed funding band based on recent out-of-sample model error.",
            ),
            "predicted_funding_backtest_mae_pct": st.column_config.NumberColumn(
                "Model MAE",
                format="%.4f%%",
                help="Mean absolute error of recent funding backtests for this symbol.",
            ),
            "predicted_funding_backtest_count": st.column_config.NumberColumn(
                "Model N",
                format="%d",
                help="Number of settled funding windows used for the recent backtest calibration.",
            ),
            "funding_window_elapsed_pct": st.column_config.NumberColumn(
                "Window Elapsed",
                format="%.0f%%",
                help="How much of the current funding window has elapsed. Higher values usually make the estimate more informative.",
            ),
            "long_short_account_ratio": st.column_config.NumberColumn(
                "L/S Acct Ratio",
                format="%.2f",
                help="Binance global long/short account ratio for this symbol. This is account-count based, not position-size based.",
            ),
            "long_account_pct": st.column_config.NumberColumn(
                "Long Accts",
                format="%.1f%%",
                help="Share of Binance accounts net long this symbol for the selected long/short ratio period.",
            ),
            "short_account_pct": st.column_config.NumberColumn(
                "Short Accts",
                format="%.1f%%",
                help="Share of Binance accounts net short this symbol for the selected long/short ratio period.",
            ),
            "short_account_history_points": st.column_config.NumberColumn(
                "Short Hist N",
                format="%d",
                help="Number of Binance global long/short account rows used for short-account change calculations.",
            ),
            "short_account_change_1p_pct": st.column_config.NumberColumn("Short Δ 1p", format="%.2f%%"),
            "short_account_change_1p_pp": st.column_config.NumberColumn("Short Δ 1p pp", format="%.2f pp"),
            "short_account_previous_1h_pct": st.column_config.NumberColumn("Prev Short 1h", format="%.1f%%"),
            "short_account_roc_1h_pct": st.column_config.NumberColumn(
                "Short ROC 1h",
                format="%.2f%%",
                help="Relative change in Binance global short-account share over the last 1h account-ratio step.",
            ),
            "short_account_roc_1h_pp": st.column_config.NumberColumn(
                "Short ROC 1h pp",
                format="%.2f pp",
                help="Percentage-point change in Binance global short-account share over the last 1h account-ratio step.",
            ),
            "short_account_roc_1h_abs_pp": st.column_config.NumberColumn(
                "Abs ROC 1h pp",
                format="%.2f pp",
                help="Absolute percentage-point move in short-account share over the last 1h account-ratio step.",
            ),
            "short_account_roc_1h_direction": st.column_config.TextColumn("1h Direction"),
            "short_account_roc_smoothed_3p_pp": st.column_config.NumberColumn(
                "Short ROC Smooth",
                format="%.2f pp",
                help="Mean one-step short-account percentage-point change across the latest three observations.",
            ),
            "short_account_roc_smoothed_3p_pct": st.column_config.NumberColumn(
                "Short ROC Smooth %",
                format="%.2f%%",
                help="Mean relative short-account change across the latest three observations.",
            ),
            "short_account_acceleration_1h_pp": st.column_config.NumberColumn(
                "Short Accel 1h",
                format="%.2f pp",
                help="Latest change in the one-step short-account percentage-point rate of change.",
            ),
            "short_account_acceleration_smoothed_3p_pp": st.column_config.NumberColumn(
                "Short Accel Smooth",
                format="%.2f pp",
                help="Three-observation mean of short-account acceleration to reduce single-print noise.",
            ),
            "short_account_roc_zscore": st.column_config.NumberColumn(
                "Short ROC Z",
                format="%.2f",
                help="Latest one-step short-account move standardized against the token's prior observed changes.",
            ),
            "short_account_direction_persistence": st.column_config.NumberColumn(
                "Short Persist",
                format="%d",
                help="Consecutive observations in the current short-account build or cover direction.",
            ),
            "short_account_change_3p_pct": st.column_config.NumberColumn("Short Δ 3p", format="%.2f%%"),
            "short_account_change_3p_pp": st.column_config.NumberColumn("Short Δ 3p pp", format="%.2f pp"),
            "short_account_change_6p_pct": st.column_config.NumberColumn("Short Δ 6p", format="%.2f%%"),
            "short_account_change_6p_pp": st.column_config.NumberColumn("Short Δ 6p pp", format="%.2f pp"),
            "short_account_change_12p_pct": st.column_config.NumberColumn("Short Δ 12p", format="%.2f%%"),
            "short_account_change_12p_pp": st.column_config.NumberColumn("Short Δ 12p pp", format="%.2f pp"),
            "short_account_change_24p_pct": st.column_config.NumberColumn("Short Δ 24p", format="%.2f%%"),
            "short_account_change_24p_pp": st.column_config.NumberColumn("Short Δ 24p pp", format="%.2f pp"),
            "short_account_change_max_pct": st.column_config.NumberColumn(
                "Max Short Δ",
                format="%.2f%%",
                help="Largest positive relative change in short-account share across the configured lookback windows.",
            ),
            "short_account_change_max_pp": st.column_config.NumberColumn(
                "Max Short Δ pp",
                format="%.2f pp",
                help="Largest positive percentage-point change in short-account share across the configured lookback windows.",
            ),
            "short_account_change_max_window": st.column_config.TextColumn("Max Short Δ Window"),
            "short_account_change_min_pct": st.column_config.NumberColumn(
                "Min Short Δ",
                format="%.2f%%",
                help="Most negative relative change in short-account share across the configured lookback windows.",
            ),
            "short_account_change_min_pp": st.column_config.NumberColumn(
                "Min Short Δ pp",
                format="%.2f pp",
                help="Most negative percentage-point change in short-account share across the configured lookback windows.",
            ),
            "short_account_change_min_window": st.column_config.TextColumn("Min Short Δ Window"),
            "hour_return_pct": st.column_config.NumberColumn("1H Return", format="%.2f%%"),
            "hour_return_z": st.column_config.NumberColumn(
                "1H Return Z",
                format="%.2f",
                help="Latest closed 1-hour return normalized by the recent hourly return distribution.",
            ),
            "day_return_pct": st.column_config.NumberColumn("24H Return", format="%.2f%%"),
            "hour_quote_volume": st.column_config.NumberColumn("1H Quote Vol", format="$%.0f"),
            "hour_quote_volume_previous_1h": st.column_config.NumberColumn("Prev 1H Quote Vol", format="$%.0f"),
            "hour_volume_roc_1h_pct": st.column_config.NumberColumn(
                "1H Volume ROC",
                format="%.2f%%",
                help="Quote-volume rate of change from the preceding closed 1-hour window to the latest closed 1-hour window.",
            ),
            "hour_volume_multiple": st.column_config.NumberColumn(
                "1H Vol x",
                format="%.2fx",
                help="Latest closed 1-hour quote volume versus the prior 24-hour average hourly quote volume.",
            ),
            "hour_trade_count_multiple": st.column_config.NumberColumn(
                "1H Trades x",
                format="%.2fx",
                help="Latest closed 1-hour trade count versus the prior 24-hour average hourly trade count.",
            ),
            "hour_upper_wick_pct": st.column_config.NumberColumn(
                "Upper Wick",
                format="%.1f%%",
                help="Upper-wick size as a share of the latest closed hourly candle range. Higher often means blowoff/exhaustion.",
            ),
            "hour_close_location_pct": st.column_config.NumberColumn(
                "Close in Range",
                format="%.1f%%",
                help="Where the latest closed hourly candle finished inside its range. Near 100% means it closed near the high.",
            ),
            "oi_value_usdt": st.column_config.NumberColumn("OI Value", format="$%.0f"),
            "oi_delta_pct": st.column_config.NumberColumn(
                "OI Delta",
                format="%.2f%%",
                help="Change in open-interest notional value over the structure scan period.",
            ),
            "oi_to_24h_volume_pct": st.column_config.NumberColumn(
                "OI / 24H Vol",
                format="%.2f%%",
                help="Open-interest notional divided by 24-hour quote volume.",
            ),
            "taker_buy_sell_ratio": st.column_config.NumberColumn(
                "Taker B/S",
                format="%.2f",
                help="Aggressive buy volume divided by aggressive sell volume over the structure scan period.",
            ),
            "taker_buy_share_pct": st.column_config.NumberColumn("Taker Buy %", format="%.1f%%"),
            "top_trader_position_ratio": st.column_config.NumberColumn(
                "Top Pos L/S",
                format="%.2f",
                help="Top-trader long/short ratio based on positions.",
            ),
            "top_trader_long_position_pct": st.column_config.NumberColumn("Top Pos Long %", format="%.1f%%"),
            "top_trader_account_ratio": st.column_config.NumberColumn(
                "Top Acct L/S",
                format="%.2f",
                help="Top-trader long/short ratio based on accounts.",
            ),
            "top_trader_long_account_pct": st.column_config.NumberColumn("Top Acct Long %", format="%.1f%%"),
            "crowd_top_position_divergence_pct": st.column_config.NumberColumn(
                "Crowd-Top Div",
                format="%.1f pp",
                help="Global long-account share minus top-trader long-position share. Positive means crowd is more long than top traders.",
            ),
            "crowd_top_account_divergence_pct": st.column_config.NumberColumn(
                "Crowd-Top Acct Div",
                format="%.1f pp",
                help="Global long-account share minus top-trader long-account share.",
            ),
            "basis_rate_pct": st.column_config.NumberColumn(
                "Basis Rate",
                format="%.3f%%",
                help="Perpetual basis rate over the selected structure scan period.",
            ),
            "basis_usdt": st.column_config.NumberColumn("Basis", format="%.4f"),
            "ask_depth_1pct_usdt": st.column_config.NumberColumn(
                "Ask Depth 1%",
                format="$%.0f",
                help="Visible ask-side notional within 1% above the mid price.",
            ),
            "ask_depth_to_24h_volume_pct": st.column_config.NumberColumn(
                "Ask Depth / 24H Vol",
                format="%.2f%%",
                help="Visible ask-side 1% depth divided by 24-hour quote volume. Lower means a thinner book.",
            ),
            "crime_carry_stress_score": st.column_config.NumberColumn("Carry Stress", format="%.1f"),
            "crime_pump_score": st.column_config.NumberColumn(
                "Structure Score",
                format="%.1f",
                help="Composite stress score using 1H velocity, volume spike, OI expansion, carry/basis stress, taker aggression, crowd divergence, and book thinness.",
            ),
            "crime_ignition_score": st.column_config.NumberColumn(
                "Ignition Score",
                format="%.1f",
                help="Earlier-stage squeeze/ignition score emphasizing momentum, OI expansion, taker aggression, trade-count expansion, and close-near-high behavior.",
            ),
            "crime_exhaustion_score": st.column_config.NumberColumn(
                "Exhaustion Score",
                format="%.1f",
                help="Later-stage blowoff score emphasizing wickiness, carry stress, crowding, OI fade, and leverage saturation.",
            ),
            "terminal_edge_score": st.column_config.NumberColumn(
                "Terminal Edge",
                format="%.1f",
                help="Evidence score combining float, shorts, ignition, runway, regime, liquidity reality, and late-stage risk.",
            ),
            "terminal_structure_edge_score": st.column_config.NumberColumn(
                "Structure Edge",
                format="%.1f",
                help="Control-plane, pre-ignition, distribution pressure, short-fuel, and liquidity confluence before late-stage decay.",
            ),
            "terminal_control_plane_score": st.column_config.NumberColumn("Control Plane", format="%.1f"),
            "terminal_distribution_pressure_score": st.column_config.NumberColumn("Distribution Pressure", format="%.1f"),
            "terminal_pre_ignition_quality_score": st.column_config.NumberColumn("Pre-Ignition Quality", format="%.1f"),
            "archetype_match_score": st.column_config.NumberColumn("Archetype Match", format="%.1f"),
            "archetype_best_match": st.column_config.TextColumn("Best Case-Study Analogue"),
            "archetype_match_note": st.column_config.TextColumn("Archetype Note"),
            "archetype_reference_symbol": st.column_config.TextColumn("Historical Anchor"),
            "archetype_reference_date": st.column_config.TextColumn("Anchor Date"),
            "archetype_reference_pattern": st.column_config.TextColumn("Anchor Fingerprint"),
            "archetype_rave_score": st.column_config.NumberColumn("RAVE-Style", format="%.1f"),
            "archetype_lab_score": st.column_config.NumberColumn("LAB-Style", format="%.1f"),
            "archetype_siren_score": st.column_config.NumberColumn("SIREN-Style", format="%.1f"),
            "archetype_river_score": st.column_config.NumberColumn("RIVER-Style", format="%.1f"),
            "archetype_sto_score": st.column_config.NumberColumn("STO-Style", format="%.1f"),
            "early_pump_radar_score": st.column_config.NumberColumn(
                "Pump Radar",
                format="%.1f",
                help="Composite early-structure score for target CEX flow, whale/control, low float, squeeze fuel, timing, venue support, and not-late risk.",
            ),
            "early_pump_flow_score": st.column_config.NumberColumn("Pump Flow", format="%.1f"),
            "early_pump_whale_score": st.column_config.NumberColumn("Pump Whale", format="%.1f"),
            "early_pump_float_score": st.column_config.NumberColumn("Pump Float", format="%.1f"),
            "early_pump_short_squeeze_score": st.column_config.NumberColumn("Pump Squeeze", format="%.1f"),
            "early_pump_timing_score": st.column_config.NumberColumn("Pump Timing", format="%.1f"),
            "early_pump_venue_score": st.column_config.NumberColumn("Pump Venue", format="%.1f"),
            "early_pump_archetype_score": st.column_config.NumberColumn("Pump Analogue", format="%.1f"),
            "early_pump_not_late_score": st.column_config.NumberColumn("Pump Not Late", format="%.1f"),
            "early_pump_confirmed_target_flow": st.column_config.CheckboxColumn("Target Flow"),
            "early_pump_holder_evidence_gate": st.column_config.CheckboxColumn("Holder Evidence"),
            "early_pump_whale_gate": st.column_config.CheckboxColumn("Top10 Whale Gate"),
            "early_pump_short_gate": st.column_config.CheckboxColumn("Short Gate"),
            "early_pump_float_gate": st.column_config.CheckboxColumn("Float Gate"),
            "early_pump_binance_bitget_gate": st.column_config.CheckboxColumn("Binance+Bitget"),
            "early_pump_venue_gate": st.column_config.CheckboxColumn("Venue Gate"),
            "early_pump_not_late_gate": st.column_config.CheckboxColumn("Not-Late Gate"),
            "early_pump_no_recent_pump_gate": st.column_config.CheckboxColumn("60D No Pump"),
            "early_pump_alert_flag": st.column_config.CheckboxColumn("Pump Watch"),
            "early_pump_state": st.column_config.TextColumn("Pump State"),
            "early_pump_primary_signal": st.column_config.TextColumn("Pump Signal"),
            "early_pump_next_check": st.column_config.TextColumn("Pump Next Check"),
            "early_pump_note": st.column_config.TextColumn("Pump Note"),
            "pre_activity_pump_score": st.column_config.NumberColumn(
                "Pre-Activity Score",
                format="%.1f",
                help="Latent setup score for controlled float, target-CEX inventory tells, short-fuse perp positioning, thin books, and quiet tape before obvious activity.",
            ),
            "pre_activity_control_score": st.column_config.NumberColumn("Pre-Control", format="%.1f"),
            "pre_activity_float_score": st.column_config.NumberColumn("Pre-Float", format="%.1f"),
            "pre_activity_behavior_score": st.column_config.NumberColumn("Pre-CEX Tell", format="%.1f"),
            "pre_activity_short_fuse_score": st.column_config.NumberColumn("Pre-Short Fuse", format="%.1f"),
            "pre_activity_quiet_score": st.column_config.NumberColumn("Pre-Quiet", format="%.1f"),
            "pre_activity_venue_score": st.column_config.NumberColumn("Pre-Venue", format="%.1f"),
            "pre_activity_thin_book_score": st.column_config.NumberColumn("Pre-Thin Book", format="%.1f"),
            "pre_activity_preignition_score": st.column_config.NumberColumn("Pre-Ignition Base", format="%.1f"),
            "pre_activity_heat_score": st.column_config.NumberColumn("Activity Heat", format="%.1f"),
            "pre_activity_confirmed_target_flow": st.column_config.CheckboxColumn("Pre Target Flow"),
            "pre_activity_holder_evidence_gate": st.column_config.CheckboxColumn("Pre Holder Evidence"),
            "pre_activity_whale_gate": st.column_config.CheckboxColumn("Pre Top10 Whale"),
            "pre_activity_binance_bitget_gate": st.column_config.CheckboxColumn("Pre Binance+Bitget"),
            "pre_activity_structure_gate": st.column_config.CheckboxColumn("Pre Structure"),
            "pre_activity_behavior_gate": st.column_config.CheckboxColumn("Pre Behaviour"),
            "pre_activity_quiet_gate": st.column_config.CheckboxColumn("Pre Quiet Gate"),
            "pre_activity_no_recent_pump_gate": st.column_config.CheckboxColumn("Pre 60D No Pump"),
            "pre_activity_alert_flag": st.column_config.CheckboxColumn("Pre-Activity Watch"),
            "pre_activity_state": st.column_config.TextColumn("Pre-Activity State"),
            "pre_activity_primary_signal": st.column_config.TextColumn("Pre-Activity Signal"),
            "pre_activity_next_check": st.column_config.TextColumn("Pre-Activity Next Check"),
            "pre_activity_note": st.column_config.TextColumn("Pre-Activity Note"),
            "terminal_regime_score": st.column_config.NumberColumn("Regime", format="%.1f"),
            "terminal_liquidity_score": st.column_config.NumberColumn("Liquidity Reality", format="%.1f"),
            "terminal_float_score": st.column_config.NumberColumn("Float Evidence", format="%.1f"),
            "terminal_short_pressure_score": st.column_config.NumberColumn("Short Evidence", format="%.1f"),
            "terminal_ignition_score": st.column_config.NumberColumn("Ignition Evidence", format="%.1f"),
            "terminal_runway_score": st.column_config.NumberColumn("Runway Evidence", format="%.1f"),
            "terminal_opaque_supply_score": st.column_config.NumberColumn(
                "Opaque Supply",
                format="%.1f",
                help="Private/unclear supply-path evidence: incomplete distribution data, issuer-linked supply estimates, and hidden-float markers.",
            ),
            "terminal_exchange_flow_score": st.column_config.NumberColumn(
                "CEX Flow",
                format="%.1f",
                help="Concentration-gated CEX-flow evidence from large recent token transfers into labelled exchange wallets when available.",
            ),
            "cex_deposit_flow_score": st.column_config.NumberColumn(
                "Recent CEX Flow",
                format="%.1f",
                help="Large labelled CEX deposits found only after the holder concentration gate is met.",
            ),
            "cex_deposit_flow_flag": st.column_config.CheckboxColumn("Recent CEX Flow Flag"),
            "cex_deposit_flow_risk_level": st.column_config.TextColumn("Flow Risk"),
            "cex_deposit_24h_count": st.column_config.NumberColumn("CEX Deposits 24h", format="%d"),
            "cex_deposit_24h_token_amount": st.column_config.NumberColumn("CEX Deposit Tokens 24h", format="%.2f"),
            "cex_deposit_24h_max_amount": st.column_config.NumberColumn("Largest CEX Deposit Tokens", format="%.2f"),
            "cex_deposit_24h_whale_sender_count": st.column_config.NumberColumn(
                "Top-Holder Sender Tx",
                format="%d",
                help="Number of labelled CEX deposits whose sender matched a scanned top-holder wallet.",
            ),
            "cex_deposit_24h_whale_sender_token_amount": st.column_config.NumberColumn(
                "Whale-Origin Tokens 24h",
                format="%.2f",
                help="Total 24h token amount sent into labelled CEX wallets by matched top-holder wallets.",
            ),
            "cex_deposit_24h_whale_sender_max_amount": st.column_config.NumberColumn(
                "Largest Whale-Origin Tokens",
                format="%.2f",
                help="Largest single labelled CEX deposit from a matched top-holder wallet.",
            ),
            "cex_deposit_24h_top_sender_rank": st.column_config.NumberColumn(
                "Top Sender Rank",
                format="%.0f",
                help="Holder-table rank for the largest matched CEX-deposit sender.",
            ),
            "cex_deposit_24h_top_sender_pct": st.column_config.NumberColumn(
                "Top Sender Holder %",
                format="%.2f%%",
                help="Holder-table ownership percentage for the largest matched CEX-deposit sender.",
            ),
            "cex_deposit_24h_top_sender_address": st.column_config.TextColumn(
                "Top Sender Wallet",
                help="Wallet address for the largest matched top-holder-origin CEX deposit.",
            ),
            "cex_deposit_24h_notional_usd": st.column_config.NumberColumn("CEX Deposit Notional", format="$%.0f"),
            "cex_deposit_24h_max_notional_usd": st.column_config.NumberColumn("Largest Deposit Notional", format="$%.0f"),
            "cex_deposit_24h_total_pct_supply": st.column_config.NumberColumn("CEX Deposits % Supply", format="%.2f%%"),
            "cex_deposit_24h_max_pct_supply": st.column_config.NumberColumn("Largest CEX Deposit % Supply", format="%.2f%%"),
            "cex_deposit_24h_notional_to_ask_depth_pct": st.column_config.NumberColumn(
                "Deposits / 1% Ask Depth",
                format="%.1f%%",
                help="Recent labelled CEX deposit notional divided by visible 1% ask depth.",
            ),
            "cex_deposit_24h_max_notional_to_ask_depth_pct": st.column_config.NumberColumn(
                "Largest Deposit / 1% Ask Depth",
                format="%.1f%%",
                help="Largest labelled CEX deposit notional divided by visible 1% ask depth.",
            ),
            "cex_deposit_24h_notional_to_volume_pct": st.column_config.NumberColumn(
                "Deposits / 24H Volume",
                format="%.2f%%",
                help="Recent labelled CEX deposit notional divided by 24-hour quote volume.",
            ),
            "cex_deposit_inventory_stress_score": st.column_config.NumberColumn(
                "Inventory Stress",
                format="%.1f",
                help="Venue-inventory stress from recent CEX deposit notional versus visible liquidity and turnover.",
            ),
            "cex_deposit_inventory_stress_note": st.column_config.TextColumn("Inventory Stress Note"),
            "cex_deposit_24h_target_exchanges": st.column_config.TextColumn("CEX Deposit Targets"),
            "cex_deposit_concentration_gate": st.column_config.TextColumn("CEX Flow Gate"),
            "cex_deposit_flow_note": st.column_config.TextColumn("CEX Flow Note"),
            "cex_deposit_flow_evidence_summary": st.column_config.TextColumn("Flow Evidence"),
            "cex_deposit_flow_interpretation": st.column_config.TextColumn("Venue-Flow Read"),
            "cex_deposit_flow_next_check": st.column_config.TextColumn("Next Check"),
            "cex_deposit_flow_alert_line": st.column_config.TextColumn("Discord Alert Line"),
            "cex_deposit_flow_error": st.column_config.TextColumn("CEX Flow Error"),
            "cex_deposit_flow_source": st.column_config.TextColumn(
                "CEX Flow Path",
                help="Data path used for the wallet-to-CEX read, such as explorer Advanced Filter or token-transfer API fallback.",
            ),
            "cex_deposit_24h_source_url": st.column_config.LinkColumn("CEX Flow Source"),
            "terminal_private_unlock_score": st.column_config.NumberColumn(
                "Private Unlock",
                format="%.1f",
                help="Private unlock, OTC, cliff, vesting-opacity, or hidden-overhang evidence when available.",
            ),
            "terminal_information_asymmetry_score": st.column_config.NumberColumn("Info Asymmetry", format="%.1f"),
            "terminal_hidden_float_reflexivity_score": st.column_config.NumberColumn("Hidden Float Reflexivity", format="%.1f"),
            "terminal_risk_score": st.column_config.NumberColumn("Late Risk", format="%.1f"),
            "terminal_market_regime": st.column_config.TextColumn("Market Regime"),
            "terminal_liquidity_reality": st.column_config.TextColumn("Liquidity Reality"),
            "terminal_setup_archetype": st.column_config.TextColumn("Archetype"),
            "terminal_structural_opacity_note": st.column_config.TextColumn("Structural Opacity"),
            "terminal_structure_edge_note": st.column_config.TextColumn("Structure Edge Note"),
            "terminal_evidence_summary": st.column_config.TextColumn("Evidence Summary"),
            "terminal_confirmation_needed": st.column_config.TextColumn("Confirmation Needed"),
            "terminal_invalidation_map": st.column_config.TextColumn("Invalidation Map"),
            "terminal_case_study_key": st.column_config.TextColumn("Case Study Key"),
            "timing_score": st.column_config.NumberColumn(
                "Timing Score",
                format="%.1f",
                help="Short-horizon timing score: trigger quality, reclaim proximity, flow confirmation, early/not-late status, and liquidity sanity.",
            ),
            "timing_trigger_score": st.column_config.NumberColumn("Trigger", format="%.1f"),
            "timing_reclaim_score": st.column_config.NumberColumn("Reclaim", format="%.1f"),
            "timing_flow_score": st.column_config.NumberColumn("Flow", format="%.1f"),
            "timing_early_score": st.column_config.NumberColumn("Early", format="%.1f"),
            "timing_too_late_score": st.column_config.NumberColumn("Too Late", format="%.1f"),
            "timing_state": st.column_config.TextColumn("Timing State"),
            "timing_observed_trigger": st.column_config.TextColumn("Observed Trigger"),
            "timing_confirmation_needed": st.column_config.TextColumn("Timing Confirmation"),
            "timing_invalidation": st.column_config.TextColumn("Timing Invalidation"),
            "timing_failure_condition": st.column_config.TextColumn("Failure Condition"),
            "timing_hold_condition": st.column_config.TextColumn("Structure Relevant While"),
            "timing_liquidity_warning": st.column_config.TextColumn("Timing Liquidity"),
        }
        scan_mode_label = str(scan_mode)
        available_crypto_count = int(
            pd.to_numeric(all_df.get("available_crypto_perp_count"), errors="coerce").dropna().max()
        ) if "available_crypto_perp_count" in all_df.columns and not all_df.empty else 0
        scanned_symbol_count = int(len(all_df))
        coverage_pct = scanned_symbol_count / available_crypto_count * 100.0 if available_crypto_count else float("nan")
        if scan_mode_label == "All Short Account %":
            universe_label = (
                f"all {available_crypto_count} currently trading Binance USDT crypto perps; "
                f"returned {scanned_symbol_count} rows ({coverage_pct:.1f}% coverage)"
            )
        elif scan_mode_label == "Full ATH":
            universe_label = (
                f"up to {FULL_ATH_MAX_SYMBOLS_TO_SCAN} non-major ATH-runway candidates; "
                f"top {FULL_ATH_EXTERNAL_SYMBOLS_TO_SCAN} externally enriched"
            )
        elif scan_mode_label == "Deep":
            universe_label = (
                f"capped at {DEEP_MAX_TOTAL_SYMBOLS_TO_SCAN} total symbols; "
                f"top {DEEP_EXTERNAL_SYMBOLS_TO_SCAN} externally enriched; "
                f"includes top {MAX_SYMBOLS_TO_SCAN} volume perps plus up to "
                f"{min(ATH_RUNWAY_SYMBOLS_TO_SCAN, DEEP_ATH_SYMBOLS_TO_SCAN)} ATH-runway candidates"
            )
        else:
            universe_label = (
                f"top {FAST_MAX_SYMBOLS} crypto USDT perps by 24h quote volume, plus any open signed-account positions"
            )
        st.caption(
            f"Last scan: {_now_utc()} | Scan mode: {scan_mode_label} | "
            f"Universe scanned: {universe_label} | "
            f"Modeled funding: {'enabled' if ENABLE_MODELED_FUNDING and scan_mode_label == 'Deep' else 'off'} | "
            f"L/S ratio period: {LONG_SHORT_RATIO_PERIOD} (global Binance account ratio) | "
            f"Market-structure period: {CRIME_PUMP_PERIOD}"
        )
        try:
            _write_latest_convex_longs_cache(all_df, scan_mode=scan_mode_label)
        except Exception as exc:
            st.warning(f"Could not write latest Convex Long cache for Discord commands: {exc}")
        discord_alert_status = _maybe_notify_discord_convex_longs(
            all_df,
            scan_key=f"{scan_mode_label}:{st.session_state.get('breakout_refresh_nonce', 0)}",
            scan_mode=scan_mode_label,
        )
        if discord_alert_status:
            if discord_alert_status.startswith("Discord alert failed"):
                st.warning(discord_alert_status)
            else:
                st.info(discord_alert_status)

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Pairs scanned", int(len(all_df)))
        c2.metric("5D high breaks", int(all_df["broke_high_5d"].sum()) if not all_df.empty else 0)
        c3.metric("20D high breaks", int(all_df["broke_high_20d"].sum()) if not all_df.empty else 0)
        c4.metric("90D high breaks", int(all_df["broke_high_90d"].sum()) if not all_df.empty else 0)
        c5.metric("180D high breaks", int(all_df["broke_high_180d"].sum()) if not all_df.empty else 0)

        d1, d2, d3, d4 = st.columns(4)
        d1.metric("5D low breaks", int(all_df["broke_low_5d"].sum()) if not all_df.empty else 0)
        d2.metric("20D low breaks", int(all_df["broke_low_20d"].sum()) if not all_df.empty else 0)
        d3.metric("90D low breaks", int(all_df["broke_low_90d"].sum()) if not all_df.empty else 0)
        d4.metric("180D low breaks", int(all_df["broke_low_180d"].sum()) if not all_df.empty else 0)

        e1, e2, e3, e4 = st.columns(4)
        e1.metric("Structure signals", int(all_df["crime_pump_flag"].sum()) if not all_df.empty else 0)
        e2.metric("Ignition setups", int(all_df["ignition_setup_flag"].sum()) if not all_df.empty else 0)
        e3.metric("Exhaustion flags", int(all_df["exhaustion_flag"].sum()) if not all_df.empty else 0)
        median_pump_score = float(all_df["crime_pump_score"].median()) if not all_df.empty else 0.0
        e4.metric("Median structure score", f"{median_pump_score:.1f}")

        f1, f2, f3, f4 = st.columns(4)
        f1.metric("Pre-ignition", int(all_df["pre_pump_candidate_flag"].sum()) if not all_df.empty else 0)
        f2.metric("Convex prime", int(all_df["convexity_prime_flag"].sum()) if not all_df.empty else 0)
        f3.metric("Chase risk", int(all_df["convexity_chase_risk_flag"].sum()) if not all_df.empty else 0)
        median_convexity = float(all_df["convexity_entry_score"].median()) if not all_df.empty else 0.0
        f4.metric("Median entry score", f"{median_convexity:.1f}")

        g1, g2, g3, g4 = st.columns(4)
        runway_20x_count = int(all_df["ath_runway_20x_flag"].fillna(False).astype(bool).sum()) if not all_df.empty else 0
        max_ath_multiple = float(pd.to_numeric(all_df["ath_multiple"], errors="coerce").max()) if not all_df.empty else float("nan")
        confluence_median = float(pd.to_numeric(all_df["convexity_confluence_score"], errors="coerce").median()) if not all_df.empty else 0.0
        multi_mech_count = int((pd.to_numeric(all_df["convexity_confluence_count"], errors="coerce").fillna(0) >= 4).sum()) if not all_df.empty else 0
        machine_count = int(all_df["squeeze_machine_flag"].fillna(False).astype(bool).sum()) if not all_df.empty else 0
        g1.metric("20x ATH runway", runway_20x_count)
        g2.metric("Max ATH runway", f"{max_ath_multiple:.1f}x" if math.isfinite(max_ath_multiple) else "n/a")
        g3.metric("Squeeze machines", machine_count)
        g4.metric("Median confluence", f"{confluence_median:.1f}")

        st.subheader("Trade Buckets")
        st.caption(
            "Quick triage bucket for each coin. Convex Long now requires the hard thesis gate first: 90%+ top10 holder evidence, "
            "Binance+Bitget trading evidence, 60D no-pump proof, float/FDV evidence, short crowd plus squeeze fuel, and early/not-late structure. Raw convex signals that miss a hard gate stay in watchlist "
            "territory with the missing prerequisite shown inline."
        )
        bucket_cols = [
            "symbol",
            "base_asset",
            "trade_bucket",
            "trade_bucket_score",
            "raw_convex_long_signal",
            "thesis_gate",
            "thesis_base_gate",
            "thesis_gate_note",
            "thesis_holder_gate",
            "thesis_venue_gate",
            "thesis_no_pump_gate",
            "thesis_float_gate",
            "thesis_short_squeeze_gate",
            "thesis_not_late_gate",
            "thesis_core_squeeze_fuel_score",
            "thesis_core_float_score",
            "trade_bucket_note",
            "range_breakout_event",
            "range_breakout_side",
            "range_breakout_score",
            "range_high_break_count",
            "range_low_break_count",
            "pre_pump_candidate_flag",
            "convexity_score",
            "convexity_entry_score",
            "convexity_prime_flag",
            "early_convexity_flag",
            "convexity_chase_risk_flag",
            "convexity_too_late_flag",
            "convexity_summary",
            "convexity_confluence_score",
            "convexity_confluence_count",
            "convexity_confluence_note",
            "squeeze_machine_flag",
            "forced_buying_setup_flag",
            "clean_convex_setup_flag",
            "squeeze_machine_score",
            "forced_buying_setup_score",
            "clean_convex_setup_score",
            "crowd_skew_confluence_score",
            "short_liquidation_fuel_score",
            "spot_control_score",
            "valuation_trap_score",
            "trend_confluence_score",
            "spot_flow_confluence_score",
            "perp_squeeze_confluence_score",
            "float_control_confluence_score",
            "mm_sponsor_confluence_score",
            "ath_runway_confluence_score",
            "last_price",
            "ath_multiple",
            "ath_price",
            "ath_source",
            "ath_runway_20x_flag",
            "convexity_float_score",
            "convexity_sponsor_score",
            "convexity_preignition_score",
            "convexity_expansion_score",
            "convexity_squeeze_score",
            "convexity_runway_score",
            "convexity_late_penalty",
            "convexity_seed_score",
            "crime_ignition_score",
            "crime_pump_score",
            "crime_exhaustion_score",
            "carry_funding_pct",
            "predicted_funding_pct",
            "oi_delta_pct",
            "daily_quote_volume_multiple",
            "hour_trade_count_multiple",
            "taker_buy_sell_ratio",
            "hour_close_location_pct",
            "crowd_top_position_divergence_pct",
            "broke_high_5d",
            "broke_high_20d",
            "broke_high_90d",
            "distance_to_high_5d_pct",
            "distance_to_high_20d_pct",
            "distance_to_high_90d_pct",
        ]
        convex_col, scalp_col, avoid_col = st.columns(3)

        convex_df = all_df[all_df["trade_bucket"] == "Convex Long"].sort_values(
            [
                "pre_pump_candidate_flag",
                "clean_convex_setup_flag",
                "forced_buying_setup_flag",
                "convexity_prime_flag",
                "early_convexity_flag",
                "convexity_confluence_count",
                "clean_convex_setup_score",
                "forced_buying_setup_score",
                "convexity_confluence_score",
                "trade_bucket_score",
                "convexity_entry_score",
                "symbol",
            ],
            ascending=[False, False, False, False, False, False, False, False, False, False, False, True],
        )
        scalp_df = all_df[all_df["trade_bucket"] == "Scalp Only"].sort_values(
            [
                "pre_pump_candidate_flag",
                "clean_convex_setup_flag",
                "forced_buying_setup_flag",
                "early_convexity_flag",
                "trade_bucket_score",
                "convexity_entry_score",
                "crime_pump_score",
                "symbol",
            ],
            ascending=[False, False, False, False, False, False, False, True],
        )
        avoid_df = all_df[all_df["trade_bucket"] == "Avoid"].sort_values(
            ["convexity_too_late_flag", "trade_bucket_score", "crime_exhaustion_score", "symbol"],
            ascending=[False, False, False, True],
        )

        convex_col.subheader("Convex Long")
        if convex_df.empty:
            convex_col.info("No coins are clearing the cleaner convex-long filter in this scan.")
        else:
            convex_col.dataframe(
                _display_frame(convex_df, bucket_cols),
                use_container_width=True,
                hide_index=True,
                column_config=breakout_column_config,
            )

        scalp_col.subheader("Scalp Only")
        if scalp_df.empty:
            scalp_col.info("No hot-but-fragile momentum names in this scan.")
        else:
            scalp_col.dataframe(
                _display_frame(scalp_df, bucket_cols),
                use_container_width=True,
                hide_index=True,
                column_config=breakout_column_config,
            )

        avoid_col.subheader("Avoid")
        if avoid_df.empty:
            avoid_col.info("No late / toxic structures are currently flagged.")
        else:
            avoid_col.dataframe(
                _display_frame(avoid_df, bucket_cols),
                use_container_width=True,
                hide_index=True,
                column_config=breakout_column_config,
            )

        st.subheader("Pairs that hit 20D/90D/180D highs or lows in the last 24h")
        if highs_df.empty:
            st.info("No 20D/90D/180D high/low events detected in the scanned universe.")
        else:
            display_cols = [
                "symbol",
                "base_asset",
                "trade_bucket",
                "trade_bucket_score",
                "range_breakout_event",
                "range_breakout_side",
                "range_breakout_score",
                "range_high_break_count",
                "range_low_break_count",
                "market_type",
                "last_price",
                "funding_countdown_hours",
                "carry_funding_pct",
                "carry_funding_annualized_pct",
                "long_short_account_ratio",
                "long_account_pct",
                "short_account_pct",
                "predicted_funding_pct",
                "predicted_funding_annualized_pct",
                "predicted_funding_low_pct",
                "predicted_funding_high_pct",
                "funding_window_elapsed_pct",
                "predicted_funding_backtest_mae_pct",
                "corr_window_days",
                "corr_to_btc_6m",
                "high_24h",
                "high_5d",
                "high_20d",
                "low_20d",
                "high_90d",
                "low_90d",
                "high_180d",
                "low_180d",
                "broke_high_5d",
                "broke_low_5d",
                "broke_high_20d",
                "broke_low_20d",
                "broke_high_90d",
                "broke_low_90d",
                "broke_high_180d",
                "broke_low_180d",
            ]
            st.dataframe(
                _display_frame(highs_df, display_cols),
                use_container_width=True,
                hide_index=True,
                column_config=breakout_column_config,
            )

        screener_tabs = st.tabs(
            [
                "5D Highs",
                "5D Lows",
                "20D Highs",
                "20D Lows",
                "Carry / Funding",
                "Funding Flipped // Short Squeeze",
                "20x ATH Runway",
                "Structure Radar",
                "Terminal Evidence",
                "CEX Flow",
                "Timing",
                "1H Short ROC",
                "Short Account Moves",
                "RAVE/LAB Radar",
                "Pump Radar",
                "Pre-Activity Radar",
                "Convex Mechanisms",
                "Shorts Fighting Uptrend",
                "Volume Spikes",
            ]
        )

        short_window_cols = [
            "symbol",
            "base_asset",
            "trade_bucket",
            "trade_bucket_score",
            "market_type",
            "last_price",
            "funding_interval_hours",
            "funding_countdown_hours",
            "carry_funding_pct",
            "carry_funding_annualized_pct",
            "long_carry_pct",
            "long_carry_annualized_pct",
            "long_short_account_ratio",
            "long_account_pct",
            "short_account_pct",
            "premium_index_pct",
            "predicted_funding_pct",
            "predicted_funding_annualized_pct",
            "predicted_funding_low_pct",
            "predicted_funding_high_pct",
            "predicted_funding_band_pct",
            "predicted_funding_backtest_mae_pct",
            "funding_window_elapsed_pct",
            "corr_to_btc_6m",
            "high_24h",
            "low_24h",
            "high_5d",
            "low_5d",
            "high_20d",
            "low_20d",
            "broke_high_5d",
            "broke_low_5d",
            "broke_high_20d",
            "broke_low_20d",
        ]

        with screener_tabs[0]:
            highs_5d_df = all_df[all_df["broke_high_5d"]].sort_values(
                ["carry_funding_pct", "symbol"],
                ascending=[False, True],
            )
            if highs_5d_df.empty:
                st.info("No 5D upside breakouts detected in the scanned universe.")
            else:
                st.dataframe(
                    _display_frame(highs_5d_df, short_window_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

        with screener_tabs[1]:
            lows_5d_df = all_df[all_df["broke_low_5d"]].sort_values(
                ["carry_funding_pct", "symbol"],
                ascending=[True, True],
            )
            if lows_5d_df.empty:
                st.info("No 5D downside breakouts detected in the scanned universe.")
            else:
                st.dataframe(
                    _display_frame(lows_5d_df, short_window_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

        with screener_tabs[2]:
            highs_20d_df = all_df[all_df["broke_high_20d"]].sort_values(
                ["carry_funding_pct", "symbol"],
                ascending=[False, True],
            )
            if highs_20d_df.empty:
                st.info("No 20D upside breakouts detected in the scanned universe.")
            else:
                st.dataframe(
                    _display_frame(highs_20d_df, short_window_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

        with screener_tabs[3]:
            lows_20d_df = all_df[all_df["broke_low_20d"]].sort_values(
                ["carry_funding_pct", "symbol"],
                ascending=[True, True],
            )
            if lows_20d_df.empty:
                st.info("No 20D downside breakouts detected in the scanned universe.")
            else:
                st.dataframe(
                    _display_frame(lows_20d_df, short_window_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

        with screener_tabs[4]:
            st.caption(
                "Est. Funding is Binance's live estimate from the mark-price snapshot and matches the funding number shown in Binance's UI. "
                "Positive means a short should receive and a long should pay; negative means a short should pay and a long should receive. "
                "Modeled Funding is our separate reconstruction/backtest model, kept here as a secondary comparison only. "
                "L/S Acct Ratio is Binance's global account-count ratio for the symbol."
            )
            funding_cols = [
                "symbol",
                "base_asset",
                "trade_bucket",
                "trade_bucket_score",
                "market_type",
                "last_price",
                "funding_interval_hours",
                "funding_countdown_hours",
                "carry_funding_pct",
                "carry_funding_annualized_pct",
                "long_carry_pct",
                "long_carry_annualized_pct",
                "long_short_account_ratio",
                "long_account_pct",
                "short_account_pct",
                "premium_index_pct",
                "predicted_funding_pct",
                "predicted_funding_annualized_pct",
                "predicted_long_carry_pct",
                "predicted_long_carry_annualized_pct",
                "predicted_funding_low_pct",
                "predicted_funding_high_pct",
                "predicted_funding_band_pct",
                "predicted_funding_backtest_mae_pct",
                "predicted_funding_backtest_count",
                "funding_window_elapsed_pct",
                "corr_to_btc_6m",
                "broke_high_5d",
                "broke_low_5d",
                "broke_high_20d",
                "broke_low_20d",
                "broke_high_90d",
                "broke_low_90d",
            ]
            top_carry, bottom_carry = st.columns(2)
            top_carry.subheader("Best est. carry for shorts")
            top_carry.dataframe(
                _display_frame(all_df.sort_values(["carry_funding_pct", "symbol"], ascending=[False, True]).head(20), funding_cols),
                use_container_width=True,
                hide_index=True,
                column_config=breakout_column_config,
            )
            bottom_carry.subheader("Best est. carry for longs")
            bottom_carry.dataframe(
                _display_frame(all_df.sort_values(["carry_funding_pct", "symbol"], ascending=[True, True]).head(20), funding_cols),
                use_container_width=True,
                hide_index=True,
                column_config=breakout_column_config,
            )
            crowded_long, crowded_short = st.columns(2)
            crowded_long.subheader("Most long-skewed accounts")
            crowded_long.dataframe(
                _display_frame(all_df.sort_values(["long_short_account_ratio", "symbol"], ascending=[False, True]).head(20), funding_cols),
                use_container_width=True,
                hide_index=True,
                column_config=breakout_column_config,
            )
            crowded_short.subheader("Most short-skewed accounts")
            crowded_short.dataframe(
                _display_frame(all_df.sort_values(["long_short_account_ratio", "symbol"], ascending=[True, True]).head(20), funding_cols),
                use_container_width=True,
                hide_index=True,
                column_config=breakout_column_config,
            )
            with st.expander("Show full carry / funding table"):
                st.dataframe(
                    _display_frame(all_df.sort_values(["carry_funding_pct", "symbol"], ascending=[False, True]), funding_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

        with screener_tabs[5]:
            st.caption(
                "This tab hunts the exact shape of move where funding was recently negative, flips positive, "
                "and price confirms with stacked upside breakouts, rising OI, taker buyers, and still-meaningful short crowding. "
                "Scanned ATH is the max daily high in the loaded Binance history window, so treat it as a history-window proxy rather than guaranteed full lifetime ATH."
            )
            squeeze_cols = [
                "symbol",
                "base_asset",
                "trade_bucket",
                "trade_bucket_score",
                "short_squeeze_score",
                "forced_buying_setup_flag",
                "clean_convex_setup_flag",
                "forced_buying_setup_score",
                "clean_convex_setup_score",
                "crowd_skew_confluence_score",
                "short_liquidation_fuel_score",
                "accumulation_absorption_score",
                "accumulation_absorption_flag",
                "accumulation_absorption_note",
                "funding_flip_score",
                "short_crowding_score",
                "breakout_pressure_score",
                "runway_score",
                "funding_flip_up_flag",
                "fresh_flip_flag",
                "active_short_squeeze_flag",
                "squeeze_chase_flag",
                "short_squeeze_summary",
                "short_squeeze_top_factors",
                "short_squeeze_offsets",
                "last_price",
                "ath_scanned",
                "upside_to_ath_pct",
                "carry_funding_pct",
                "predicted_funding_pct",
                "last_settled_funding_pct",
                "prior_settled_funding_pct",
                "funding_flip_delta_pct",
                "premium_index_pct",
                "basis_rate_pct",
                "long_short_account_ratio",
                "long_account_pct",
                "short_account_pct",
                "top_trader_position_ratio",
                "top_trader_account_ratio",
                "oi_value_usdt",
                "oi_delta_pct",
                "oi_to_24h_volume_pct",
                "hour_return_pct",
                "hour_return_z",
                "day_return_pct",
                "hour_volume_multiple",
                "hour_trade_count_multiple",
                "taker_buy_sell_ratio",
                "taker_buy_share_pct",
                "hour_close_location_pct",
                "hour_upper_wick_pct",
                "breakout_stack_count",
                "high_5d",
                "high_20d",
                "high_90d",
                "high_180d",
                "broke_high_5d",
                "broke_high_20d",
                "broke_high_90d",
                "broke_high_180d",
            ]
            squeeze_view_df = all_df[
                (all_df["funding_flip_up_flag"])
                | (all_df["breakout_stack_count"] >= 1)
                | (all_df["short_squeeze_score"] >= 35.0)
                | (all_df["forced_buying_setup_score"] >= 45.0)
                | (all_df["clean_convex_setup_score"] >= 50.0)
            ].copy()
            squeeze_ranked_df = squeeze_view_df.sort_values(
                [
                    "active_short_squeeze_flag",
                    "forced_buying_setup_flag",
                    "clean_convex_setup_flag",
                    "fresh_flip_flag",
                    "funding_flip_up_flag",
                    "forced_buying_setup_score",
                    "clean_convex_setup_score",
                    "short_squeeze_score",
                    "funding_flip_score",
                    "breakout_stack_count",
                    "upside_to_ath_pct",
                    "symbol",
                ],
                ascending=[False] * 11 + [True],
            )
            fresh_flip_df = squeeze_ranked_df[squeeze_ranked_df["fresh_flip_flag"]].copy()
            active_short_df = squeeze_ranked_df[squeeze_ranked_df["active_short_squeeze_flag"]].copy()
            chase_df = squeeze_ranked_df[squeeze_ranked_df["squeeze_chase_flag"]].copy()

            sq1, sq2, sq3, sq4 = st.columns(4)
            sq1.metric("Funding flipped now", int(all_df["funding_flip_up_flag"].sum()) if not all_df.empty else 0)
            sq2.metric("Fresh flips", int(all_df["fresh_flip_flag"].sum()) if not all_df.empty else 0)
            sq3.metric("Active short squeezes", int(all_df["active_short_squeeze_flag"].sum()) if not all_df.empty else 0)
            sq4.metric("Short squeeze median", f"{float(squeeze_ranked_df['short_squeeze_score'].median()) if not squeeze_ranked_df.empty else 0.0:.1f}")

            flip_col, active_col, chase_col = st.columns(3)
            flip_col.subheader("Fresh Flip")
            if fresh_flip_df.empty:
                flip_col.info("No fresh funding-flip setups right now.")
            else:
                flip_col.dataframe(
                    _display_frame(fresh_flip_df.head(15), squeeze_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            active_col.subheader("Active Short Squeeze")
            if active_short_df.empty:
                active_col.info("No active short squeezes in this scan.")
            else:
                active_col.dataframe(
                    _display_frame(active_short_df.head(15), squeeze_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            chase_col.subheader("Chase Risk")
            if chase_df.empty:
                chase_col.info("No overextended squeeze names are currently flagged.")
            else:
                chase_col.dataframe(
                    _display_frame(chase_df.head(15), squeeze_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            st.markdown("#### Ranked Short Squeeze Tape")
            if squeeze_ranked_df.empty:
                st.info("No funding-flip / short-squeeze signals in the scanned universe.")
            else:
                st.dataframe(
                    _display_frame(squeeze_ranked_df.head(30), squeeze_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            with st.expander("Show full funding-flip / short-squeeze table"):
                if squeeze_ranked_df.empty:
                    st.info("No short-squeeze rows to show.")
                else:
                    st.dataframe(
                        _display_frame(squeeze_ranked_df, squeeze_cols),
                        use_container_width=True,
                        hide_index=True,
                        column_config=breakout_column_config,
                    )

        with screener_tabs[6]:
            st.caption(
                "Ranks coins trading at least 20x below their best available ATH. "
                "Deep mode enriches the strongest runway candidates with CoinGecko lifetime ATH where possible; "
                f"Full ATH scans up to {FULL_ATH_MAX_SYMBOLS_TO_SCAN} wider non-major Binance perp candidates and "
                "falls back to Binance scanned-history ATH when external ATH is unavailable."
            )
            ath_runway_cols = [
                "symbol",
                "base_asset",
                "trade_bucket",
                "trade_bucket_score",
                "raw_convex_long_signal",
                "thesis_gate",
                "thesis_gate_note",
                "thesis_holder_gate",
                "thesis_venue_gate",
                "thesis_no_pump_gate",
                "trade_bucket_note",
                "last_price",
                "ath_price",
                "ath_multiple",
                "ath_upside_pct",
                "ath_source",
                "coingecko_ath_usd",
                "coingecko_ath_change_pct",
                "coingecko_ath_date",
                "ath_scanned",
                "ath_runway_20x_flag",
                "convexity_score",
                "convexity_entry_score",
                "convexity_confluence_score",
                "convexity_confluence_count",
                "convexity_confluence_note",
                "squeeze_machine_flag",
                "forced_buying_setup_flag",
                "clean_convex_setup_flag",
                "squeeze_machine_score",
                "forced_buying_setup_score",
                "clean_convex_setup_score",
                "crowd_skew_confluence_score",
                "short_liquidation_fuel_score",
                "spot_control_score",
                "valuation_trap_score",
                "pre_pump_candidate_flag",
                "convexity_prime_flag",
                "early_convexity_flag",
                "convexity_chase_risk_flag",
                "convexity_too_late_flag",
                "trend_confluence_score",
                "spot_flow_confluence_score",
                "perp_squeeze_confluence_score",
                "float_control_confluence_score",
                "mm_sponsor_confluence_score",
                "ath_runway_confluence_score",
                "breakout_stack_count",
                "broke_high_5d",
                "broke_high_20d",
                "broke_high_90d",
                "broke_high_180d",
                "distance_to_high_5d_pct",
                "distance_to_high_20d_pct",
                "distance_to_high_90d_pct",
                "daily_quote_volume_multiple",
                "hour_volume_multiple",
                "hour_trade_count_multiple",
                "day_return_pct",
                "hour_return_pct",
                "carry_funding_pct",
                "funding_flip_up_flag",
                "short_crowding_score",
                "perp_pressure_score",
                "oi_delta_pct",
                "oi_to_market_cap_pct",
                "spot_flow_confluence_flag",
                "perp_squeeze_confluence_flag",
                "float_control_confluence_flag",
                "ath_runway_confluence_flag",
                "cex_to_dex_volume_ratio",
                "cex_volume_share_pct",
                "binance_bitget_gate_share_pct",
                "emfx_volume_share_pct",
                "krw_volume_share_pct",
                "try_volume_share_pct",
                "top_venue",
                "top_venue_volume_share_pct",
                "spot_volume_to_mcap_pct",
                "perp_volume_to_mcap_pct",
                "market_cap_usd",
                "fdv_to_market_cap",
                "locked_supply_pct",
                "top10_holder_pct",
                "holder_count",
            ]
            ath_multiple = pd.to_numeric(all_df["ath_multiple"], errors="coerce") if "ath_multiple" in all_df.columns else pd.Series(float("nan"), index=all_df.index)
            major_mask = all_df["crime_excluded_major"].fillna(False).astype(bool) if "crime_excluded_major" in all_df.columns else pd.Series(False, index=all_df.index)
            runway_df = all_df[(ath_multiple >= 20.0) & (~major_mask)].copy()
            runway_df = runway_df.sort_values(
                [
                    "ath_multiple",
                    "pre_pump_candidate_flag",
                    "convexity_prime_flag",
                    "convexity_confluence_score",
                    "convexity_entry_score",
                    "daily_quote_volume_multiple",
                    "symbol",
                ],
                ascending=[False, False, False, False, False, False, True],
            )
            ranked_runway_df = all_df[(ath_multiple >= 5.0) & (~major_mask)].copy().sort_values(
                [
                    "ath_multiple",
                    "convexity_confluence_score",
                    "convexity_entry_score",
                    "symbol",
                ],
                ascending=[False, False, False, True],
            )

            rw1, rw2, rw3, rw4 = st.columns(4)
            rw1.metric("20x+ runway names", int(len(runway_df)))
            rw2.metric("50x+ runway names", int(((ath_multiple.fillna(0.0) >= 50.0) & (~major_mask)).sum()))
            rw3.metric(
                "Best runway",
                f"{float(runway_df['ath_multiple'].max()):.1f}x" if not runway_df.empty else "n/a",
            )
            cg_backed = int((runway_df["ath_source"].astype(str) == "CoinGecko").sum()) if not runway_df.empty and "ath_source" in runway_df.columns else 0
            rw4.metric("CG-backed ATHs", cg_backed)

            st.markdown("#### 20x+ ATH Runway")
            if runway_df.empty:
                st.info("No non-major coins in the scanned universe are currently at least 20x below ATH.")
            else:
                st.dataframe(
                    _display_frame(runway_df, ath_runway_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            with st.expander("Show 5x+ ATH runway ranked table"):
                if ranked_runway_df.empty:
                    st.info("No 5x+ ATH runway rows in this scan.")
                else:
                    st.dataframe(
                        _display_frame(ranked_runway_df, ath_runway_cols),
                        use_container_width=True,
                        hide_index=True,
                        column_config=breakout_column_config,
                    )

        with screener_tabs[7]:
            if scan_mode == "Fast":
                st.info("Fast mode skips the heavier structure fetches for speed. Switch to Deep scan for the full structural diagnostics.")
            st.caption(
                "Structure-radar flags try to catch unusual perp squeezes: fast upside velocity, big 1H and 24H momentum, "
                "trade-count expansion, rising OI, aggressive taker buys, positive carry/basis, crowd-longing ahead of top traders, "
                "a thin ask book, external spot support, Coinbase spot liquidity-sponsor diagnostics, manual MM/social-graph confluence, and float/holder concentration proxies. "
                "Majors are excluded from this tab by default. "
                "Ignition looks for forceful closes near the hourly high; Exhaustion looks for upper wicks, carry stress, and OI fade."
            )
            crime_cols = [
                "symbol",
                "base_asset",
                "trade_bucket",
                "trade_bucket_score",
                "trade_bucket_note",
                "crime_eligible",
                "crime_excluded_major",
                "crime_mechanics_score",
                "crime_coinbase_lane_score",
                "crime_owner_circle_score",
                "mm_presence_score",
                "mm_bid_support_score",
                "mm_withdrawal_risk_score",
                "mm_proximity_score",
                "mm_proximity_maker",
                "dwf_labs_portfolio",
                "dwf_labs_portfolio_score",
                "dwf_labs_portfolio_rank",
                "mm_proximity_note",
                "mm_proximity_source",
                "inventory_transfer_risk_score",
                "inventory_sponsor_mismatch_score",
                "inventory_transfer_risk_flag",
                "inventory_transfer_note",
                "crime_microstructure_score",
                "crime_largecap_penalty_score",
                "crime_spot_impulse_score",
                "crime_supply_control_score",
                "market_type",
                "last_price",
                "float_trap_score",
                "perp_pressure_score",
                "venue_support_score",
                "exit_fragility_score",
                "crime_pump_score_v2",
                "squeeze_machine_flag",
                "forced_buying_setup_flag",
                "clean_convex_setup_flag",
                "squeeze_machine_score",
                "forced_buying_setup_score",
                "clean_convex_setup_score",
                "crowd_skew_confluence_score",
                "short_liquidation_fuel_score",
                "spot_control_score",
                "valuation_trap_score",
                "cmc_mover_score",
                "cmc_mover_label",
                "cmc_rank_1h",
                "cmc_rank_24h",
                "cmc_pct_1h",
                "cmc_pct_24h",
                "cmc_name",
                "cmc_market_cap_usd",
                "cmc_volume_24h",
                "cmc_volume_to_mcap_pct",
                "setup_ready_flag",
                "active_squeeze_flag",
                "blowoff_watch_flag",
                "unwind_risk_flag",
                "why_flagged_summary",
                "why_flagged_top_factors",
                "why_flagged_offsets",
                "convexity_score",
                "convexity_entry_score",
                "pre_pump_candidate_flag",
                "convexity_prime_flag",
                "early_convexity_flag",
                "convexity_chase_risk_flag",
                "convexity_too_late_flag",
                "convexity_summary",
                "convexity_confluence_score",
                "convexity_confluence_count",
                "convexity_confluence_note",
                "squeeze_machine_flag",
                "forced_buying_setup_flag",
                "clean_convex_setup_flag",
                "squeeze_machine_score",
                "forced_buying_setup_score",
                "clean_convex_setup_score",
                "crowd_skew_confluence_score",
                "short_liquidation_fuel_score",
                "spot_control_score",
                "valuation_trap_score",
                "trend_confluence_score",
                "spot_flow_confluence_score",
                "perp_squeeze_confluence_score",
                "float_control_confluence_score",
                "mm_sponsor_confluence_score",
                "ath_runway_confluence_score",
                "convexity_float_score",
                "convexity_sponsor_score",
                "convexity_preignition_score",
                "convexity_expansion_score",
                "convexity_squeeze_score",
                "convexity_runway_score",
                "convexity_late_penalty",
                "convexity_seed_score",
                "ath_multiple",
                "ath_price",
                "ath_upside_pct",
                "ath_source",
                "ath_runway_20x_flag",
                "crime_pump_score",
                "ignition_score_v2",
                "crime_ignition_score",
                "crime_exhaustion_score",
                "crime_pump_flag",
                "ignition_setup_flag",
                "exhaustion_flag",
                "squeeze_risk_flag",
                "blowoff_risk_flag",
                "hour_return_pct",
                "hour_return_z",
                "day_return_pct",
                "daily_quote_volume_multiple",
                "hour_volume_multiple",
                "hour_trade_count_multiple",
                "hour_upper_wick_pct",
                "hour_close_location_pct",
                "oi_value_usdt",
                "oi_delta_pct",
                "oi_to_24h_volume_pct",
                "oi_to_market_cap_pct",
                "carry_funding_pct",
                "predicted_funding_pct",
                "premium_index_pct",
                "basis_rate_pct",
                "crime_carry_stress_score",
                "taker_buy_sell_ratio",
                "taker_buy_share_pct",
                "long_short_account_ratio",
                "long_account_pct",
                "top_trader_position_ratio",
                "top_trader_long_position_pct",
                "top_trader_account_ratio",
                "top_trader_long_account_pct",
                "crowd_top_position_divergence_pct",
                "crowd_top_account_divergence_pct",
                "ask_depth_1pct_usdt",
                "ask_depth_to_24h_volume_pct",
                "coinbase_spot_listed",
                "spot_external_quote_volume_24h",
                "coinbase_spot_quote_volume_24h",
                "coingecko_total_volume_24h",
                "coingecko_cex_volume_24h",
                "kraken_spot_quote_volume_24h",
                "upbit_spot_quote_volume_24h",
                "upbit_krw_quote_volume_24h",
                "try_spot_quote_volume_24h",
                "emfx_spot_quote_volume_24h",
                "coingecko_dex_volume_24h",
                "cex_volume_share_pct",
                "cex_to_dex_volume_ratio",
                "cex_dex_volume_ratio_score",
                "coinbase_volume_share_pct",
                "binance_volume_share_pct",
                "bitget_volume_share_pct",
                "gate_volume_share_pct",
                "kraken_volume_share_pct",
                "upbit_volume_share_pct",
                "krw_volume_share_pct",
                "try_volume_share_pct",
                "emfx_volume_share_pct",
                "binance_bitget_gate_share_pct",
                "binance_bitget_gate_share_score",
                "top_venue",
                "top_venue_volume_share_pct",
                "top3_venue_volume_share_pct",
                "venue_hhi",
                "venue_hhi_score",
                "venue_count",
                "dex_volume_share_pct",
                "emfx_lane_score",
                "coinbase_bid_ask_spread_pct",
                "coinbase_bid_depth_2pct_usd",
                "coinbase_ask_depth_2pct_usd",
                "coinbase_total_depth_2pct_usd",
                "coinbase_book_imbalance_pct",
                "coinbase_depth_to_volume_pct",
                "coinbase_depth_to_perp_volume_pct",
                "spot_to_perp_volume_pct",
                "coinbase_to_perp_volume_pct",
                "spot_volume_to_mcap_pct",
                "perp_volume_to_mcap_pct",
                "market_cap_usd",
                "fdv_to_market_cap",
                "locked_supply_pct",
                "top10_holder_pct",
                "holder_count",
                "owner_holder_pct",
                "creator_holder_pct",
                "broke_high_5d",
                "broke_high_20d",
                "broke_high_90d",
                "distance_to_high_5d_pct",
                "distance_to_high_20d_pct",
                "distance_to_high_90d_pct",
            ]
            crime_bucket_cols = [
                "symbol",
                "base_asset",
                "trade_bucket",
                "trade_bucket_score",
                "trade_bucket_note",
                "crime_eligible",
                "crime_excluded_major",
                "crime_mechanics_score",
                "crime_coinbase_lane_score",
                "crime_owner_circle_score",
                "mm_presence_score",
                "mm_bid_support_score",
                "mm_withdrawal_risk_score",
                "mm_proximity_score",
                "mm_proximity_maker",
                "dwf_labs_portfolio",
                "dwf_labs_portfolio_score",
                "dwf_labs_portfolio_rank",
                "inventory_transfer_risk_score",
                "inventory_sponsor_mismatch_score",
                "inventory_transfer_risk_flag",
                "convexity_score",
                "convexity_entry_score",
                "pre_pump_candidate_flag",
                "convexity_prime_flag",
                "early_convexity_flag",
                "convexity_chase_risk_flag",
                "convexity_too_late_flag",
                "convexity_summary",
                "convexity_confluence_score",
                "convexity_confluence_count",
                "convexity_confluence_note",
                "forced_buying_setup_flag",
                "clean_convex_setup_flag",
                "forced_buying_setup_score",
                "clean_convex_setup_score",
                "crowd_skew_confluence_score",
                "trend_confluence_score",
                "spot_flow_confluence_score",
                "perp_squeeze_confluence_score",
                "float_control_confluence_score",
                "mm_sponsor_confluence_score",
                "ath_runway_confluence_score",
                "convexity_float_score",
                "convexity_sponsor_score",
                "convexity_preignition_score",
                "convexity_expansion_score",
                "convexity_squeeze_score",
                "convexity_runway_score",
                "convexity_late_penalty",
                "convexity_seed_score",
                "ath_multiple",
                "ath_price",
                "ath_upside_pct",
                "ath_source",
                "ath_runway_20x_flag",
                "float_trap_score",
                "perp_pressure_score",
                "venue_support_score",
                "exit_fragility_score",
                "crime_pump_score_v2",
                "cmc_mover_score",
                "cmc_mover_label",
                "cmc_pct_1h",
                "cmc_pct_24h",
                "cmc_volume_to_mcap_pct",
                "setup_ready_flag",
                "active_squeeze_flag",
                "blowoff_watch_flag",
                "unwind_risk_flag",
                "crime_microstructure_score",
                "crime_largecap_penalty_score",
                "crime_spot_impulse_score",
                "crime_supply_control_score",
                "last_price",
                "crime_ignition_score",
                "crime_pump_score",
                "crime_exhaustion_score",
                "oi_delta_pct",
                "daily_quote_volume_multiple",
                "hour_trade_count_multiple",
                "taker_buy_sell_ratio",
                "hour_close_location_pct",
                "carry_funding_pct",
                "crowd_top_position_divergence_pct",
                "coinbase_spot_listed",
                "coinbase_volume_share_pct",
                "coingecko_cex_volume_24h",
                "coingecko_dex_volume_24h",
                "cex_to_dex_volume_ratio",
                "cex_dex_volume_ratio_score",
                "binance_volume_share_pct",
                "bitget_volume_share_pct",
                "gate_volume_share_pct",
                "krw_volume_share_pct",
                "try_volume_share_pct",
                "emfx_volume_share_pct",
                "binance_bitget_gate_share_pct",
                "binance_bitget_gate_share_score",
                "top_venue_volume_share_pct",
                "venue_hhi",
                "venue_hhi_score",
                "coinbase_total_depth_2pct_usd",
                "coinbase_book_imbalance_pct",
                "coinbase_depth_to_volume_pct",
                "coinbase_depth_to_perp_volume_pct",
                "emfx_lane_score",
                "spot_to_perp_volume_pct",
                "spot_volume_to_mcap_pct",
                "perp_volume_to_mcap_pct",
                "oi_to_market_cap_pct",
                "locked_supply_pct",
                "top10_holder_pct",
                "holder_count",
                "broke_high_5d",
                "broke_high_20d",
                "broke_high_90d",
                "distance_to_high_5d_pct",
                "distance_to_high_20d_pct",
                "distance_to_high_90d_pct",
            ]
            st.markdown("#### Market-Structure Convexity")
            st.caption(
                "These are the same triage buckets, but now with explicit early-convexity ranking and hard thesis gates. Convex Long "
                "should be the names that clear concentration, Binance+Bitget, no-pump proof, float/FDV, short crowd plus squeeze fuel, and early/not-late structure before breakout/flow signals matter."
            )
            crime_convex_col, crime_scalp_col, crime_avoid_col = st.columns(3)
            candidate_view_df = all_df[
                (~all_df["crime_excluded_major"].fillna(False).astype(bool))
                & (
                    all_df["crime_eligible"].fillna(False).astype(bool)
                    | all_df["pre_pump_candidate_flag"].fillna(False).astype(bool)
                    | all_df["early_convexity_flag"].fillna(False).astype(bool)
                    | all_df["convexity_prime_flag"].fillna(False).astype(bool)
                    | all_df["squeeze_machine_flag"].fillna(False).astype(bool)
                    | all_df["forced_buying_setup_flag"].fillna(False).astype(bool)
                    | all_df["clean_convex_setup_flag"].fillna(False).astype(bool)
                    | (all_df["convexity_entry_score"].fillna(0.0) >= 42.0)
                    | (all_df["convexity_seed_score"].fillna(0.0) >= 55.0)
                    | (all_df["squeeze_machine_score"].fillna(0.0) >= 52.0)
                    | (all_df["clean_convex_setup_score"].fillna(0.0) >= 54.0)
                    | (all_df["forced_buying_setup_score"].fillna(0.0) >= 50.0)
                    | (
                        (all_df["convexity_confluence_count"].fillna(0.0) >= 3.0)
                        & (all_df["convexity_confluence_score"].fillna(0.0) >= 42.0)
                    )
                    | all_df["ath_runway_20x_flag"].fillna(False).astype(bool)
                )
            ].copy()
            crime_view_df = candidate_view_df.copy()
            radar_1, radar_2, radar_3, radar_4, radar_5 = st.columns(5)
            radar_1.metric("Pre-ignition signals", int(all_df["pre_pump_candidate_flag"].sum()) if not all_df.empty else 0)
            radar_2.metric("Convex prime", int(all_df["convexity_prime_flag"].sum()) if not all_df.empty else 0)
            radar_3.metric("Squeeze machines", int(all_df["squeeze_machine_flag"].sum()) if not all_df.empty else 0)
            radar_4.metric("Chase risk", int(all_df["convexity_chase_risk_flag"].sum()) if not all_df.empty else 0)
            radar_5.metric("Median entry score", f"{float(candidate_view_df['convexity_entry_score'].median()) if not candidate_view_df.empty else 0.0:.1f}")

            st.markdown("#### Pre-Ignition Radar")
            top_convexity_df = candidate_view_df.sort_values(
                [
                    "pre_pump_candidate_flag",
                    "clean_convex_setup_flag",
                    "forced_buying_setup_flag",
                    "squeeze_machine_flag",
                    "convexity_prime_flag",
                    "early_convexity_flag",
                    "clean_convex_setup_score",
                    "forced_buying_setup_score",
                    "squeeze_machine_score",
                    "convexity_confluence_count",
                    "convexity_confluence_score",
                    "convexity_entry_score",
                    "short_liquidation_fuel_score",
                    "spot_control_score",
                    "convexity_preignition_score",
                    "convexity_sponsor_score",
                    "symbol",
                ],
                ascending=[False] * 16 + [True],
            )
            if top_convexity_df.empty:
                st.info("No symbols are showing strong pre-ignition convexity right now.")
            else:
                st.dataframe(
                    _display_frame(top_convexity_df.head(20), crime_bucket_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            st.markdown("#### Structure Buckets")
            crime_convex_df = crime_view_df[crime_view_df["trade_bucket"] == "Convex Long"].sort_values(
                [
                    "pre_pump_candidate_flag",
                    "clean_convex_setup_flag",
                    "forced_buying_setup_flag",
                    "squeeze_machine_flag",
                    "convexity_prime_flag",
                    "early_convexity_flag",
                    "clean_convex_setup_score",
                    "forced_buying_setup_score",
                    "squeeze_machine_score",
                    "convexity_confluence_count",
                    "convexity_confluence_score",
                    "trade_bucket_score",
                    "convexity_entry_score",
                    "symbol",
                ],
                ascending=[False] * 13 + [True],
            )
            crime_scalp_df = crime_view_df[crime_view_df["trade_bucket"] == "Scalp Only"].sort_values(
                [
                    "clean_convex_setup_flag",
                    "forced_buying_setup_flag",
                    "squeeze_machine_flag",
                    "pre_pump_candidate_flag",
                    "early_convexity_flag",
                    "clean_convex_setup_score",
                    "forced_buying_setup_score",
                    "squeeze_machine_score",
                    "trade_bucket_score",
                    "convexity_entry_score",
                    "crime_pump_score",
                    "symbol",
                ],
                ascending=[False, False, False, False, False, False, False, False, False, False, False, True],
            )
            crime_avoid_df = crime_view_df[crime_view_df["trade_bucket"] == "Avoid"].sort_values(
                ["convexity_too_late_flag", "blowoff_watch_flag", "trade_bucket_score", "exit_fragility_score", "symbol"],
                ascending=[False, False, False, False, True],
            )

            crime_convex_col.subheader("Convex Long")
            if crime_convex_df.empty:
                crime_convex_col.info("No cleaner convex-long structure watches in this scan.")
            else:
                crime_convex_col.dataframe(
                    _display_frame(crime_convex_df, crime_bucket_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            crime_scalp_col.subheader("Scalp Only")
            if crime_scalp_df.empty:
                crime_scalp_col.info("No scalp-only structure names right now.")
            else:
                crime_scalp_col.dataframe(
                    _display_frame(crime_scalp_df, crime_bucket_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            crime_avoid_col.subheader("Avoid")
            if crime_avoid_df.empty:
                crime_avoid_col.info("No late / fragile structure names are currently flagged.")
            else:
                crime_avoid_col.dataframe(
                    _display_frame(crime_avoid_df, crime_bucket_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            st.markdown("#### Ranked Structure Tape")
            ranked_crime_df = crime_view_df.sort_values(
                [
                    "active_squeeze_flag",
                    "clean_convex_setup_flag",
                    "forced_buying_setup_flag",
                    "squeeze_machine_flag",
                    "pre_pump_candidate_flag",
                    "convexity_prime_flag",
                    "early_convexity_flag",
                    "clean_convex_setup_score",
                    "forced_buying_setup_score",
                    "squeeze_machine_score",
                    "convexity_entry_score",
                    "crime_pump_score_v2",
                    "short_liquidation_fuel_score",
                    "spot_control_score",
                    "convexity_preignition_score",
                    "cmc_mover_score",
                    "setup_ready_flag",
                    "ignition_score_v2",
                    "perp_pressure_score",
                    "venue_support_score",
                    "hour_return_z",
                    "symbol",
                ],
                ascending=[
                    False,
                    False,
                    False,
                    False,
                    False,
                    False,
                    False,
                    False,
                    False,
                    False,
                    False,
                    False,
                    False,
                    False,
                    False,
                    False,
                    False,
                    False,
                    False,
                    False,
                    False,
                    True,
                ],
            )
            if ranked_crime_df.empty:
                st.info("No symbols are currently crossing the pre-ignition / structure filters after excluding majors.")
            else:
                st.dataframe(
                    _display_frame(ranked_crime_df.head(30), crime_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )
            flagged_crime_df = ranked_crime_df[
                ranked_crime_df["pre_pump_candidate_flag"]
                | ranked_crime_df["clean_convex_setup_flag"]
                | ranked_crime_df["forced_buying_setup_flag"]
                | ranked_crime_df["squeeze_machine_flag"]
                | ranked_crime_df["convexity_prime_flag"]
                | ranked_crime_df["early_convexity_flag"]
                | ranked_crime_df["convexity_chase_risk_flag"]
                | ranked_crime_df["convexity_too_late_flag"]
                | ranked_crime_df["active_squeeze_flag"]
                | ranked_crime_df["setup_ready_flag"]
                | ranked_crime_df["blowoff_watch_flag"]
                | ranked_crime_df["unwind_risk_flag"]
                | ranked_crime_df["crime_pump_flag"]
                | ranked_crime_df["ignition_setup_flag"]
                | ranked_crime_df["exhaustion_flag"]
                | ranked_crime_df["squeeze_risk_flag"]
                | ranked_crime_df["blowoff_risk_flag"]
            ]
            with st.expander("Show flagged structure signals only"):
                if flagged_crime_df.empty:
                    st.info("No symbols are crossing the current structure, ignition, exhaustion, or squeeze/blowoff thresholds.")
                else:
                    st.dataframe(
                        _display_frame(flagged_crime_df, crime_cols),
                        use_container_width=True,
                        hide_index=True,
                        column_config=breakout_column_config,
                    )

        with screener_tabs[8]:
            st.caption(
                "A terminal-style evidence view: score every perp by float structure, short pressure, ignition, runway, "
                "liquidity reality, market regime, and late-stage risk. This is research tooling, not trade instruction."
            )
            terminal_cols = [
                "symbol",
                "base_asset",
                "trade_bucket",
                "trade_bucket_score",
                "terminal_edge_score",
                "terminal_structure_edge_score",
                "terminal_control_plane_score",
                "terminal_distribution_pressure_score",
                "terminal_pre_ignition_quality_score",
                "archetype_match_score",
                "archetype_best_match",
                "archetype_match_note",
                "terminal_setup_archetype",
                "terminal_market_regime",
                "terminal_liquidity_reality",
                "terminal_evidence_summary",
                "terminal_structural_opacity_note",
                "terminal_structure_edge_note",
                "terminal_confirmation_needed",
                "terminal_invalidation_map",
                "accumulation_absorption_score",
                "accumulation_absorption_flag",
                "accumulation_absorption_note",
                "terminal_float_score",
                "terminal_short_pressure_score",
                "terminal_ignition_score",
                "terminal_runway_score",
                "terminal_opaque_supply_score",
                "terminal_exchange_flow_score",
                "cex_deposit_flow_score",
                "cex_deposit_inventory_stress_score",
                "cex_deposit_inventory_stress_note",
                "cex_deposit_flow_flag",
                "cex_deposit_24h_count",
                "cex_deposit_24h_token_amount",
                "cex_deposit_24h_notional_usd",
                "cex_deposit_24h_notional_to_ask_depth_pct",
                "cex_deposit_24h_notional_to_volume_pct",
                "cex_deposit_24h_max_pct_supply",
                "cex_deposit_24h_total_pct_supply",
                "cex_deposit_24h_target_exchanges",
                "cex_deposit_concentration_gate",
                "cex_deposit_flow_note",
                "cex_deposit_24h_source_url",
                "terminal_private_unlock_score",
                "terminal_information_asymmetry_score",
                "terminal_hidden_float_reflexivity_score",
                "terminal_liquidity_score",
                "terminal_regime_score",
                "terminal_risk_score",
                "archetype_rave_score",
                "archetype_lab_score",
                "archetype_siren_score",
                "archetype_river_score",
                "archetype_sto_score",
                "pre_pump_precision_score",
                "dormant_short_fuse_score",
                "rave_lab_setup_score",
                "convexity_entry_score",
                "clean_convex_setup_score",
                "forced_buying_setup_score",
                "short_account_pct",
                "short_account_change_max_pct",
                "long_account_pct",
                "oi_delta_pct",
                "oi_value_usdt",
                "daily_quote_volume_multiple",
                "hour_volume_multiple",
                "hour_trade_count_multiple",
                "day_return_pct",
                "range_24h_pct",
                "top10_holder_pct",
                "insider_team_holder_pct",
                "low_float_score",
                "centralized_ownership_score",
                "fdv_to_market_cap",
                "locked_supply_pct",
                "target_cex_flow_score",
                "cex_to_dex_volume_ratio",
                "ask_depth_1pct_usdt",
                "ask_depth_to_24h_volume_pct",
                "ath_multiple",
                "convexity_late_penalty",
                "no_chase_penalty_score",
                "terminal_case_study_key",
            ]
            terminal_df = all_df.copy().sort_values(
                [
                    "terminal_edge_score",
                    "terminal_structure_edge_score",
                    "archetype_match_score",
                    "pre_pump_precision_flag",
                    "dormant_short_fuse_flag",
                    "terminal_control_plane_score",
                    "terminal_short_pressure_score",
                    "terminal_float_score",
                    "terminal_ignition_score",
                    "terminal_risk_score",
                    "symbol",
                ],
                ascending=[False, False, False, False, False, False, False, False, False, True, True],
            )
            t1, t2, t3, t4 = st.columns(4)
            t1.metric("Top terminal score", f"{float(pd.to_numeric(terminal_df['terminal_edge_score'], errors='coerce').max()):.1f}" if not terminal_df.empty else "n/a")
            t2.metric("Score 75+", int((pd.to_numeric(terminal_df["terminal_edge_score"], errors="coerce").fillna(0) >= 75).sum()) if not terminal_df.empty else 0)
            t3.metric("Low-vol short fuse", int(terminal_df.get("dormant_short_fuse_flag", pd.Series(False, index=terminal_df.index)).fillna(False).astype(bool).sum()) if not terminal_df.empty else 0)
            t4.metric("Precision flags", int(terminal_df.get("pre_pump_precision_flag", pd.Series(False, index=terminal_df.index)).fillna(False).astype(bool).sum()) if not terminal_df.empty else 0)

            st.subheader("Market-Structure Evidence Terminal")
            if terminal_df.empty:
                st.info("No terminal evidence rows are available yet.")
            else:
                st.dataframe(
                    _display_frame(terminal_df.head(60), terminal_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )
                selected_symbol = st.selectbox(
                    "Open setup dossier",
                    terminal_df["symbol"].astype(str).head(60).tolist(),
                    key="terminal_dossier_symbol",
                )
                selected_row = terminal_df[terminal_df["symbol"].astype(str) == selected_symbol].head(1)
                if not selected_row.empty:
                    st.markdown(build_setup_dossier(selected_row.iloc[0]))

            with st.expander("Show full terminal table"):
                if terminal_df.empty:
                    st.info("No terminal rows to show.")
                else:
                    st.dataframe(
                        _display_frame(terminal_df, terminal_cols),
                        use_container_width=True,
                        hide_index=True,
                        column_config=breakout_column_config,
                    )

        with screener_tabs[9]:
            st.caption(
                "Wallet-to-CEX flow monitor: for mapped perp tokens, the scanner checks Etherscan-style "
                "Advanced Filter transfer pages for large token transfers into labelled CEX wallets over the last "
                f"{CEX_DEPOSIT_FLOW_LOOKBACK_HOURS}h. Rows are only scored when holder concentration already meets the "
                f"gate: top 10 >= {CEX_DEPOSIT_FLOW_MIN_TOP10_PCT:.0f}%. Top 100 concentration is context only. "
                "Matched top-holder sender fields separate whale-origin inventory movement from generic wallet deposits. "
                "This is venue-flow evidence for structural-risk research, not trade instruction or an intent conclusion."
            )
            flow_score = pd.to_numeric(
                all_df.get("cex_deposit_flow_score", pd.Series(0.0, index=all_df.index)),
                errors="coerce",
            ).fillna(0.0)
            flow_flag_raw = all_df.get("cex_deposit_flow_flag", pd.Series(False, index=all_df.index))
            flow_flag = flow_flag_raw.astype(str).str.lower().isin({"1", "true", "yes", "y", "on"})
            cex_flow_df = all_df[flow_flag | flow_score.gt(0.0)].copy()
            if not cex_flow_df.empty:
                cex_flow_df["_cex_flow_score_sort"] = pd.to_numeric(
                    cex_flow_df.get("cex_deposit_flow_score"), errors="coerce"
                ).fillna(0.0)
                cex_flow_df["_cex_total_pct_sort"] = pd.to_numeric(
                    cex_flow_df.get("cex_deposit_24h_total_pct_supply"), errors="coerce"
                ).fillna(0.0)
                cex_flow_df["_cex_count_sort"] = pd.to_numeric(
                    cex_flow_df.get("cex_deposit_24h_count"), errors="coerce"
                ).fillna(0.0)
                cex_flow_df = cex_flow_df.sort_values(
                    ["_cex_flow_score_sort", "_cex_total_pct_sort", "_cex_count_sort", "symbol"],
                    ascending=[False, False, False, True],
                )
            f1, f2, f3, f4 = st.columns(4)
            f1.metric("Flow flags", int(len(cex_flow_df)))
            f2.metric(
                "Top flow score",
                f"{float(pd.to_numeric(cex_flow_df.get('cex_deposit_flow_score', pd.Series(dtype='float')), errors='coerce').max()):.1f}"
                if not cex_flow_df.empty
                else "n/a",
            )
            f3.metric(
                "Max 24h CEX flow % supply",
                f"{float(pd.to_numeric(cex_flow_df.get('cex_deposit_24h_total_pct_supply', pd.Series(dtype='float')), errors='coerce').max()):.2f}%"
                if not cex_flow_df.empty
                else "n/a",
            )
            gated = all_df.get("cex_deposit_concentration_gate", pd.Series("", index=all_df.index)).astype(str).str.strip().ne("")
            f4.metric("Concentration-gated rows", int(gated.sum()))

            st.subheader("Wallet-to-CEX Flow Monitor")
            if cex_flow_df.empty:
                st.info(
                    "No concentration-gated wallet-to-CEX token-transfer flow is currently scored. "
                    "Rows may also be blank where no contract hint exists yet for that perp symbol."
                )
            else:
                preview_row = cex_flow_df.head(1).iloc[0]
                st.markdown("**Top alert preview**")
                st.code(build_cex_flow_discord_block(preview_row, max_chars=1400))
                st.dataframe(
                    _display_frame(cex_flow_df.head(80), CEX_FLOW_DASHBOARD_COLUMNS),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            with st.expander("Show CEX-flow scan diagnostics"):
                diag_df = all_df[
                    gated
                    | all_df.get("cex_deposit_flow_error", pd.Series("", index=all_df.index)).astype(str).str.strip().ne("")
                ].copy()
                if diag_df.empty:
                    st.info("No CEX-flow diagnostics are available yet.")
                else:
                    st.dataframe(
                        _display_frame(diag_df, CEX_FLOW_DIAGNOSTIC_COLUMNS),
                        use_container_width=True,
                        hide_index=True,
                        column_config=breakout_column_config,
                    )

        with screener_tabs[10]:
            st.caption(
                "Timing view: separates structural selection from the current moment. "
                "It looks for triggering/reclaiming setups and penalizes late, wick-heavy, or fading flow."
            )
            timing_cols = [
                "symbol",
                "base_asset",
                "trade_bucket",
                "terminal_edge_score",
                "timing_score",
                "timing_state",
                "timing_observed_trigger",
                "timing_confirmation_needed",
                "timing_invalidation",
                "timing_failure_condition",
                "timing_hold_condition",
                "timing_liquidity_warning",
                "timing_trigger_score",
                "timing_reclaim_score",
                "timing_flow_score",
                "timing_early_score",
                "timing_too_late_score",
                "short_account_pct",
                "long_account_pct",
                "oi_delta_pct",
                "hour_return_pct",
                "day_return_pct",
                "hour_volume_multiple",
                "daily_quote_volume_multiple",
                "hour_trade_count_multiple",
                "hour_close_location_pct",
                "hour_upper_wick_pct",
                "distance_to_high_5d_pct",
                "distance_to_high_20d_pct",
                "ask_depth_1pct_usdt",
                "top100_holder_pct",
            ]
            timing_df = all_df.copy().sort_values(
                [
                    "timing_score",
                    "timing_trigger_score",
                    "timing_too_late_score",
                    "terminal_edge_score",
                    "symbol",
                ],
                ascending=[False, False, True, False, True],
            )
            timing_metrics = st.columns(4)
            timing_metrics[0].metric("Top timing score", f"{float(pd.to_numeric(timing_df['timing_score'], errors='coerce').max()):.1f}" if not timing_df.empty else "n/a")
            timing_metrics[1].metric("Triggering+", int(timing_df["timing_state"].isin(["Triggering", "Confirmed"]).sum()) if not timing_df.empty else 0)
            timing_metrics[2].metric("Coiling", int(timing_df["timing_state"].eq("Coiling").sum()) if not timing_df.empty else 0)
            timing_metrics[3].metric("Extended/fragile", int(timing_df["timing_state"].eq("Extended / fragile").sum()) if not timing_df.empty else 0)

            st.subheader("Timing Watchlist")
            if timing_df.empty:
                st.info("No timing rows are available yet.")
            else:
                st.dataframe(
                    _display_frame(timing_df.head(60), timing_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )
                timing_symbol = st.selectbox(
                    "Open timing card",
                    timing_df["symbol"].astype(str).head(60).tolist(),
                    key="timing_card_symbol",
                )
                timing_row = timing_df[timing_df["symbol"].astype(str) == timing_symbol].head(1)
                if not timing_row.empty:
                    st.markdown("```text\n" + build_timing_card(timing_row.iloc[0]) + "\n```")

            with st.expander("Show full timing table"):
                if timing_df.empty:
                    st.info("No timing rows to show.")
                else:
                    st.dataframe(
                        _display_frame(timing_df, timing_cols),
                        use_container_width=True,
                        hide_index=True,
                        column_config=breakout_column_config,
                    )

        with screener_tabs[11]:
            st.caption(
                "Dedicated 1-hour rate-of-change grid for Binance global short-account share. "
                "Positive percentage-point moves mean accounts are moving net short; negative moves mean short accounts are covering or long accounts are increasing."
            )
            short_roc_cols = [
                "symbol",
                "base_asset",
                "trade_bucket",
                "trade_bucket_score",
                "market_type",
                "last_price",
                "short_account_roc_1h_direction",
                "short_account_previous_1h_pct",
                "short_account_pct",
                "short_account_roc_1h_pp",
                "short_account_roc_1h_pct",
                "short_account_roc_1h_abs_pp",
                "short_account_roc_smoothed_3p_pp",
                "short_account_roc_smoothed_3p_pct",
                "short_account_acceleration_1h_pp",
                "short_account_acceleration_smoothed_3p_pp",
                "short_account_roc_zscore",
                "short_account_direction_persistence",
                "long_account_pct",
                "long_short_account_ratio",
                "short_account_history_points",
                "oi_delta_pct",
                "oi_value_usdt",
                "hour_return_pct",
                "hour_volume_multiple",
                "short_liquidation_fuel_score",
                "funding_flip_score",
                "forced_buying_setup_score",
                "short_crowding_score",
                "quote_volume_24h",
                "day_return_pct",
            ]
            short_roc_df = all_df[
                pd.to_numeric(all_df["short_account_history_points"], errors="coerce").fillna(0) >= 2
            ].copy()
            short_roc_df["short_account_roc_1h_abs_pp"] = pd.to_numeric(
                short_roc_df.get("short_account_roc_1h_abs_pp", pd.Series(0.0, index=short_roc_df.index)),
                errors="coerce",
            ).fillna(0.0)
            short_roc_df = short_roc_df.sort_values(
                ["short_account_roc_1h_abs_pp", "quote_volume_24h", "symbol"],
                ascending=[False, False, True],
            )
            roc_increase_df = short_roc_df[pd.to_numeric(short_roc_df.get("short_account_roc_1h_pp"), errors="coerce").fillna(0.0) > 0]
            roc_decrease_df = short_roc_df[pd.to_numeric(short_roc_df.get("short_account_roc_1h_pp"), errors="coerce").fillna(0.0) < 0]
            biggest_abs = float(short_roc_df["short_account_roc_1h_abs_pp"].max()) if not short_roc_df.empty else float("nan")
            avg_abs = float(short_roc_df["short_account_roc_1h_abs_pp"].mean()) if not short_roc_df.empty else float("nan")
            sr1, sr2, sr3, sr4 = st.columns(4)
            sr1.metric("Symbols with 1h history", int(len(short_roc_df)))
            sr2.metric("Short builds", int(len(roc_increase_df)))
            sr3.metric("Short covers", int(len(roc_decrease_df)))
            sr4.metric("Biggest abs move", f"{biggest_abs:.2f} pp" if math.isfinite(biggest_abs) else "n/a")
            st.metric("Average abs 1h move", f"{avg_abs:.2f} pp" if math.isfinite(avg_abs) else "n/a")

            if short_roc_df.empty:
                st.info("No 1-hour short-account history is available in this scan.")
            else:
                st.dataframe(
                    _display_frame(short_roc_df.head(80), short_roc_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

        with screener_tabs[12]:
            st.caption(
                "Ranks the biggest changes in Binance global short-account share by symbol. "
                f"Period: {LONG_SHORT_RATIO_PERIOD}; windows: {', '.join(f'{window}p' for window in SHORT_ACCOUNT_CHANGE_WINDOWS)}; "
                f"history rows requested per symbol: {LONG_SHORT_RATIO_HISTORY_LIMIT}. "
                "Positive changes mean more accounts have moved net short; negative changes mean shorts are covering or longs are increasing."
            )
            short_change_cols = [
                "symbol",
                "base_asset",
                "trade_bucket",
                "trade_bucket_score",
                "market_type",
                "last_price",
                "short_account_pct",
                "long_account_pct",
                "long_short_account_ratio",
                "short_account_change_max_pct",
                "short_account_change_max_pp",
                "short_account_change_max_window",
                "short_account_change_min_pct",
                "short_account_change_min_pp",
                "short_account_change_min_window",
                "short_account_change_1p_pct",
                "short_account_change_1p_pp",
                "short_account_change_3p_pct",
                "short_account_change_3p_pp",
                "short_account_change_6p_pct",
                "short_account_change_6p_pp",
                "short_account_change_12p_pct",
                "short_account_change_12p_pp",
                "short_account_change_24p_pct",
                "short_account_change_24p_pp",
                "short_account_history_points",
                "forced_buying_setup_flag",
                "clean_convex_setup_flag",
                "forced_buying_setup_score",
                "clean_convex_setup_score",
                "crowd_skew_confluence_score",
                "short_liquidation_fuel_score",
                "short_crowding_score",
                "funding_flip_score",
                "oi_delta_pct",
                "oi_value_usdt",
                "carry_funding_pct",
                "day_return_pct",
                "hour_return_pct",
                "taker_buy_share_pct",
                "breakout_pressure_score",
                "convexity_entry_score",
                "squeeze_machine_score",
            ]
            short_change_base_df = all_df[
                pd.to_numeric(all_df["short_account_history_points"], errors="coerce").fillna(0) >= 2
            ].copy()
            short_build_df = short_change_base_df.sort_values(
                [
                    "short_account_change_max_pct",
                    "short_account_change_max_pp",
                    "short_account_pct",
                    "oi_delta_pct",
                    "symbol",
                ],
                ascending=[False, False, False, False, True],
            )
            short_cover_df = short_change_base_df.sort_values(
                [
                    "short_account_change_min_pct",
                    "short_account_change_min_pp",
                    "short_account_pct",
                    "symbol",
                ],
                ascending=[True, True, False, True],
            )
            squeeze_watch_df = short_change_base_df[
                (
                    (pd.to_numeric(short_change_base_df["short_account_change_max_pct"], errors="coerce") >= 3.0)
                    | (pd.to_numeric(short_change_base_df["short_account_change_max_pp"], errors="coerce") >= 1.5)
                )
                & (
                    (pd.to_numeric(short_change_base_df["short_account_pct"], errors="coerce") >= 50.0)
                    | short_change_base_df["forced_buying_setup_flag"].fillna(False).astype(bool)
                    | (pd.to_numeric(short_change_base_df["short_liquidation_fuel_score"], errors="coerce") >= 45.0)
                )
            ].copy()
            squeeze_watch_df = squeeze_watch_df.sort_values(
                [
                    "forced_buying_setup_flag",
                    "clean_convex_setup_flag",
                    "short_account_change_max_pct",
                    "short_account_change_max_pp",
                    "oi_delta_pct",
                    "convexity_entry_score",
                    "symbol",
                ],
                ascending=[False, False, False, False, False, False, True],
            )

            max_build = float(pd.to_numeric(short_change_base_df["short_account_change_max_pct"], errors="coerce").max()) if not short_change_base_df.empty else float("nan")
            max_cover = float(pd.to_numeric(short_change_base_df["short_account_change_min_pct"], errors="coerce").min()) if not short_change_base_df.empty else float("nan")
            median_current_short = float(pd.to_numeric(short_change_base_df["short_account_pct"], errors="coerce").median()) if not short_change_base_df.empty else float("nan")
            sm1, sm2, sm3, sm4 = st.columns(4)
            sm1.metric("Symbols with history", int(len(short_change_base_df)))
            sm2.metric("Biggest short build", f"{max_build:.2f}%" if math.isfinite(max_build) else "n/a")
            sm3.metric("Biggest short cover", f"{max_cover:.2f}%" if math.isfinite(max_cover) else "n/a")
            sm4.metric("Median short accounts", f"{median_current_short:.1f}%" if math.isfinite(median_current_short) else "n/a")

            build_col, cover_col = st.columns(2)
            build_col.subheader("Shorts Piling In")
            if short_build_df.empty:
                build_col.info("No short-account history is available in this scan.")
            else:
                build_col.dataframe(
                    _display_frame(short_build_df.head(30), short_change_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            cover_col.subheader("Shorts Covering Fast")
            if short_cover_df.empty:
                cover_col.info("No short-account history is available in this scan.")
            else:
                cover_col.dataframe(
                    _display_frame(short_cover_df.head(30), short_change_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            st.subheader("Short Build + Convex Fuel")
            if squeeze_watch_df.empty:
                st.info("No symbols currently combine rising short-account share with enough squeeze/convex fuel.")
            else:
                st.dataframe(
                    _display_frame(squeeze_watch_df.head(40), short_change_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            with st.expander("Show full short-account change table"):
                if short_change_base_df.empty:
                    st.info("No short-account history is available in this scan.")
                else:
                    st.dataframe(
                        _display_frame(short_build_df, short_change_cols),
                        use_container_width=True,
                        hide_index=True,
                        column_config=breakout_column_config,
                    )

        with screener_tabs[13]:
            st.caption(
                "Ranks RAVE/LAB-style controlled-float upside structures by combining centralized holder/insider proxies, "
                "low-float and FDV gap, rising short-account share, target CEX-flow proxies for Binance/Bitget/Gate/OKX, "
                "price/volume ignition, and convexity fuel. This is a structural upside/risk screen, not proof of manipulation."
            )
            rave_lab_cols = [
                "symbol",
                "base_asset",
                "trade_bucket",
                "trade_bucket_score",
                "pre_pump_precision_score",
                "pre_pump_precision_flag",
                "rave_lab_setup_score",
                "dormant_short_fuse_score",
                "dormant_short_fuse_flag",
                "rave_lab_extreme_flag",
                "rave_lab_setup_flag",
                "rave_lab_watch_flag",
                "pre_pump_precision_note",
                "dormant_short_fuse_note",
                "rave_lab_setup_note",
                "last_price",
                "range_24h_pct",
                "day_return_pct",
                "hour_return_pct",
                "daily_quote_volume_multiple",
                "hour_volume_multiple",
                "hour_trade_count_multiple",
                "short_account_pct",
                "long_account_pct",
                "short_account_change_max_pct",
                "short_account_change_max_pp",
                "short_account_change_max_window",
                "long_short_account_ratio",
                "insider_team_holder_pct",
                "owner_holder_pct",
                "creator_holder_pct",
                "top10_holder_pct",
                "holder_count",
                "locked_supply_pct",
                "circulating_supply_pct",
                "fdv_to_market_cap",
                "target_cex_volume_share_pct",
                "target_cex_flow_score",
                "binance_volume_share_pct",
                "bitget_volume_share_pct",
                "gate_volume_share_pct",
                "okx_volume_share_pct",
                "cex_to_dex_volume_ratio",
                "inventory_transfer_risk_score",
                "inventory_transfer_note",
                "centralized_ownership_score",
                "low_float_score",
                "pre_pump_compression_score",
                "short_trap_score",
                "silent_oi_accumulation_score",
                "short_account_build_score",
                "short_dominance_score",
                "low_volatility_coil_score",
                "pre_pump_short_fuse_score",
                "price_volume_ignition_score",
                "cex_lane_wakeup_score",
                "target_cex_share_change_pp",
                "oi_value_change_since_scan_pct",
                "ask_depth_1pct_change_pct",
                "ask_depth_1pct_usdt",
                "ask_depth_to_24h_volume_pct",
                "ask_depth_withdrawal_score",
                "thin_ask_trap_score",
                "rave_lab_convex_fuel_score",
                "rave_lab_late_penalty_score",
                "no_chase_penalty_score",
                "no_chase_ok_flag",
                "clean_convex_setup_score",
                "forced_buying_setup_score",
                "squeeze_machine_score",
                "convexity_entry_score",
                "ath_multiple",
                "ath_upside_pct",
            ]
            major_mask = (
                all_df["crime_excluded_major"].fillna(False).astype(bool)
                if "crime_excluded_major" in all_df.columns
                else pd.Series(False, index=all_df.index)
            )
            radar_df = all_df[~major_mask].copy()
            score_series = pd.to_numeric(radar_df["rave_lab_setup_score"], errors="coerce") if "rave_lab_setup_score" in radar_df.columns else pd.Series(dtype="float64")
            radar_ranked_df = radar_df.sort_values(
                [
                    "pre_pump_precision_flag",
                    "dormant_short_fuse_flag",
                    "rave_lab_extreme_flag",
                    "rave_lab_setup_flag",
                    "pre_pump_precision_score",
                    "dormant_short_fuse_score",
                    "rave_lab_setup_score",
                    "low_volatility_coil_score",
                    "short_dominance_score",
                    "short_account_build_score",
                    "price_volume_ignition_score",
                    "target_cex_flow_score",
                    "symbol",
                ],
                ascending=[False, False, False, False, False, False, False, False, False, False, False, False, True],
            )
            precision_df = radar_ranked_df[
                (pd.to_numeric(radar_ranked_df["pre_pump_precision_score"], errors="coerce").fillna(0.0) >= 45.0)
                & (pd.to_numeric(radar_ranked_df["no_chase_penalty_score"], errors="coerce").fillna(100.0) < 68.0)
            ].sort_values(
                [
                    "pre_pump_precision_flag",
                    "pre_pump_precision_score",
                    "short_trap_score",
                    "silent_oi_accumulation_score",
                    "thin_ask_trap_score",
                    "symbol",
                ],
                ascending=[False, False, False, False, False, True],
            )
            dormant_short_fuse_df = radar_ranked_df[
                (pd.to_numeric(radar_ranked_df["dormant_short_fuse_score"], errors="coerce").fillna(0.0) >= 45.0)
                & (pd.to_numeric(radar_ranked_df["low_volatility_coil_score"], errors="coerce").fillna(0.0) >= 42.0)
                & (pd.to_numeric(radar_ranked_df["short_dominance_score"], errors="coerce").fillna(0.0) >= 38.0)
            ].sort_values(
                [
                    "dormant_short_fuse_flag",
                    "dormant_short_fuse_score",
                    "low_volatility_coil_score",
                    "short_dominance_score",
                    "low_float_score",
                    "centralized_ownership_score",
                    "symbol",
                ],
                ascending=[False, False, False, False, False, False, True],
            )
            low_float_short_df = radar_ranked_df[
                (pd.to_numeric(radar_ranked_df["low_float_score"], errors="coerce").fillna(0.0) >= 45.0)
                & (pd.to_numeric(radar_ranked_df["short_account_build_score"], errors="coerce").fillna(0.0) >= 42.0)
            ].copy()
            cex_control_df = radar_ranked_df[
                (pd.to_numeric(radar_ranked_df["target_cex_flow_score"], errors="coerce").fillna(0.0) >= 45.0)
                & (pd.to_numeric(radar_ranked_df["centralized_ownership_score"], errors="coerce").fillna(0.0) >= 38.0)
            ].copy()
            ignition_df = radar_ranked_df[
                (pd.to_numeric(radar_ranked_df["price_volume_ignition_score"], errors="coerce").fillna(0.0) >= 55.0)
                & (pd.to_numeric(radar_ranked_df["rave_lab_late_penalty_score"], errors="coerce").fillna(0.0) < 72.0)
            ].copy()

            r1, r2, r3, r4 = st.columns(4)
            best_score = float(score_series.max()) if not score_series.empty and pd.notna(score_series.max()) else float("nan")
            r1.metric("Best setup score", f"{best_score:.1f}" if math.isfinite(best_score) else "n/a")
            r2.metric("Short-fuse flags", int(radar_df.get("dormant_short_fuse_flag", pd.Series(False, index=radar_df.index)).fillna(False).astype(bool).sum()))
            r3.metric("Precision flags", int(radar_df.get("pre_pump_precision_flag", pd.Series(False, index=radar_df.index)).fillna(False).astype(bool).sum()))
            r4.metric("Watchlist", int(radar_df.get("rave_lab_watch_flag", pd.Series(False, index=radar_df.index)).fillna(False).astype(bool).sum()))

            st.subheader("High-Precision Pre-Ignition Radar")
            st.caption(
                "This is the strictest view: compression + short trap + silent OI + low-float/owner pressure, "
                "with CEX/depth scan memory and a no-chase gate."
            )
            if precision_df.empty:
                st.info("No high-precision pre-ignition rows currently clear the filter.")
            else:
                st.dataframe(
                    _display_frame(precision_df.head(35), rave_lab_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            st.subheader("Low-Vol Short Fuse")
            st.caption(
                "CHIP-style pre-ignition radar: quiet 24h range, muted returns, shorts already dominant or building, "
                "and enough owner/float concentration to make the float structurally fragile."
            )
            if dormant_short_fuse_df.empty:
                st.info("No quiet short-fuse rows currently clear the filter.")
            else:
                st.dataframe(
                    _display_frame(dormant_short_fuse_df.head(35), rave_lab_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            st.subheader("Best Controlled-Float Upside Scores")
            if radar_ranked_df.empty:
                st.info("No RAVE/LAB-style radar rows are available in this scan.")
            else:
                st.dataframe(
                    _display_frame(radar_ranked_df.head(40), rave_lab_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            focus_left, focus_right = st.columns(2)
            focus_left.subheader("Low Float + Shorts Increasing")
            if low_float_short_df.empty:
                focus_left.info("No symbols currently combine low-float structure with rising short-account share.")
            else:
                focus_left.dataframe(
                    _display_frame(low_float_short_df.head(25), rave_lab_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            focus_right.subheader("Centralized Ownership + Target CEX Flow")
            if cex_control_df.empty:
                focus_right.info("No symbols currently combine centralized holder proxies with target CEX-flow signals.")
            else:
                focus_right.dataframe(
                    _display_frame(cex_control_df.head(25), rave_lab_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            st.subheader("Price / Volume Ignition Without Late-Stage Heat")
            if ignition_df.empty:
                st.info("No early ignition rows currently clear the heat filter.")
            else:
                st.dataframe(
                    _display_frame(ignition_df.head(30), rave_lab_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            st.subheader("Forward Label Tracker")
            st.caption(
                "Every scan appends a lightweight snapshot. This panel labels prior top-10 pre-ignition signals by "
                "the best later price observed inside each horizon, so we can tune for precision instead of guessing."
            )
            history = _read_pre_pump_snapshot_history()
            label_cols = st.columns(4)
            label_cols[0].metric("Stored snapshots", int(len(history)))
            label_events_6h = _pre_pump_label_events(history, horizon_hours=6, top_per_scan=10)
            label_events_24h = _pre_pump_label_events(history, horizon_hours=24, top_per_scan=10)
            label_events_72h = _pre_pump_label_events(history, horizon_hours=72, top_per_scan=10)

            def _hit_rate(events: pd.DataFrame, column: str = "hit_20pct") -> str:
                if events.empty or column not in events.columns:
                    return "n/a"
                return f"{float(events[column].mean() * 100.0):.1f}%"

            label_cols[1].metric("6h hit +20%", _hit_rate(label_events_6h))
            label_cols[2].metric("24h hit +20%", _hit_rate(label_events_24h))
            label_cols[3].metric("72h hit +20%", _hit_rate(label_events_72h))
            if label_events_24h.empty:
                st.info("Forward labels will populate after enough scans have run across at least one horizon.")
            else:
                st.dataframe(
                    label_events_24h.sort_values(
                        ["hit_100pct", "hit_50pct", "hit_20pct", "max_return_24h_pct", "pre_pump_precision_score"],
                        ascending=[False, False, False, False, False],
                    ).head(40),
                    use_container_width=True,
                    hide_index=True,
                )

            with st.expander("Show full RAVE/LAB radar table"):
                if radar_ranked_df.empty:
                    st.info("No radar rows to show.")
                else:
                    st.dataframe(
                        _display_frame(radar_ranked_df, rave_lab_cols),
                        use_container_width=True,
                        hide_index=True,
                        column_config=breakout_column_config,
                    )

        with screener_tabs[14]:
            st.caption(
                "One-board triage for the exact early move pattern: explorer-backed top10 whale control, Binance+Bitget trading evidence, "
                "60D no-pump/dormancy proof, confirmed Binance/Bitget/Gate wallet-to-CEX flow when available, short-account squeeze fuel, low-float structure, and not-late timing."
            )
            pump_cols = [
                "symbol",
                "base_asset",
                "early_pump_radar_score",
                "early_pump_state",
                "early_pump_alert_flag",
                "early_pump_primary_signal",
                "early_pump_next_check",
                "early_pump_note",
                "early_pump_confirmed_target_flow",
                "early_pump_holder_evidence_gate",
                "early_pump_whale_gate",
                "early_pump_short_gate",
                "early_pump_float_gate",
                "early_pump_binance_bitget_gate",
                "early_pump_venue_gate",
                "early_pump_not_late_gate",
                "early_pump_no_recent_pump_gate",
                "early_pump_flow_score",
                "early_pump_whale_score",
                "early_pump_float_score",
                "early_pump_short_squeeze_score",
                "early_pump_timing_score",
                "early_pump_venue_score",
                "early_pump_archetype_score",
                "early_pump_not_late_score",
                "archetype_best_match",
                "archetype_match_score",
                "archetype_rave_score",
                "archetype_lab_score",
                "archetype_siren_score",
                "archetype_river_score",
                "archetype_sto_score",
                "trade_bucket",
                "trade_bucket_score",
                "terminal_edge_score",
                "timing_score",
                "timing_state",
                "timing_observed_trigger",
                "cex_deposit_flow_score",
                "cex_deposit_inventory_stress_score",
                "cex_deposit_24h_count",
                "cex_deposit_24h_max_amount",
                "cex_deposit_24h_notional_usd",
                "cex_deposit_24h_target_exchanges",
                "cex_deposit_flow_source",
                "cex_deposit_24h_source_url",
                "top10_holder_pct",
                "top100_holder_pct",
                "centralized_ownership_score",
                "low_float_score",
                "float_trap_score",
                "fdv_to_market_cap",
                "short_account_pct",
                "short_account_change_max_pct",
                "oi_delta_pct",
                "hour_return_pct",
                "day_return_pct",
                "hour_volume_multiple",
                "hour_trade_count_multiple",
                "hour_close_location_pct",
                "hour_upper_wick_pct",
                "binance_bitget_gate_share_pct",
                "binance_volume_share_pct",
                "bitget_volume_share_pct",
                "gate_volume_share_pct",
                "ath_multiple",
                "convexity_late_penalty",
                "timing_too_late_score",
            ]
            pump_df = all_df.copy()
            if "early_pump_radar_score" in pump_df.columns:
                pump_df = pump_df.sort_values(
                    [
                        "early_pump_alert_flag",
                        "early_pump_confirmed_target_flow",
                        "early_pump_radar_score",
                        "early_pump_flow_score",
                        "early_pump_short_squeeze_score",
                        "symbol",
                    ],
                    ascending=[False, False, False, False, False, True],
                )

            pump_dormant_gate = _dashboard_bool_series(pump_df, "early_pump_no_recent_pump_gate")
            watch_mask = _early_pump_dashboard_watch_mask(pump_df)
            pump_watch_df = pump_df[watch_mask].copy()
            prime_count = int((pump_df.get("early_pump_state", pd.Series("", index=pump_df.index)).astype(str) == "Prime early squeeze").sum())
            dormant_count = int(pump_dormant_gate.sum())
            p1, p2, p3, p4 = st.columns(4)
            p1.metric(
                "Top pump radar",
                f"{float(pd.to_numeric(pump_df.get('early_pump_radar_score', pd.Series(dtype='float64')), errors='coerce').max()):.1f}"
                if not pump_df.empty
                else "n/a",
            )
            p2.metric("Watch rows", int(len(pump_watch_df)))
            p3.metric("Prime early squeezes", prime_count)
            p4.metric("60D no-pump rows", dormant_count)

            st.subheader("Early Pump Catch Board")
            if pump_watch_df.empty:
                st.info("No rows currently clear the pump radar watch floor.")
            else:
                st.dataframe(
                    _display_frame(pump_watch_df.head(60), pump_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            with st.expander("Show full pump radar table"):
                if pump_df.empty:
                    st.info("No pump radar rows to show.")
                else:
                    st.dataframe(
                        _display_frame(pump_df, pump_cols),
                        use_container_width=True,
                        hide_index=True,
                        column_config=breakout_column_config,
                    )

        with screener_tabs[15]:
            st.caption(
                "Pre-activity radar: explorer-backed top10 holder control, Binance+Bitget trading evidence, controlled float, target-CEX inventory tells, "
                "60D no-pump/dormancy proof, short-fuse perp positioning, and thin books, while filtering out names that already have chase heat."
            )
            pre_activity_cols = [
                "symbol",
                "base_asset",
                "pre_activity_pump_score",
                "pre_activity_state",
                "pre_activity_alert_flag",
                "pre_activity_primary_signal",
                "pre_activity_next_check",
                "pre_activity_note",
                "pre_activity_confirmed_target_flow",
                "pre_activity_holder_evidence_gate",
                "pre_activity_whale_gate",
                "pre_activity_binance_bitget_gate",
                "pre_activity_structure_gate",
                "pre_activity_behavior_gate",
                "pre_activity_quiet_gate",
                "pre_activity_no_recent_pump_gate",
                "pre_activity_control_score",
                "pre_activity_float_score",
                "pre_activity_behavior_score",
                "pre_activity_short_fuse_score",
                "pre_activity_quiet_score",
                "pre_activity_heat_score",
                "pre_activity_venue_score",
                "pre_activity_thin_book_score",
                "pre_activity_preignition_score",
                "archetype_reference_symbol",
                "archetype_reference_date",
                "archetype_reference_pattern",
                "cex_deposit_flow_score",
                "cex_deposit_inventory_stress_score",
                "cex_deposit_24h_count",
                "cex_deposit_24h_max_amount",
                "cex_deposit_24h_target_exchanges",
                "top10_holder_pct",
                "top100_holder_pct",
                "holder_count",
                "low_float_score",
                "fdv_to_market_cap",
                "ask_depth_1pct_usdt",
                "ask_depth_to_24h_volume_pct",
                "short_account_pct",
                "short_account_change_max_pp",
                "oi_to_24h_volume_pct",
                "binance_bitget_gate_share_pct",
                "hour_return_pct",
                "day_return_pct",
                "range_24h_pct",
                "hour_volume_multiple",
                "daily_quote_volume_multiple",
                "cmc_mover_score",
            ]
            pre_df = all_df.copy()
            if "pre_activity_pump_score" in pre_df.columns:
                pre_df = pre_df.sort_values(
                    [
                        "pre_activity_alert_flag",
                        "pre_activity_confirmed_target_flow",
                        "pre_activity_pump_score",
                        "pre_activity_behavior_score",
                        "pre_activity_quiet_score",
                        "symbol",
                    ],
                    ascending=[False, False, False, False, False, True],
                )
            pre_dormant_gate = _dashboard_bool_series(pre_df, "pre_activity_no_recent_pump_gate")
            pre_watch_mask = _pre_activity_dashboard_watch_mask(pre_df)
            pre_watch_df = pre_df[pre_watch_mask].copy()
            latent_flow_count = int(
                pre_df.get("pre_activity_confirmed_target_flow", pd.Series(False, index=pre_df.index)).fillna(False).astype(bool).sum()
            )
            q1, q2, q3, q4 = st.columns(4)
            q1.metric(
                "Top pre-activity score",
                f"{float(pd.to_numeric(pre_df.get('pre_activity_pump_score', pd.Series(dtype='float64')), errors='coerce').max()):.1f}"
                if not pre_df.empty
                else "n/a",
            )
            q2.metric("Watch rows", int(len(pre_watch_df)))
            q3.metric(
                "60D no-pump rows",
                int(pre_dormant_gate.sum()),
            )
            q4.metric("Target-flow rows", latent_flow_count)

            st.subheader("Pre-Activity Crime-Pump Radar")
            if pre_watch_df.empty:
                st.info("No rows currently clear the pre-activity watch floor.")
            else:
                st.dataframe(
                    _display_frame(pre_watch_df.head(60), pre_activity_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            with st.expander("Show full pre-activity radar table"):
                if pre_df.empty:
                    st.info("No pre-activity radar rows to show.")
                else:
                    st.dataframe(
                        _display_frame(pre_df, pre_activity_cols),
                        use_container_width=True,
                        hide_index=True,
                        column_config=breakout_column_config,
                    )

        with screener_tabs[16]:
            st.caption(
                "Mechanism map for convex structures: the table ranks the dominant reflexive loop instead of only listing raw signals. "
                "The crowded-short uptrend score is the positive-funding, high-shorts, rising-shorts, advancing-price structure you called out."
            )
            mechanism_cols = [
                "symbol",
                "base_asset",
                "mechanism_score",
                "mechanism_primary",
                "mechanism_stage",
                "mechanism_playbook_label",
                "mechanism_playbook_rule",
                "mechanism_reflexivity_loop",
                "mechanism_evidence_note",
                "mechanism_next_check",
                "mechanism_invalidation",
                "mechanism_crowded_short_uptrend_score",
                "mechanism_hidden_float_score",
                "mechanism_inventory_squeeze_score",
                "mechanism_compression_ignition_score",
                "mechanism_runway_breakout_score",
                "mechanism_late_failure_score",
                "crowded_short_uptrend_score",
                "crowded_short_uptrend_note",
                "short_account_pct",
                "short_account_roc_1h_pp",
                "short_account_change_max_pp",
                "carry_funding_pct",
                "predicted_funding_pct",
                "broke_high_5d",
                "broke_high_20d",
                "broke_high_90d",
                "broke_high_180d",
                "range_high_break_count",
                "day_return_pct",
                "hour_return_pct",
                "oi_delta_pct",
                "terminal_edge_score",
                "terminal_short_pressure_score",
                "terminal_float_score",
                "terminal_exchange_flow_score",
                "cex_deposit_flow_score",
                "cex_deposit_inventory_stress_score",
                "top10_holder_pct",
                "top100_holder_pct",
                "trade_bucket",
                "trade_bucket_score",
            ]
            mechanism_df = all_df.copy()
            if "market_type" in mechanism_df.columns:
                mechanism_df = mechanism_df[~mechanism_df["market_type"].astype(str).str.upper().isin(TRADFI_ALWAYS_INCLUDE_TYPES)].copy()
            if "mechanism_score" in mechanism_df.columns:
                mechanism_df = mechanism_df.sort_values(
                    [
                        "mechanism_score",
                        "mechanism_crowded_short_uptrend_score",
                        "mechanism_inventory_squeeze_score",
                        "mechanism_hidden_float_score",
                        "symbol",
                    ],
                    ascending=[False, False, False, False, True],
                )
            active_mechanisms = mechanism_df[
                pd.to_numeric(mechanism_df.get("mechanism_score", pd.Series(dtype="float64")), errors="coerce").fillna(0.0) >= 45.0
            ].copy()
            crowded_mechanisms = mechanism_df[
                pd.to_numeric(
                    mechanism_df.get("mechanism_crowded_short_uptrend_score", pd.Series(dtype="float64")),
                    errors="coerce",
                ).fillna(0.0)
                >= 45.0
            ].copy()
            late_risk_mechanisms = mechanism_df[
                pd.to_numeric(mechanism_df.get("mechanism_late_failure_score", pd.Series(dtype="float64")), errors="coerce").fillna(0.0)
                >= 70.0
            ].copy()
            m1, m2, m3, m4 = st.columns(4)
            top_mechanism = float(pd.to_numeric(mechanism_df.get("mechanism_score", pd.Series(dtype="float64")), errors="coerce").max()) if not mechanism_df.empty else float("nan")
            m1.metric("Active mechanisms", int(len(active_mechanisms)))
            m2.metric("Best mechanism", f"{top_mechanism:.1f}" if math.isfinite(top_mechanism) else "n/a")
            m3.metric("Short-uptrend loops", int(len(crowded_mechanisms)))
            m4.metric("Late-risk rows", int(len(late_risk_mechanisms)))

            st.subheader("Dominant Convex Mechanisms")
            if active_mechanisms.empty:
                st.info("No rows currently have a dominant mechanism score above 45.")
            else:
                st.dataframe(
                    _display_frame(active_mechanisms.head(60), mechanism_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            with st.expander("Crowded-short uptrend continuation only"):
                if crowded_mechanisms.empty:
                    st.info("No positive-funding, high-shorts, rising-shorts uptrend loops are active in this scan.")
                else:
                    st.dataframe(
                        _display_frame(crowded_mechanisms.head(80), mechanism_cols),
                        use_container_width=True,
                        hide_index=True,
                        column_config=breakout_column_config,
                    )

            with st.expander("Case-study event evidence"):
                fetch_case_price_paths = st.checkbox(
                    "Fetch Binance daily price paths",
                    value=False,
                    key="mechanism_case_study_fetch_price_paths",
                )
                try:
                    case_client = BinanceFuturesPublic(requests_per_second=2.0, retries=2) if fetch_case_price_paths else None
                    case_df = build_case_study_event_frame(root=APP_DIR, kline_client=case_client)
                except Exception as exc:
                    st.warning(f"Case-study evidence could not be loaded: {exc}")
                    case_df = pd.DataFrame(columns=EVENT_STUDY_COLUMNS)
                case_cols = [
                    "symbol",
                    "event_date",
                    "mechanism_hypothesis",
                    "local_snapshot_count",
                    "best_snapshot_file",
                    "observed_phase",
                    "contract_hint_status",
                    "contract_hint_chain",
                    "contract_hint_address",
                    "price_path_status",
                    "price_event_date",
                    "price_event_date_source",
                    "event_day_return_pct",
                    "event_break_prior_20d_high",
                    "post_7d_high_return_pct",
                    "post_7d_low_drawdown_pct",
                    "mechanism_read",
                    "mechanism_verdict",
                    "scanner_lesson",
                    "evidence_gap_severity",
                    "next_data_action",
                    "evidence_gaps",
                ]
                st.dataframe(
                    _display_frame(case_df, case_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            with st.expander("Show full mechanism table"):
                if mechanism_df.empty:
                    st.info("No mechanism rows to show.")
                else:
                    st.dataframe(
                        _display_frame(mechanism_df.head(200), mechanism_cols),
                        use_container_width=True,
                        hide_index=True,
                        column_config=breakout_column_config,
                    )

        with screener_tabs[17]:
            st.caption(
                "Continuation lens for coins where shorts are still crowded and building while funding is positive and price structure is trending up. "
                "Downside breaks and late heat stay visible as penalties because high-volatility trends can still be valid until the structure actually unwinds."
            )
            crowded_uptrend_cols = [
                "symbol",
                "base_asset",
                "crowded_short_uptrend_score",
                "crowded_short_uptrend_note",
                "crowded_short_uptrend_funding_gate",
                "crowded_short_uptrend_short_gate",
                "crowded_short_uptrend_build_gate",
                "crowded_short_uptrend_trend_gate",
                "crowded_short_uptrend_effective_funding_pct",
                "carry_funding_pct",
                "predicted_funding_pct",
                "short_account_pct",
                "short_account_previous_1h_pct",
                "short_account_roc_1h_pp",
                "short_account_roc_1h_pct",
                "short_account_roc_smoothed_3p_pp",
                "short_account_acceleration_smoothed_3p_pp",
                "short_account_roc_zscore",
                "short_account_direction_persistence",
                "short_account_change_max_pp",
                "short_account_change_max_pct",
                "short_account_change_max_window",
                "long_short_account_ratio",
                "last_price",
                "anchored_vwap_30d",
                "price_vs_anchored_vwap_30d_pct",
                "day_return_pct",
                "hour_return_pct",
                "range_high_break_count",
                "range_low_break_count",
                "broke_high_5d",
                "broke_high_20d",
                "broke_high_90d",
                "broke_high_180d",
                "broke_low_5d",
                "broke_low_20d",
                "trend_confluence_score",
                "breakout_pressure_score",
                "daily_quote_volume_multiple",
                "hour_volume_multiple",
                "hour_close_location_pct",
                "oi_delta_pct",
                "oi_to_24h_volume_pct",
                "forced_buying_setup_score",
                "short_liquidation_fuel_score",
                "crowded_short_uptrend_funding_score",
                "crowded_short_uptrend_short_score",
                "crowded_short_uptrend_build_score",
                "crowded_short_uptrend_trend_score",
                "crowded_short_uptrend_oi_score",
                "crowded_short_uptrend_late_heat_score",
                "trade_bucket",
                "trade_bucket_score",
                "convexity_entry_score",
                "terminal_edge_score",
                "timing_score",
            ]
            control_cols = st.columns(4)
            min_short_pct = float(
                control_cols[0].number_input(
                    "Min short accounts %",
                    min_value=35.0,
                    max_value=90.0,
                    value=50.0,
                    step=1.0,
                    key="crowded_uptrend_min_short_pct",
                )
            )
            min_short_roc_pp = float(
                control_cols[1].number_input(
                    "Min 1h short build pp",
                    min_value=0.0,
                    max_value=10.0,
                    value=0.25,
                    step=0.25,
                    key="crowded_uptrend_min_short_roc_pp",
                )
            )
            min_funding_pct = float(
                control_cols[2].number_input(
                    "Min funding %",
                    min_value=-0.1000,
                    max_value=0.2500,
                    value=0.0000,
                    step=0.0025,
                    format="%.4f",
                    key="crowded_uptrend_min_funding_pct",
                )
            )
            top_n = int(
                control_cols[3].number_input(
                    "Rows",
                    min_value=10,
                    max_value=150,
                    value=50,
                    step=10,
                    key="crowded_uptrend_top_n",
                )
            )
            crowded_uptrend_df = _crowded_short_uptrend_candidates(
                all_df,
                min_short_pct=min_short_pct,
                min_short_roc_1h_pp=min_short_roc_pp,
                min_funding_pct=min_funding_pct,
            )
            best_score = float(pd.to_numeric(crowded_uptrend_df.get("crowded_short_uptrend_score", pd.Series(dtype="float64")), errors="coerce").max()) if not crowded_uptrend_df.empty else float("nan")
            median_short = float(pd.to_numeric(crowded_uptrend_df.get("short_account_pct", pd.Series(dtype="float64")), errors="coerce").median()) if not crowded_uptrend_df.empty else float("nan")
            median_funding = float(pd.to_numeric(crowded_uptrend_df.get("crowded_short_uptrend_effective_funding_pct", pd.Series(dtype="float64")), errors="coerce").median()) if not crowded_uptrend_df.empty else float("nan")
            late_heat_count = int(
                (
                    pd.to_numeric(
                        crowded_uptrend_df.get("crowded_short_uptrend_late_heat_score", pd.Series(dtype="float64")),
                        errors="coerce",
                    ).fillna(0.0)
                    >= 55.0
                ).sum()
            ) if not crowded_uptrend_df.empty else 0
            metric_cols = st.columns(4)
            metric_cols[0].metric("Candidates", int(len(crowded_uptrend_df)))
            metric_cols[1].metric("Best score", f"{best_score:.1f}" if math.isfinite(best_score) else "n/a")
            metric_cols[2].metric("Median shorts", f"{median_short:.1f}%" if math.isfinite(median_short) else "n/a")
            metric_cols[3].metric("Median funding", f"{median_funding:.4f}%" if math.isfinite(median_funding) else "n/a")
            st.metric("Late-heat candidates", late_heat_count)

            st.subheader("Positive Funding + Crowded Shorts + Uptrend")
            if crowded_uptrend_df.empty:
                st.info("No coins currently clear the crowded-short uptrend filter. Lower the thresholds or run a wider/deeper scan if you want more coverage.")
            else:
                st.dataframe(
                    _display_frame(crowded_uptrend_df.head(top_n), crowded_uptrend_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

            with st.expander("Show every gate-scored row"):
                scored_all = _crowded_short_uptrend_candidates(
                    all_df,
                    min_short_pct=0.0,
                    min_short_roc_1h_pp=0.0,
                    min_funding_pct=-1.0,
                    return_all=True,
                )
                if scored_all.empty:
                    st.info("No gate-scored crypto rows are available in this scan.")
                else:
                    st.dataframe(
                        _display_frame(scored_all.head(150), crowded_uptrend_cols),
                        use_container_width=True,
                        hide_index=True,
                        column_config=breakout_column_config,
                    )

        with screener_tabs[18]:
            volume_spike_cols = [
                "symbol",
                "base_asset",
                "market_type",
                "last_price",
                "quote_volume_24h",
                "quote_volume_prior_30d_total",
                "quote_volume_prior_30d_daily_avg",
                "quote_volume_prior_30d_days",
                "quote_volume_24h_vs_prior_30d_avg_ratio",
                "anchored_vwap_30d",
                "price_vs_anchored_vwap_30d_pct",
                "anchored_vwap_30d_days",
                "day_return_pct",
                "hour_return_pct",
                "hour_volume_multiple",
                "oi_delta_pct",
                "short_account_pct",
                "short_account_roc_1h_pct",
                "carry_funding_pct",
                "trade_bucket",
            ]
            volume_ratio = pd.to_numeric(
                all_df["quote_volume_24h_vs_prior_30d_avg_ratio"],
                errors="coerce",
            )
            volume_spikes_df = all_df[volume_ratio.notna()].sort_values(
                ["quote_volume_24h_vs_prior_30d_avg_ratio", "quote_volume_24h", "symbol"],
                ascending=[False, False, True],
            )
            if volume_spikes_df.empty:
                st.info("No prior daily-volume baseline is available in this scan.")
            else:
                st.dataframe(
                    _display_frame(volume_spikes_df, volume_spike_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )

        if INCLUDE_TRADFI_BREAKOUTS:
            st.subheader("Tracked commodities")
            tradfi_cols = [
                "symbol",
                "base_asset",
                "market_type",
                "history_days",
                "funding_interval_hours",
                "funding_countdown_hours",
                "carry_funding_pct",
                "carry_funding_annualized_pct",
                "long_short_account_ratio",
                "long_account_pct",
                "short_account_pct",
                "premium_index_pct",
                "predicted_funding_pct",
                "predicted_funding_annualized_pct",
                "predicted_funding_low_pct",
                "predicted_funding_high_pct",
                "predicted_funding_backtest_mae_pct",
                "predicted_funding_backtest_count",
                "funding_window_elapsed_pct",
                "corr_window_days",
                "last_price",
                "corr_to_btc_6m",
                "high_24h",
                "low_24h",
                "high_5d",
                "low_5d",
                "high_20d",
                "low_20d",
                "high_90d",
                "low_90d",
                "high_180d",
                "low_180d",
                "broke_high_5d",
                "broke_low_5d",
                "broke_high_20d",
                "broke_low_20d",
                "broke_high_90d",
                "broke_high_180d",
                "broke_low_90d",
                "broke_low_180d",
            ]
            commodity_df = all_df[all_df["market_type"] == "COMMODITY"].copy()
            if commodity_df.empty:
                st.info("Binance returned no TradFi commodity symbols in this scan.")
            else:
                commodity_df = commodity_df.sort_values(["symbol"]).copy()
                st.dataframe(
                    _display_frame(commodity_df, tradfi_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )
                st.caption(
                    "New listings can appear here before they have enough closed daily candles for the longer 90D/180D "
                    "levels or the full 180-day BTC correlation window."
                )

            st.subheader("Tracked equities")
            equity_df = all_df[all_df["market_type"] == "EQUITY"].copy()
            if equity_df.empty:
                st.info("Binance returned no TradFi equity symbols in this scan.")
            else:
                equity_df = equity_df.sort_values(["symbol"]).copy()
                st.dataframe(
                    _display_frame(equity_df, tradfi_cols),
                    use_container_width=True,
                    hide_index=True,
                    column_config=breakout_column_config,
                )
                st.caption("This section follows Binance's current TradFi equity listings, which today include symbols like NVDAUSDT and GOOGLUSDT.")

        st.subheader("Correlation to BTC")
        correlation_cols = [
            "symbol",
            "base_asset",
            "market_type",
            "history_days",
            "funding_interval_hours",
            "funding_countdown_hours",
            "carry_funding_pct",
            "carry_funding_annualized_pct",
            "long_short_account_ratio",
            "long_account_pct",
            "short_account_pct",
            "premium_index_pct",
            "predicted_funding_pct",
            "predicted_funding_annualized_pct",
            "predicted_funding_low_pct",
            "predicted_funding_high_pct",
            "predicted_funding_backtest_mae_pct",
            "predicted_funding_backtest_count",
            "funding_window_elapsed_pct",
            "corr_window_days",
            "corr_to_btc_6m",
            "last_price",
            "broke_high_5d",
            "broke_low_5d",
            "broke_high_20d",
            "broke_low_20d",
            "broke_high_90d",
            "broke_high_180d",
            "broke_low_90d",
            "broke_low_180d",
        ]
        correlation_df = all_df.sort_values(["corr_to_btc_6m", "symbol"], ascending=[False, True]).copy()
        st.dataframe(
            _display_frame(correlation_df, correlation_cols),
            use_container_width=True,
            hide_index=True,
            column_config=breakout_column_config,
        )

        with st.expander("Show full scanned table"):
            st.dataframe(
                all_df,
                use_container_width=True,
                hide_index=True,
                column_config=breakout_column_config,
            )
    else:
        st.markdown(
            '<div class="card">Click <b>Scan now</b> to fetch Binance data once and show 5D/20D/90D/180D breakouts plus live carry, modeled next funding, crowding, and the structure-radar tabs.</div>',
            unsafe_allow_html=True,
        )


def render_screener_dashboard() -> None:
    st.title("Cross-Asset Screener")
    st.caption(
        "Near-live cross-asset tape using Yahoo Finance for macro markets and Binance Futures for BTC. "
        "Venue delays and change calculations can differ by source."
    )

    if st.button("Refresh screener", type="primary", key="refresh_screener"):
        st.session_state["screener_requested"] = True
        st.session_state["screener_refresh_nonce"] = st.session_state.get("screener_refresh_nonce", 0) + 1

    if not st.session_state.get("screener_requested"):
        st.markdown(
            '<div class="card">Click <b>Refresh screener</b> to load the cross-asset tape for indices, '
            "volatility, commodities, rates, managed futures, and BTC.</div>",
            unsafe_allow_html=True,
        )
        return

    try:
        with st.spinner("Loading cross-asset screener..."):
            screener = load_screener_cached(st.session_state.get("screener_refresh_nonce", 0))
    except Exception as exc:
        st.error(f"Unable to load the screener right now: {exc}")
        return

    st.caption(f"Updated: {_now_utc()} | Sources: Yahoo Finance + Binance Futures")

    if screener.quotes_df.empty:
        st.warning("No screener assets could be loaded from the configured feeds.")
        if screener.errors:
            for error in screener.errors:
                st.write(f"- {error}")
        return

    quotes_df = screener.quotes_df.copy()
    quotes_df["price_sparkline"] = quotes_df["sparkline"]

    metrics = st.columns(4)
    metrics[0].metric("Assets loaded", str(int(len(quotes_df))))
    metrics[1].metric("Positive movers", str(int((quotes_df["change_pct"] > 0).sum())))
    metrics[2].metric("Negative movers", str(int((quotes_df["change_pct"] < 0).sum())))
    metrics[3].metric("Sources", str(int(quotes_df["source"].nunique())))

    st.subheader("Cross-asset tape")
    display_cols = [
        "code",
        "name",
        "category",
        "last_price",
        "change",
        "change_pct",
        "corr_window_days",
        "corr_to_btc",
        "corr_to_spx",
        "source",
        "price_sparkline",
    ]
    st.dataframe(
        _display_frame(quotes_df, display_cols),
        use_container_width=True,
        hide_index=True,
        column_config={
            "code": st.column_config.TextColumn("Ticker"),
            "name": st.column_config.TextColumn("Asset"),
            "category": st.column_config.TextColumn("Category"),
            "last_price": st.column_config.NumberColumn("Last", format="%.2f"),
            "change": st.column_config.NumberColumn("Change", format="%.2f"),
            "change_pct": st.column_config.NumberColumn("% Change", format="%.2f%%"),
            "corr_window_days": st.column_config.NumberColumn("Corr Window (D)", format="%d"),
            "corr_to_btc": st.column_config.NumberColumn("Corr to BTC", format="%.3f"),
            "corr_to_spx": st.column_config.NumberColumn("Corr to SPX", format="%.3f"),
            "source": st.column_config.TextColumn("Source"),
            "price_sparkline": st.column_config.LineChartColumn("Intraday"),
        },
    )

    if not screener.intraday_df.empty:
        st.subheader("Normalized intraday move")
        st.caption("Each line starts at 100 so you can compare intraday direction across very different markets.")
        st.line_chart(screener.intraday_df, use_container_width=True)

    if screener.errors:
        with st.expander("Unavailable screener assets"):
            for error in screener.errors:
                st.write(f"- {error}")


def render_pnl_dashboard() -> None:
    st.title("Binance Futures PnL Dashboard")
    st.caption(
        "Expanded analysis view with timeframe presets, a custom range control, cumulative charts, "
        "asset breakdowns, and detailed PnL stats."
    )

    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        st.warning("Set BINANCE_API_KEY and BINANCE_API_SECRET in .env or your environment to enable PnL.")
        return

    if st.button("Load / refresh PnL", type="primary", key="load_pnl"):
        st.session_state["pnl_requested"] = True
        st.session_state["pnl_refresh_nonce"] = st.session_state.get("pnl_refresh_nonce", 0) + 1

    if not st.session_state.get("pnl_requested"):
        st.markdown(
            '<div class="card">Click <b>Load / refresh PnL</b> to fetch Binance futures account data for '
            "the richer PnL analysis view.</div>",
            unsafe_allow_html=True,
        )
        return

    try:
        with st.spinner("Loading Binance PnL data..."):
            result = load_pnl_dashboard_cached(
                _key_fingerprint(BINANCE_API_KEY),
                st.session_state.get("pnl_refresh_nonce", 0),
            )
    except BinanceHTTPError as exc:
        payload = exc.payload if isinstance(exc.payload, dict) else {"msg": str(exc.payload)}
        st.error(f"Binance rejected the PnL request: {payload}")
        if payload.get("code") == -1022:
            st.info(
                "Binance is rejecting the API key/secret pair before any PnL data is returned. "
                "That means the blocker is the credentials rather than the dashboard logic."
            )
            for note in _credential_diagnostics(BINANCE_API_KEY, BINANCE_API_SECRET):
                st.write(f"- {note}")
            st.write("- Re-copy the API secret from Binance and update `.env`.")
            st.write("- Confirm this API key belongs to the same Binance account shown in the website PnL page.")
            st.write("- Confirm Futures read permissions are enabled on that key.")
            st.write("- Restart Streamlit after updating `.env`.")
        return
    except Exception as exc:
        st.error(f"Unable to load Binance PnL right now: {exc}")
        return

    st.caption(
        f"Updated: {_now_utc()} | Recent signed income lookback: {PNL_RECENT_DAYS} days | "
        f"Annual exports cache: {PNL_CACHE_DIR}"
    )

    account = result.account
    wallet_balance = _safe_float(account.get("totalWalletBalance"))
    margin_balance = _safe_float(account.get("totalMarginBalance"))
    unrealized_profit = _safe_float(account.get("totalUnrealizedProfit"))
    available_balance = _safe_float(account.get("availableBalance"))

    header_row = st.columns(4)
    header_row[0].metric("Wallet balance", _format_usd(wallet_balance))
    header_row[1].metric("Margin balance", _format_usd(margin_balance))
    header_row[2].metric("Unrealized PnL", _format_usd(unrealized_profit))
    header_row[3].metric("Open positions", str(_open_position_count(account)))

    if result.coverage_start is None or result.coverage_end is None:
        st.warning("Binance returned no usable PnL history for this account yet.")
        return

    now_utc = _utc_now()
    today_start = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc)
    day7_start = now_utc - timedelta(days=6)
    day30_start = now_utc - timedelta(days=29)
    three_year_start = now_utc - timedelta(days=365 * 3)
    pnl_currency = result.headline_currency

    cards_a = st.columns(4)
    cards_a[0].metric("Available balance", _format_usd(available_balance))
    cards_a[1].metric("Today's PnL", _format_pnl(_metric_period_total(result.daily_df, today_start), pnl_currency))
    cards_a[2].metric("7D PnL", _format_pnl(_metric_period_total(result.daily_df, day7_start), pnl_currency))
    cards_a[3].metric("30D PnL", _format_pnl(_metric_period_total(result.daily_df, day30_start), pnl_currency))

    cards_b = st.columns(4)
    cards_b[0].metric(
        _period_label("YTD PnL", result.completeness["ytd"]),
        _format_pnl(result.period_totals["ytd"], pnl_currency),
    )
    cards_b[1].metric(
        _period_label("1Y PnL", result.completeness["one_year"]),
        _format_pnl(result.period_totals["one_year"], pnl_currency),
    )
    cards_b[2].metric(
        _period_label("3Y PnL", _period_complete(result, three_year_start)),
        _format_pnl(_metric_period_total(result.daily_df, three_year_start), pnl_currency),
    )
    cards_b[3].metric(
        _period_label("Lifetime (ITD) PnL", result.completeness["itd"]),
        _format_pnl(result.period_totals["itd"], pnl_currency),
    )

    controls = st.columns([2, 3])
    preset = controls[0].radio("Range", RANGE_PRESETS, horizontal=True, key="pnl_range")
    min_date = _to_utc_date(result.coverage_start)
    max_date = _to_utc_date(result.coverage_end)
    default_start, default_end = _range_bounds("1Y", coverage_start=result.coverage_start, coverage_end=result.coverage_end)
    slider_value = controls[1].slider(
        "Custom range",
        min_value=min_date,
        max_value=max_date,
        value=(_to_utc_date(default_start), _to_utc_date(default_end)),
        format="YYYY-MM-DD",
        key="pnl_range_slider",
    )

    if preset == "Custom":
        start_dt = _date_to_utc(slider_value[0])
        end_dt = _date_to_utc(slider_value[1], end_of_day=True)
    else:
        start_dt, end_dt = _range_bounds(preset, coverage_start=result.coverage_start, coverage_end=result.coverage_end)
        start_dt = max(start_dt, result.coverage_start.to_pydatetime())

    selected_income = _filter_income_frame(result.income_df, start_dt, end_dt)
    selected_daily = _complete_daily_frame(_filter_daily_frame(result.daily_df, start_dt, end_dt), start_dt, end_dt)
    baseline_balance = _baseline_balance(result)
    stats = _build_period_stats(selected_income, selected_daily, baseline_balance=baseline_balance)

    st.subheader("Profit and Loss Analysis")
    st.caption(
        f"Selected range: {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')} | "
        f"Coverage starts: {result.coverage_start.strftime('%Y-%m-%d')}"
    )
    _render_stat_grid(stats, pnl_currency)

    chart_cols = st.columns(2)
    chart_cols[0].subheader("Daily net PnL")
    daily_chart = selected_daily.rename(columns={"date": "Date", "net_pnl": "Daily net PnL"}).set_index("Date")
    chart_cols[0].bar_chart(daily_chart[["Daily net PnL"]], use_container_width=True)

    chart_cols[1].subheader("Cumulative PnL")
    cumulative_chart = selected_daily.rename(columns={"date": "Date", "cumulative_pnl": "Cumulative PnL"}).set_index("Date")
    chart_cols[1].line_chart(cumulative_chart[["Cumulative PnL"]], use_container_width=True)

    benchmark_options: list[str] = []
    for symbol in result.symbol_totals_df.get("symbol", pd.Series(dtype=str)).head(6).tolist():
        if symbol and symbol not in benchmark_options:
            benchmark_options.append(symbol)
    for symbol in PNL_BENCHMARKS:
        if symbol not in benchmark_options:
            benchmark_options.append(symbol)

    benchmark_symbols = st.multiselect(
        "Benchmarks",
        options=benchmark_options,
        default=[symbol for symbol in PNL_BENCHMARKS if symbol in benchmark_options][:2],
        key="pnl_benchmarks",
    )
    if benchmark_symbols:
        with st.spinner("Loading benchmark comparison..."):
            compare_df = _build_benchmark_comparison(result, selected_daily, benchmark_symbols=benchmark_symbols)
        if not compare_df.empty:
            st.subheader("Cumulative PnL % vs benchmarks")
            st.caption("PnL % uses current wallet balance as the baseline, so treat it as directional rather than an exact Binance website clone.")
            compare_chart = compare_df.rename(columns={"date": "Date"}).set_index("Date")
            st.line_chart(compare_chart, use_container_width=True)

    asset_cols = st.columns(2)
    asset_cols[0].subheader("Current asset balances")
    if result.current_balances_df.empty:
        asset_cols[0].info("No non-zero balances returned.")
    else:
        asset_cols[0].bar_chart(result.current_balances_df.set_index("asset")[["wallet_balance"]], use_container_width=True)
        asset_cols[0].dataframe(result.current_balances_df, use_container_width=True, hide_index=True)

    asset_cols[1].subheader("Selected-range PnL by asset")
    if selected_income.empty:
        asset_cols[1].info("No PnL rows in this range.")
    else:
        selected_asset_totals = (
            selected_income.groupby("asset", as_index=False)
            .agg(net_pnl=("income", "sum"), events=("income", "size"))
            .sort_values("net_pnl", ascending=False)
        )
        asset_cols[1].bar_chart(selected_asset_totals.set_index("asset")[["net_pnl"]], use_container_width=True)
        asset_cols[1].dataframe(selected_asset_totals, use_container_width=True, hide_index=True)

    tabs = st.tabs(["Income Types", "Symbols", "Transactions", "Coverage"])

    with tabs[0]:
        if selected_income.empty:
            st.info("No income rows in this range.")
        else:
            income_type_totals = (
                selected_income.groupby("incomeType", as_index=False)
                .agg(net_pnl=("income", "sum"), events=("income", "size"))
                .sort_values("net_pnl", ascending=False)
            )
            st.dataframe(income_type_totals, use_container_width=True, hide_index=True)

    with tabs[1]:
        if selected_income.empty:
            st.info("No symbol-level PnL rows in this range.")
        else:
            symbol_totals = (
                selected_income[selected_income["symbol"] != ""]
                .groupby("symbol", as_index=False)
                .agg(net_pnl=("income", "sum"), events=("income", "size"))
                .sort_values("net_pnl", ascending=False)
            )
            st.dataframe(symbol_totals, use_container_width=True, hide_index=True)

    with tabs[2]:
        st.dataframe(selected_income.sort_values("time", ascending=False), use_container_width=True, hide_index=True)

    with tabs[3]:
        for note in result.notes:
            st.write(f"- {note}")
        if not result.notes:
            st.write("- No additional coverage notes.")
        st.write(f"- Earliest loaded PnL event: {result.coverage_start.strftime('%Y-%m-%d')}")
        st.write(f"- Latest loaded PnL event: {result.coverage_end.strftime('%Y-%m-%d')}")
        st.write(f"- Current benchmark baseline: {_format_pnl(baseline_balance, pnl_currency)}")


def _concentration_cache() -> ScanCache:
    return ScanCache(APP_DIR / "data" / "concentration_scanner.sqlite")


def _candidate_from_row(row: dict[str, Any]) -> PerpUniverseCandidate:
    fields = PerpUniverseCandidate.__dataclass_fields__.keys()
    return PerpUniverseCandidate(**{field: row.get(field) for field in fields})


def _candidate_rows(candidates: list[PerpUniverseCandidate]) -> list[dict[str, Any]]:
    return [candidate.__dict__ for candidate in candidates]


def _raw_holder(holder: Any) -> HolderRecord:
    raw = holder.raw_holder if hasattr(holder, "raw_holder") else holder
    return HolderRecord(
        rank=raw.rank,
        address=raw.address,
        label=raw.label,
        balance_raw=raw.balance_raw,
        balance_decimal=raw.balance_decimal,
        pct_total_supply=raw.pct_total_supply,
        value_usd=raw.value_usd,
        is_contract=raw.is_contract,
        explorer_url=raw.explorer_url,
        first_seen_token_transfer=raw.first_seen_token_transfer,
        last_seen_token_transfer=raw.last_seen_token_transfer,
        recent_inflows=raw.recent_inflows,
        recent_outflows=raw.recent_outflows,
        net_balance_change_24h=raw.net_balance_change_24h,
        net_balance_change_7d=raw.net_balance_change_7d,
        gas_funder=raw.gas_funder,
        token_source=raw.token_source,
        funding_source=raw.funding_source,
    )


def _render_concentration_result(result: Any) -> None:
    st.subheader(f"{result.token.name} ({result.token.symbol})")
    st.caption(
        f"{result.chain.upper()} contract {result.contract_address} | status {result.status.scanner_status} | "
        f"holder snapshot {result.status.last_holder_fetch_at or 'fixture/manual'}"
    )
    if result.status.scanner_error:
        st.warning(result.status.scanner_error)

    metric_cols = st.columns(6)
    metric_cols[0].metric("Master Score", f"{result.master_score.master_score:.1f}")
    metric_cols[1].metric("Master Label", result.master_score.master_label)
    metric_cols[2].metric("Manipulable Whale", f"{result.scores.manipulable_whale_score:.1f}")
    metric_cols[3].metric("RaveDAO Score", f"{result.scores.ravedao_archetype_score:.1f}")
    metric_cols[4].metric("Raw Top 1", f"{result.concentration.raw_top_1_pct:.2f}%")
    metric_cols[5].metric("Adjusted Top 5", f"{result.concentration.adjusted_top_5_pct:.2f}%")

    st.info(result.summary)
    if result.representation.wrapped_representation_warning:
        st.warning(
            "This holder table appears to be a wrapped or chain-specific representation. "
            "Global ownership should not be inferred without native-chain holder data."
        )

    tabs = st.tabs(["Mission Score", "Holders", "Risk Model", "Manipulable Filter", "Forensics", "Clusters", "Thin-Float View", "Contract Controls", "Manual Overrides"])

    with tabs[0]:
        mission_cols = st.columns(4)
        mission_cols[0].metric("Controlled-Float Squeeze", f"{result.master_score.controlled_float_squeeze_score:.1f}")
        mission_cols[1].metric("Pre-Ignition Risk", f"{result.master_score.pre_pump_risk_score:.1f}")
        mission_cols[2].metric("Insider/Whale Concentration", f"{result.master_score.insider_whale_concentration_score:.1f}")
        mission_cols[3].metric("Futures / Spot", f"{result.perp_context.futures_to_spot_volume_ratio:.2f}x" if result.perp_context.futures_to_spot_volume_ratio is not None else "n/a")
        st.write("Ranked reasons")
        st.dataframe(pd.DataFrame({"reason": result.master_score.ranked_reasons}), use_container_width=True, hide_index=True)
        st.dataframe(pd.DataFrame([result.perp_context.__dict__]), use_container_width=True, hide_index=True)

    with tabs[1]:
        holders_df = pd.DataFrame(
            [
                {
                    "rank": h.rank,
                    "address": h.address,
                    "label": h.label,
                    "category": h.holder_category,
                    "pct_total_supply": h.pct_total_supply,
                    "balance": h.balance_decimal,
                    "excluded_from_adjusted_float": h.excluded_from_adjusted_float,
                    "owner_relation": h.owner_relation,
                    "round_allocation": h.is_round_allocation,
                    "confidence": h.evidence_confidence,
                    "notes": h.evidence_notes,
                }
                for h in result.holders
            ]
        )
        st.dataframe(holders_df, use_container_width=True, hide_index=True)

    with tabs[2]:
        risk_cols = st.columns(2)
        score_row = {
            "concentration_score": result.scores.concentration_score,
            "unexplained_whale_score": result.scores.unexplained_whale_score,
            "owner_related_score": result.scores.owner_related_score,
            "protocol_control_score": result.scores.protocol_control_score,
            "exchange_inventory_score": result.scores.exchange_inventory_score,
            "contract_admin_score": result.scores.contract_admin_score,
            "controlled_float_score": result.scores.controlled_float_score,
            "distribution_risk_score": result.scores.distribution_risk_score,
            "ravedao_archetype_score": result.scores.ravedao_archetype_score,
        }
        risk_cols[0].dataframe(pd.DataFrame([score_row]).T.rename(columns={0: "score"}), use_container_width=True)
        active_flags = [name for name, value in vars(result.flags).items() if isinstance(value, bool) and value]
        risk_cols[1].write("Active structural-risk flags")
        risk_cols[1].dataframe(pd.DataFrame({"flag": active_flags}), use_container_width=True, hide_index=True)

    with tabs[3]:
        whale = result.manipulable
        whale_cols = st.columns(5)
        whale_cols[0].metric("Manipulable Whale Score", f"{result.scores.manipulable_whale_score:.1f}")
        whale_cols[1].metric("Largest Manipulable Holder", f"{whale.largest_manipulable_holder_pct:.2f}%")
        whale_cols[2].metric("Filtered Top 5", f"{whale.filtered_top_5_manipulable_pct:.2f}%")
        whale_cols[3].metric("Largest Cluster", f"{whale.cluster_manipulable_supply_pct:.2f}%")
        whale_cols[4].metric("Supply Overhang", f"{result.scores.supply_overhang_score:.1f}")
        st.info(whale.evidence_summary or "Manipulable-whale evidence is not available for this scan.")
        st.dataframe(pd.DataFrame([whale.__dict__]), use_container_width=True, hide_index=True)

    with tabs[4]:
        if result.wallet_forensics:
            st.dataframe(pd.DataFrame([item.__dict__ for item in result.wallet_forensics]), use_container_width=True, hide_index=True)
        else:
            st.info("Wallet forensics have not been computed for this result.")

    with tabs[5]:
        if result.wallet_clusters:
            st.dataframe(pd.DataFrame([item.__dict__ for item in result.wallet_clusters]), use_container_width=True, hide_index=True)
        else:
            st.info("No linked top-holder clusters were detected in this sample.")

    with tabs[6]:
        thin = result.thin_float
        thin_cols = st.columns(4)
        thin_cols[0].metric("ATH Multiple", f"{thin.ath_multiple_from_atl:.2f}x" if thin.ath_multiple_from_atl is not None else "n/a")
        thin_cols[1].metric("Drawdown From ATH", f"{thin.current_drawdown_from_ath_pct:.2f}%" if thin.current_drawdown_from_ath_pct is not None else "n/a")
        thin_cols[2].metric("Non-Top-100 Float", f"{thin.estimated_non_top100_float_pct:.4f}%")
        thin_cols[3].metric("FDV / Market Cap", f"{thin.fdv_to_market_cap_ratio:.2f}x" if thin.fdv_to_market_cap_ratio is not None else "n/a")
        st.dataframe(pd.DataFrame([thin.__dict__]), use_container_width=True, hide_index=True)

    with tabs[7]:
        st.dataframe(pd.DataFrame([result.contract_control.__dict__]), use_container_width=True, hide_index=True)

    with tabs[8]:
        st.caption("Override a holder category, then recompute adjusted float and structural-risk scores immediately.")
        if result.holders:
            holder_options = {
                f"#{h.rank} {h.address[:10]}... {h.holder_category}": h.address
                for h in result.holders
            }
            selected_holder = st.selectbox("Holder", list(holder_options), key="concentration_override_holder")
            categories = [
                "exchange",
                "liquidity_pool",
                "bridge",
                "wrapper",
                "staking",
                "vesting",
                "treasury",
                "treasury_reserve",
                "dao_multisig",
                "dao_multisig_reserve",
                "protocol_contract",
                "protocol_storage",
                "claim_distribution_reserve",
                "deployer",
                "owner",
                "admin",
                "proxy_admin",
                "market_maker",
                "possible_insider",
                "unexplained_whale",
                "unknown_wallet",
                "unknown_contract",
                "real_wallet",
                "burn",
            ]
            category = st.selectbox("Override category", categories, key="concentration_override_category")
            excluded = st.checkbox(
                "Exclude from adjusted float",
                value=category
                in {
                    "exchange",
                    "liquidity_pool",
                    "bridge",
                    "wrapper",
                    "burn",
                    "staking",
                    "vesting",
                    "treasury",
                    "treasury_reserve",
                    "dao_multisig_reserve",
                    "protocol_contract",
                    "protocol_storage",
                    "claim_distribution_reserve",
                },
            )
            note = st.text_input("Override note", value="manual analyst override")
            if st.button("Apply override and recompute"):
                scanner = TokenConcentrationScanner(cache=_concentration_cache())
                recomputed = scanner.build_result(
                    market=result.token,
                    chain=result.chain,
                    contract=result.contract_address,
                    holders=[_raw_holder(holder) for holder in result.holders],
                    contract_control=result.contract_control,
                    market_fetch_at=result.status.last_market_data_fetch_at,
                    holder_fetch_at=result.status.last_holder_fetch_at,
                    scanner_error=result.status.scanner_error,
                    partial=result.concentration.partial_result,
                    perp_context=result.perp_context,
                    overrides=[
                        ManualOverride(
                            address=holder_options[selected_holder],
                            holder_category=category,
                            excluded_from_adjusted_float=excluded,
                            note=note,
                        )
                    ],
                )
                _concentration_cache().upsert_result(recomputed)
                st.session_state["last_concentration_result"] = recomputed
                st.rerun()


def render_concentration_dashboard() -> None:
    st.title("Binance Perp Controlled-Float Scanner")
    st.caption(
        f"Automatically walks the Binance USDT perpetual universe, resolves token contracts from a local {THESIS_HOLDER_CHAIN_LABEL} seed file plus explorers, "
        "fetches holder tables, filters custody/storage false positives, and ranks controlled-float squeeze candidates."
    )

    cache = _concentration_cache()
    tabs = st.tabs(["Binance Perp Scanner", "Controlled-Float Candidates", "Manipulable Whales", "RaveDAO-Type Tokens", "Advanced / Cache"])

    with tabs[0]:
        st.subheader("Universe builder")
        seed_file_path = st.text_input(f"{THESIS_HOLDER_CHAIN_LABEL} contract seed file", value=str(DEFAULT_SEED_PATH))
        settings = st.columns(4)
        oi_top_n = int(settings[0].number_input("Enrich OI top N", min_value=0, max_value=200, value=25, step=5))
        holder_top_n = int(settings[1].number_input("Holder rows/scan", min_value=100, max_value=1000, value=100, step=100))
        include_majors = settings[2].checkbox("Include majors", value=True)
        include_stables = settings[3].checkbox("Include stables", value=True)

        action_cols = st.columns(4)
        if action_cols[0].button("Build Binance perp universe", type="primary"):
            with st.spinner("Fetching Binance perpetuals and matching local/explorer contract metadata..."):
                builder = BinancePerpUniverseBuilder()
                candidates = builder.build_candidates(
                    seed_path=seed_file_path,
                    include_majors=include_majors,
                    include_stables=include_stables,
                    enrich_open_interest_top_n=oi_top_n,
                )
            st.session_state["perp_universe_candidates"] = _candidate_rows(candidates)
            st.success(f"Loaded {len(candidates)} Binance perpetual candidates.")

        candidate_rows = st.session_state.get("perp_universe_candidates", [])
        candidate_frame = pd.DataFrame(candidate_rows)
        if not candidate_frame.empty:
            candidate_frame = candidate_frame.sort_values(["futures_to_spot_volume_ratio", "perp_volume_24h"], ascending=[False, False])
            candidate_cols = [
                "symbol",
                "base_asset",
                "chain",
                "contract_address",
                "token_name",
                "token_symbol",
                "market_cap",
                "spot_volume_24h",
                "perp_volume_24h",
                "futures_to_spot_volume_ratio",
                "open_interest_notional",
                "oi_to_market_cap_ratio",
                "price_change_24h",
                "match_confidence",
                "skip_reason",
            ]
            st.dataframe(
                candidate_frame[[col for col in candidate_cols if col in candidate_frame.columns]],
                use_container_width=True,
                hide_index=True,
            )

        scan_limit = int(action_cols[1].number_input("Scan top N now", min_value=1, max_value=500, value=25, step=5))
        if action_cols[2].button("Scan ranked candidates") and candidate_rows:
            scanner = TokenConcentrationScanner(cache=cache)
            progress = st.progress(0.0)
            scanned = 0
            failures: list[str] = []
            candidates = [_candidate_from_row(row) for row in candidate_frame.head(scan_limit).to_dict("records")]
            for index, candidate in enumerate(candidates, start=1):
                progress.progress(index / max(1, len(candidates)))
                if not candidate.contract_address or not candidate.chain:
                    failures.append(f"{candidate.symbol}: no local {THESIS_HOLDER_CHAIN_LABEL} contract match")
                    continue
                try:
                    result = scanner.scan(
                        ScannerInput(
                            contract_address=candidate.contract_address,
                            symbol=candidate.token_symbol or candidate.base_asset,
                            chain=candidate.chain,
                            top_n=holder_top_n,
                        ),
                        perp_context=candidate.context(),
                    )
                    st.session_state["last_concentration_result"] = result
                    scanned += 1
                except Exception as exc:
                    failures.append(f"{candidate.symbol}: {exc}")
            st.success(f"Scanned {scanned} Binance perp token contracts.")
            if failures:
                st.warning("Some symbols could not be scanned: " + "; ".join(failures[:12]))

        if action_cols[3].button("Queue all matched perps") and candidate_rows:
            matched = [row for row in candidate_rows if row.get("contract_address") and row.get("chain")]
            cache.enqueue("binance_perp_concentration", {"candidates": matched, "holder_top_n": holder_top_n})
            st.success(f"Queued {len(matched)} matched Binance perpetuals for batch scanning.")

        result = st.session_state.get("last_concentration_result")
        if result is not None:
            _render_concentration_result(result)

    with tabs[1]:
        frame = cache_rows_to_frame(cache.list_rows())
        if frame.empty:
            st.info("No cached Binance perp concentration scans yet.")
        else:
            filter_cols = st.columns(5)
            pre_ignition_only = filter_cols[0].checkbox("Pre-ignition only", value=False)
            top1_over_20 = filter_cols[1].checkbox("Raw top 1 >20%")
            top5_over_60 = filter_cols[2].checkbox("Top 5 >60%")
            perps_spot_5 = filter_cols[3].checkbox("Futures/spot >5x")
            high_master = filter_cols[4].checkbox("High/Extreme master")
            filtered = frame.copy()
            if pre_ignition_only:
                price_7d = pd.to_numeric(filtered["price_change_7d"], errors="coerce")
                price_30d = pd.to_numeric(filtered["price_change_30d"], errors="coerce")
                filtered = filtered[(price_7d.between(20, 100, inclusive="both")) | (price_30d.between(50, 300, inclusive="both"))]
            if top1_over_20:
                filtered = filtered[pd.to_numeric(filtered["raw_top_1_pct"], errors="coerce") > 20]
            if top5_over_60:
                filtered = filtered[pd.to_numeric(filtered["raw_top_5_pct"], errors="coerce") > 60]
            if perps_spot_5:
                filtered = filtered[pd.to_numeric(filtered["futures_to_spot_volume_ratio"], errors="coerce") > 5]
            if high_master:
                filtered = filtered[filtered["master_label"].isin(["High", "Extreme"])]
            sort_cols = [
                "master_score",
                "largest_manipulable_holder_pct",
                "cluster_manipulable_supply_pct",
                "adjusted_top_5_pct",
                "futures_to_spot_volume_ratio",
                "oi_to_adjusted_float_market_cap_ratio",
                "ravedao_archetype_score",
            ]
            filtered = filtered.sort_values(sort_cols, ascending=[False] * len(sort_cols))
            display_cols = [
                "binance_symbol",
                "token",
                "symbol",
                "chain",
                "contract",
                "price",
                "market_cap",
                "fdv",
                "volume_24h",
                "perp_volume_24h",
                "spot_volume_24h",
                "futures_to_spot_volume_ratio",
                "open_interest_notional",
                "oi_to_market_cap_ratio",
                "oi_to_adjusted_float_market_cap_ratio",
                "volume_to_adjusted_float_market_cap",
                "master_score",
                "master_label",
                "pre_pump_risk_score",
                "price_change_24h",
                "price_change_7d",
                "price_change_30d",
                "circulating_supply_pct",
                "raw_top_1_pct",
                "raw_top_5_pct",
                "raw_top_10_pct",
                "raw_top_100_pct",
                "adjusted_top_1_pct",
                "adjusted_top_5_pct",
                "adjusted_top_10_pct",
                "largest_unexplained_holder_pct",
                "largest_manipulable_holder_pct",
                "cluster_manipulable_supply_pct",
                "top_1_label",
                "top_1_category",
                "top_1_confidence",
                "excluded_supply_pct",
                "gini",
                "holder_hhi_index",
                "ravedao_archetype_score",
                "risk_score",
                "risk_label",
                "master_reasons",
                "key_flags",
            ]
            st.dataframe(filtered[[col for col in display_cols if col in filtered.columns]], use_container_width=True, hide_index=True)

    with tabs[2]:
        frame = cache_rows_to_frame(cache.list_rows())
        if frame.empty:
            st.info("No cached manipulable-whale scans yet.")
        else:
            filter_cols = st.columns(6)
            exclude_cex = filter_cols[0].checkbox("Exclude CEX top holders", value=True)
            exclude_storage = filter_cols[1].checkbox("Exclude storage top holders", value=False)
            holder_over_10 = filter_cols[2].checkbox("Top manipulable >10%")
            holder_over_20 = filter_cols[3].checkbox("Top manipulable >20%")
            cluster_over_20 = filter_cols[4].checkbox("Cluster >20%")
            high_confidence = filter_cols[5].checkbox("High confidence only")
            hide_wrapped = st.checkbox("Hide wrapped/bridged representations", value=True)
            filtered = frame.copy()
            if hide_wrapped and "wrapped_representation_warning" in filtered.columns:
                filtered = filtered[~filtered["wrapped_representation_warning"].fillna(False).astype(bool)]
            if exclude_cex:
                filtered = filtered[filtered["top_1_category"] != "exchange"]
            if exclude_storage:
                filtered = filtered[~filtered["top_1_category"].isin(["bridge", "wrapper", "liquidity_pool", "burn", "vesting", "treasury", "treasury_reserve", "dao_multisig_reserve", "protocol_contract", "protocol_storage"])]
            if holder_over_10:
                filtered = filtered[filtered["largest_manipulable_holder_pct"] > 10]
            if holder_over_20:
                filtered = filtered[filtered["largest_manipulable_holder_pct"] > 20]
            if cluster_over_20:
                filtered = filtered[filtered["cluster_manipulable_supply_pct"] > 20]
            if high_confidence:
                filtered = filtered[filtered["cluster_confidence"].isin(["high", "medium"])]
            sort_cols = [
                "largest_manipulable_holder_pct",
                "manipulable_whale_score",
                "cluster_manipulable_supply_pct",
                "filtered_top_5_manipulable_pct",
            ]
            filtered = filtered.sort_values(sort_cols, ascending=[False] * len(sort_cols))
            whale_cols = [
                "binance_symbol",
                "token",
                "symbol",
                "chain",
                "contract",
                "price",
                "market_cap",
                "fdv",
                "perp_volume_24h",
                "spot_volume_24h",
                "futures_to_spot_volume_ratio",
                "open_interest_notional",
                "largest_manipulable_holder_pct",
                "largest_manipulable_holder_address",
                "largest_manipulable_holder_category",
                "largest_manipulable_holder_score",
                "filtered_top_5_manipulable_pct",
                "filtered_top_10_manipulable_pct",
                "cluster_manipulable_supply_pct",
                "cluster_confidence",
                "cex_storage_supply_pct",
                "treasury_storage_supply_pct",
                "vesting_lockup_supply_pct",
                "supply_overhang_score",
                "manipulable_whale_score",
                "key_forensic_flags",
                "confidence",
            ]
            st.dataframe(filtered[[col for col in whale_cols if col in filtered.columns]], use_container_width=True, hide_index=True)

    with tabs[3]:
        frame = cache_rows_to_frame(cache.list_rows())
        if frame.empty:
            st.info("No cached RaveDAO-type scans yet.")
        else:
            filter_cols = st.columns(5)
            ath20 = filter_cols[0].checkbox("ATH multiple >20x", value=False)
            top5_90 = filter_cols[1].checkbox("Top 5 >90%", value=False)
            top100_99 = filter_cols[2].checkbox("Top 100 >99%", value=False)
            peak_1bn = filter_cols[3].checkbox("Peak market cap >1bn", value=False)
            extreme_rave = filter_cols[4].checkbox("Extreme RaveDAO only", value=False)
            filtered = frame.copy()
            if ath20:
                filtered = filtered[filtered["ath_multiple_from_atl"] > 20]
            if top5_90:
                filtered = filtered[filtered["raw_top_5_pct"] > 90]
            if top100_99:
                filtered = filtered[filtered["raw_top_100_pct"] > 99]
            if peak_1bn:
                filtered = filtered[filtered["peak_market_cap"] > 1_000_000_000]
            if extreme_rave:
                filtered = filtered[filtered["ravedao_archetype_score"] >= 75]
            sort_cols = [
                "ravedao_archetype_score",
                "ath_multiple_from_atl",
                "raw_top_1_pct",
                "raw_top_5_pct",
                "peak_market_cap",
                "current_drawdown_from_ath_pct",
            ]
            filtered = filtered.sort_values(sort_cols, ascending=[False] * len(sort_cols))
            rave_cols = [
                "token",
                "symbol",
                "chain",
                "contract",
                "current_price",
                "all_time_low_price",
                "all_time_high_price",
                "ath_multiple_from_atl",
                "current_drawdown_from_ath_pct",
                "current_market_cap",
                "peak_market_cap",
                "current_fdv",
                "peak_fdv",
                "raw_top_1_pct",
                "raw_top_5_pct",
                "raw_top_10_pct",
                "raw_top_100_pct",
                "adjusted_top_1_pct",
                "adjusted_top_5_pct",
                "largest_unexplained_holder_pct",
                "top_1_label",
                "top_1_category",
                "top_1_confidence",
                "estimated_non_top100_float_pct",
                "estimated_non_top10_float_pct",
                "peak_value_of_non_top100_float",
                "top_1_wallet_peak_value",
                "top_5_wallet_peak_value",
                "gini",
                "whale_concentration_pct",
                "ravedao_archetype_score",
                "risk_label",
                "key_flags",
            ]
            st.dataframe(filtered[[col for col in rave_cols if col in filtered.columns]], use_container_width=True, hide_index=True)

    with tabs[4]:
        st.subheader("Advanced manual tools and cache")
        with st.expander("Manual single-token scan", expanded=False):
            input_cols = st.columns(3)
            symbol = input_cols[0].text_input("Symbol", placeholder="BIO")
            contract = input_cols[1].text_input("Contract address", placeholder="0x...")
            chain = input_cols[2].selectbox("Chain", list(THESIS_HOLDER_CHAIN_OPTIONS), index=0)
            top_n = int(st.number_input("Top holders", min_value=20, max_value=1000, value=100, step=20))
            if st.button("Scan single token"):
                if not contract.strip():
                    st.error(f"Enter an {THESIS_HOLDER_CHAIN_LABEL} contract address.")
                else:
                    scanner = TokenConcentrationScanner(cache=cache)
                    result = scanner.scan(
                        ScannerInput(
                            symbol=symbol.strip() or None,
                            contract_address=contract.strip(),
                            chain=chain,
                            top_n=top_n,
                        )
                    )
                    st.session_state["last_concentration_result"] = result
                    st.rerun()

        if st.button("Load acceptance fixtures"):
            for fixture_result in acceptance_fixture_results():
                cache.upsert_result(fixture_result)
            st.success("Loaded scanner acceptance fixtures.")

        cached_rows = cache.list_rows()
        if st.button("Show most recent cached scan") and cached_rows:
            st.session_state["last_concentration_result"] = cache.load_result(cached_rows[0]["cache_key"])
            st.rerun()

        st.subheader("Scanner queue")
        mode = st.selectbox("Mode", ["universe", "pump", "concentration", "dominant_holder", "ravedao_archetype"])
        queue_cols = st.columns(4)
        seed_queue_path = queue_cols[0].text_input("Seed file", value=str(DEFAULT_SEED_PATH))
        top_n_volume = queue_cols[1].number_input("Top N by volume", min_value=0, max_value=500, value=50, step=10)
        min_holders = queue_cols[2].number_input("Minimum holder count", min_value=0, max_value=10000, value=100, step=50)
        chain_filter = queue_cols[3].multiselect(
            "Chain filter",
            list(THESIS_HOLDER_CHAIN_OPTIONS),
            default=list(THESIS_HOLDER_CHAIN_OPTIONS),
        )
        if st.button("Queue scanner job"):
            cache.enqueue(
                mode,
                {
                    "seed_file": seed_queue_path,
                    "top_n_by_volume": top_n_volume,
                    "minimum_holder_count": min_holders,
                    "chain_filter": chain_filter,
                },
            )
            st.success("Scanner job queued for the backend batch runner.")
        st.dataframe(pd.DataFrame(cache.queue_rows()), use_container_width=True, hide_index=True)


def _read_optional_csv(path: Path) -> pd.DataFrame:
    try:
        if not path.exists() or path.stat().st_size <= 1:
            return pd.DataFrame()
        return pd.read_csv(path, low_memory=False)
    except (OSError, ValueError, pd.errors.ParserError):
        return pd.DataFrame()


def _latest_symbol_rows(frame: pd.DataFrame, timestamp_columns: tuple[str, ...]) -> pd.DataFrame:
    if frame.empty or "symbol" not in frame.columns:
        return pd.DataFrame()
    out = frame.copy()
    out["symbol"] = out["symbol"].astype(str).str.upper().str.strip()
    timestamp_column = next((column for column in timestamp_columns if column in out.columns), None)
    if timestamp_column:
        out["_radar_timestamp"] = pd.to_datetime(out[timestamp_column], errors="coerce", utc=True)
        out = out.sort_values("_radar_timestamp", na_position="first")
    return out.drop_duplicates(subset=["symbol"], keep="last").reset_index(drop=True)


def _squeeze_seed_frames() -> list[pd.DataFrame]:
    frames = [_read_optional_csv(path) for path in SQUEEZE_RADAR_SHORT_SEED_PATHS]
    memory = _read_optional_csv(PRE_PUMP_SNAPSHOT_PATH)
    if not memory.empty:
        frames.append(_latest_symbol_rows(memory, ("snapshot_ts",)))
    latest_deep = _read_optional_csv(DISCORD_CONVEX_CACHE_PATH)
    if not latest_deep.empty:
        frames.append(_latest_symbol_rows(latest_deep, ("scanned_at_utc",)))
    return [frame for frame in frames if not frame.empty]


def _set_evidence_value(record: dict[str, Any], key: str, value: Any, *, overwrite: bool = True) -> None:
    if value is None:
        return
    try:
        if pd.isna(value):
            return
    except (TypeError, ValueError):
        pass
    if isinstance(value, str) and not value.strip():
        return
    if overwrite or key not in record:
        record[key] = value


def _mark_squeeze_evidence(
    record: dict[str, Any],
    *,
    source: str,
    level: str,
    timestamp: Any,
) -> None:
    """Track proxy and verified evidence separately; proxy must never replace verified age."""
    sources = record.setdefault("structural_evidence_sources", set())
    sources.add(source)
    normalized_level = str(level or "NONE").upper().strip() or "NONE"
    priority = {"NONE": 0, "PROXY": 1, "VERIFIED": 2}
    previous_level = str(record.get("structural_evidence_level") or "NONE").upper().strip()
    if priority.get(normalized_level, 0) >= priority.get(previous_level, 0):
        record["structural_evidence_level"] = normalized_level
    if normalized_level == "PROXY":
        _set_evidence_value(record, "structural_proxy_updated_at", timestamp)
    elif normalized_level == "VERIFIED":
        _set_evidence_value(record, "structural_evidence_updated_at", timestamp)


def _attach_cached_squeeze_evidence(live_frame: pd.DataFrame) -> pd.DataFrame:
    if live_frame.empty:
        return live_frame.copy()

    evidence: dict[str, dict[str, Any]] = {}

    memory = _latest_symbol_rows(_read_optional_csv(PRE_PUMP_SNAPSHOT_PATH), ("snapshot_ts",))
    memory_columns = (
        "centralized_ownership_score",
        "low_float_score",
        "rave_lab_setup_score",
        "pre_pump_precision_score",
        "dormant_short_fuse_score",
        "target_cex_volume_share_pct",
    )
    for _, row in memory.iterrows():
        symbol = str(row.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        record = evidence.setdefault(symbol, {"structural_evidence_sources": set()})
        for column in memory_columns:
            _set_evidence_value(record, column, row.get(column))
        _mark_squeeze_evidence(
            record,
            source="scan memory",
            level="PROXY",
            timestamp=row.get("snapshot_ts"),
        )

    concentration_path = APP_DIR / "data" / "concentration_scanner.sqlite"
    if concentration_path.exists():
        try:
            concentration = cache_rows_to_frame(ScanCache(concentration_path).list_rows())
        except (OSError, ValueError, TypeError):
            concentration = pd.DataFrame()
        concentration_mapping = {
            "raw_top_10_pct": "top10_holder_pct",
            "raw_top_100_pct": "top100_holder_pct",
            "adjusted_top_10_pct": "adjusted_top_10_pct",
            "controlled_float_squeeze_score": "controlled_float_squeeze_score",
            "ravedao_archetype_score": "ravedao_archetype_score",
            "risk_score": "structural_risk_score",
            "protocol_storage_score": "protocol_storage_score",
            "cex_storage_supply_pct": "cex_storage_supply_pct",
            "holder_table_not_global_supply": "holder_table_not_global_supply",
            "wrapped_representation_warning": "wrapped_representation_warning",
        }
        for _, row in concentration.iterrows():
            binance_symbol = str(row.get("binance_symbol") or "").upper().strip()
            token_symbol = str(row.get("symbol") or "").upper().strip()
            symbol = binance_symbol or (f"{token_symbol}USDT" if token_symbol else "")
            if not symbol:
                continue
            record = evidence.setdefault(symbol, {"structural_evidence_sources": set()})
            for source, target in concentration_mapping.items():
                _set_evidence_value(record, target, row.get(source))
            contract = row.get("contract")
            _set_evidence_value(record, "token_contract", contract)
            contract_text = str(contract or "").strip().lower()
            _set_evidence_value(
                record,
                "structural_storage_checked",
                bool(contract_text and contract_text not in {"nan", "none", "null"}),
            )
            _mark_squeeze_evidence(
                record,
                source="holder cache",
                level="VERIFIED" if str(row.get("contract") or "").strip() else "PROXY",
                timestamp=row.get("updated_at"),
            )

    deep = _latest_symbol_rows(_read_optional_csv(DISCORD_CONVEX_CACHE_PATH), ("scanned_at_utc",))
    deep_columns = (
        "top10_holder_pct",
        "top100_holder_pct",
        "adjusted_top_10_pct",
        "owner_holder_pct",
        "creator_holder_pct",
        "controlled_float_squeeze_score",
        "low_float_score",
        "centralized_ownership_score",
        "ravedao_archetype_score",
        "rave_lab_setup_score",
        "pre_pump_precision_score",
        "bitget_volume_share_pct",
        "gate_volume_share_pct",
        "binance_volume_share_pct",
        "target_cex_volume_share_pct",
        "protocol_storage_score",
        "cex_storage_supply_pct",
        "holder_table_not_global_supply",
        "wrapped_representation_warning",
    )
    for _, row in deep.iterrows():
        symbol = str(row.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        record = evidence.setdefault(symbol, {"structural_evidence_sources": set()})
        has_holder_measure = any(
            _float_nan(row.get(column)) == _float_nan(row.get(column))
            for column in ("top10_holder_pct", "top100_holder_pct", "adjusted_top_10_pct")
        )
        has_contract_hint = any(
            str(row.get(column) or "").strip()
            for column in ("token_contract", "contract", "contract_address", "source_url", "holder_source")
        )
        deep_level = "VERIFIED" if has_holder_measure and has_contract_hint else "PROXY"
        preserve_verified = str(record.get("structural_evidence_level") or "NONE").upper() == "VERIFIED" and deep_level != "VERIFIED"
        for column in deep_columns:
            _set_evidence_value(record, column, row.get(column), overwrite=not preserve_verified)
        _mark_squeeze_evidence(
            record,
            source="deep scan",
            level=deep_level,
            timestamp=row.get("scanned_at_utc"),
        )

        storage_columns_present = any(
            _float_nan(row.get(column)) == _float_nan(row.get(column))
            for column in (
                "protocol_storage_score",
                "cex_storage_supply_pct",
                "holder_table_not_global_supply",
                "wrapped_representation_warning",
            )
        )
        if storage_columns_present:
            _set_evidence_value(record, "structural_storage_checked", True)

    refreshed_structure = _latest_symbol_rows(
        _read_optional_csv(SQUEEZE_RADAR_STRUCTURAL_EVIDENCE_PATH),
        ("structural_evidence_updated_at",),
    )
    structural_columns = (
        "top10_holder_pct",
        "top100_holder_pct",
        "adjusted_top_10_pct",
        "controlled_float_squeeze_score",
        "low_float_score",
        "centralized_ownership_score",
        "ravedao_archetype_score",
        "protocol_storage_score",
        "cex_storage_supply_pct",
        "holder_table_not_global_supply",
        "wrapped_representation_warning",
        "structural_storage_checked",
        "token_contract",
        "token_chain",
        "structural_evidence_source",
        "structural_evidence_updated_at",
    )
    for _, row in refreshed_structure.iterrows():
        symbol = str(row.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        record = evidence.setdefault(symbol, {"structural_evidence_sources": set()})
        for column in structural_columns:
            _set_evidence_value(record, column, row.get(column))
        _mark_squeeze_evidence(
            record,
            source="live structural refresh",
            level=str(row.get("structural_evidence_level") or "VERIFIED"),
            timestamp=row.get("structural_evidence_updated_at"),
        )

    rows: list[dict[str, Any]] = []
    for symbol, record in evidence.items():
        copied = dict(record)
        sources = copied.pop("structural_evidence_sources", set())
        copied["structural_evidence_source"] = ", ".join(sorted(sources))
        copied.setdefault("structural_evidence_level", "NONE")
        copied["symbol"] = symbol
        rows.append(copied)
    if not rows:
        out = live_frame.copy()
        out["structural_evidence_source"] = ""
        out["structural_evidence_level"] = "NONE"
        out["structural_evidence_updated_at"] = ""
        out["structural_proxy_updated_at"] = ""
        out["structural_storage_checked"] = False
        out["structural_evidence_age_days"] = float("nan")
        out["structural_proxy_age_days"] = float("nan")
        return out

    evidence_frame = pd.DataFrame(rows)
    out = live_frame.merge(evidence_frame, on="symbol", how="left")
    if "structural_evidence_level" not in out.columns:
        out["structural_evidence_level"] = "NONE"
    out["structural_evidence_level"] = (
        out["structural_evidence_level"].fillna("NONE").astype(str).str.upper().str.strip()
    )
    if "structural_storage_checked" not in out.columns:
        out["structural_storage_checked"] = False
    out["structural_storage_checked"] = out["structural_storage_checked"].map(_truthy_value).fillna(False)
    evidence_time = pd.to_datetime(
        out["structural_evidence_updated_at"]
        if "structural_evidence_updated_at" in out.columns
        else pd.Series(pd.NaT, index=out.index),
        errors="coerce",
        utc=True,
    )
    proxy_time = pd.to_datetime(
        out["structural_proxy_updated_at"]
        if "structural_proxy_updated_at" in out.columns
        else pd.Series(pd.NaT, index=out.index),
        errors="coerce",
        utc=True,
    )
    out["structural_evidence_age_days"] = (
        pd.Timestamp.now(tz="UTC") - evidence_time
    ).dt.total_seconds() / 86400.0
    out["structural_proxy_age_days"] = (
        pd.Timestamp.now(tz="UTC") - proxy_time
    ).dt.total_seconds() / 86400.0
    return out


def _refresh_squeeze_structural_evidence(
    frame: pd.DataFrame,
    *,
    max_symbols: int = SQUEEZE_RADAR_STRUCTURAL_REFRESH_MAX_SYMBOLS,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Run the heavier concentration engine only for a bounded review queue."""
    if frame.empty or "symbol" not in frame.columns:
        return frame.copy(), {"attempted": 0, "verified": 0, "errors": 0}

    ranked = frame.copy()
    for column in ("squeeze_market_trigger", "squeeze_entry_ready"):
        if column in ranked.columns:
            ranked[column] = ranked[column].map(_truthy_value)
        else:
            ranked[column] = False
    for column in ("squeeze_score", "squeeze_market_confidence", "squeeze_fuel_remaining_score"):
        if column not in ranked.columns:
            ranked[column] = 0.0
        ranked[column] = pd.to_numeric(ranked[column], errors="coerce").fillna(0.0)
    ranked = ranked.sort_values(
        ["squeeze_entry_ready", "squeeze_market_trigger", "squeeze_score", "squeeze_market_confidence", "squeeze_fuel_remaining_score"],
        ascending=[False, False, False, False, False],
    ).head(max(1, int(max_symbols)))

    concentration_path = APP_DIR / "data" / "concentration_scanner.sqlite"
    scanner = TokenConcentrationScanner(cache=ScanCache(concentration_path))
    updated = frame.copy()
    evidence_rows: list[dict[str, Any]] = []
    attempted = 0
    verified = 0
    errors = 0
    refresh_time = _utc_now().isoformat()

    for _, row in ranked.iterrows():
        symbol = str(row.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        attempted += 1
        hint = resolve_contract_hint(row.to_dict(), hints_path=DISCORD_HOLDER_CONTRACTS_FILE)
        if hint is None:
            errors += 1
            continue
        try:
            result = scanner.scan(
                ScannerInput(
                    symbol=str(row.get("base_asset") or symbol.removesuffix("USDT")),
                    contract_address=hint.contract_address,
                    chain=hint.chain,
                    top_n=100,
                )
            )
        except Exception:
            errors += 1
            continue

        status = str(result.status.scanner_status or "").lower()
        scanner_error = str(result.status.scanner_error or "").strip()
        has_holder_measure = (
            len(getattr(result, "holders", [])) >= 10
            and math.isfinite(float(result.concentration.raw_top_10_pct))
        )
        level = "VERIFIED" if status == "complete" and not scanner_error and has_holder_measure else "PROXY"
        if level != "VERIFIED":
            errors += 1
            continue

        verified += 1
        record: dict[str, Any] = {
            "symbol": symbol,
            "structural_evidence_level": level,
            "structural_evidence_updated_at": refresh_time,
            "structural_evidence_source": "live concentration scanner",
            "structural_storage_checked": True,
            "token_contract": hint.contract_address,
            "token_chain": hint.chain,
            "top10_holder_pct": float(result.concentration.raw_top_10_pct),
            "top100_holder_pct": float(result.concentration.raw_top_100_pct),
            "adjusted_top_10_pct": float(result.concentration.adjusted_top_10_pct),
            "controlled_float_squeeze_score": float(result.master_score.controlled_float_squeeze_score),
            "low_float_score": float(result.thin_float.squeeze_proxy_score),
            "ravedao_archetype_score": float(result.scores.ravedao_archetype_score),
            "protocol_storage_score": float(result.scores.protocol_storage_score),
            "cex_storage_supply_pct": float(result.manipulable.cex_storage_supply_pct),
            "holder_table_not_global_supply": bool(result.representation.holder_table_not_global_supply),
            "wrapped_representation_warning": bool(result.representation.wrapped_representation_warning),
        }
        evidence_rows.append(record)

        matches = updated["symbol"].astype(str).str.upper().eq(symbol)
        for column, value in record.items():
            if column != "symbol":
                updated.loc[matches, column] = value

    if evidence_rows:
        persisted = pd.DataFrame(evidence_rows)
        existing = _read_optional_csv(SQUEEZE_RADAR_STRUCTURAL_EVIDENCE_PATH)
        combined = pd.concat([existing, persisted], ignore_index=True, sort=False)
        combined["symbol"] = combined["symbol"].astype(str).str.upper().str.strip()
        combined = combined.drop_duplicates(subset=["symbol"], keep="last")
        SQUEEZE_RADAR_STRUCTURAL_EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(SQUEEZE_RADAR_STRUCTURAL_EVIDENCE_PATH, index=False)

    if "structural_evidence_updated_at" in updated.columns:
        evidence_time = pd.to_datetime(updated["structural_evidence_updated_at"], errors="coerce", utc=True)
        updated["structural_evidence_age_days"] = (
            pd.Timestamp.now(tz="UTC") - evidence_time
        ).dt.total_seconds() / 86400.0

    return updated, {
        "attempted": attempted,
        "verified": verified,
        "errors": errors,
        "path": str(SQUEEZE_RADAR_STRUCTURAL_EVIDENCE_PATH),
    }


def _forced_open_position_symbols(client: BinanceFuturesPublic, valid_symbols: set[str]) -> set[str]:
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        return set()
    signed_client = _client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)
    positions = _safe_public_fetch([], signed_client.position_information_v3, None)
    return {
        str(position.get("symbol") or "").upper()
        for position in positions
        if str(position.get("symbol") or "").upper() in valid_symbols
        and abs(_float_nan(position.get("positionAmt"))) > 0
    }


def _probe_current_short_account_pct(client: BinanceFuturesPublic, symbol: str) -> float:
    """Fetch one current account-count observation for coarse squeeze preselection."""
    rows = _safe_public_fetch(
        [],
        client.global_long_short_account_ratio,
        symbol,
        period=LONG_SHORT_RATIO_PERIOD,
        limit=1,
    )
    if not rows:
        return float("nan")
    return _share_to_pct(rows[-1].get("shortAccount"))


def _source_event_time_utc(*collections: Any) -> str:
    """Return the newest explicit Binance source timestamp, if present.

    A receipt time is kept separately on each radar row.  When an endpoint
    provides no event timestamp, the canonical observation model records the
    fallback as ``snapshot_time`` rather than pretending it is source-timed.
    """

    candidates: list[datetime] = []
    for collection in collections:
        if isinstance(collection, dict):
            collection = [collection]
        if isinstance(collection, (list, tuple)):
            for item in collection:
                value: Any = item.get("timestamp") or item.get("time") or item.get("T") if isinstance(item, dict) else None
                if isinstance(item, (list, tuple)) and len(item) > 6:
                    value = item[6]
                try:
                    numeric = float(value)
                    if math.isfinite(numeric):
                        if numeric > 10_000_000_000:
                            numeric /= 1000.0
                        candidates.append(datetime.fromtimestamp(numeric, tz=timezone.utc))
                except (TypeError, ValueError, OverflowError, OSError):
                    continue
    if not candidates:
        return ""
    return max(candidates).isoformat().replace("+00:00", "Z")


def _attach_reflexivity_assessments(frame: pd.DataFrame) -> pd.DataFrame:
    """Adapt the canonical research projection to the live dashboard clock."""

    return project_reflexivity_assessments(frame, as_of=_utc_now())


@_cache_data(ttl=45, show_spinner=False)
def run_squeeze_radar_scan(refresh_nonce: int, max_symbols: int = SQUEEZE_RADAR_DEFAULT_SYMBOLS) -> tuple[pd.DataFrame, dict[str, Any]]:
    _ = refresh_nonce
    started = _utc_now()
    client = BinanceFuturesPublic(
        base_url=BASE_URL,
        timeout=TIMEOUT,
        requests_per_second=SQUEEZE_RADAR_REQUESTS_PER_SECOND,
        retries=RETRIES,
    )
    symbol_meta = {
        item.symbol: item
        for item in client.perpetual_usdt_symbols()
        if str(item.underlying_type or "").upper() not in TRADFI_ALWAYS_INCLUDE_TYPES
    }
    ticker = pd.DataFrame(client.ticker_24hr())
    if ticker.empty or not symbol_meta:
        return pd.DataFrame(), {"error": "Binance returned no live USDT perpetual universe."}

    ticker["symbol"] = ticker["symbol"].astype(str).str.upper()
    ticker = ticker[ticker["symbol"].isin(symbol_meta)].copy()
    for column in ("lastPrice", "highPrice", "lowPrice", "quoteVolume", "priceChangePercent", "count"):
        ticker[column] = pd.to_numeric(ticker.get(column), errors="coerce")
    ticker = ticker.dropna(subset=["lastPrice", "highPrice", "lowPrice", "quoteVolume"])
    ticker["base_asset"] = ticker["symbol"].map(lambda symbol: symbol_meta[symbol].base_asset)
    ticker["market_type"] = ticker["symbol"].map(lambda symbol: symbol_meta[symbol].underlying_type or "CRYPTO")

    forced_symbols = set(ALWAYS_SCAN_SYMBOLS) & set(symbol_meta)
    forced_symbols |= _forced_open_position_symbols(client, set(symbol_meta))
    seed_frames = _squeeze_seed_frames()
    prefilter_budget = min(
        len(ticker),
        max(int(max_symbols) * 3, SQUEEZE_RADAR_PREFILTER_SYMBOLS),
    )
    prefilter = select_squeeze_candidates(
        ticker,
        seed_frames=seed_frames,
        forced_symbols=forced_symbols,
        max_symbols=prefilter_budget,
    )
    if prefilter.empty:
        return pd.DataFrame(), {"error": "No crypto candidates survived the bounded universe selector."}

    short_probe_values: dict[str, float] = {}
    for symbol in prefilter["symbol"].astype(str).str.upper():
        short_probe_values[symbol] = _probe_current_short_account_pct(client, symbol)
    prefilter["live_short_account_pct"] = prefilter["symbol"].map(short_probe_values)
    selected = select_squeeze_candidates(
        prefilter,
        forced_symbols=forced_symbols,
        max_symbols=max_symbols,
    )
    if selected.empty:
        return pd.DataFrame(), {"error": "No candidates survived the live short-account prefilter."}

    funding_by_symbol = {
        str(item.get("symbol") or "").upper(): item
        for item in _safe_public_fetch([], client.mark_price)
        if str(item.get("symbol") or "").upper() in symbol_meta
    }
    funding_info_by_symbol = {
        str(item.get("symbol") or "").upper(): item
        for item in _safe_public_fetch([], client.funding_info)
        if str(item.get("symbol") or "").upper() in symbol_meta
    }

    rows: list[dict[str, Any]] = []
    incomplete_symbols = 0
    crowd_diagnostic_symbols = set(selected["symbol"].astype(str).str.upper()).intersection(
        set(selected.head(SQUEEZE_RADAR_CROWD_DIAGNOSTIC_MAX_SYMBOLS)["symbol"].astype(str).str.upper())
    )
    crowd_diagnostic_count = 0
    scanned_at = _utc_now()
    for _, ticker_row in selected.iterrows():
        symbol = str(ticker_row["symbol"])
        daily = _safe_public_fetch([], client.klines_1d, symbol, limit=62)
        hourly = _safe_public_fetch([], client.klines, symbol, interval="1h", limit=27)
        short_history = _safe_public_fetch(
            [],
            client.global_long_short_account_ratio,
            symbol,
            period=LONG_SHORT_RATIO_PERIOD,
            limit=LONG_SHORT_RATIO_HISTORY_LIMIT,
        )
        oi_rows = _safe_public_fetch(
            [],
            client.open_interest_statistics,
            symbol,
            period="1h",
            limit=7,
        )

        missing: list[str] = []
        if len(daily) < 22:
            missing.append("daily history")
        if len(hourly) < 4:
            missing.append("hourly history")
        if not short_history:
            missing.append("short accounts")
        if len(oi_rows) < 2:
            missing.append("OI history")
        if missing:
            incomplete_symbols += 1

        levels = levels_from_klines(daily)
        recent_pump = recent_pump_stats_from_klines(daily, lookback_days=NO_LARGE_PUMP_LOOKBACK_DAYS)
        hourly_stats = _hourly_market_stats(hourly)
        short_stats = _short_account_history_stats(short_history)
        latest_short = short_history[-1] if short_history else {}
        short_account_pct = _share_to_pct(latest_short.get("shortAccount"))
        long_account_pct = _share_to_pct(latest_short.get("longAccount"))
        short_values = [
            value
            for value in (_share_to_pct(item.get("shortAccount")) for item in short_history)
            if math.isfinite(value)
        ]
        short_peak = max(short_values) if short_values else float("nan")
        short_peak_drawdown = (
            short_account_pct - short_peak
            if math.isfinite(short_account_pct) and math.isfinite(short_peak)
            else float("nan")
        )

        top_position_snapshot: dict[str, Any] = {}
        top_account_snapshot: dict[str, Any] = {}
        taker_snapshot: dict[str, Any] = {}
        if symbol in crowd_diagnostic_symbols:
            top_position_rows = _safe_public_fetch(
                [],
                client.top_trader_long_short_position_ratio,
                symbol,
                period="1h",
                limit=1,
            )
            top_account_rows = _safe_public_fetch(
                [],
                client.top_trader_long_short_account_ratio,
                symbol,
                period="1h",
                limit=1,
            )
            taker_rows = _safe_public_fetch(
                [],
                client.taker_buy_sell_volume,
                symbol,
                period="1h",
                limit=1,
            )
            top_position_snapshot = top_position_rows[-1] if top_position_rows else {}
            top_account_snapshot = top_account_rows[-1] if top_account_rows else {}
            taker_snapshot = taker_rows[-1] if taker_rows else {}
            if top_position_snapshot or top_account_snapshot or taker_snapshot:
                crowd_diagnostic_count += 1

        top_trader_long_position_pct = _share_to_pct(top_position_snapshot.get("longAccount"))
        top_trader_short_position_pct = _share_to_pct(top_position_snapshot.get("shortAccount"))
        top_trader_long_account_pct = _share_to_pct(top_account_snapshot.get("longAccount"))
        top_trader_short_account_pct = _share_to_pct(top_account_snapshot.get("shortAccount"))
        crowd_top_position_divergence_pct = (
            long_account_pct - top_trader_long_position_pct
            if math.isfinite(long_account_pct) and math.isfinite(top_trader_long_position_pct)
            else float("nan")
        )
        crowd_top_account_divergence_pct = (
            long_account_pct - top_trader_long_account_pct
            if math.isfinite(long_account_pct) and math.isfinite(top_trader_long_account_pct)
            else float("nan")
        )
        taker_buy_sell_ratio = _float_nan(taker_snapshot.get("buySellRatio"))
        taker_buy_volume = _float_nan(taker_snapshot.get("buyVol"))
        taker_sell_volume = _float_nan(taker_snapshot.get("sellVol"))
        taker_total_volume = taker_buy_volume + taker_sell_volume
        taker_buy_share_pct = (
            taker_buy_volume / taker_total_volume * 100.0
            if math.isfinite(taker_buy_volume) and math.isfinite(taker_sell_volume) and taker_total_volume > 0
            else float("nan")
        )

        oi_stats = oi_history_stats(oi_rows)
        oi_value = _float_nan(oi_stats.get("oi_current_usdt"))
        oi_delta = _float_nan(oi_stats.get("oi_change_1h_pct"))
        last_price = float(ticker_row["lastPrice"])
        quote_volume = float(ticker_row["quoteVolume"])
        received_at = _utc_now()
        source_event_time = _source_event_time_utc(short_history, oi_rows, hourly[:-1] if len(hourly) > 1 else hourly)
        volume_context = _daily_quote_volume_30d_context(daily, quote_volume)
        anchored_vwap = closed_daily_anchored_vwap_metrics(
            daily,
            last_price=last_price,
            lookback_days=30,
        )
        funding_snapshot = funding_by_symbol.get(symbol, {})
        funding_info = funding_info_by_symbol.get(symbol, {})
        funding_interval = _coerce_funding_interval_hours(funding_info.get("fundingIntervalHours"))
        funding_pct = _funding_rate_to_pct(funding_snapshot.get("lastFundingRate"))
        high_24h = float(ticker_row["highPrice"])
        low_24h = float(ticker_row["lowPrice"])

        row: dict[str, Any] = {
            "scanned_at_utc": scanned_at.isoformat(),
            "received_at_utc": received_at.isoformat().replace("+00:00", "Z"),
            "event_time_utc": source_event_time,
            "source": "Binance Futures public endpoints",
            "venue": "Binance Futures",
            "provenance": "bounded radar: ticker + klines + account-count ratio + OI + funding endpoints",
            "signal_version": REFLEXIVITY_SIGNAL_VERSION,
            "scan_universe_count": len(ticker),
            "scan_candidate_count": len(selected),
            "symbol": symbol,
            "base_asset": symbol_meta[symbol].base_asset,
            "market_type": symbol_meta[symbol].underlying_type or "CRYPTO",
            "binance_perp_universe": True,
            "candidate_seed_score": _float_nan(ticker_row.get("candidate_seed_score")),
            "candidate_rank_score": _float_nan(ticker_row.get("candidate_rank_score")),
            "prefilter_short_account_pct": _float_nan(ticker_row.get("live_short_account_pct")),
            "short_account_source": "live Binance account-count ratio",
            "last_price": last_price,
            "price_change_24h_pct": _float_nan(ticker_row.get("priceChangePercent")),
            "range_24h_pct": (high_24h / low_24h - 1.0) * 100.0 if low_24h > 0 else float("nan"),
            "quote_volume_24h": quote_volume,
            **volume_context,
            "anchored_vwap_30d": float(anchored_vwap["anchored_vwap_30d"]),
            "price_vs_anchored_vwap_30d_pct": float(anchored_vwap["price_vs_anchored_vwap_30d_pct"]),
            "anchored_vwap_30d_days": int(anchored_vwap["anchored_vwap_30d_days"]),
            "history_days": max(0, len(daily) - 1),
            "recent_max_pump_60d_pct": recent_pump.max_pump_pct,
            "recent_pump_60d_days": recent_pump.used_days,
            "carry_funding_pct": funding_pct,
            "carry_funding_annualized_pct": _annualized_funding_pct(
                funding_snapshot.get("lastFundingRate"),
                interval_hours=funding_interval,
            ),
            "funding_interval_hours": funding_interval,
            "funding_countdown_hours": _funding_countdown_hours(funding_snapshot.get("nextFundingTime")),
            "long_account_pct": long_account_pct,
            "short_account_pct": short_account_pct,
            "short_account_peak_pct": short_peak,
            "short_account_peak_drawdown_pp": short_peak_drawdown,
            "short_account_history_points": int(short_stats.get("short_account_history_points", 0) or 0),
            "short_account_previous_1h_pct": _float_nan(short_stats.get("short_account_previous_1h_pct")),
            "short_account_roc_1h_pct": _float_nan(short_stats.get("short_account_roc_1h_pct")),
            "short_account_roc_1h_pp": _float_nan(short_stats.get("short_account_roc_1h_pp")),
            "short_account_change_3p_pp": _float_nan(short_stats.get("short_account_change_3p_pp")),
            "short_account_change_4p_pp": _float_nan(short_stats.get("short_account_change_4p_pp")),
            "short_account_change_6p_pp": _float_nan(short_stats.get("short_account_change_6p_pp")),
            "short_account_change_12p_pp": _float_nan(short_stats.get("short_account_change_12p_pp")),
            "short_account_change_24p_pp": _float_nan(short_stats.get("short_account_change_24p_pp")),
            "short_account_roc_smoothed_3p_pp": _float_nan(short_stats.get("short_account_roc_smoothed_3p_pp")),
            "short_account_acceleration_1h_pp": _float_nan(short_stats.get("short_account_acceleration_1h_pp")),
            "short_account_direction_persistence": int(short_stats.get("short_account_direction_persistence", 0) or 0),
            "top_trader_long_position_pct": top_trader_long_position_pct,
            "top_trader_short_position_pct": top_trader_short_position_pct,
            "top_trader_long_account_pct": top_trader_long_account_pct,
            "top_trader_short_account_pct": top_trader_short_account_pct,
            "crowd_top_position_divergence_pct": crowd_top_position_divergence_pct,
            "crowd_top_account_divergence_pct": crowd_top_account_divergence_pct,
            "taker_buy_sell_ratio": taker_buy_sell_ratio,
            "taker_buy_share_pct": taker_buy_share_pct,
            **hourly_stats,
            "oi_value_usdt": oi_value,
            "oi_delta_pct": oi_delta,
            "oi_acceleration_1h_pct": _float_nan(oi_stats.get("oi_acceleration_1h_pct")),
            "oi_history_points": int(oi_stats.get("oi_history_points", 0) or 0),
            "oi_change_3p_pct": _float_nan(oi_stats.get("oi_change_3p_pct")),
            "oi_change_6p_pct": _float_nan(oi_stats.get("oi_change_6p_pct")),
            "oi_build_persistence": int(oi_stats.get("oi_build_persistence", 0) or 0),
            "oi_peak_drawdown_pct": _float_nan(oi_stats.get("oi_peak_drawdown_pct")),
            "oi_to_24h_volume_pct": oi_value / quote_volume * 100.0 if math.isfinite(oi_value) and quote_volume > 0 else float("nan"),
            "high_5d": levels.high_5d,
            "high_20d": levels.high_20d,
            "low_20d": levels.low_20d,
            "broke_high_5d": _crossed_above(levels.high_5d, high_24h),
            "broke_high_20d": _crossed_above(levels.high_20d, high_24h),
            "broke_low_20d": _crossed_below(levels.low_20d, low_24h),
            "scan_error": ", ".join(missing),
        }
        rows.append(row)

    frame = _attach_cached_squeeze_evidence(pd.DataFrame(rows))
    frame = _attach_reflexivity_assessments(frame)
    elapsed = (_utc_now() - started).total_seconds()
    metadata = {
        "scanned_at_utc": scanned_at.isoformat(),
        "universe_count": len(ticker),
        "candidate_count": len(selected),
        "prefilter_count": len(prefilter),
        "short_probe_count": len(short_probe_values),
        "short_probe_coverage_pct": (
            sum(math.isfinite(value) for value in short_probe_values.values())
            / len(short_probe_values)
            * 100.0
            if short_probe_values
            else 0.0
        ),
        "crowd_diagnostic_count": crowd_diagnostic_count,
        "crowd_diagnostic_coverage_pct": (
            crowd_diagnostic_count / len(crowd_diagnostic_symbols) * 100.0
            if crowd_diagnostic_symbols
            else 0.0
        ),
        "returned_count": len(frame),
        "incomplete_count": incomplete_symbols,
        "elapsed_seconds": elapsed,
    }
    return frame, metadata


def _load_latest_squeeze_radar() -> pd.DataFrame:
    return _read_optional_csv(SQUEEZE_RADAR_LATEST_PATH)


def _persist_latest_squeeze_radar(frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    SQUEEZE_RADAR_LATEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(SQUEEZE_RADAR_LATEST_PATH, index=False)


SQUEEZE_RADAR_HISTORY_COLUMNS = [
    "symbol",
    "scanned_at_utc",
    "last_price",
    "short_account_pct",
    "short_account_roc_1h_pp",
    "short_account_change_3p_pp",
    "short_account_change_4p_pp",
    "oi_delta_pct",
    "oi_acceleration_1h_pct",
    "oi_change_3p_pct",
    "day_return_pct",
    "hour_volume_roc_1h_pct",
    "squeeze_stage",
    "squeeze_score",
    "squeeze_market_trigger",
    "squeeze_entry_ready",
]


def _squeeze_radar_history_snapshot(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "symbol" not in frame.columns or "scanned_at_utc" not in frame.columns:
        return pd.DataFrame(columns=SQUEEZE_RADAR_HISTORY_COLUMNS)
    snapshot = pd.DataFrame(index=frame.index)
    for column in SQUEEZE_RADAR_HISTORY_COLUMNS:
        if column in frame.columns:
            snapshot[column] = frame[column]
        else:
            snapshot[column] = "" if column in {"symbol", "scanned_at_utc", "squeeze_stage"} else float("nan")
    snapshot["symbol"] = snapshot["symbol"].astype(str).str.upper().str.strip()
    snapshot["scanned_at_utc"] = pd.to_datetime(snapshot["scanned_at_utc"], errors="coerce", utc=True)
    snapshot = snapshot[
        snapshot["symbol"].ne("") & snapshot["scanned_at_utc"].notna()
    ].copy()
    return snapshot


def _persist_squeeze_radar_history(frame: pd.DataFrame) -> None:
    snapshot = _squeeze_radar_history_snapshot(frame)
    if snapshot.empty:
        return
    existing = _read_optional_csv(SQUEEZE_RADAR_HISTORY_PATH)
    if not existing.empty:
        existing = _squeeze_radar_history_snapshot(existing)
    history = pd.concat([existing, snapshot], ignore_index=True)
    history["scanned_at_utc"] = pd.to_datetime(history["scanned_at_utc"], errors="coerce", utc=True)
    cutoff = _utc_now() - timedelta(days=SQUEEZE_RADAR_HISTORY_RETENTION_DAYS)
    history = history[history["scanned_at_utc"] >= cutoff].copy()
    history = history.drop_duplicates(subset=["symbol", "scanned_at_utc"], keep="last")
    history = history.sort_values(["scanned_at_utc", "symbol"]).tail(25000)
    SQUEEZE_RADAR_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    history["scanned_at_utc"] = history["scanned_at_utc"].dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    history.to_csv(SQUEEZE_RADAR_HISTORY_PATH, index=False)


def _attach_saved_squeeze_history(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    history = _read_optional_csv(SQUEEZE_RADAR_HISTORY_PATH)
    return attach_squeeze_history_features(frame, history, lookback_hours=24.0)


SQUEEZE_RADAR_TABLE_COLUMNS = [
    "squeeze_rank",
    "symbol",
    "reflexivity_state",
    "reflexivity_score",
    "reflexivity_data_quality_pct",
    "reflexivity_market_trigger",
    "reflexivity_funding_regime",
    "squeeze_stage",
    "squeeze_score",
    "squeeze_market_trigger",
    "squeeze_entry_ready",
    "squeeze_evidence_tier",
    "structural_evidence_level",
    "short_account_pct",
    "short_account_roc_1h_pp",
    "short_account_change_3p_pp",
    "short_account_change_4p_pp",
    "short_account_roc_smoothed_3p_pp",
    "squeeze_fuel_remaining_score",
    "carry_funding_pct",
    "hour_volume_roc_1h_pct",
    "quote_volume_24h_vs_prior_30d_avg_ratio",
    "oi_delta_pct",
    "oi_acceleration_1h_pct",
    "oi_change_3p_pct",
    "crowd_top_position_divergence_pct",
    "taker_buy_share_pct",
    "price_vs_anchored_vwap_30d_pct",
    "radar_confirmation_label",
    "broke_high_20d",
    "squeeze_late_score",
    "squeeze_gate_failures",
]


def _squeeze_radar_column_config() -> dict[str, Any]:
    return {
        "squeeze_rank": st.column_config.NumberColumn("Rank", format="%d", width="small"),
        "symbol": st.column_config.TextColumn("Symbol", width="small"),
        "reflexivity_state": st.column_config.TextColumn(
            "Research State",
            width="medium",
            help="Point-in-time rule state: discovery, building, active reflexivity, accelerating, exhaustion risk, or invalidated.",
        ),
        "reflexivity_score": st.column_config.ProgressColumn(
            "Mechanism Score",
            min_value=0,
            max_value=100,
            format="%.1f",
            help="Small, explicit mechanism model. This is not a probability or expected return.",
        ),
        "reflexivity_data_quality_pct": st.column_config.NumberColumn(
            "Data Quality",
            format="%.0f%%",
            help="Coverage of the required live fields; missing or stale data is not silently scored as neutral.",
        ),
        "reflexivity_market_trigger": st.column_config.CheckboxColumn(
            "Reflexivity Trigger",
            help="Short crowding/build, participation, OI, price confirmation, and no-exhaustion gates agree at the observation time.",
        ),
        "reflexivity_funding_regime": st.column_config.TextColumn(
            "Funding Regime",
            width="medium",
            help="Positive means longs pay shorts; negative means shorts pay longs. The label is context, not a causal claim.",
        ),
        "squeeze_stage": st.column_config.TextColumn("Stage", width="small"),
        "squeeze_score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.1f"),
        "squeeze_market_trigger": st.column_config.CheckboxColumn(
            "Market Trigger",
            help="Live price/volume/OI/funding agreement; this is not entry-ready without structural proof.",
        ),
        "squeeze_entry_ready": st.column_config.CheckboxColumn(
            "Entry Ready",
            help="Market trigger plus fresh verified holder concentration and venue evidence.",
        ),
        "squeeze_evidence_tier": st.column_config.TextColumn("Evidence", width="medium"),
        "structural_evidence_level": st.column_config.TextColumn("Proof Level", width="small"),
        "structural_storage_checked": st.column_config.CheckboxColumn(
            "Storage Checked",
            help="Holder proof also includes custody/storage/representation controls.",
        ),
        "short_account_pct": st.column_config.NumberColumn(
            "Short Accts",
            format="%.2f%%",
            help="Global short-account share by account count, not short dollar notional.",
        ),
        "short_account_roc_1h_pp": st.column_config.NumberColumn("1H Short d", format="%+.2fpp"),
        "short_account_change_3p_pp": st.column_config.NumberColumn(
            "3H Short d",
            format="%+.2fpp",
            help="Net short-account-share change over the last three closed hourly observations.",
        ),
        "short_account_change_4p_pp": st.column_config.NumberColumn(
            "4H Short d",
            format="%+.2fpp",
            help="Net short-account-share change over the last four closed hourly observations.",
        ),
        "short_account_roc_smoothed_3p_pp": st.column_config.NumberColumn("3H Smooth", format="%+.2fpp"),
        "squeeze_fuel_remaining_score": st.column_config.ProgressColumn("Fuel", min_value=0, max_value=100, format="%.0f"),
        "carry_funding_pct": st.column_config.NumberColumn("Funding", format="%+.4f%%"),
        "hour_volume_roc_1h_pct": st.column_config.NumberColumn("1H Vol ROC", format="%+.1f%%"),
        "quote_volume_24h_vs_prior_30d_avg_ratio": st.column_config.NumberColumn("24H / 30D", format="%.2fx"),
        "oi_delta_pct": st.column_config.NumberColumn("1H OI", format="%+.2f%%"),
        "oi_acceleration_1h_pct": st.column_config.NumberColumn(
            "OI Accel",
            format="%+.2fpp",
            help="Change in one-hour open-interest growth versus the prior closed hour.",
        ),
        "oi_change_3p_pct": st.column_config.NumberColumn(
            "3H OI",
            format="%+.2f%%",
            help="Net open-interest change over the last three closed hourly observations.",
        ),
        "crowd_top_position_divergence_pct": st.column_config.NumberColumn(
            "Crowd - Top Pos",
            format="%+.1fpp",
            help="Overall account long share minus top-trader long position share. Negative values mean the broad account crowd is shorter than top traders.",
        ),
        "taker_buy_share_pct": st.column_config.NumberColumn(
            "Taker Buy",
            format="%.1f%%",
            help="Taker buy volume share in the sampled hourly window.",
        ),
        "price_vs_anchored_vwap_30d_pct": st.column_config.NumberColumn("vs 30D AVWAP", format="%+.1f%%"),
        "radar_confirmation_label": st.column_config.TextColumn(
            "Scan Repeat",
            width="small",
            help="NEW, REPEATED, or PERSISTENT based on prior radar snapshots in the last 24 hours.",
        ),
        "broke_high_20d": st.column_config.CheckboxColumn("20D High"),
        "squeeze_late_score": st.column_config.ProgressColumn("Late", min_value=0, max_value=100, format="%.0f"),
        "squeeze_gate_failures": st.column_config.TextColumn("Missing / Veto", width="large"),
        "reflexivity_gate_summary": st.column_config.TextColumn("Mechanism Gates", width="large"),
        "reflexivity_missing_fields": st.column_config.TextColumn("Research Gaps", width="large"),
        "reflexivity_explanation": st.column_config.TextColumn("Mechanism Read", width="large"),
        "reflexivity_event_time_utc": st.column_config.TextColumn("Event Time (UTC)", width="medium"),
        "reflexivity_received_at_utc": st.column_config.TextColumn("Received (UTC)", width="medium"),
        "reflexivity_source": st.column_config.TextColumn("Source", width="medium"),
        "reflexivity_venue": st.column_config.TextColumn("Venue", width="medium"),
        "reflexivity_signal_version": st.column_config.TextColumn("Signal Version", width="small"),
        "quote_volume_24h": st.column_config.NumberColumn("24H Vol", format="$%.0f"),
        "hour_quote_volume": st.column_config.NumberColumn("1H Vol", format="$%.0f"),
        "squeeze_market_confidence": st.column_config.ProgressColumn("Live Coverage", min_value=0, max_value=100, format="%.0f%%"),
        "squeeze_structure_score": st.column_config.ProgressColumn("Structure", min_value=0, max_value=100, format="%.0f"),
        "top10_holder_pct": st.column_config.NumberColumn("Top 10", format="%.1f%%"),
        "top100_holder_pct": st.column_config.NumberColumn("Top 100", format="%.1f%%"),
        "bitget_volume_share_pct": st.column_config.NumberColumn("Bitget Share", format="%.2f%%"),
        "gate_volume_share_pct": st.column_config.NumberColumn("Gate Share", format="%.2f%%"),
        "structural_evidence_age_days": st.column_config.NumberColumn("Evidence Age", format="%.1fD"),
        "structural_proxy_age_days": st.column_config.NumberColumn("Proxy Age", format="%.1fD"),
        "structural_evidence_source": st.column_config.TextColumn("Evidence Source"),
        "squeeze_snapshot_age_minutes": st.column_config.NumberColumn("Snapshot Age", format="%.0fm"),
        "scan_error": st.column_config.TextColumn("Coverage Gaps"),
    }


def _render_squeeze_table(frame: pd.DataFrame, *, columns: list[str] | None = None, height: int = 430) -> None:
    if frame.empty:
        st.info("No symbols currently clear this state.")
        return
    requested = columns or SQUEEZE_RADAR_TABLE_COLUMNS
    available = [column for column in requested if column in frame.columns]
    st.dataframe(
        frame.loc[:, available],
        use_container_width=True,
        hide_index=True,
        height=height,
        column_config=_squeeze_radar_column_config(),
    )


def _scan_age_text(frame: pd.DataFrame) -> str:
    if frame.empty or "scanned_at_utc" not in frame.columns:
        return "no saved scan"
    timestamps = pd.to_datetime(frame["scanned_at_utc"], errors="coerce", utc=True).dropna()
    if timestamps.empty:
        return "timestamp unavailable"
    age_seconds = max(0.0, (pd.Timestamp.now(tz="UTC") - timestamps.max()).total_seconds())
    if age_seconds < 120:
        return f"{int(age_seconds)}s old"
    if age_seconds < 7200:
        return f"{age_seconds / 60.0:.0f}m old"
    return f"{age_seconds / 3600.0:.1f}h old"


def _short_seed_age_text() -> str:
    modified = [
        path.stat().st_mtime
        for path in SQUEEZE_RADAR_SHORT_SEED_PATHS
        if path.exists() and path.stat().st_size > 1
    ]
    if not modified:
        return "missing"
    latest = datetime.fromtimestamp(max(modified), tz=timezone.utc)
    age_seconds = max(0.0, (_utc_now() - latest).total_seconds())
    if age_seconds < 7200:
        return f"{age_seconds / 60.0:.0f}m old"
    if age_seconds < 172800:
        return f"{age_seconds / 3600.0:.1f}h old"
    return f"{age_seconds / 86400.0:.0f}D old"


def render_breakout_dashboard() -> None:
    header_left, header_right = st.columns([4.5, 1.5], vertical_alignment="bottom")
    with header_left:
        st.title("Convex Squeeze Radar")
        st.caption("Forced-flow setups in Binance USDT crypto perps | short accounts are account count, not short notional")
    with header_right:
        st.caption("Live market mechanics + cached holder and venue evidence")

    control_scan, control_profile, control_budget, control_status = st.columns([1.1, 1.6, 1.2, 3.1], vertical_alignment="bottom")
    with control_profile:
        profile_name = st.segmented_control(
            "Sensitivity",
            options=list(SQUEEZE_RADAR_PROFILES),
            default="Primary",
            key="squeeze_profile",
        ) or "Primary"
    with control_budget:
        budget_options = [24, 36, 48]
        default_budget = min(budget_options, key=lambda value: abs(value - SQUEEZE_RADAR_DEFAULT_SYMBOLS))
        symbol_budget = st.selectbox(
            "Live candidates",
            options=budget_options,
            index=budget_options.index(default_budget),
            key="squeeze_candidate_budget",
        )
    with control_scan:
        scan_clicked = st.button(
            "Refresh live",
            type="primary",
            icon=":material/refresh:",
            use_container_width=True,
            key="refresh_squeeze_radar",
        )

    if "squeeze_radar_raw" not in st.session_state:
        st.session_state["squeeze_radar_raw"] = _load_latest_squeeze_radar()
    raw_frame = st.session_state.get("squeeze_radar_raw", pd.DataFrame())
    if not raw_frame.empty and "market_type" in raw_frame.columns:
        crypto_mask = ~raw_frame["market_type"].astype(str).str.upper().isin(TRADFI_ALWAYS_INCLUDE_TYPES)
        raw_frame = raw_frame[crypto_mask].copy()
    scan_metadata = st.session_state.get("squeeze_radar_metadata", {})

    if scan_clicked:
        nonce = int(st.session_state.get("squeeze_radar_nonce", 0)) + 1
        st.session_state["squeeze_radar_nonce"] = nonce
        try:
            with st.spinner(f"Live-enriching {symbol_budget} candidates from the full crypto-perp universe..."):
                refreshed, scan_metadata = run_squeeze_radar_scan(nonce, int(symbol_budget))
            if refreshed.empty:
                st.error(str(scan_metadata.get("error") or "The live radar returned no rows."))
            else:
                raw_frame = refreshed
                st.session_state["squeeze_radar_raw"] = refreshed
                st.session_state["squeeze_radar_metadata"] = scan_metadata
                _persist_latest_squeeze_radar(refreshed)
        except Exception as exc:
            st.error("The bounded Binance scan failed. The last saved radar remains visible.")
            st.exception(exc)

    raw_frame = _attach_saved_squeeze_history(raw_frame)

    with control_status:
        if raw_frame.empty:
            st.caption("No saved scan | refresh live to initialize")
        else:
            universe = int(pd.to_numeric(raw_frame.get("scan_universe_count"), errors="coerce").max()) if "scan_universe_count" in raw_frame.columns else 0
            elapsed = _safe_float(scan_metadata.get("elapsed_seconds"))
            elapsed_text = f" | {elapsed:.1f}s" if elapsed > 0 else ""
            probe_count = int(_safe_float(scan_metadata.get("short_probe_count"))) if scan_metadata.get("short_probe_count") else 0
            probe_coverage = _safe_float(scan_metadata.get("short_probe_coverage_pct"))
            probe_text = f" | {probe_count} live short probes ({probe_coverage:.0f}%)" if probe_count else ""
            crowd_count = int(_safe_float(scan_metadata.get("crowd_diagnostic_count"))) if scan_metadata.get("crowd_diagnostic_count") else 0
            crowd_text = f" | {crowd_count} crowd-flow diagnostics" if crowd_count else ""
            st.caption(f"{_scan_age_text(raw_frame)} | {len(raw_frame)}/{universe or '?'} live-enriched{probe_text}{crowd_text}{elapsed_text}")

    if raw_frame.empty:
        st.warning("No radar snapshot is available yet.")
        return

    scored = score_squeeze_radar(raw_frame, profile=profile_name)
    scored = _attach_reflexivity_assessments(scored)
    if scan_clicked and not scored.empty:
        _persist_squeeze_radar_history(scored)
    high_conviction = scored[scored["squeeze_high_conviction"]].copy()
    market_triggers = scored[scored["squeeze_market_trigger"]].copy()
    structural_watch = scored[scored["squeeze_structural_watch"]].copy()
    armed = scored[scored["squeeze_stage"] == "ARMED"].copy()
    late = scored[scored["squeeze_stage"] == "LATE"].copy()
    stale = scored[scored["squeeze_snapshot_stale"]].copy()
    best = scored.iloc[0] if not scored.empty else pd.Series(dtype="object")

    if not stale.empty:
        st.warning(
            "This saved radar snapshot is stale. Refresh live before treating any row as current; stale rows are shown for context only."
        )

    active_reflexivity = scored[scored["reflexivity_state"].isin({"ACTIVE_REFLEXIVITY", "ACCELERATING"})].copy()
    exhaustion_risk = scored[scored["reflexivity_state"] == "EXHAUSTION_RISK"].copy()
    kpi_cols = st.columns(5)
    kpi_cols[0].metric("Active reflexivity", len(active_reflexivity))
    kpi_cols[1].metric("Building", int((scored["reflexivity_state"] == "BUILDING").sum()))
    kpi_cols[2].metric("Entry-ready proof", len(high_conviction))
    kpi_cols[3].metric("Exhaustion risk", len(exhaustion_risk))
    best_symbol = str(best.get("symbol") or "n/a")
    best_score = _safe_float(best.get("squeeze_score"))
    kpi_cols[4].metric("Top ranked", best_symbol, f"score {best_score:.1f}" if best_score else None)

    radar_tab, watch_tab, lifecycle_tab, evidence_tab = st.tabs(["Radar", "Watch", "Lifecycle", "Evidence"])

    with radar_tab:
        st.subheader("Entry-Ready Structures")
        if high_conviction.empty:
            st.info("No current row clears both live ignition and fresh verified holder plus Bitget/Gate evidence.")
        else:
            _render_squeeze_table(high_conviction, height=300)

        st.subheader("Market Ignition, Evidence Pending")
        if market_triggers.empty:
            closest = scored[
                (~scored["squeeze_stage"].isin({"LATE", "UNWIND", "STALE"}))
            ].head(12)
            st.caption("No current market trigger; nearest live structures are shown. Market ignition alone is not an entry signal.")
            _render_squeeze_table(closest, height=380)
        else:
            _render_squeeze_table(market_triggers, height=380)

        st.subheader("Mechanism Read")
        mechanism_rows = scored[
            scored["reflexivity_state"].isin({"ACTIVE_REFLEXIVITY", "ACCELERATING", "EXHAUSTION_RISK"})
        ].copy()
        _render_squeeze_table(
            mechanism_rows,
            columns=[
                "squeeze_rank",
                "symbol",
                "reflexivity_state",
                "reflexivity_score",
                "reflexivity_data_quality_pct",
                "reflexivity_gate_summary",
                "reflexivity_explanation",
                "reflexivity_invalidation",
            ],
            height=300,
        )

    with watch_tab:
        st.subheader("Verified Structure Watch")
        _render_squeeze_table(structural_watch, height=360)
        st.subheader("Armed Before Ignition")
        _render_squeeze_table(armed, height=360)
        st.subheader("Fuel Watch")
        fuel_watch = scored[
            (pd.to_numeric(scored["short_account_pct"], errors="coerce") >= SQUEEZE_RADAR_PROFILES[profile_name].min_short_pct - 2.5)
            & (~scored["squeeze_stage"].isin({"LATE", "UNWIND", "REFLEXIVE", "IGNITION"}))
        ].sort_values(
            ["squeeze_fuel_remaining_score", "squeeze_volume_score", "squeeze_score"],
            ascending=[False, False, False],
        )
        _render_squeeze_table(fuel_watch, height=360)

    with lifecycle_tab:
        state_counts = (
            scored["reflexivity_state"].value_counts()
            .reindex(["ACCELERATING", "ACTIVE_REFLEXIVITY", "BUILDING", "DISCOVERY", "EXHAUSTION_RISK", "INVALIDATED"], fill_value=0)
            .rename_axis("Research state")
            .to_frame("Symbols")
        )
        st.bar_chart(state_counts, height=230)
        lifecycle = scored[scored["squeeze_stage"].isin({"REFLEXIVE", "IGNITION", "UNWIND", "LATE", "STALE"})]
        lifecycle_columns = SQUEEZE_RADAR_TABLE_COLUMNS + ["squeeze_invalidation", "reflexivity_invalidation"]
        _render_squeeze_table(lifecycle, columns=lifecycle_columns, height=430)

    with evidence_tab:
        st.caption(
            "Verified means contract-backed holder/venue evidence no more than 30 days old. "
            "Proxy-only evidence can rank a row for investigation but can never make it entry-ready; "
            "market snapshots older than 90 minutes are marked stale."
        )
        refresh_structure_col, refresh_note_col = st.columns([1.2, 3.0], vertical_alignment="center")
        with refresh_structure_col:
            refresh_structure = st.button(
                "Refresh structural proof",
                icon=":material/account_balance_wallet:",
                help=(
                    f"Run the heavier concentration scanner for the top {SQUEEZE_RADAR_STRUCTURAL_REFRESH_MAX_SYMBOLS} live candidates. "
                    "This is deliberately separate from the fast market refresh."
                ),
                key="refresh_squeeze_structural_proof",
            )
        with refresh_note_col:
            st.caption(
                f"On-demand only: up to {SQUEEZE_RADAR_STRUCTURAL_REFRESH_MAX_SYMBOLS} candidates, cached locally in the concentration scanner."
            )
        if refresh_structure:
            with st.spinner("Refreshing holder concentration and storage controls for the top live candidates..."):
                refreshed_raw, refresh_metadata = _refresh_squeeze_structural_evidence(scored)
            if refresh_metadata.get("verified", 0):
                st.session_state["squeeze_radar_raw"] = refreshed_raw
                _persist_latest_squeeze_radar(refreshed_raw)
                st.success(
                    f"Verified structural proof for {refresh_metadata['verified']} of {refresh_metadata['attempted']} candidates."
                )
                st.rerun()
            else:
                st.warning(
                    f"No verified structural rows returned ({refresh_metadata.get('errors', 0)} coverage gaps). "
                    "Market evidence remains visible, but the row stays non-actionable."
                )
        evidence_kpis = st.columns(4)
        evidence_kpis[0].metric("Live metric coverage", f"{float(scored['squeeze_market_confidence'].median()):.0f}%")
        evidence_kpis[1].metric("Fresh verified rows", int(scored["squeeze_structural_evidence_fresh"].sum()))
        evidence_kpis[2].metric("Proxy-only rows", int((scored["structural_evidence_level"] == "PROXY").sum()) if "structural_evidence_level" in scored.columns else 0)
        evidence_kpis[3].metric("Background short census", _short_seed_age_text())
        evidence_columns = [
            "squeeze_rank",
            "symbol",
            "squeeze_evidence_tier",
            "structural_evidence_level",
            "structural_storage_checked",
            "squeeze_market_confidence",
            "squeeze_structure_score",
            "top10_holder_pct",
            "top100_holder_pct",
            "bitget_volume_share_pct",
            "crowd_top_position_divergence_pct",
            "crowd_top_account_divergence_pct",
            "taker_buy_share_pct",
            "structural_evidence_age_days",
            "structural_proxy_age_days",
            "structural_evidence_source",
            "reflexivity_event_time_utc",
            "reflexivity_received_at_utc",
            "reflexivity_source",
            "reflexivity_venue",
            "reflexivity_signal_version",
            "squeeze_snapshot_age_minutes",
            "scan_error",
            "squeeze_gate_failures",
        ]
        _render_squeeze_table(scored, columns=evidence_columns, height=520)

    st.subheader("Setup Drilldown")
    selected_symbol = st.selectbox(
        "Symbol",
        options=scored["symbol"].astype(str).tolist(),
        key="squeeze_drilldown_symbol",
        label_visibility="collapsed",
    )
    selected = scored[scored["symbol"] == selected_symbol].iloc[0]
    detail_cols = st.columns(10)
    detail_cols[0].metric("Stage", str(selected.get("squeeze_stage") or "n/a"))
    detail_cols[1].metric("Score", f"{_safe_float(selected.get('squeeze_score')):.1f}")
    detail_cols[2].metric("Short accounts", f"{_safe_float(selected.get('short_account_pct')):.2f}%")
    detail_cols[3].metric("1H short change", f"{_safe_float(selected.get('short_account_roc_1h_pp')):+.2f}pp")
    detail_cols[4].metric("Fuel", f"{_safe_float(selected.get('squeeze_fuel_remaining_score')):.0f}/100")
    detail_cols[5].metric("Late heat", f"{_safe_float(selected.get('squeeze_late_score')):.0f}/100")
    detail_cols[6].metric("3H short change", f"{_safe_float(selected.get('short_account_change_3p_pp')):+.2f}pp")
    detail_cols[7].metric("4H short change", f"{_safe_float(selected.get('short_account_change_4p_pp')):+.2f}pp")
    detail_cols[8].metric("3H OI change", f"{_safe_float(selected.get('oi_change_3p_pct')):+.2f}%")
    detail_cols[9].metric("OI acceleration", f"{_safe_float(selected.get('oi_acceleration_1h_pct')):+.2f}pp")

    st.markdown(
        f"**Canonical research state:** `{selected.get('reflexivity_state') or 'n/a'}` | "
        f"mechanism score `{_safe_float(selected.get('reflexivity_score')):.1f}` | "
        f"data quality `{_safe_float(selected.get('reflexivity_data_quality_pct')):.0f}%`"
    )

    canonical_component_scores = selected.get("reflexivity_component_scores")
    canonical_component_status = selected.get("reflexivity_component_status")
    canonical_component_evidence = selected.get("reflexivity_component_evidence")
    if isinstance(canonical_component_scores, dict):
        component_rows = []
        for component_name, score in canonical_component_scores.items():
            evidence = canonical_component_evidence.get(component_name, []) if isinstance(canonical_component_evidence, dict) else []
            component_rows.append(
                {
                    "Component": component_name.replace("_", " ").title(),
                    "Score": float(score) if score is not None else float("nan"),
                    "Status": canonical_component_status.get(component_name, "unknown") if isinstance(canonical_component_status, dict) else "unknown",
                    "Evidence": "; ".join(str(item) for item in evidence),
                }
            )
        component_detail_frame = pd.DataFrame(component_rows)
        component_frame = component_detail_frame.set_index("Component")[["Score"]]
    else:
        component_detail_frame = pd.DataFrame()
        component_frame = pd.DataFrame(
            {
                "Component": ["Short level", "Current build", "Volume", "Trend", "OI", "Funding", "Structure", "Venue", "Late heat"],
                "Score": [
                    _safe_float(selected.get("squeeze_short_level_score")),
                    _safe_float(selected.get("squeeze_short_build_score")),
                    _safe_float(selected.get("squeeze_volume_score")),
                    _safe_float(selected.get("squeeze_trend_score")),
                    _safe_float(selected.get("squeeze_oi_score")),
                    _safe_float(selected.get("squeeze_funding_score")),
                    _safe_float(selected.get("squeeze_structure_score")),
                    _safe_float(selected.get("squeeze_venue_score")),
                    _safe_float(selected.get("squeeze_late_score")),
                ],
            }
        ).set_index("Component")
    chart_col, read_col = st.columns([1.35, 1.0])
    with chart_col:
        st.bar_chart(component_frame, height=290)
        if not component_detail_frame.empty:
            st.dataframe(
                component_detail_frame,
                use_container_width=True,
                hide_index=True,
                height=290,
                column_config={
                    "Component": st.column_config.TextColumn("Mechanism component"),
                    "Score": st.column_config.NumberColumn("Score", format="%.1f"),
                    "Status": st.column_config.TextColumn("Evidence status"),
                    "Evidence": st.column_config.TextColumn("Observed evidence"),
                },
            )
    with read_col:
        st.markdown(f"**Mechanism read**\n\n{str(selected.get('reflexivity_explanation') or selected.get('squeeze_signal') or 'No complete signal.')}")
        st.markdown(f"**Mechanism gates**\n\n{str(selected.get('reflexivity_gate_summary') or selected.get('squeeze_gate_failures') or 'None')}")
        st.markdown(f"**Research gaps**\n\n{str(selected.get('reflexivity_missing_fields') or 'None')}")
        st.markdown(f"**Invalidation**\n\n{str(selected.get('reflexivity_invalidation') or selected.get('squeeze_invalidation') or 'n/a')}")
        st.caption("Research tooling only. Convexity still depends on small, predefined losses and rare outliers.")


def main_dashboard() -> None:
    render_breakout_dashboard()


if not IMPORT_ONLY:
    main_dashboard()
