# Discord Alpha Workflow

This repo treats Discord as the live operating surface for the scanner. The dashboard is useful for investigation, but Discord is where the system should quickly answer:

- What deserves attention now?
- Why did it flag?
- What would confirm or invalidate it?
- Did prior alerts actually work?

The integration is intentionally research-first. It avoids trade-call language and keeps execution responsibility outside the bot.

## Signal Stack

The highest-quality Discord flags usually combine several of these:

- `venue gate`: Binance perp plus Bitget or Gate venue support, or Bitget/Gate as the CEX-flow target
- `float control`: top-holder concentration, low float score, centralized ownership score, opaque supply score
- `perp fuel`: short-account crowding, short build, liquidation fuel, OI expansion
- `ignition`: volume/trade-count expansion, reclaim quality, breakout context
- `CEX flow`: large transfers from non-CEX wallets into labelled exchange wallets after holder concentration gates
- `timing`: coiling or triggering state without late-stage fragility
- `proof`: archived alert records with later outcome refreshes

No single component is treated as proof. The point is to build a fast evidence stack and then measure the result.

## Command Loop

Recommended live workflow:

```text
/alpha
/precrime min_tokens:20000
/ravelab min_tokens:20000
/pumpwatch min_tokens:20000
/setupscore min_tokens:20000 strict:true
/flowproof symbol:PLAYUSDT min_tokens:20000
/coincheck symbol:PLAYUSDT min_tokens:20000
/cextargets min_tokens:20000
/floattrap min_score:60
/squeezeready min_short_pct:50
/funding side:both limit:10
/whales min_pct:90 bucket:top100
/cexflow min_tokens:20000
/cexdiag min_tokens:1000 require_venue_gate:false symbol_limit:25
/earlyflow
/flowcoin symbol:PLAYUSDT min_tokens:20000
/flowstress min_tokens:20000
/flowblocked min_tokens:20000
/flowhealth min_tokens:20000
/sethflow min_tokens:10000000
/high days:20D
/low days:20D
/terminal
/timing
/corr threshold:0.5
/coin <symbol>
/dossier <symbol>
/convex_scoreboard
```

Use `/alpha` as the triage queue. It blends structure, timing, CEX-flow, scanner score, and short-account fuel into a compact venue-gated watchlist.

Use `/precrime` before `/pumpwatch` when you specifically want the quiet pre-activity version of the thesis. It rewards holder/control concentration, low-float/high-FDV structure, Binance/Bitget/Gate inventory tells, short-fuse perp positioning, and thin visible books, but it penalizes names that already have breakout, volume, CMC-mover, or high-return chase heat. Keep `require_quiet:true` when hunting before the crowd notices; use `require_target_flow:true` when you only want confirmed labelled CEX-transfer rows.

Historical anchors: `RAVEUSDT` on `2026-04-18` is the RAVE-style cap-table reflexivity example; `LABUSDT` on `2026-05-11` is the LAB-style venue-inventory stress example. These are used as pattern references for review/backtesting context, not as claims about current intent.

Use `/ravelab` when you specifically want the strict early version of the thesis. By default it requires observed 90%+ whale/top-holder concentration, explicit Binance plus Bitget venue evidence, a two-month no-chase/dormancy gate, and short-squeeze/perp-fuel priming before it ranks anything. RAVE-like rows lean cap-table concentration, hidden/opaque float, and low-float FDV gaps; LAB-like rows lean controlled float plus labelled Binance/Bitget/Gate flow or venue-inventory stress. Use `style:rave` or `style:lab` to focus the screen, and only relax `require_binance_bitget` or `require_dormant_2m` when diagnosing near misses.

Use `/pumpwatch` as the fastest catch board. It does not force every row to have confirmed transfer evidence by default; it rank-orders target-CEX flow, whale/control, low float, short-squeeze fuel, timing, venue support, archetype match, and not-late risk into one watch state. Set `require_target_flow:true` when you only want verified Binance/Gate/Bitget transfer rows.

Use `/setupscore` as the strict full-thesis ranking. It requires confirmed recent transfer evidence into Binance, Gate.io, or Bitget, whale concentration, short-account dominance, low-float/high-FDV evidence, and a not-late/dormant structure. Use `strict:false` when you want the nearest misses for diagnosis.

Use `/flowproof` when a transfer claim needs audit detail. It prints the verdict, transfer count, total and largest token amount, top tx/hash, target CEX labels, source path, concentration gate, data error, and query URL. A row is only called verified when the active scan has count > 0, largest transfer above the floor, and a labelled destination.

Use `/coincheck` for one-symbol pass/fail triage across the full checklist: target-CEX flow, whale dominance, short dominance, low-float/high-FDV, and dormant/not-late structure.

Use `/cextargets` to view only confirmed Binance, Gate.io, and Bitget transfer rows. Use `/floattrap` for the low-float/high-FDV board and `/squeezeready` for short-crowded perp-book squeeze fuel.

Use `/funding` to rank live Binance USDT perpetuals by funding carry. `side:shorts` shows positive-funding markets where longs pay shorts, `side:longs` shows negative-funding markets where shorts pay longs, and `side:both` prints both tables with 24h volume, mark price, next funding time, and the latest Binance global long/short account split when available.

Use `/whales` to rank symbols by holder concentration. The default is `min_pct:90 bucket:top100`, which surfaces symbols where the top 100 observed contract holders control at least 90% of supply. Use `bucket:top10` for a stricter top-wallet read, `bucket:either` to accept either top10 or top100, and `bucket:both` when both buckets must pass. If the fresh scan lacks holder columns, `/whales` computes holder composition from the configured contract hints and writes `data/latest_whale_dominance.csv`; use `refresh:true` to force recompute and `max_symbols` to cap the live fetch. Treat this as observed contract-holder concentration, not native-chain global supply proof.

Use `/cexflow` when wallet-to-exchange movement is the primary event. The command accepts `min_tokens`, so `/cexflow min_tokens:20000` reruns the fresh scan with a 20k-token transfer floor instead of the default environment threshold. It also accepts `require_venue_gate`; use `/cexflow min_tokens:1000 require_venue_gate:false` to inspect all concentration-gated labelled CEX flow before applying the Binance/Bitget/Gate venue filter. These rows are most interesting when the same symbol also shows short crowding, OI expansion, or thin visible liquidity.

Use `/cexdiag` when `/cexflow` returns zero. It breaks the empty result into scan rows, contract hints, concentration-gate rows, CEX-flow attempts, no-transfer rows, explorer errors, venue-gate survival, and the attempted symbols. If HTTP 403 dominates, the scanner now attempts the Etherscan V2 token-transfer API with the chain ID for that network. Rows are still only counted as verified CEX flow when the destination can be labelled by explorer data, API labels, or a local CEX address book. Attempted rows are not transfer confirmations unless the status starts with `FLOW`.

Use `/earlyflow` as the low-float sweep. It defaults to `DISCORD_EARLY_FLOW_MIN_TOKENS`, or 20k tokens when unset, and supports the same `require_venue_gate` switch.

Use `/flowcoin` when a specific symbol needs a custom whale-to-CEX transfer check without scanning the whole output manually.

Use `/flowstress` to rank verified CEX-flow rows by venue-inventory stress: deposit notional versus visible ask depth and 24h turnover.

Use `/flowblocked` to list rows where the HTML explorer path or API fallback could not verify labelled destination flow. These rows are source-health problems, not proof that flow is absent.

Use `/flowhealth` to see API-key readiness and local CEX-address-label coverage. Configure `CEX_ADDRESS_LABELS` or `CEX_ADDRESS_BOOK_FILE` when API fallback rows need destination labels after explorer HTML blocks.

Use `/sethflow` to run the whole checklist in one shot: verified Binance/Gate/Bitget wallet-to-CEX flow above the requested transfer floor, holder concentration, more than 50% short accounts by default, and then a dormant/early chart-structure gate. The output says `RESEARCH`, `WAIT`, or `SKIP`; it is a triage state, not an execution instruction.

Use `/high days:20D` and `/low days:20D` to list all symbols that broke above/below the selected range. The bot accepts any `1D`-`1499D` lookback; common dashboard columns such as `5D`, `20D`, `90D`, and `180D` are read directly, while custom windows are computed from live Binance daily candles. The optional `limit` parameter trims the output when the list is noisy.

Use `/terminal` for slower structural evidence and `/timing` for current trigger quality. A symbol that appears on both lists is usually more interesting than a symbol that appears on only one.

Use `/corr threshold:0.5` to surface symbols whose BTC correlation is at or below `+0.50`; every negative-correlation symbol is included, and the threshold only cuts off highly BTC-correlated names. The dashboard caps the BTC-correlation target window at 180 days; younger symbols use their available overlap and the Discord row prints that actual day count.

Use `/coin` for a fast symbol card and `/dossier` when the setup needs a more complete review trail.

Use `/convex_scoreboard` to check whether the signal stack is improving over time instead of relying on screenshots.

Use `/sync_commands` after deploying slash-command schema changes. If Discord returns "This command is outdated", close the command composer, wait briefly, run `/sync_commands`, and type the command again from scratch.

## Watcher Modes

`DISCORD_WATCHER_ALERT_SOURCE` controls automated posts:

```text
terminal_timing  both structural evidence and timing quality
terminal         structural ranking only
timing           timing ranking only
cex_flow         concentration-gated wallet-to-CEX transfer flow
convex           legacy Convex Long candidate selection
```

Suggested starting point:

```text
DISCORD_WATCHER_ALERT_SOURCE=terminal_timing
DISCORD_WATCHER_SCAN_MODE=Deep
DISCORD_WATCHER_SCAN_INTERVAL_SECONDS=180
DISCORD_WATCHER_TOP_N=25
DISCORD_WATCHER_REALERT_HOURS=12
DISCORD_REQUIRE_BITGET_OR_GATE=1
DISCORD_CLEAR_GLOBAL_COMMANDS_ON_GUILD_SYNC=0
```

For a dedicated transfer monitor:

```text
DISCORD_WATCHER_ALERT_SOURCE=cex_flow
DISCORD_WATCHER_MIN_CEX_FLOW_SCORE=35
CEX_DEPOSIT_FLOW_ENABLED=1
CEX_DEPOSIT_FLOW_MAX_SYMBOLS=0
CEX_DEPOSIT_FLOW_LOOKBACK_HOURS=24
CEX_DEPOSIT_FLOW_MIN_TRANSFER_TOKENS=500000
DISCORD_EARLY_FLOW_MIN_TOKENS=20000
ETHERSCAN_V2_API_KEY=
ETHERSCAN_API_KEY=
CEX_ADDRESS_BOOK_FILE=data/cex_address_book.csv
CEX_ADDRESS_LABELS=
```

## Alert Card Contract

The main Discord card is designed to be readable under pressure:

- `Convex thesis`: the concise reason the setup might have nonlinear payoff
- `Evidence stack`: the strongest available component scores
- `Perp positioning`: short/long account skew, L/S ratio, OI context
- `Recent CEX flow`: large wallet-to-exchange movement, when present
- `Why flagged`: the concrete scanner reason
- `Observed trigger`: what is happening now
- `Next check`: what to inspect on the next scan
- `Invalidation`: what would weaken the read
- `Liquidity warning`: why slippage and exit depth matter
- `Risk level`: watch-only/elevated/high/extreme

This structure keeps alerts useful for both research review and later outcome attribution.

## Proof Loop

Webhook alerts are archived to:

```text
data/archive/flags/YYYY-MM-DD.jsonl
```

Outcome refreshes are written to:

```text
data/archive/outcomes/YYYY-MM-DD_outcomes.jsonl
```

The scoreboard command reads those files so the system can track which evidence combinations led to later upside, drawdown, invalidation, or no follow-through.
