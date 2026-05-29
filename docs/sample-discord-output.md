# Sample Discord Output

These examples are representative text outputs for reviewers. Live values depend on scan mode, API availability, cache freshness, and configured thresholds.

## `/alpha`

```text
Alpha brief - venue-gated convex watchlist
Source: fresh Deep scan at 2026-05-16 15:40:00 UTC | Scan mode: Deep | Updated: 2026-05-16 15:40:00 UTC
Venue gate: Binance perp + Bitget/Gate venue support (any visible share or Bitget/Gate transfer target)
Ranking blends structural edge, timing quality, wallet-to-CEX flow, scanner score, and short-account fuel.

Candidates: /FLOWUSDT /RAVEUSDT /PLAYUSDT

FLOWUSDT | brief 82.7 | terminal 79 | timing 68 | CEX 88 | shorts 63.0% | Triggering
  evidence: CEX flow 88 | float control 84 | terminal 79 | perp fuel 75 | timing 68
  next: recheck target-exchange balances, OI expansion, and whether price absorbs or rejects added venue inventory.

RAVEUSDT | brief 74.1 | terminal 81 | timing 58 | CEX 36 | shorts 68.5% | Coiling
  evidence: terminal 81 | perp fuel 78 | float control 77 | timing 58 | runway 55
  next: recheck short-account pressure, OI, funding, and reclaim or failed-reclaim behavior on the next scan.
```

## `/precrime min_tokens:20000`

```text
Pre-activity crime-pump radar
Source: fresh Deep scan at 2026-05-28 09:20:00 UTC | Transfer floor: 20.00K tokens | Lookback: 24h | Target CEX: Binance, Gate.io, Bitget | Min latent score: 58 | Target flow required: False | Quiet required: True | Behaviour gate required: True
Matches: 2 | Target-flow rows: 1 | Quiet-gated rows: 2 | Read: structural-risk evidence, not trade instruction.

Candidates: /SLEEPUSDT /COILUSDT

/SLEEPUSDT | Stealth inventory setup | latent 79/100 | target CEX flow 92/100 | CEX-tell 92 Binance, Gate.io 2tx max 240.00K | control 91 | float 86 | thin-book 94 | quiet 82 heat 12 | top10 90.0%, top100 99.0% | shorts 63.0% | anchor LABUSDT 2026-05-11 | next: watch for absorption, OI expansion, and first volume lift while price remains below chase heat
/COILUSDT | Control-plane watch | latent 64/100 | holder control 88/100 | CEX-tell 43 no target flow 0tx max n/a | control 88 | float 79 | thin-book 81 | quiet 90 heat 6 | top10 86.0%, top100 98.7% | shorts 58.2% | next: verify target CEX flow or venue-inventory tell before treating this as live
```

## `/ravelab min_tokens:20000`

```text
Strict RAVE/LAB crime-pump early radar
Source: fresh Deep scan at 2026-05-28 09:22:00 UTC | Transfer floor: 20.00K tokens | Lookback: 24h | Style: both | Min early score: 60 | Min RAVE/LAB archetype: 0 | Whale gate: >= 90.0% | Squeeze gate: >= 50 | Binance+Bitget required: True | Dormant 2m required: True | Quiet required: True | Target flow required: False
Anchors: RAVEUSDT 2026-04-18 = cap-table reflexivity; LABUSDT 2026-05-11 = venue-inventory stress.
Matches: 2 | RAVE-like: 1 | LAB-like: 1 | Mixed: 0 | Target-flow rows: 1 | Read: historical-analogue screen, not trade instruction.
All shown rows passed whale >= 90.0%, Binance+Bitget, dormant2m, squeeze >= 50.

Candidates: /CAPUSDT /LABXUSDT

/CAPUSDT | RAVE-like | early 73/100 | RAVE 58 LAB 25 | gates whale Y venue Y dormant2m Y squeeze Y | venues Bn Y/Bg Y/Gate N | whale 99.8% (t10 94.0%, t100 99.8%) | squeeze 62 shorts 54.0% | breakout 18 | CEX no target flow 0tx max n/a | control 100 float 88 | quiet 85 heat 0 | dashboard 0 latent 66 | anchor RAVEUSDT 2026-04-18 | next: watch 1D-5D highs, first volume lift, and OI expansion without chase heat
/LABXUSDT | LAB-like | early 82/100 | RAVE 56 LAB 88 | gates whale Y venue Y dormant2m Y squeeze Y | venues Bn Y/Bg Y/Gate Y | whale 99.2% (t10 91.0%, t100 99.2%) | squeeze 58 shorts 51.0% | breakout 18 | CEX Binance, Gate.io 2tx max 360.00K | control 99 float 84 | quiet 86 heat 0 | dashboard 0 latent 92 | anchor LABUSDT 2026-05-11 | next: watch for absorption after target-CEX inventory movement and first perp response
```

## `/corr threshold:0.5`

```text
BTC low-correlation screen
Source: fresh Deep scan at 2026-05-17 10:15:00 UTC | Scan mode: Deep | Updated: 2026-05-17 10:15:00 UTC
Threshold: corr <= 0.50 | Target window: max 180d; younger symbols use available overlap.

Matches: 3

/YOUNGUSDT | corr -0.820 | used 37d (max available) | shorts 61.2% | 24h 4.5%
/INVERSEUSDT | corr -0.610 | used 180d | shorts 54.0% | 24h -2.1%
/WEAKPOSUSDT | corr 0.420 | used 180d | shorts 51.5% | 24h 1.1%
```

## `/high days:20D`

```text
20D high breakout screen
Source: fresh Deep scan at 2026-05-27 10:15:00 UTC | Scan mode: Deep | Updated: 2026-05-27 10:15:00 UTC
Filter: `broke_high_20d` is true | Windows: any 1D-1499D window; common dashboard columns: 5D, 20D, 90D, 180D

Matches: 2

/FASTUSDT | broke 20D high | 24h +8.2% | price 0.12 | breaks H2/L0 | shorts 61.0%
/SLOWUSDT | broke 20D high | 24h +2.1% | breaks H1/L0
```

## `/low days:90D`

```text
90D low breakout screen
Source: fresh Deep scan at 2026-05-27 10:15:00 UTC | Scan mode: Deep | Updated: 2026-05-27 10:15:00 UTC
Filter: `broke_low_90d` is true | Windows: any 1D-1499D window; common dashboard columns: 5D, 20D, 90D, 180D

Matches: 2

/LOWERUSDT | broke 90D low | 24h -9.5% | breaks H0/L2
/BOUNCEUSDT | broke 90D low | 24h -2.0% | breaks H0/L1
```

## `/funding side:both limit:3`

```text
Funding carry leaderboard
Source: live Binance futures premiumIndex at 2026-05-21 13:20:00 UTC
Read: positive funding = longs pay shorts; negative funding = shorts pay longs. Funding is current/last premiumIndex rate.
Side: both | Limit per side: 3 | Account-ratio period: 1h | Min abs funding: 0.0000%

Short-carry candidates (positive funding; shorts receive)
/HOTUSDT | funding +0.1200%/8h | ann +131.4% | mark 0.0123 | 24h +4.2% | vol 12.30M | shorts 60.0% | longs 40.0% | next 2.0h

Long-carry candidates (negative funding; longs receive)
/COLDUSDT | funding -0.0800%/8h | ann -87.6% | mark 0.00001234 | 24h -2.5% | vol 9.90M | shorts 30.0% | longs 70.0% | next 1.0h
```

## `/setupscore min_tokens:20000 strict:true`

```text
Insider-structure setup score
Source: fresh Deep scan at 2026-05-21 13:30:00 UTC | Transfer floor: 20.00K tokens | Lookback: 24h | Target CEX: Binance, Gate.io, Bitget | Gates: top100 >= 90.0% or top10 >= 80.0%, shorts >= 50.0%, low-float/FDV, not-late structure | Strict: True
Matches: 2 | Read: rank-order evidence, not an execution instruction.

Candidates: /PRIMEUSDT /FLOWUSDT

/PRIMEUSDT | PASS | score 86 | flow 92 Bitget, GateIO 3tx max 12.00M | whale t10 91.0% | t100 99.0% | shorts 64.0% | float 82 | FDV/MC 8.0x | structure 80 | OI 4.2%
```

## `/pumpwatch min_tokens:20000`

```text
Early pump watch
Source: fresh Deep scan at 2026-05-21 13:30:00 UTC | Transfer floor: 20.00K tokens | Lookback: 24h | Target CEX: Binance, Gate.io, Bitget | Min radar: 55 | Target flow required: False | Venue gate: Binance/Bitget/Gate support or confirmed target transfer
Matches: 3 | Confirmed target-flow rows: 2 | Read: rank-order evidence, not an execution instruction.

Candidates: /PRIMEUSDT /STOUSDT /SIRENUSDT

/PRIMEUSDT | Prime early squeeze | radar 89/100 | target CEX flow 92/100 | flow 92 Bitget, GateIO 3tx max 12.00M | top10 91.0%, top100 99.0% | shorts 64.0% | float 82 | timing 78 | not-late 95 | LAB-style venue-inventory stress | next: check whether deposited inventory is absorbed while OI/volume expand and rejection wicks stay muted
/STOUSDT | Flow-first watch | radar 76/100 | target CEX flow 74/100 | flow 74 Binance 1tx max 3.20M | top10 84.0%, top100 96.0% | shorts 58.0% | float 70 | timing 64 | not-late 88 | STO-style target-venue squeeze
```

## `/flowproof symbol:PRIMEUSDT min_tokens:20000`

```text
PRIMEUSDT flow proof
Verdict: VERIFIED target-CEX transfer evidence
Source: fresh Deep scan at 2026-05-21 13:30:00 UTC | Floor: 20.00K tokens | Lookback: 24h
Read: only rows with count > 0, largest transfer above floor, and a labelled destination are treated as confirmed.

Targets: Bitget, GateIO
Transfers: 3
Total token amount: 26.00M
Largest transfer: 12.00M
Top tx/hash: 0xprime
Flow source: token_transfer_api
Concentration gate: top10 91.0% / top100 99.0%
```

## `/whales min_pct:90 bucket:top100`

```text
Whale dominance ranking
Source: computed holder composition (42 rows, 3 skipped) from contract hints | Threshold: >= 90.0% | Bucket: top100 | Read: observed contract-holder concentration, not proof of control or native-chain global supply.
Matches: 18 | Showing: 3 | Hidden: 15

Candidates: /MEGAUSDT /WHALEUSDT /FLOWUSDT

/MEGAUSDT | top100 99.4% | top10 91.0% | holders 120 | shorts 63.2% | terminal 82 | CEX 72 | chain ethereum
/WHALEUSDT | top100 96.8% | top10 74.0% | holders 420 | shorts 58.4% | terminal 61 | CEX 30 | chain base
/FLOWUSDT | top100 94.1% | top10 82.5% | holders 880 | shorts 55.0% | terminal 70 | CEX 88 | chain bsc
... 15 more match(es) hidden; raise limit to inspect more.
```

## Main Alert Card

```text
/FLOWUSDT

Convex Score: 86/100
Structure: High short pressure + rising OI + thin upside liquidity
Convex thesis: concentrated holder structure plus fresh CEX-flow creates a venue-inventory stress window; validate against OI and price absorption.
Evidence stack: CEX flow 88 | float control 91 | terminal 78 | timing 64 | perp fuel 63
Perp positioning: short accounts 63.0% | long accounts 37.0% | L/S acct 0.59 | OI change +2.1%
Recent CEX flow: score 88/100 | 3 large deposit(s) | Bitget | top10 91.0% / top100 99.0% | 2.50M tokens
Why flagged: scanner score 86/100 + 63.0% short-account pressure + concentration-gated CEX-flow signal
Observed trigger: short crowd remains crowded while OI holds or expands; reclaim pressure can create reflexive conditions.
Next check: recheck target-exchange balances, OI expansion, and whether price absorbs or rejects added venue inventory.
Invalidation: OI contracts, short crowd normalizes, price fails to reclaim, and volume fades.
Liquidity warning: recent concentration-gated CEX-flow signal; visible depth can change quickly around stress.
Risk level: High
Failure condition: OI contracts, short pressure unwinds, reclaim fails, and volume fades across the next scan window.
Structure remains relevant while: higher lows continue while short pressure stays elevated and OI/volume expand without a liquidation flush.
Research constraint: user owns entries, sizing, stops, and execution
Principle: small losses; stay exposed only while structure remains intact
```

## `/cexflow min_tokens:20000`

```text
Wallet-to-CEX flow monitor
The highest-signal read is concentrated holder inventory moving into labelled exchange wallets.
Source: fresh Deep scan at 2026-05-16 15:40:00 UTC | CEX min transfer 20000 tokens | Gate: top10 >= 80% or top100 >= 90% | Min transfer: 20.00K tokens | Lookback: 24h
Venue gate: Binance perp + Bitget/Gate venue support (any visible share or Bitget/Gate transfer target)
Flow rows before venue gate: 1 | After venue gate: 1
Coverage: scan rows 168 | contract hints 42 | precomputed concentration rows 31 | precomputed gate pass 12
CEX-flow attempts 12 | no-transfer rows 8 | gate-not-met rows 0 | errors 3 | raw flow 1
Status: verified labelled CEX-flow rows exist; venue gate decides whether they appear in `/cexflow`.

Candidates: /FLOWUSDT

/FLOWUSDT
CEX Flow Score: 88/100 | Risk: High
Evidence: Concentration-gated wallet-to-CEX flow: 3 large transfer(s) into Bitget; total 2.50M tokens; largest 1.20M; notional $750.00K; total 2.50% of supply; top10 91.0% / top100 99.0%.
Inventory stress: venue-inventory stress 72/100; total notional $750.00K; 240.0% of visible 1% ask depth.
Venue-flow read: Token inventory moved from non-CEX wallets into labelled exchange wallets after the concentration gate was met. Treat this as venue-flow and distribution-risk evidence, not a conclusion about intent.
Next check: Watch whether CEX balances keep rising, OI/volume expands, and price absorbs or rejects the added venue inventory.
Source: https://api.etherscan.io/v2/api?chainid=8453&module=account&action=tokentx&contractaddress=0x...
```

## `/cexdiag min_tokens:1000 require_venue_gate:false symbol_limit:25`

```text
CEX-flow scan diagnostics
Source: fresh Deep scan at 2026-05-16 15:42:00 UTC | CEX min transfer 1000 tokens | Gate: top10 >= 80% or top100 >= 90% | Min transfer: 1.00K tokens | Lookback: 24h | Venue gate: disabled for this command
Flow rows before venue gate: 0 | After venue gate: 0
Coverage: scan rows 168 | contract hints 42 | precomputed concentration rows 31 | precomputed gate pass 12
CEX-flow attempts 12 | no-transfer rows 9 | gate-not-met rows 0 | errors 3 | raw flow 0
Status: explorer blocked 2 CEX-flow attempts with HTTP 403; API fallback/label coverage decides whether zero raw flow is conclusive.
Top CEX-flow errors: advanced filter HTTP 403; token-transfer API fallback found no labelled CEX destination matches x2; holder composition failed: timeout x1
CEX-flow source paths: advanced_filter_blocked_api_fallback x2; holder_gate x9

No verified labelled CEX token-transfer rows were produced because explorer requests were blocked and API fallback could not label the destinations. Attempted-symbol rows are query attempts at the requested transfer floor, not confirmed transfers.

Attempted symbols (not confirmed transfers unless status starts FLOW):
/FLOWUSDT | blocked/error: advanced filter HTTP 403; token-transfer API fallback found no labelled CEX destination matches | API fallback reached token transfers; no labelled CEX destination matched | top10 91.0% / top100 99.0% | query URL available
/MICROUSDT | FLOW 67/100 -> Bitget | 2 tx | total 75.00K tokens | max 50.00K | top10 92.0% / top100 96.0% | query URL available
/SLOWUSDT | checked: no labelled CEX transfer met threshold/lookback | top10 88.0% / top100 94.0% | query URL available

Read: zero raw flow means no verified labelled CEX-transfer rows were produced.
When HTTP 403 dominates, the scanner tries Etherscan V2 token-transfer APIs; label coverage then becomes the next bottleneck.
Blocked attempted-symbol rows are query attempts at the requested transfer floor, not confirmed transfers.
Use `/flowcoin symbol:<symbol>` for single-coin detail/query URL and `/flowhealth` for API-key/address-label coverage.
```

## `/earlyflow`

```text
Early wallet-to-CEX flow sweep
The highest-signal read is concentrated holder inventory moving into labelled exchange wallets.
Source: fresh Deep scan at 2026-05-16 15:45:00 UTC | CEX min transfer 20000 tokens | Gate: top10 >= 80% or top100 >= 90% | Min transfer: 20.00K tokens | Lookback: 24h
Venue gate: Binance perp + Bitget/Gate venue support (any visible share or Bitget/Gate transfer target)
Flow rows before venue gate: 1 | After venue gate: 1
Coverage: scan rows 168 | contract hints 42 | precomputed concentration rows 31 | precomputed gate pass 12
CEX-flow attempts 12 | no-transfer rows 8 | gate-not-met rows 0 | errors 3 | raw flow 1
Status: verified labelled CEX-flow rows exist; venue gate decides whether they appear in `/cexflow`.

Candidates: /MICROUSDT

/MICROUSDT
CEX Flow Score: 52/100 | Risk: Elevated
Evidence: Concentration-gated wallet-to-CEX flow: 1 large transfer(s) into Gate; total 25.00K tokens; largest 25.00K; top10 91.0% / top100 99.0%.
Venue-flow read: Token inventory moved from non-CEX wallets into labelled exchange wallets after the concentration gate was met. Treat this as venue-flow and distribution-risk evidence, not a conclusion about intent.
Next check: Watch whether CEX balances keep rising, OI/volume expands, and price absorbs or rejects the added venue inventory.
```

## `/flowstress min_tokens:20000`

```text
CEX inventory-stress monitor
Source: fresh Deep scan at 2026-05-16 15:47:00 UTC | Min transfer: 20.00K tokens | Lookback: 24h | Venue gate: Binance perp + Bitget/Gate venue support (any visible share or Bitget/Gate transfer target)
Inventory-stress rows before venue gate: 2 | After venue gate: 1

Candidates: /FLOWUSDT

/FLOWUSDT | stress 72/100 | flow 88/100 | Bitget | notional 750.00K | deposits/ask 240.0% | source token_transfer_api
  venue-inventory stress 72/100; total notional $750.00K; 240.0% of visible 1% ask depth
```

## `/flowblocked min_tokens:20000`

```text
CEX-flow blocked/error rows
Source: fresh Deep scan at 2026-05-16 15:48:00 UTC | Min transfer: 20.00K tokens | Lookback: 24h
Blocked/error rows: 2

/BLOCKEDUSDT | advanced filter HTTP 403; token-transfer API fallback found no labelled CEX destination matches | source advanced_filter_blocked_api_fallback
  https://api.etherscan.io/v2/api?chainid=8453&module=account&action=tokentx&contractaddress=0x...

Read: these are data-source failures or no labelled API matches, not proof that CEX flow is absent.
```

## `/flowhealth min_tokens:20000`

```text
CEX-flow scan diagnostics
Source: fresh Deep scan at 2026-05-16 15:49:00 UTC | CEX min transfer 20000 tokens | Gate: top10 >= 80% or top100 >= 90% | Min transfer: 20.00K tokens | Lookback: 24h | Venue gate: disabled for this command
Flow rows before venue gate: 1 | After venue gate: 1
Coverage: scan rows 168 | contract hints 42 | precomputed concentration rows 31 | precomputed gate pass 12
CEX-flow attempts 12 | no-transfer rows 8 | gate-not-met rows 0 | errors 2 | raw flow 1
CEX-flow source paths: token_transfer_api x1; advanced_filter_blocked_api_fallback x2

API fallback readiness:
- arbitrum: no key (ETHERSCAN_V2_API_KEY or ETHERSCAN_API_KEY or ARBISCAN_API_KEY)
- base: key present (ETHERSCAN_V2_API_KEY or ETHERSCAN_API_KEY or BASESCAN_API_KEY)
- bsc: key present (ETHERSCAN_V2_API_KEY or ETHERSCAN_API_KEY or BSCSCAN_API_KEY)
- ethereum: key present (ETHERSCAN_V2_API_KEY or ETHERSCAN_API_KEY)
- optimism: no key (ETHERSCAN_V2_API_KEY or ETHERSCAN_API_KEY or OPTIMISTIC_ETHERSCAN_API_KEY)
- polygon: no key (ETHERSCAN_V2_API_KEY or ETHERSCAN_API_KEY or POLYGONSCAN_API_KEY)
- CEX address labels loaded: 14
- Configure CEX_ADDRESS_LABELS or CEX_ADDRESS_BOOK_FILE to classify API token-transfer destinations without scraping explorer labels.
```

## `/sethflow min_tokens:10000000`

```text
Seth flow checklist
Source: fresh Deep scan at 2026-05-16 15:50:00 UTC | Confirmed target-CEX flow only | Min transfer: >= 10.00M tokens | Lookback: 24h | Target CEX: Binance, Gate.io, Bitget | Whale gate: top10 >= 80% or top100 >= 90% | Short gate: >= 50.0% | Structure gate: dormant/early only
Confirmed target-CEX flow rows: 3 | Whale+short+dormant pass: 1

Checklist: 1 flow -> 2 whale dominated -> 3 >50% short accounts -> 4 dormant/early, not already wild -> 5 research state.

Candidates: /FLOWUSDT

/FLOWUSDT | RESEARCH: dormant candidate; wait for absorption/reclaim evidence | flow 88/100 | 2 tx into Bitget | total 22.00M, max 12.00M | top10 91.0%, top100 99.0% | shorts 63.0% | structure dormant candidate
  chart gate: range 8.0%, 24h 2.0%, setup 78 | not a trade instruction; validate OI/volume and price absorption.
```

## `/convex_scoreboard`

```text
Weekly scanner scoreboard
Flags reviewed: 84
Median max upside after flag: 8.7%
Median max drawdown after flag: -4.2%
Reached +20%: 18
Reached +50%: 6
Reached 2x: 2
Best alert source: terminal_timing
Most common invalidation: OI/volume failed to confirm
```
