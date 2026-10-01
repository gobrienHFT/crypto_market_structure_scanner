# Full-market dashboard

Launch `run_dashboard.bat`, then choose **Scan all pairs**. The default `app.py`
workspace now scans every currently trading crypto perpetual contract returned
by Binance's USD-M exchange information endpoint, without a volume floor,
major-coin exclusion, or candidate budget. TradFi contracts, delivery futures,
spot markets and the separate COIN-M API are outside this universe. Quote
currencies are exposed as a filter; symbols are never silently renamed.

For an offline UI walkthrough, launch `run_dashboard_demo.bat`. It generates a
fixed synthetic workspace in ignored `artifacts/dashboard_demo/` and opens
port 8502. A persistent banner labels every value as synthetic and dates the
observation; event ages refer to that fixed observation time. Live scan controls
are hidden and on-chain refresh is disabled. The ordinary launcher on
port 8501 uses public exchange data and a separate saved workspace.

## Views

- **All Markets:** sortable price, account-count positioning, funding, volume,
  OI, BTC correlation and moving-average columns. Expand all columns or export CSV.
- **Reflexivity:** the existing squeeze and canonical reflexivity models over
  every enriched pair. Cached ownership evidence remains labelled with its
  source, age and quality. Hourly sample ages and partial coverage are shown
  alongside rankings. Refresh on-chain evidence for a selected pair.
- **Breakouts:** 5/20/90/180-day highs and lows, current flags, recent crossing
  ages, per-event timing resolution, MA200 crossings and daily price history.
- **Volume & OI:** raw baseline values, observation counts and relative changes.
- **Correlations:** matched daily return correlation to BTC, with the actual
  observation count for each pair, including short-history listings.
- **Market Breadth:** fraction of eligible assets beyond each level and above
  MA200, deduplicating base assets and preferring their USDT contracts. This is
  breadth, not a capitalization-weighted index or a CMC index replica.

## Measurement definitions

Breakout levels are calculated from the previous N complete UTC daily candles.
The active day never contributes to its own threshold. Missing daily candles
or insufficient listing history produce unknown levels, not shorter-window
substitutes. Current flags compare the ticker's last price to those levels.

Event detection looks back through 73 hourly candles (roughly 72 hours). It
compares consecutive candle extremes to the threshold known at that day's UTC
open, so a falling rolling threshold alone does not count as a crossing. An
already-active breakout at the beginning of coverage has an unknown event age.
The last observed fresh excursion is used, including excursions that later fail.

With minute timing enabled, detected event hours are refined using one-minute
candles. Ages are measured from the crossing candle's opening time and are
therefore interval estimates, not exact trade timestamps. The resolution column
is **1 minute** when refinement succeeds and **60 minutes** otherwise. Absence
of a timestamp means no observed crossing or unavailable history; it does not
prove no breakout occurred outside coverage. Candle gaps do not create events.
MA200 is a simple average of 200 closed daily closes, fixed for each UTC day.

The 24h volume is Binance's rolling quote volume. Its baseline is up to 30 prior
closed UTC days whose candles do not overlap the rolling 24h window. Both the
total and daily average are exposed. The hourly volume ROC compares the latest
closed hourly candle to its immediate predecessor, with a missing result if
those candles are not consecutive. Volume units are the pair's quote currency;
USDT and USDC values are approximately dollar values, while BTC quotes are not.

OI is a stock, not turnover: the current hourly observation is compared to up
to 30 earlier daily observations. Both OI-value and OI-unit ratios are provided,
because a price increase can raise OI value without increasing contract units.
Binance only exposes roughly one month of OI history, so 29 baseline observations
is a normal result and is displayed as 29. Gaps in hourly OI/account samples do
not get relabelled as one-hour changes.

Short-account and OI readings are suppressed when their latest hourly sample is
at least 120 minutes old. The actual sample age remains visible, and that pair
is marked partial with a stale-data reason. Binance's [funding-info response](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data) lists
adjusted contracts; a successful response implies the standard eight-hour
interval for unlisted contracts, as described in Binance's [funding FAQ](https://www.binance.com/en/support/faq/detail/360033525031).
If that request fails, the interval is unknown.

Correlation is Pearson correlation of aligned closed daily percentage returns,
using at most 180 matched observations and a minimum of three. Missing days are
not forward-filled. Account percentages describe the distribution of accounts,
not the distribution of short and long notional. Scores do not establish market
maker involvement, manipulation, coordinated ownership, or a profitable edge.

## Runtime and coverage

The first scan must fetch several public data series per contract and takes
minutes. Four workers share request pacing, including a separate cap on the
historical derivatives data routes. The interface remains usable and displays
pending, complete, partial and unavailable rows. Stop interrupts the scan and
retains completed results. HTTP 418/429 stops further requests for the scan.

Public responses and snapshots persist in `data/market_workspace.sqlite`.
Cached forming candles are fetched again after their close time passes, so
an unfinished daily or hourly bar cannot become a historical observation just
because it was read after a UTC boundary. A saved daily chart likewise keeps
the capture-time distinction between finished and unfinished bars.
Cached rows retain timestamps and stale snapshots are identified. On reopening,
sample ages advance with elapsed time; expired short-account and OI readings
are cleared from display, and old rows leave the live Reflexivity ranking and
current summary counts until the next scan. The browser never promotes a cached
unfinished daily candle to a completed chart candle
just because time has passed. Empty universe responses retain the previous
snapshot, and malformed cached JSON is treated as a cache miss. The browser
updates individual panels without recreating the tab navigation. A scan is a
sequence of observations, not an atomic market snapshot; inspect observation
and sample ages before comparing instruments.

The broader UI is in `market_dashboard_ui.py`; public collection and point-in-time
measurements are in `market_dashboard_data.py`. The existing Discord and trading
execution entry points continue to use their existing paths.

Tests cover complete universes, new listings, missing candles, UTC boundaries,
76-minute event ages, failed-breakout timing, MA200, non-overlapping baselines,
OI samples, short-history correlations, provider failures, snapshot restoration
and populated Streamlit views.
