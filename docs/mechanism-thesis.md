# Convex Market-Structure Mechanism Thesis

This repo is trying to catch a narrow failure mode in perp-listed crypto: a token can reprice violently when real tradable float is much smaller than headline supply, the active venue set concentrates order flow, and the perp crowd leans the wrong way while price is already trending.

The scanner should not read any one signal as proof. The useful signal is a stack of independent hints that point to the same reflexive loop.

## Mechanism Map

### 1. Hidden-float cap-table reflexivity

Reference pattern: `RAVEUSDT` on `2026-04-18`.

External reporting around RAVE described a rapid vertical move followed by a collapse, exchange investigations by Binance and Bitget, allegations of insider-engineered activity, very high wallet concentration, exchange transfers before the move, and large short liquidations. Public reports vary on exact percentages and peak values, so the scanner treats RAVE as a mechanism anchor rather than a legal claim about intent.

Scanner interpretation:

- observed top-holder concentration or adjusted control is high
- FDV/market-cap or locked-supply structure implies low real float
- the order book can move without much visible spot depth
- a breakout forces late buyers and wrong-way shorts into the same thin float
- after the vertical phase, the same structure can unwind violently

Primary scanner columns:

- `mechanism_hidden_float_score`
- `terminal_hidden_float_reflexivity_score`
- `terminal_control_plane_score`
- `centralized_ownership_score`
- `low_float_score`
- `top10_holder_pct`
- `top100_holder_pct`
- `fdv_to_market_cap`
- `ath_multiple`
- `mechanism_late_failure_score`

### 2. CEX inventory squeeze

Reference pattern: `LABUSDT` on `2026-05-11`.

The public evidence for LAB is less clean than RAVE, but market commentary and token-data pages repeatedly describe a low-float, high-FDV, thin-liquidity token that traded with extreme upside and crash volatility. The scanner treats LAB as the venue-inventory stress pattern: controlled or thin float plus visible transfer/venue evidence plus perp fuel.

Scanner interpretation:

- controlled float or concentrated holder structure is present
- whale or control-wallet inventory moves toward a labelled exchange wallet
- the target exchange is also where perp/spot demand is active
- sellable inventory can be absorbed, trapped, or used to shape supply
- price can continue higher even while naive traders expect the CEX deposit to be bearish

Primary scanner columns:

- `mechanism_inventory_squeeze_score`
- `cex_deposit_flow_score`
- `cex_deposit_inventory_stress_score`
- `cex_deposit_24h_token_amount`
- `cex_deposit_24h_max_amount`
- `cex_deposit_24h_target_exchanges`
- `terminal_exchange_flow_score`
- `target_cex_flow_score`
- `inventory_transfer_risk_score`

### 3. Crowded-short uptrend continuation

Reference pattern: current/recent `VELVETUSDT`-style behavior.

This is the pattern the new dashboard section explicitly promotes: price is structurally advancing, funding is positive, short-account share is high, and shorts are still building. That combination can mean traders are paying funding to fight an uptrend while each new high increases liquidation/fomo pressure.

Scanner interpretation:

- positive funding does not automatically mean "too late"; in this setup it can prove shorts are paying to stay short
- high short-account share is more useful when short share is rising into strength
- a multi-window high-break stack matters more than a single candle
- the loop fails when price breaks recent lows, funding flips, or shorts stop building

Primary scanner columns:

- `mechanism_crowded_short_uptrend_score`
- `crowded_short_uptrend_score`
- `short_account_pct`
- `short_account_roc_1h_pp`
- `short_account_change_max_pp`
- `carry_funding_pct`
- `predicted_funding_pct`
- `broke_high_5d`
- `broke_high_20d`
- `broke_high_90d`
- `range_high_break_count`
- `breakout_pressure_score`
- `trend_confluence_score`
- `oi_delta_pct`

### 4. Compression ignition

Reference pattern: `SIRENUSDT`-style short-fuse compression.

This is the pre-breakout version of the squeeze. The setup is quiet, shorts or OI build, volatility compresses, and the first decisive range break can create an outsized reaction because the tape has not yet attracted broad chase behavior.

Primary scanner columns:

- `mechanism_compression_ignition_score`
- `pre_pump_compression_score`
- `pre_pump_short_fuse_score`
- `low_volatility_coil_score`
- `dormant_short_fuse_score`
- `silent_oi_accumulation_score`
- `terminal_pre_ignition_quality_score`

### 5. Runway breakout reflexivity

Reference patterns: `RIVERUSDT` / `STOUSDT`-style breakouts.

This is less about one CEX-flow event and more about payoff geometry. If a token has significant distance to prior extremes, enough venue support, and a clean high-break stack, the market can keep repricing as long as shorts, OI, volume, and narrative attention reinforce the trend.

Primary scanner columns:

- `mechanism_runway_breakout_score`
- `terminal_runway_score`
- `convexity_runway_score`
- `ath_runway_confluence_score`
- `range_breakout_score`
- `range_high_break_count`
- `breakout_pressure_score`
- `trend_confluence_score`

## Practical Dashboard Usage

Start with `Convex Mechanisms`.

- `Primary Mechanism` tells you which loop is most active.
- `Mechanism Evidence` gives the compact reason.
- `Reflexivity Loop` explains why the setup can keep going.
- `Next Check` tells you what to verify before treating the row seriously.
- `Invalidation` keeps the idea honest.

Then drill down:

- Use `Shorts Fighting Uptrend` for the VELVET-style continuation basket.
- Use `CEX Flow` for labelled exchange-transfer evidence.
- Use `RAVE/LAB Radar` for strict controlled-float analogues.
- Use `Terminal Evidence` for a broader structural dossier.
- Use `Pre-Activity Radar` before price has fully chased.

## Event-Study Evidence

The current local snapshot summary is in [Case-Study Event Summary](case-study-event-summary.md). It intentionally prints missing local evidence instead of filling gaps with assumptions. Where Binance daily candles are available, it also adds event-day and post-event price-path metrics.

The current evidence backlog is in [Case-Study Evidence Backfill Checklist](case-study-backfill-checklist.md). It groups missing evidence by next action so the research loop can move from mechanism hypothesis to stronger proof.

The latest holder-backfill attempt is in [Case-Study Holder Backfill](case-study-holder-backfill.md). It records whether the local contract hints could produce holder concentration rows or whether explorer coverage blocked the fetch.

A stronger full event study should keep extending each named historical example with:

- event date and local scan snapshot
- 7D/3D/1D pre-event returns
- funding path
- short-account path
- OI path
- high-break stack on the trigger day
- holder concentration at or before the event
- CEX-flow evidence, including whether blocked explorer coverage makes the result inconclusive
- post-event max upside and max drawdown

That turns the mechanism taxonomy from a strong qualitative framework into a measurable backtest surface.

## External Sources Used For The Thesis

- DL News, "Binance and Bitget to investigate Rave token market manipulation": https://www.dlnews.com/articles/markets/binance-and-bitget-under-fire-after-ravedao-crash/
- CoinDesk, "Binance and Bitget to Probe RAVE's 4,500% Token Surge": https://www.coindesk.com/business/2026/04/18/binance-and-biget-to-probe-rave-s-4-500-token-surge-as-claims-of-insider-orchestrated-rally-grow
- Binance Square summary of RAVE short liquidations and wallet concentration: https://www.binance.com/en/square/post/314021662378449
- Bitget article comparing BEAT with RAVE/LAB-style low circulating-supply structures: https://www.bitget.com/news/detail/12560605453967
- Phemex LAB market snapshot discussing high FDV, low liquidity ratio, and sharp rally: https://phemex.com/blogs/lab-token-price-prediction
