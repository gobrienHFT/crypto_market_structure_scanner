# Reflexivity Casebook

RAVE and LAB are useful because the charts make the shape of the question easy
to see: a quiet or compressed market, a sharp repricing, and then a period in
which continuation and exhaustion are both possible. They are examples to
study, not proof that the same mechanism caused either move.

For each case I keep four things apart: what the supplied material actually
shows, what I think it may indicate, what would need to be tested, and what is
still unavailable.

## RAVEUSDT | 2026-04-18

**Working pattern:** vertical repricing followed by an unwind.

### What is directly visible

- The supplied chart identifies a Binance RAVE/USDT perpetual daily chart.
- It shows a quiet sub-dollar region followed by a very large upward wick and a sharp subsequent retracement.

### What it may indicate

- The price path is consistent with a thin-liquidity, reflexive repricing episode.
- It is a useful shape for testing entry and exhaustion rules, but the chart does not establish a repeatable cause.

### What I would want to test

- A concentrated or constrained spot supply may have amplified marginal perp demand and forced buying.
- A crowded short-account cohort may have supplied fuel, but that needs to be checked against OI, top-trader positioning, and account-level outcomes.

### What the chart cannot tell us

- Point-in-time holder classification, adjusted float, labelled CEX flow, venue depth, funding, OI, and short-account observations are not reconstructed by the screenshots alone.
- Exact entry time, fills, liquidation tape, and a no-lookahead event-study row are unavailable until a frozen source snapshot is imported.

### Phase notes

#### Before

- There is no point-in-time ownership/float or derivatives baseline in the supplied chart.
- The visible chart suggests a quieter lower-price regime before the large repricing.

#### Detection

- A historical detection row cannot be reconstructed from the screenshot alone. Volume, OI, short-account, funding, and venue timestamps are missing.

#### Active move

- The daily chart records a very large upside wick followed by a sharp retracement.
- Whether short covering or liquidation contributed remains an unverified hypothesis.

#### Exhaustion

- The retracement is observed; the specific fuel-reset sequence, holder CEX flows, and liquidation tape are not.

**Sources:** user-supplied chart reference; historical_examples.py

## LABUSDT | 2026-05-11

**Working pattern:** venue/float stress followed by continuation and high volatility.

### What is directly visible

- The supplied chart identifies a Binance LAB/USDT perpetual daily chart dated May 11, 2026.
- It shows a long low-price base, a sharp repricing, a large upside wick, and continued high-volatility trading afterward.

### What it may indicate

- The episode is consistent with a constrained-liquidity repricing in which a large move can coexist with deep intratrend drawdowns.
- A high-volume trigger would be more informative when paired with contemporaneous OI, account crowding, venue, and holder evidence.

### What I would want to test

- Venue inventory and concentrated effective float may have amplified the impact of forced flows.
- Positive funding can mean longs paid shorts while still coexisting with a long-squeeze hypothesis. Funding sign needs context; it is not a causal label.

### What the chart cannot tell us

- The chart does not establish wallet intent, actual short notional, liquidation volume, or whether observed holders represented controllable supply.
- The point-in-time market and on-chain evidence needed for a causal test is not available in the chart reference.

### Phase notes

#### Before

- The chart shows an extended low-price/base regime before the May 11, 2026 repricing.
- Normal prior volume, OI, adjusted float, and account positioning are not available from the chart.

#### Detection

- The sharp price/volume change is visible, but the exact point-in-time detection threshold cannot be recovered from the screenshot.

#### Active move

- The chart shows a large upside move with high volatility and continued elevated trading afterward.
- Venue inventory stress and short-clientele fuel remain hypotheses until source snapshots are replayed.

#### Exhaustion

- A later stabilization/repricing path is visible, but short-share collapse, OI reset, funding extreme, and CEX inflow evidence are unavailable.

**Sources:** user-supplied chart reference; historical_examples.py; event_study.py
