# Low-Float Perpetual Reflexivity Hypothesis

## Purpose and framing

I am testing a narrow hypothesis about low-float, highly concentrated tokens whose spot and perpetual markets may become vulnerable to forced buying and reflexive short squeezes.

I am not trying to estimate a token's intrinsic value or prove that any actor is manipulating a market. The mechanical question is simpler: when tradeable float is genuinely scarce, ownership is concentrated, liquidity is thin, and a perpetual market attracts persistent short participation, can relatively modest net buying produce a self-reinforcing move? The research process looks for that structure before the obvious vertical phase and defines continuation, exhaustion, and invalidation observations in advance.

This is a hypothesis and an event-driven research process, not a guarantee of future returns. The relevant assets can move violently in both directions, can gap through stops, can be delisted, and can have incomplete or misleading data. A correlation between a signal and a price move is not proof of causation or coordinated activity.

## One-sentence thesis

The hypothesis is most interesting when a controlled or unusually concentrated low-float token has Binance perpetual access, supporting Bitget/Gate activity, an early breakout, rising derivatives participation, and a persistent or growing short-account cohort. The test is whether that combination remains informative before the structure becomes a late vertical move, and whether short-account rollover or other exhaustion signals mark a change in the regime.

## What the market structure is

This is not a valuation trade. A high FDV is not, by itself, a reason to short, and a low-quality project is not automatically a squeeze candidate. The object of study is **forced-flow mechanics**:

- A small economically available float can make displayed spot liquidity fragile.
- Concentrated ownership can make the public float materially smaller than headline supply figures imply.
- A perpetual market allows traders to express a valuation-based short without owning spot inventory.
- Rising price can force short covering, discretionary short exits, and liquidations.
- Those purchases can be large relative to thin spot/perpetual depth, causing further price appreciation.
- A visible move can attract momentum buyers and new shorts simultaneously, extending the reflexive loop.

The outcome distribution is asymmetric and discontinuous: many observations will do nothing or fail, while a minority can produce unusually large moves alongside equally unusual volatility and crash risk. That is why survival, small sizing, and early detection matter more here than pretending to forecast every move precisely.

## The market-structure hypothesis

### 1. Real float can be far lower than reported supply

Headline circulating supply is not the same as continuously tradeable supply. A token may show a substantial circulating supply while a large fraction is held by a small set of wallets, insiders, related entities, market-making inventory, vesting addresses, contracts, or other non-public holders. The key question is not simply "what percentage do the top wallets own?" It is:

> How much supply is likely to be independently held, available for sale, and actually sitting in accessible spot order books?

If effective float is small, new net spot demand can move price disproportionately. Apparent liquidity can also be transient: bids or offers may be canceled, replenished selectively, or be too shallow for market orders. This is a structural precondition to investigate, not a signal by itself.

### 2. Concentration must be adjusted for benign or mechanical holders

Raw holder concentration is noisy. A top-ten concentration statistic can be inflated by an exchange omnibus wallet, bridge, wrapper, liquidity pool, burn address, treasury, vesting contract, staking contract, DAO reserve, protocol contract, or distribution reserve. Treating these mechanically as coordinated directional control would create false positives.

I therefore want raw concentration kept separate from **effective/adjusted manipulable concentration**. Known custody and storage categories should be filtered or discounted where possible, with on-chain evidence from Ethereum, BNB Chain, and Arbitrum recorded separately. The current hard evidence gate generally uses observed adjusted top-ten concentration of at least 90%, but that is only a screening threshold. It does not show that the wallets are coordinated or malicious.

The most interesting cases are where, after reasonable exclusions, a small number of non-benign or unexplained wallets still control a very large share of supply. This is a cap-table/float risk condition. It should be described as concentration or opacity, never as proof of intent.

### 3. Perpetuals allow a short crowd to form without spot supply

In a conventional liquid market, a high valuation may invite spot sellers and short sellers, whose activity can improve two-sided liquidity. In a low-float token, however, the perpetual market can make shorting much easier than sourcing or delivering spot. Traders can short a chart they believe is "obviously overvalued" even when genuine spot inventory is scarce.

This creates an asymmetric condition:

- The short side is visible and can be forced to buy back.
- The spot supply required to push the market upward may be scarce.
- The same price rise that makes a valuation short look worse can mechanically create more buy pressure through covering and liquidation.

I watch the **percentage of Binance accounts that are short**, its change, OI, funding, price, and volume. The account-based statistic is only a proxy: it does not reveal position size, leverage, liquidation prices, account overlap, hedges, or large-trader exposure. It is directional context, not a liquidation map.

### 4. The reflexive squeeze loop

A sequence worth testing is:

1. A token has concentrated ownership and a low effective float.
2. It has a listed or developing perpetual venue, particularly Binance, with supporting activity on Bitget and/or Gate.
3. Price and/or open interest begin to rise after a quiet or compressed period.
4. Retail and systematic traders interpret the valuation, chart, or funding as a short opportunity.
5. The short-account percentage remains high or rises while price holds trend/breakout structure.
6. Spot demand, inventory positioning, or a limited amount of net buying moves through thin liquidity.
7. Shorts cover or are liquidated; their buy orders reinforce the move.
8. New long momentum and new short attempts can coexist, keeping the loop alive.
9. Eventually, the short cohort stops building and begins to cover materially; OI/funding/volume can peak, price can go vertical, and the risk/reward shifts from early convexity to late fragility.

The research question concerns the middle of this sequence, not prediction of the eventual top and not a short thesis based merely on an asset looking artificial or expensive.

## Venue selection and why it matters

The research universe prioritizes Binance perpetuals and requires supporting Bitget trading evidence for the main thesis alerts; Gate and labelled CEX transfer targets are additional context. These venues are used because they are where the observed examples and the intended derivatives/spot interaction are most visible.

I have a further hypothesis that venue mix, inventory practices, and hedging behavior can affect price discovery and inventory stress. That needs testing, not assertion. Nothing here supports claims that an exchange or market maker engages in B-booking, manipulation, or coordinated conduct without direct evidence.

The practical reason for the venue gate is simpler and testable: a candidate needs liquid enough perpetual access to form a visible short cohort and enough cross-venue activity for the market structure to be actionable and observable. A labelled Binance, Bitget, or Gate deposit can be important, but transfer target alone is not a substitute for actual trading/venue evidence.

## The signal stack

No individual field is sufficient. I treat the signal as a conjunction of imperfect observations, ranked for review rather than treated as a binary verdict.

### A. Ownership and float evidence

Required questions:

- Is there a reliable contract address and chain attribution?
- What are raw top-10, top-50, and top-100 holder shares?
- What are the adjusted holder shares after removing/discounting labeled exchanges, bridges, wrappers, burn wallets, liquidity pools, treasury/vesting/staking addresses, and protocol contracts?
- Is the remaining concentration explained by transparent lockups, or is it opaque?
- Is float low relative to FDV/market cap and to the expected size of derivatives turnover?
- Does the token have a long enough history to distinguish a newly launched asset from a dormant structure?

Positive evidence is high adjusted concentration, low effective float, a high FDV relative to liquid float, and wallet ownership that is unusually centralized after false-positive filtering. Missing holder data is not a pass; it is an evidence gap.

### B. On-chain wallet-to-CEX flow

The scanner tracks large token movements from relevant/whale wallets into labeled exchange wallets, especially Binance, Bitget, and Gate, over configurable lookback windows. The threshold must be variable because a transfer of 20,000 tokens can be meaningful in a low-float asset while 500,000 tokens may be irrelevant in another.

The useful fields are not only token amount:

- Token amount and USD notional at transfer time.
- Sender wallet identity/category and whether it is a large or concentrated holder.
- Destination exchange and destination wallet label confidence.
- Number of distinct whale senders and transfers.
- Time since transfer and clustering of transfers.
- Deposit notional versus visible ask depth and versus 24-hour turnover.
- Whether the flow occurs before ignition, during a trend, or after verticality.

Interpretation is deliberately conditional. A CEX deposit can mean inventory provisioning, a market-making operation, a forthcoming distribution, collateral movement, or a simple transfer. It is not inherently bullish or bearish. In a low-float venue-stress setup it may signal that inventory has reached the venue where price discovery and derivatives stress are occurring; after a vertical move, it can instead be an exit/distribution warning.

The current scanner calls this **concentration-gated CEX flow**: CEX movements are given greater weight when the sender/control-plane evidence and token concentration gate are present. Explorer HTTP 403 errors or incomplete holder endpoints make the result inconclusive, not clean/no-flow.

### C. Perpetual positioning: short-account level and rate of change

Core readings:

- `short_account_pct`: estimated share of accounts that are short in Binance's account-ratio dataset.
- `short_account_previous_1h_pct`: prior one-hour reading.
- `short_account_roc_1h_pp`: absolute one-hour percentage-point change.
- `short_account_roc_1h_pct`: one-hour relative percentage change.
- Multi-period maximum short-account changes where available.

The desired early condition is not merely "many shorts." It is a **persistent or increasing short cohort while the asset is holding or advancing**. High short accounts plus rising price is more interesting than high short accounts during a breakdown. A growing short percentage while price trends up can mean potential squeeze fuel is accumulating, although it may also reflect hedging, basis trades, or account-size distortion.

The exit/reduction condition is the opposite: when short accounts roll over and fall materially, fewer participants may remain to be forced into buying. This is treated as loss of fuel, not a declaration that price must immediately reverse.

### D. Open interest

Open interest is watched for changes in participation and leverage. Useful states include:

- Price rising plus OI rising: new derivatives exposure is entering; this can support continuation but does not reveal whether it is new long or short exposure.
- Price rising plus high/rising short-account share: potentially constructive squeeze fuel if other structure is intact.
- Price rising while OI falls: may reflect short covering; it can be a squeeze in progress but may also indicate fuel is being consumed.
- Price falling plus OI rising: may indicate new shorts/longs but is not automatically a long setup.
- OI, funding, and volume peaking together after a large vertical move: a late/exhaustion warning rather than a fresh entry signal.

OI must be interpreted with price, funding, volume, and short-account change. It is not directional by itself.

### E. Funding

Funding is used as a sentiment/carry input, not a simplistic contrarian rule. A particularly interesting continuation profile observed by the operator is:

- Price is structurally trending or breaking higher.
- Funding is positive.
- Short-account percentage is high.
- Short-account percentage is still increasing or has recently built strongly.
- Price has not already entered a terminal vertical phase.

Positive funding alongside elevated short accounts can occur because funding is driven by aggregate perp pricing and positions, while account ratios count accounts rather than notional. It may reveal a market with small numerous shorts and larger long exposure, or a more complex mix. It should not be interpreted as a contradiction without examining the rest of the data.

Negative funding can also be consistent with a squeeze hypothesis in some cases, but the full context matters more than the sign. I would not treat either funding sign or a funding flip as sufficient on its own.

### F. Price, volume, and breakout structure

The price filter is designed to avoid buying a dormant chart solely because its cap table is concentrated. The scanner identifies breaks above or below arbitrary lookback highs/lows, with common windows such as 5D, 10D, 20D, 50D, 90D, 180D, and longer-history windows. The Discord commands accept flexible lookback days rather than fixed presets.

The preferred long behavior is:

- A quiet base, compression, or controlled grind rather than a fully extended blowoff.
- Breakout above a relevant prior high, ideally with multiple timeframe confirmation.
- Constructive close location and persistence above the breakout level rather than a one-candle wick.
- Volume and OI beginning to expand rather than already climaxing.
- Evidence that the token has not already had a large recent pump; the early-pump system currently seeks roughly 60 days of history/no-large-pump proof and penalizes large prior expansion.

Breakout is a timing confirmation. It does not repair a weak float thesis, nor does it make a late vertical move attractive.

### G. Liquidity and inventory stress

The scanner considers thin displayed liquidity, visible ask depth, turnover, and CEX-flow size. A deposit or forced buy flow matters most when it is large relative to available order-book depth and trading turnover. The mechanism is not "large transfer equals pump"; it is the interaction of inventory, shallow liquidity, derivatives positioning, and timing.

Thin liquidity is a double-edged condition. It can help an upside squeeze travel quickly, but it also makes entries, exits, stops, and position sizing more dangerous. Any expected edge must exceed spread, slippage, gaps, and inability to exit during disorderly conditions.

## How a candidate moves through review

### 1. Universe and discovery

Start with tokens that have Binance perpetual contracts, then retain those with supporting Bitget evidence and optionally Gate or labelled CEX flow. Traditional-finance proxy pairs are excluded from short-account trend scans because their positioning does not represent the intended crypto low-float universe.

Scan for low effective float, high adjusted concentration, relevant contract data, quiet history, and no major recent expansion. The first output is a watchlist, not an entry list.

### 2. Structural validation

For each candidate, validate contract/chain, holder source quality, adjusted concentration, supply/float data, venue evidence, transfer provenance, and liquidity. Log what is observed, what is inferred, and what is missing.

Candidates should be rejected or demoted when the concentration is entirely explained by benign storage, when venue support is absent, when data quality is poor, or when the price has already made the move the strategy was designed to catch.

### 3. Pre-ignition monitoring

Monitor the candidate before it is obvious:

- Are price, volume, and OI transitioning from quiet to rising?
- Is price holding a base or breaking a relevant high?
- Are short accounts elevated and/or increasing while price holds higher?
- Is funding consistent with an active derivatives market rather than a dead contract?
- Is there a fresh, concentration-gated transfer into a relevant exchange?
- Is the target venue showing meaningful activity relative to the rest of the market?

The live screens give these conditions labels such as sleeper watch, squeeze watch, flow-first watch, prime early squeeze, too late/fragile, and no edge. I treat those labels as ways to organize attention, not as automatic trade instructions.

### 4. Entry concept

The intended entry, if the research ever supports one, is early, small, and unlevered. I avoid leverage in the hypothesis because these assets can make extreme drawdowns and recoveries that mechanically liquidate both late shorts and leveraged longs. Any exposure would need to be small enough that a full loss does not force a decision under pressure.

The idea is not a prediction that the token is good. It is a test of whether several structural conditions coexist before the market becomes a vertical, obvious crowd event. There is no averaging-down premise. If the structure invalidates, the observation was wrong or early; adding risk does not repair it.

### 5. Position monitoring and exits

The key exit hypothesis is that short-account rollover can mark fading squeeze fuel. I would read the live short-account percentage and its one-hour change alongside OI, volume, funding, trend persistence, CEX wallet flow, and the degree of verticality.

Exit/reduction warnings include:

- Short-account percentage declines materially after a sustained build.
- Price becomes vertical or parabolic after the move is already obvious.
- OI, funding, and volume peak together.
- A relevant top/whale wallet deposits tokens to a CEX after the run.
- Breakout persistence fails or price loses structural levels.
- The current setup becomes dominated by late-entry/exhaustion penalties.

The current live close-monitor implementation can close a profitable Binance futures position when the one-hour short-account metric rolls over. Its default logic requires profit and triggers when **either** of the following is true:

- Relative short-account ROC is more negative than `-2.5%`; or
- Absolute short-account change is more negative than `-1.0 percentage point`.

This is a production implementation detail, not necessarily the final strategy rule. If the desired exit is strictly "more than 2.5% relative decline," the percentage-point fallback must be disabled or set to an intentionally unreachable threshold. A short-account decline is a fuel warning, not a guarantee of an immediate reversal, so it should be audited against actual exits before being made the sole exit mechanism.

The monitor uses an explicit live enablement guard and writes history and closed-trade CSVs. It should be treated as automation requiring continuous operational testing: API success, symbol normalization, order type, reduce-only behavior, data freshness, webhook health, and a reconciliation of actual exchange fills must all be verified.

## Historical archetypes used as references

These examples are pattern labels, not proof that the same cause drove each event.

| Archetype | Reference | Working fingerprint | Main lesson |
| --- | --- | --- | --- |
| RAVE-style cap-table reflexivity | RAVEUSDT, 18 April 2026 | Quiet base, apparent FDV/float asymmetry, thin liquidity, concentrated/control-plane concern, later forced-flow behavior | A vertical prior-high move can become a blowoff; do not chase a late spike or short simply because it looks fake. |
| LAB-style venue-inventory stress | LABUSDT, 11 May 2026 | Controlled float, target-venue inventory pressure, quiet-to-grind transition, thin displayed liquidity, violent repricing | CEX/holder proof plus breakout can create continuation, but deep drawdowns remain normal. |
| SIREN-style short-fuse compression | SIRENUSDT | Quiet tape, short/OI pressure, compression, pre-ignition structure | Compression without late chase heat is a better research state than post-impulse excitement. |
| RIVER-style runway breakout | RIVERUSDT | Range/high-break structure, room to prior extremes, venue support, unexhausted short/OI fuel | A breakout needs short fuel and holder/venue proof before promotion. |
| STO-style target-venue squeeze | STOUSDT | Target venue support, whale/control evidence, early timing, high-break confirmation | Target venue and concentration evidence matter, but weak data remains weak data. |

The repository's backfill work has explicitly recorded evidence gaps for several of these cases. Historical similarity is not a substitute for a complete event study.

## How the software is used

The software has three ways to look at the same work:

- A Streamlit dashboard for broad scan review, score decomposition, breakouts, correlation, CEX flow, holder data, and trend context.
- Discord slash commands and alert webhooks for rapid triage and monitoring.
- A proof archive and CSV outputs for later outcome measurement and rule refinement.

The operational layer includes thesis screens, CEX flow with adjustable thresholds and lookbacks, flexible high/low breakout searches, short-account rate-of-change rankings, BTC correlation, and RAVE/LAB-style structural matching. Dedicated hourly monitors exist for selected tokens, and the generic short-ROC close monitor accepts a ticker input.

The Discord/CSV output should always display both the live short-account percentage and its change. ROC without the level can be misleading: a 2% change from 10% and a 2% change from 70% describe different positioning contexts.

## What would change my mind

I would weaken or reject the hypothesis when:

- Adjusted concentration disappears after correctly classifying storage/custody wallets.
- Apparent low float is an artifact of bad circulating-supply data.
- The venue mix does not have meaningful tradeability or derivatives participation.
- CEX deposits consistently precede distribution rather than inventory stress/continuation.
- Short-account metrics do not add predictive value after controlling for price, volatility, liquidity, and token age.
- OI/funding/short-account combinations are common in failed candidates and not selectively enriched before winners.
- The breakout signal is just a generic momentum effect that performs similarly without the concentration/flow filters.
- Slippage, gaps, funding, and missed fills erase the observed gross edge.
- The position-close rule exits too early during successful trends or too late during reversals.

## Where the data can fail

- Explorer APIs can return HTTP 403, incomplete holder lists, stale labels, or rate-limit errors. A failed request is unknown, not evidence of no transfer or no concentration.
- Wallet labels can be wrong or incomplete. Exchange deposit ownership and sender identity are probabilistic.
- Account-ratio data measures account counts rather than notional and cannot expose actual liquidation levels.
- Exchange REST data can be delayed, aggregated, rate-limited, or unavailable during stress.
- OI, funding, and volume differ by venue and contract specification.
- Token supply, FDV, and circulating-float sources can be inaccurate or stale.
- Historical examples can suffer from survivorship bias and post-hoc pattern fitting.
- Backtests must use point-in-time data, correct listing ages, delisted symbols, realistic fees/funding/slippage, and the exact signals available at the decision time.
- Live execution has API, key, order, reduce-only, partial-fill, and reconciliation risk. The system should never assume a submitted order equals a completed close.

## Practical guardrails

1. Treat every signal as evidence with a confidence level, not a fact about intent.
2. Never use the strategy's belief that a move is manipulated as a reason to increase risk.
3. Avoid leverage in the intended implementation; these structures can produce extreme adverse excursions.
4. Do not average down by default.
5. Do not short solely because a token is expensive, concentrated, or has already risen sharply.
6. Do not chase a fully vertical move merely because it matches a historical example.
7. Size so that a full loss is survivable and does not force liquidation or revenge trading.
8. Separate discovery signals, entry triggers, continuation signals, and exit signals in the data store.
9. Record every candidate, including non-trades and failures, to measure false positives and missed winners.
10. Require human review before expanding automation or changing thresholds based on a small sample.

## What would convince me

The central question is whether a point-in-time combination of concentration, float, venue, flow, derivatives positioning, and timing improves on simpler baselines in a statistically and economically meaningful way.

The tests I would want are:

- Define a point-in-time universe of all Binance perpetual listings, including failures and delistings.
- Create feature snapshots at fixed intervals before and after a candidate is flagged.
- Compare the full signal stack against baselines: breakout only, volume/OI only, short-account change only, and random same-liquidity controls.
- Measure forward returns, maximum favorable excursion, maximum adverse excursion, time to peak, drawdown before peak, and liquidity-adjusted exit cost.
- Stratify by listing age, market cap/FDV, realized volatility, liquidity, BTC regime, venue mix, and token-chain source quality.
- Test whether CEX-flow data adds incremental predictive power after controlling for momentum and liquidity.
- Test whether high short-account level, rising short-account ROC, and subsequent roll-over have stable out-of-sample value.
- Test alternative exit rules: percentage ROC only, percentage-point only, persistence over multiple observations, hybrid trailing logic, and partial profit-taking.
- Include fees, funding, spread, partial fills, gaps, API delays, and a conservative slippage model.
- Use walk-forward validation and keep a final untouched out-of-sample period.
- Maintain a failure taxonomy: false concentration, no venue support, premature breakout, late chase, distribution flow, short fuel absent, data outage, and execution failure.

## How the pieces fit

At a high level, the workflow is straightforward:

1. Exchange, explorer, and market data enter the scanner orchestration layer.
2. Holder concentration and wallet-to-CEX flow enrich the market data.
3. Market-structure, short-squeeze, convexity, timing, archetype, and early-pump models score the rows.
4. Dashboard and Discord surfaces expose the ranked candidates and diagnostic evidence.
5. A proof archive stores alerts and later measures outcomes.

When coverage is weak, local caches and diagnostics should make the reason visible: a genuine negative finding, missing data, an API block, or a gate failure. I would rather see "inconclusive" than false certainty.

## Bottom line

The research programme is about **mechanically fragile market structures**, not a moral judgment about a token and not a conventional fundamental valuation. The hypothesis needs a controlled or opaque float, usable derivative venues, emerging flow and liquidity stress, persistent short-side fuel, and an early breakout/trend state that is not already exhausted. One distinctive test is to watch the short-account cohort itself: as that cohort covers, the potential forced-buying reservoir may be shrinking.

If there is an edge here, it will have to come from disciplined evidence combination, point-in-time validation, and risk control. The obvious ways to fool ourselves are treating incomplete data as confirmation, chasing verticality, confusing account ratios with actual exposure, and mistaking a plausible narrative for out-of-sample evidence.
