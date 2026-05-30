# Discord Alpha Workflow

This repo treats Discord as the live operating surface for the scanner. The dashboard is useful for investigation, but Discord is where the system should quickly answer:

- What deserves attention now?
- Why did it flag?
- What would confirm or invalidate it?
- Did prior alerts actually work?

The integration is intentionally research-first. It avoids trade-call language and keeps execution responsibility outside the bot.

## Signal Stack

The highest-quality Discord flags usually combine several of these:

- `venue gate`: Binance perp plus Bitget trading evidence; Gate and target-CEX flow are optional supporting evidence, not Bitget substitutes
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
/crimepump
/prime
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

Use `/alpha` as the triage queue. It first applies the strict thesis gate, observed 90%+ holder concentration with ETH/BNB/ARB chain+contract source/count evidence plus Binance+Bitget trading evidence, then blends structure, timing, CEX-flow, scanner score, and short-account fuel into a compact watchlist.

Use `/crimepump` as the simplest hard-gated operator queue. It uses the strict `/ravelab` gates with near misses hidden by default, then prints only the live queue and concise evidence per symbol. The `trigger` choice accepts `all`, `triggered`, `flow`, `breakout`, or `core`. Start there when you want the cleanest list of names to inspect now; `/prime` is a short alias, and `/ravelab` is the diagnostic microscope for near misses, style filtering, blockers, and full evidence rows.

Use `/precrime` before `/pumpwatch` when you specifically want the quiet pre-activity version of the thesis. It now applies the hard gates first by default: observed holder concentration at least `min_whale_pct` (90%), ETH/BNB/ARB chain+contract holder evidence, and Binance+Bitget trading evidence. After that, it rewards holder/control concentration, low-float/high-FDV structure, Binance/Bitget/Gate inventory tells, short-fuse perp positioning, and thin visible books, but it penalizes names that already have breakout, volume, CMC-mover, or high-return chase heat. Keep `require_quiet:true` when hunting before the crowd notices; use `require_target_flow:true` when you only want confirmed labelled CEX-transfer rows. Only relax `require_holder_evidence` or `require_binance_bitget` for diagnostics.

Historical anchors: `RAVEUSDT` on `2026-04-18` is the RAVE-style cap-table reflexivity example; `LABUSDT` on `2026-05-11` is the LAB-style venue-inventory stress example. These are used as pattern references for review/backtesting context, not as claims about current intent.

Use `/ravelab` when you specifically want the strict early version of the thesis. By default it lets hard gates lead rather than hiding candidates behind an arbitrary early-score floor: observed 90%+ whale/top-holder concentration, ETH/BNB/ARB chain+contract evidence plus holder source/count evidence for that read, explicit Binance plus Bitget trading evidence, at least 60 days of history, no daily high-expansion pump above `max_recent_pump_pct` during the last 60 closed daily candles, a two-month no-chase/dormancy gate, and a short-squeeze stack that pairs short crowding with perp/OI/liquidation/funding-flip/build fuel. The command now reapplies the lifecycle and short-squeeze models inside the Discord path, so older snapshots still print `crime`, `ssq`, and funding-flip evidence instead of relying only on precomputed scanner columns. High short-account percentage alone no longer clears the squeeze core gate. Missing or insufficient 60D pump history now fails the dormant gate instead of silently passing from the current 24h move. The default output starts with a trigger queue for rows that already have whale-origin CEX flow, target-CEX flow, funding flip, or requested high breakouts, plus a core-watch queue for hard-gated rows waiting on a trigger. Each row then starts with a stage label such as `A1 CORE PRIME`, `A2 BREAKOUT PRIME`, or `A3 WHALE-CEX PRIME`, then prints blockers, holder evidence, venue evidence, `pump60` plus its source, high-breakout windows, and target-CEX/whale-origin flow. It also prints a small `near_miss_limit` tail of blocked rows that still respect the required holder-evidence and Binance+Bitget gates, so failed no-pump/dormancy/optional-flow gates are visible without polluting the strict candidate list. Use `near_miss_limit:0` to hide that tail and `detail:true` for the fuller multi-line evidence stack. Bitget transfer-target text is still shown as flow evidence, but no longer satisfies the strict Bitget trading gate by itself. Use `require_holder_evidence:false` only for diagnostics; `pct-only` or `needs ETH/BNB/ARB chain+contract` means the 90% gate passed numerically but needs `/whales refresh:true require_contract_hint:true` follow-up before treating it as explorer-backed. It then overlays requested high-breakout windows, defaulting to `1D,2D,3D,4D,5D,20D`, so a slow insider-style lift is visible after the hard gates; set `require_breakout_high:true` when you only want rows that already broke one of those highs. Set `require_whale_origin_flow:true` when you only want confirmed target-CEX flow whose sender matched a scanned top-holder wallet. RAVE-like rows lean cap-table concentration, hidden/opaque float, and low-float FDV gaps; LAB-like rows lean controlled float plus labelled Binance/Bitget/Gate flow or venue-inventory stress. Use `style:rave` or `style:lab` to focus the screen, and only relax `require_binance_bitget` or `require_dormant_2m` when diagnosing broader near misses.

Use `/pumpwatch` as the fastest catch board after the same default hard gates: observed 90%+ holder concentration, ETH/BNB/ARB holder evidence, and Binance+Bitget trading evidence. It does not force every row to have confirmed transfer evidence by default; it rank-orders target-CEX flow, whale/control, low float, short-squeeze fuel, timing, venue support, archetype match, and not-late risk into one watch state. Set `require_target_flow:true` when you only want verified Binance/Gate/Bitget transfer rows, and only relax `require_holder_evidence` or `require_binance_bitget` when diagnosing coverage gaps.

Use `/setupscore` as the strict full-thesis ranking. It requires confirmed recent transfer evidence into Binance, Gate.io, or Bitget, observed 90%+ holder concentration, ETH/BNB/ARB chain+contract holder evidence by default, Binance+Bitget trading evidence by default, short-account dominance, low-float/high-FDV evidence, and a not-late/dormant structure. Use `strict:false` when you want the nearest misses for diagnosis, and only relax `require_holder_evidence` or `require_binance_bitget` when diagnosing coverage gaps.

Use `/flowproof` when a transfer claim needs audit detail. It prints the verdict, transfer count, total and largest token amount, top-holder sender evidence when the sender matches a scanned holder wallet, top tx/hash, target CEX labels, source path, concentration gate, data error, and query URL. A row is only called verified when the active scan has count > 0, largest transfer above the floor, and a labelled destination.

Use `/coincheck` for one-symbol pass/fail triage across the full checklist: target-CEX flow, Binance+Bitget trading evidence, 90%+ holder dominance plus holder evidence, short dominance, low-float/high-FDV, and dormant/not-late structure.

Use `/cextargets` to view only confirmed Binance, Gate.io, and Bitget transfer rows. Use `/floattrap` for the low-float/high-FDV board and `/squeezeready` for short-crowded perp-book squeeze fuel.

Use `/funding` to rank live Binance USDT perpetuals by funding carry. `side:shorts` shows positive-funding markets where longs pay shorts, `side:longs` shows negative-funding markets where shorts pay longs, and `side:both` prints both tables with 24h volume, mark price, next funding time, and the latest Binance global long/short account split when available.

Use `/whales` to rank symbols by holder concentration. The default is `min_pct:90 bucket:top100`, which surfaces symbols where the top 100 observed contract holders control at least 90% of supply. Use `bucket:top10` for a stricter top-wallet read, `bucket:either` to accept either top10 or top100, and `bucket:both` when both buckets must pass. If the fresh scan lacks holder columns, `/whales` computes holder composition from the configured contract hints and writes `data/latest_whale_dominance.csv`; use `refresh:true` to force recompute and `max_symbols` to cap the live fetch. Treat this as observed contract-holder concentration, not native-chain global supply proof.

Use `/cexflow` when wallet-to-exchange movement is the primary event. The command accepts `min_tokens`, so `/cexflow min_tokens:20000` reruns the fresh scan with a 20k-token transfer floor instead of the default environment threshold. It now applies strict holder and venue gates by default: observed top-holder concentration must be at least `min_whale_pct`, default 90%, `require_holder_evidence:true` requires ETH/BNB/ARB chain+contract holder evidence, and `require_venue_gate:true` requires Binance perp plus Bitget trading evidence before a transfer row can rank. Gate flow is still shown as supporting evidence, but Gate no longer substitutes for Bitget. Use `/cexflow min_tokens:1000 require_venue_gate:false` to inspect strict holder-gated labelled CEX flow before applying the Binance+Bitget thesis venue filter. Use `require_holder_evidence:false` only as a diagnostic mode for rows whose concentration exists numerically but still need holder-source coverage. These rows are most interesting when the same symbol also shows short crowding, OI expansion, or thin visible liquidity.

Use `/cexdiag` when `/cexflow` returns zero. It breaks the empty result into scan rows, contract hints, observed concentration rows, strict holder-evidence rows, CEX-flow attempts, no-transfer rows, explorer errors, holder-gate survival, venue-gate survival, and the attempted symbols. If HTTP 403 dominates, the scanner now attempts the Etherscan V2 token-transfer API with the chain ID for that network. Rows are still only counted as verified CEX flow when the destination can be labelled by explorer data, API labels, or a local CEX address book. Attempted rows are not transfer confirmations unless the status starts with `FLOW`.

Use `/earlyflow` as the low-float sweep. It defaults to `DISCORD_EARLY_FLOW_MIN_TOKENS`, or 20k tokens when unset, and supports the same `min_whale_pct`, `require_holder_evidence`, and `require_venue_gate` switches.

Use `/flowcoin` when a specific symbol needs a custom whale-to-CEX transfer check without scanning the whole output manually.

Use `/flowstress` to rank verified CEX-flow rows by venue-inventory stress: deposit notional versus visible ask depth and 24h turnover.

Use `/flowblocked` to list rows where the HTML explorer path or API fallback could not verify labelled destination flow. These rows are source-health problems, not proof that flow is absent.

Use `/flowhealth` to see API-key readiness and local CEX-address-label coverage. Configure `CEX_ADDRESS_LABELS` or `CEX_ADDRESS_BOOK_FILE` when API fallback rows need destination labels after explorer HTML blocks.

Use `/sethflow` to run the whole checklist in one shot: verified Binance/Gate/Bitget wallet-to-CEX flow above the requested transfer floor, observed 90%+ holder concentration with holder evidence by default, more than 50% short accounts by default, and then a dormant/early chart-structure gate. The output says `RESEARCH`, `WAIT`, or `SKIP`; it is a triage state, not an execution instruction.

Use `/high days:20D` and `/low days:20D` to list all symbols that broke above/below the selected range. The bot accepts any `1D`-`1499D` lookback; common dashboard columns such as `5D`, `20D`, `90D`, and `180D` are read directly, while custom windows are computed from live Binance daily candles. Rows that also pass the strict 90%+ holder-evidence plus Binance+Bitget thesis gate sort first and print `thesis Y`; set `thesis_only:true` when you only want hard-gated breakout rows.

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
DISCORD_ASSUME_SYMBOLS_ARE_BINANCE_PERPS=1
DISCORD_CLEAR_GLOBAL_COMMANDS_ON_GUILD_SYNC=0
```

Fresh scans stamp `binance_perp_universe=true`, so the Binance side of the Binance+Bitget gate is explicit. Keep `DISCORD_ASSUME_SYMBOLS_ARE_BINANCE_PERPS=1` for legacy caches generated from the Binance perp universe; set it to `0` when auditing mixed rows so symbol text alone cannot satisfy Binance evidence.

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
