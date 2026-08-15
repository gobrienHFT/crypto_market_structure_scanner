# Reflexivity Casebook

This is a neutral research record. Each section separates observed facts, inferences, hypotheses, and unavailable evidence. Historical examples are anchors for falsifiable tests, not promises or trade instructions.

## RAVEUSDT | 2026-04-18

**Archetype:** historical anchor: vertical repricing and unwind

### OBSERVED FACT
- The supplied chart identifies a Binance RAVE/USDT perpetual daily chart.
- The chart shows a quiet sub-dollar region followed by a very large upward wick and a sharp subsequent retracement.

### INFERENCE
- The price path is consistent with a thin-liquidity, reflexive repricing episode.
- The episode is useful as a shape anchor for testing entry and exhaustion rules, not as proof of a repeatable cause.

### HYPOTHESIS
- A concentrated or constrained spot supply could have amplified marginal perp demand and forced buying.
- Crowded retail short accounts may have supplied fuel, but this must be tested against OI, top-trader positioning, and account-level outcomes.

### UNAVAILABLE
- Point-in-time holder classification, adjusted float, labelled CEX flow, venue depth, funding, OI, and short-account observations are not reconstructed by the screenshots alone.
- Exact entry timestamp, fills, liquidation tape, and a no-lookahead event-study row are unavailable until a frozen source snapshot is imported.

### PHASE REPLAY

#### BEFORE
- A point-in-time ownership/float and derivatives baseline is not present in the supplied chart.
- The visible chart suggests a quieter lower-price regime before the large repricing.

#### DETECTION
- A historical detection row cannot be reconstructed from the screenshot alone; volume, OI, short-account, funding, and venue timestamps remain unavailable.

#### ACTIVE MOVE
- The daily chart records a very large upside wick followed by a sharp retracement.
- Whether short covering or liquidation contributed is an unverified hypothesis.

#### EXHAUSTION
- The retracement is observed; the specific fuel-reset sequence, holder CEX flows, and liquidation tape are unavailable.

**Sources:** user-supplied chart reference; historical_examples.py

## LABUSDT | 2026-05-11

**Archetype:** historical anchor: venue/float stress and continuation

### OBSERVED FACT
- The supplied chart identifies a Binance LAB/USDT perpetual daily chart dated May 11, 2026.
- The chart shows a long low-price base, a sharp repricing, a large upside wick, and continued high-volatility trading afterward.

### INFERENCE
- The episode is consistent with a constrained-liquidity repricing where a large move can coexist with deep intratrend drawdowns.
- A high-volume trigger would be more informative when paired with contemporaneous OI, account crowding, venue, and holder evidence.

### HYPOTHESIS
- Venue inventory and concentrated effective float may have amplified the impact of forced flows.
- Positive funding can represent longs paying shorts while still coexisting with a long squeeze thesis; funding sign must not be used as a causal label.

### UNAVAILABLE
- The chart does not establish wallet intent, actual short notional, liquidation volume, or whether observed holders were controllable supply.
- The exact point-in-time market and on-chain evidence required for a causal test is unavailable in the chart reference.

### PHASE REPLAY

#### BEFORE
- The chart shows an extended low-price/base regime before the May 11, 2026 repricing.
- Normal prior volume, OI, adjusted float, and account positioning are not available from the chart.

#### DETECTION
- The sharp price/volume change is visually observable, but the exact point-in-time detection threshold cannot be recovered from the screenshot.

#### ACTIVE MOVE
- The chart shows a large upside move with high volatility and continued elevated trading afterward.
- Venue inventory stress and short-clientele fuel remain hypotheses until source snapshots are replayed.

#### EXHAUSTION
- A later stabilization/repricing path is visible, but short-share collapse, OI reset, funding extreme, and CEX inflow evidence are unavailable.

**Sources:** user-supplied chart reference; historical_examples.py; event_study.py
