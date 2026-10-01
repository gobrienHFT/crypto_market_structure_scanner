"""Full-market Streamlit workspace. Network work lives in ScanService."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from market_dashboard_data import ScanService, WINDOWS
from squeeze_radar import score_squeeze_radar


@st.cache_resource
def service(path: str, base_url: str) -> ScanService:
    return ScanService(Path(path), base_url)


@st.cache_data(ttl=60, max_entries=4, show_spinner=False)
def ranked_frame(frame: pd.DataFrame, _app: Any) -> pd.DataFrame:
    return _app._attach_reflexivity_assessments(score_squeeze_radar(_app._attach_cached_squeeze_evidence(frame)))


LABELS = {
    "symbol": "Pair", "last_price": "Price", "quote_asset": "Quote", "scan_status": "Coverage",
    "price_change_24h_pct": "Price 24h %", "short_account_pct": "Short accounts %",
    "long_account_pct": "Long accounts %", "short_account_previous_1h_pct": "Shorts previous hour %",
    "short_account_roc_1h_pct": "Shorts 1h ROC %", "short_account_roc_1h_pp": "Shorts 1h change pp",
    "short_sample_age_minutes": "Short sample age (min)", "long_short_account_ratio": "Long / short accounts",
    "carry_funding_pct": "Funding rate %", "quote_volume_24h": "24h quote volume",
    "quote_volume_prior_30d_total": "Prior 30D volume", "quote_volume_prior_30d_daily_avg": "Prior daily average",
    "quote_volume_prior_30d_days": "Volume baseline days", "quote_volume_24h_vs_prior_30d_avg_ratio": "24h / daily average",
    "hour_quote_volume": "1h quote volume", "hour_quote_volume_previous_1h": "Previous 1h volume",
    "hour_volume_roc_1h_pct": "Volume 1h ROC %", "oi_value_usdt": "OI quote value",
    "oi_units": "OI units", "oi_delta_pct": "OI 1h change %", "oi_prior_30d_avg": "Prior OI average",
    "oi_prior_30d_days": "OI baseline days", "oi_vs_30d_avg_ratio": "OI value / average",
    "oi_units_vs_30d_avg_ratio": "OI units / average", "oi_sample_age_minutes": "OI sample age (min)",
    "corr_to_btc_6m": "BTC return correlation", "corr_window_days": "Correlation observations",
    "ma200": "MA200", "price_vs_ma200_pct": "Price / MA200 %", "history_days": "Closed history days",
    "reflexivity_score": "Reflexivity score", "reflexivity_state": "Reflexivity state",
    "squeeze_score": "Setup score", "squeeze_evidence_tier": "Evidence tier",
    "reflexivity_data_quality_pct": "Evidence quality %", "top10_holder_pct": "Top 10 holders %",
    "top100_holder_pct": "Top 100 holders %", "adjusted_top_10_pct": "Adjusted top 10 %",
    "low_float_score": "Low-float proxy score", "structural_evidence_age_days": "Holder evidence age (days)",
    "structural_evidence_sources": "Holder sources", "structural_evidence_level": "Holder evidence level",
    "squeeze_gate_failures": "Unmet setup criteria", "scan_error": "Data gaps",
    "scanned_at_utc": "Observed UTC", "event_lookback_hours": "Event history hours",
}


def config(frame: pd.DataFrame) -> dict:
    result = {}
    for c in frame.columns:
        label = LABELS.get(c, c.replace("_", " ").capitalize())
        if pd.api.types.is_numeric_dtype(frame[c]):
            fmt = "%.3f" if "corr_to" in c else "%.2f"
            if c in {"quote_volume_24h", "quote_volume_prior_30d_total", "quote_volume_prior_30d_daily_avg",
                     "hour_quote_volume", "hour_quote_volume_previous_1h", "oi_value_usdt", "oi_prior_30d_avg", "oi_units"}:
                fmt = "compact"
            if c == "carry_funding_pct":
                fmt = "%.5f"
            if c in {"last_price", "ma200"} or c in {f"{s}_{d}d" for d in WINDOWS for s in ("high", "low")}:
                fmt = "%.8g"
            if c.endswith("_age_minutes"):
                fmt = "%.0f"
            if "ratio" in c and c != "long_short_account_ratio":
                fmt = "%.2fx"
            result[c] = st.column_config.NumberColumn(label, format=fmt)
        else:
            result[c] = st.column_config.TextColumn(label)
        if c.startswith("broke_"):
            result[c] = st.column_config.CheckboxColumn(c.replace("broke_", "").replace("_", " ").upper())
        if c == "symbol":
            result[c] = st.column_config.TextColumn("Pair", pinned=True)
        for d in WINDOWS:
            for side in ("high", "low"):
                if c == f"{side}_{d}d_age_minutes":
                    result[c] = st.column_config.NumberColumn(f"{d}D {side} age (min)", format="%.0f")
                if c == f"{side}_{d}d_resolution_minutes":
                    result[c] = st.column_config.NumberColumn(f"{d}D {side} precision (min)", format="%.0f")
    return result


def table(frame: pd.DataFrame, columns: list[str], key: str, *, sort: str | None = None, ascending=False):
    view = frame.reindex(columns=[c for c in columns if c in frame]).copy()
    if sort in view:
        view = view.sort_values(sort, ascending=ascending, na_position="last")
    st.dataframe(view, hide_index=True, use_container_width=True, height=min(550, 38 + 35 * max(1, len(view))), column_config=config(view), key=key)
    st.download_button("Download CSV", view.to_csv(index=False).encode(), f"{key}.csv", "text/csv", key=f"download_{key}")


def age_events(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    for col in frame:
        if col.endswith("_event_utc"):
            ts = pd.to_datetime(frame[col], utc=True, errors="coerce")
            frame[col.replace("_event_utc", "_age_minutes")] = (pd.Timestamp.now(tz="UTC") - ts).dt.total_seconds() / 60
    return frame


CORE = ["symbol", "last_price", "quote_asset", "price_change_24h_pct", "short_account_pct", "long_account_pct",
        "short_account_roc_1h_pp", "short_account_roc_1h_pct", "carry_funding_pct", "hour_volume_roc_1h_pct",
        "quote_volume_24h", "quote_volume_24h_vs_prior_30d_avg_ratio", "oi_value_usdt", "oi_delta_pct",
        "oi_vs_30d_avg_ratio", "corr_to_btc_6m", "ma200", "price_vs_ma200_pct", "scan_status", "scanned_at_utc"]


def render(app: Any):
    demo = os.environ.get("MARKET_DASHBOARD_DEMO") == "1"
    workspace_path = os.environ.get("MARKET_WORKSPACE_DB_PATH") or str(app.APP_DIR / "data" / "market_workspace.sqlite")
    scanner = service(workspace_path, app.BASE_URL)
    st.markdown("<style>.block-container{max-width:1900px;padding-top:1rem}h1{font-size:1.7rem!important}"
                "[data-testid=stVerticalBlock]{gap:.65rem}"
                "[data-testid=stMetric]{background:transparent;border:0;border-bottom:1px solid #303741;"
                "border-radius:0;padding:.25rem 0;min-height:65px}</style>", unsafe_allow_html=True)
    st.title("Crypto Market Scanner")
    if demo:
        st.warning("OFFLINE DEMO | Synthetic examples as of 2026-09-01 12:00 UTC. Prices, rankings and signals are illustrative, not live observations.")
    else:
        st.caption("All trading Binance USD-M crypto perpetuals | all quote currencies | account counts, price structure and public market flow")
    if not demo:
        left, middle, right = st.columns([2, 2, 5], vertical_alignment="bottom")
        with left:
            if st.button("Scan all pairs", icon=":material/refresh:", type="primary", use_container_width=True):
                scanner.start(st.session_state.get("minute_events", True))
        with middle:
            if st.button("Stop scan", icon=":material/stop:", use_container_width=True):
                scanner.stop()
        with right:
            st.checkbox("Minute-resolution breakout times", value=True, key="minute_events")
    search_col, quote_col = st.columns([4, 1])
    with search_col:
        search = st.text_input("Find pairs", placeholder="BTC, LAB, RAVE ...", key="market_search")
    with quote_col:
        raw, _ = scanner.snapshot()
        quotes = sorted(set(raw.get("quote_asset", pd.Series(dtype=str)).dropna()) | {"USDT", "USDC", "USD1", "U", "BTC"})
        quote = st.selectbox("Quote currency", ["All", *quotes], key="market_quote")
    _scan_status(scanner)
    names = ["All Markets", "Reflexivity", "Breakouts", "Volume & OI", "Correlations", "Market Breadth"]
    for name, panel in zip(names, st.tabs(names)):
        with panel:
            _workspace(app, scanner, name, search, quote)


@st.fragment(run_every=5)
def _scan_status(scanner: ScanService):
    demo = os.environ.get("MARKET_DASHBOARD_DEMO") == "1"
    raw, status = scanner.snapshot()
    if demo:
        st.caption(f"Fixed synthetic sample | {len(raw)} pairs | 2026-09-01 12:00 UTC")
    elif status["running"]:
        st.progress(status["completed"] / max(1, status["total"]),
                    text=f"{status['status']} | {status['completed']} / {status['total']} pairs")
        if status.get("remaining_seconds") is not None:
            st.caption(f"Estimated remaining: {status['remaining_seconds'] / 60:.1f} min at the observed scan rate")
    else:
        st.caption(f"{status['status']} | {len(raw)} pairs")
    if raw.empty:
        st.info("No full-market snapshot yet. Scan all pairs to load the market.")
        return
    fresh = pd.to_datetime(raw.get("scanned_at_utc", pd.Series(index=raw.index, dtype=str)), utc=True, errors="coerce")
    oldest = fresh.min()
    if not demo and pd.notna(oldest) and (pd.Timestamp.now(tz="UTC") - oldest).total_seconds() > 900:
        st.warning("Some rows are over 15 minutes old. Their observation times are shown; refresh for current conditions.")
    metrics = st.columns(4)
    metrics[0].metric("Pairs", len(raw))
    metrics[1].metric("Complete", int(raw.scan_status.eq("Complete").sum()) if "scan_status" in raw else 0)
    metrics[2].metric("Above 90D high", int(raw.get("broke_high_90d", pd.Series(dtype=bool)).fillna(False).sum()))
    metrics[3].metric("Below 90D low", int(raw.get("broke_low_90d", pd.Series(dtype=bool)).fillna(False).sum()))


@st.fragment(run_every=15)
def _workspace(app: Any, scanner: ScanService, page: str, search: str, quote: str):
    raw, _ = scanner.snapshot()
    if raw.empty:
        return
    frame = raw.copy() if os.environ.get("MARKET_DASHBOARD_DEMO") == "1" else age_events(raw)
    if quote != "All":
        frame = frame[frame.quote_asset.eq(quote)]
    terms = [s.strip().upper() for s in search.split(",") if s.strip()]
    if terms:
        frame = frame[frame.symbol.map(lambda s: any(t in s for t in terms))]
    if page == "All Markets":
        expanded = st.checkbox("All data columns", key="all_market_columns")
        table(frame, list(frame.columns) if expanded else CORE, "all_markets", sort="quote_volume_24h")
    if page == "Reflexivity":
        completed = frame[frame.get("scan_status", pd.Series(index=frame.index, dtype=str)).isin(["Complete", "Partial"])]
        if completed.empty:
            st.info("Reflexivity metrics appear as pairs finish scanning.")
        else:
            static = completed.drop(columns=[c for c in completed if c.endswith("_age_minutes") and c not in {"short_sample_age_minutes", "oi_sample_age_minutes"}])
            scored = ranked_frame(static, app)
            st.caption("Market ranking plus cached ownership evidence. Concentration is not proof of coordinated ownership; scores are research hypotheses.")
            table(scored, ["symbol", "reflexivity_score", "reflexivity_state", "squeeze_score", "reflexivity_data_quality_pct",
                          "short_account_pct", "short_account_roc_1h_pp", "short_sample_age_minutes",
                          "carry_funding_pct", "funding_interval_hours", "hour_volume_roc_1h_pct",
                          "quote_volume_24h_vs_prior_30d_avg_ratio", "oi_delta_pct", "oi_vs_30d_avg_ratio",
                          "oi_sample_age_minutes", "scan_status",
                          "top10_holder_pct", "top100_holder_pct", "adjusted_top_10_pct", "low_float_score",
                          "squeeze_evidence_tier", "structural_evidence_level", "structural_evidence_sources",
                          "structural_evidence_age_days", "squeeze_gate_failures"], "reflexivity", sort="reflexivity_score")
            selected = st.selectbox("Inspect ownership evidence", sorted(scored.symbol), key="ownership_symbol")
            if st.button("Refresh on-chain evidence", icon=":material/search:", key="refresh_ownership", disabled=os.environ.get("MARKET_DASHBOARD_DEMO") == "1"):
                with st.spinner(f"Checking holder evidence for {selected}..."):
                    _, details = app._refresh_squeeze_structural_evidence(scored[scored.symbol.eq(selected)], max_symbols=1)
                ranked_frame.clear()
                st.write(details)
                st.rerun(scope="fragment")
            row = scored[scored.symbol.eq(selected)].iloc[0]
            st.write(str(row.get("reflexivity_explanation", "Evidence pending")))
            st.caption(str(row.get("reflexivity_missing_fields", "")))
    if page == "Breakouts":
        view_col, event_col = st.columns([2, 1])
        with view_col:
            mode = st.selectbox("Breakout view", ["All pairs", "High crossings", "Low crossings", "MA200 crosses"], key="breakout_mode")
        with event_col:
            horizon = st.selectbox("Sort event", ["90D", "5D", "20D", "180D"], key="event_horizon")
        st.caption("Each scan checks roughly 72 hours for the latest crossing. Timing is the crossing candle's opening time; resolution is 1 or 60 minutes. Blank means no observed crossing or insufficient history. Flags compare the observed price with the prior closed-day level.")
        show_levels = st.checkbox("Show price levels, timestamps and timing precision", key="breakout_details")
        side = "low" if mode == "Low crossings" else "high"
        sort = f"{side}_{horizon.lower()}_age_minutes"
        columns = ["symbol", "last_price", sort]
        for d in WINDOWS:
            for side in ("high", "low"):
                columns += [f"broke_{side}_{d}d", f"{side}_{d}d_age_minutes"]
                if show_levels:
                    columns += [f"{side}_{d}d", f"{side}_{d}d_event_utc", f"{side}_{d}d_resolution_minutes"]
        columns += ["ma200", "price_vs_ma200_pct", "ma200_up_age_minutes", "ma200_up_resolution_minutes",
                    "ma200_down_age_minutes", "ma200_down_resolution_minutes", "history_days", "scan_status"]
        columns = list(dict.fromkeys(columns))
        side = "low" if mode == "Low crossings" else "high"
        selected_frame = frame
        if mode != "All pairs":
            event_cols = [f"ma200_{s}_age_minutes" for s in ("up", "down")] if mode == "MA200 crosses" else [f"{side}_{d}d_age_minutes" for d in WINDOWS]
            selected_frame = frame[frame.reindex(columns=event_cols).notna().any(axis=1)]
        if mode == "MA200 crosses":
            sort = "ma200_up_age_minutes"
        table(selected_frame, columns, "breakouts", sort=sort, ascending=True)
        chart_symbol = st.selectbox("Price history", sorted(frame.symbol), key="breakout_chart_symbol") if not frame.empty else None
        if chart_symbol and hasattr(scanner, "chart"):
            chart = scanner.chart(chart_symbol)
            if not chart.empty:
                st.line_chart(chart, color=["#59C3D8", "#f0b44d"])
    if page == "Volume & OI":
        st.caption("Quote volumes are denominated in each pair's quote currency. Prior volume baseline excludes calendar days overlapping the rolling 24h window. OI is a stock: value and contract-unit ratios are shown separately, with available daily samples.")
        table(frame, ["symbol", "quote_asset", "last_price", "quote_volume_24h", "quote_volume_prior_30d_total",
                      "quote_volume_prior_30d_daily_avg", "quote_volume_prior_30d_days", "quote_volume_24h_vs_prior_30d_avg_ratio",
                      "hour_quote_volume", "hour_quote_volume_previous_1h", "hour_volume_roc_1h_pct",
                      "oi_value_usdt", "oi_units", "oi_delta_pct", "oi_prior_30d_avg", "oi_prior_30d_days",
                      "oi_vs_30d_avg_ratio", "oi_units_vs_30d_avg_ratio", "short_account_pct", "long_account_pct",
                      "scan_status"], "volume_oi", sort="quote_volume_24h_vs_prior_30d_avg_ratio")
    if page == "Correlations":
        threshold = st.slider("Maximum BTC correlation", -1.0, 1.0, 1.0, 0.05)
        include_unknown = st.checkbox("Include unavailable correlations", value=True)
        corr = pd.to_numeric(frame.get("corr_to_btc_6m", pd.Series(index=frame.index, dtype=float)), errors="coerce")
        view = frame[corr.le(threshold) | (corr.isna() & include_unknown)]
        st.caption("Pearson correlation of matched closed daily returns, up to 180 observations. New listings use available history; at least 3 matched returns are required.")
        table(view, ["symbol", "corr_to_btc_6m", "corr_window_days", "history_days", "price_change_24h_pct",
                     "short_account_pct", "hour_volume_roc_1h_pct", "scan_status"], "correlations", sort="corr_to_btc_6m", ascending=True)
    if page == "Market Breadth":
        st.caption("Breadth across scanned assets, one contract per base asset, preferring USDT. This is not a market-cap index.")
        broad = raw.copy()
        if "base_asset" in broad:
            broad["quote_priority"] = broad.get("quote_asset", pd.Series(index=broad.index, dtype=str)).ne("USDT")
            broad = broad.sort_values(["quote_priority", "symbol"]).drop_duplicates("base_asset")
        observations = []
        for d in WINDOWS:
            for side in ("high", "low"):
                level = pd.to_numeric(broad.get(f"{side}_{d}d", pd.Series(dtype=float)), errors="coerce")
                flags = broad.get(f"broke_{side}_{d}d", pd.Series(dtype=bool)).fillna(False)
                observations.append({"Measure": f"{d}D {side}", "Assets": int(flags.sum()), "Eligible": int(level.notna().sum())})
        ma = pd.to_numeric(broad.get("price_vs_ma200_pct", pd.Series(dtype=float)), errors="coerce")
        observations.append({"Measure": "Above MA200", "Assets": int(ma.gt(0).sum()), "Eligible": int(ma.notna().sum())})
        summary = pd.DataFrame(observations)
        summary["Share %"] = summary.Assets.div(summary.Eligible.where(summary.Eligible.gt(0))).mul(100)
        st.bar_chart(summary.set_index("Measure")[["Share %"]], color="#59C3D8")
        st.dataframe(summary, hide_index=True, use_container_width=True)
    if page == "All Markets":
        with st.expander("Data coverage"):
            table(frame, ["symbol", "scan_status", "scan_error", "scanned_at_utc", "history_days",
                          "short_sample_age_minutes", "oi_sample_age_minutes", "quote_volume_prior_30d_days",
                          "oi_prior_30d_days", "corr_window_days"], "coverage")
