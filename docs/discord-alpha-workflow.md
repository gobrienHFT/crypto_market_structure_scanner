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
/commands
/help
/hunt
/thesis
/radar
/prime
/precrime min_tokens:20000
/ravelab min_tokens:20000
/pumpwatch min_tokens:20000
/setupscore min_tokens:20000
/flowproof symbol:PLAYUSDT min_tokens:20000
/coincheck symbol:PLAYUSDT min_tokens:20000
/cextargets min_tokens:20000
/floattrap min_score:60
/squeezeready min_short_pct:50
/funding side:both limit:10
/whales min_pct:90 bucket:top10
/cexflow min_tokens:20000
/cexdiag min_tokens:1000 require_venue_gate:false symbol_limit:25
/earlyflow
/flowcoin symbol:PLAYUSDT min_tokens:20000
/flowstress min_tokens:20000
/flowblocked min_tokens:20000
/flowhealth min_tokens:20000
/sethflow min_tokens:10000000 require_whale_origin_flow:true
/high days:20D
/low days:20D
/terminal
/timing
/corr threshold:0.5
/coin <symbol>
/dossier <symbol>
/convex_scoreboard
```

Use `/alpha` as the triage queue. It first applies the strict core thesis gate, observed top-10 holder concentration at or above 90% with ETH/BNB/ARB chain+contract explorer holder-source snapshot evidence, Binance+Bitget trading evidence, 60D no-pump proof, low-float/high-FDV structure, short crowd plus squeeze fuel, and not-late structure, then blends structure, timing, CEX-flow, scanner score, and short-account fuel into a compact watchlist.

Use `/help` or `/commands` when the slash-command surface feels noisy. It gives the short operator map: `/hunt` or `/thesis` first, `/coincheck` for one symbol, `/ravelab` for detailed blockers and near misses, and `/cexdiag`/`/flowhealth` for data-source problems.

Use `/hunt` or `/thesis` as the simplest hard-gated operator queue and the default place to start. They use the strict `/ravelab` gates with near misses hidden by default, then print only the live queue and concise evidence per symbol. The `trigger` choice accepts `all`, `triggered`, `massive_flow`, `flow`, `target_flow`, `forced_flow`, `breakout`, or `core`. Generic target-CEX tells use `min_tokens`; the higher-conviction `flow`/`whale-CEX` lane uses `whale_flow_min_tokens`, defaulting to `DISCORD_RAVELAB_WHALE_FLOW_MIN_TOKENS` or 100k tokens. The separate `massive_flow` lane uses `DISCORD_RAVELAB_MASSIVE_WHALE_FLOW_MIN_TOKENS`, defaulting to 10M tokens, so 10M+ top-holder-origin CEX transfers are not blurred together with smaller early diagnostic flow. The `forced_flow` lane catches hard-gated rows where short crowd, OI/volume, and squeeze fuel are rising while exhaustion remains low. `/thesis` is the plain-name queue, `/radar` is the technical alias, `/prime` is the short alias, `/crimepump` is the legacy blunt-name alias, and `/ravelab` is the diagnostic microscope for near misses, style filtering, blockers, and full evidence rows.

Use `/precrime` before `/pumpwatch` when you specifically want the quiet pre-activity version of the thesis. It applies the hard gates first: observed top-10 holder concentration at least `min_whale_pct` with a hard floor of 90%, ETH/BNB/ARB chain+contract explorer holder-source snapshot evidence, Binance+Bitget trading evidence, pinned 60D no-pump/dormancy proof, low-float/high-FDV structure evidence, and short crowd plus squeeze fuel. After that, it rewards holder/control concentration, Binance/Bitget/Gate inventory tells, short-fuse perp positioning, and thin visible books, but thin-book evidence is only an amplifier and never substitutes for the float/FDV gate, and high short-account percentage alone does not clear the quiet candidate gate without build/OI/liquidation/funding/forced-buying fuel. It also penalizes names that already have breakout, volume, CMC-mover, or high-return chase heat. Keep `require_quiet:true` when hunting before the crowd notices; the legacy `require_dormant_60d` slash option cannot disable the 60D gate. Use `require_target_flow:true` when you only want confirmed labelled CEX-transfer rows. Use `/cexdiag`, `/earlyflow`, or `/whales` for looser data-coverage diagnostics instead of weakening this queue.

Historical anchors: `RAVEUSDT` on `2026-04-18` is the RAVE-style cap-table reflexivity example; `LABUSDT` on `2026-05-11` is the LAB-style venue-inventory stress example. These are used as pattern references for review/backtesting context, not as claims about current intent.

Use `/ravelab` when you specifically want the strict early version of the thesis. By default it lets hard gates lead rather than hiding candidates behind an arbitrary early-score floor: observed top-10 whale-control concentration at the requested threshold with ETH/BNB/ARB chain+contract explorer holder-source snapshot evidence, explicit Binance plus Bitget trading evidence, float/FDV trap evidence, at least 60 days of history, no daily high-expansion pump above `max_recent_pump_pct` during the last 60 closed daily candles, a two-month no-chase/dormancy gate, and a short-squeeze stack that pairs short crowding with perp/OI/liquidation/funding-flip/build fuel. When the concentration scanner provides filtered/manipulable holder metrics, the hard holder gate uses that adjusted top-10 read before raw top-10, so CEX, treasury, vesting, bridge, wrapper, LP, burn, and protocol-storage concentration cannot masquerade as insider-controlled float. Top-100 concentration can still boost context and appear in near misses, but it no longer satisfies the hard `/ravelab` whale gate without top-10 control. The command now reapplies the lifecycle and short-squeeze models inside the Discord path, so older snapshots still print `crime`, `ssq`, and funding-flip evidence instead of relying only on precomputed scanner columns. High short-account percentage alone no longer clears the squeeze core gate, and holder/venue/squeeze/dormancy alone no longer clears the full core without low-float, FDV/MC gap, locked-supply, or extreme top-wallet float evidence. Missing or insufficient 60D pump history now fails the dormant gate instead of silently passing from the current 24h move. Range-high breaks no longer fail the dormant gate by themselves; they are shown as triggers after the hard gates, while large daily expansion, volume/return chase heat, or exhaustion still blocks the row. The legacy `require_quiet` slash option cannot disable early/no-chase; blocked late rows stay in the blocker/near-miss evidence path rather than the candidate queue. The default output starts with a gate funnel, trigger-lane counts, a trigger queue for rows that already have whale-origin CEX flow, massive whale-origin CEX flow, target-CEX flow, forced-flow mechanics, funding flip, or requested high breakouts, plus a core-watch queue for hard-gated rows waiting on a trigger. Each row then starts with a stage label such as `A1 CORE PRIME`, `A2 BREAKOUT PRIME`, or `A3 WHALE-CEX PRIME`, then prints the explicit trigger reason, blockers, holder evidence, adjusted/manipulable holder evidence when available, float/FDV evidence, venue evidence, `pump60` plus its source, high-breakout windows, and target-CEX/whale-origin flow. The `flowMech` read is the forced-flow lens: short crowd still present, shorts building, OI/volume expanding, and low exhaustion means the structure is still fuelled; `forced-flow` becomes a trigger only after hard gates when those mechanics are rising and exhaustion is still below the late-risk line. `EXHAUST`, fading shorts, or high exhaustion means the forced-flow crowd may already be spent and the row should be treated as late/chase risk until OI, funding, volume, and short crowd reset. CEX target-flow lanes are recomputed against the command's `min_tokens` floor, while the A3 `whale-CEX` lane uses `whale_flow_min_tokens`, defaulting to `DISCORD_RAVELAB_WHALE_FLOW_MIN_TOKENS` or 100k tokens. The separate `massive_flow` lane uses `DISCORD_RAVELAB_MASSIVE_WHALE_FLOW_MIN_TOKENS` or 10M tokens by default, and trigger text prints the exact floor cleared, so smaller diagnostic transfers cannot masquerade as massive top-holder-origin inventory movement. It also prints a small `near_miss_limit` tail of blocked rows that still respect the required explorer holder-evidence and Binance+Bitget gates with at least three core gates already present, so failed float/FDV, squeeze, no-pump, dormant-history, or optional-flow gates are visible without polluting the strict candidate list. Use `trigger_filter:massive_flow`, `trigger_filter:flow`, `trigger_filter:target_flow`, `trigger_filter:forced_flow`, `trigger_filter:breakout`, or `trigger_filter:core` to cut the view to one operator lane; use `near_miss_limit:0` to hide the blocked tail and `detail:true` for the fuller multi-line evidence stack. Bitget transfer-target text is still shown as flow evidence, but no longer satisfies the strict Bitget trading gate by itself. Pct-only, source-less holder counts, missing explorer holder snapshots, GoPlus-only holder data, or `needs ETH/BNB/ARB chain+contract+explorer source` means the whale-control gate passed numerically but needs `/whales refresh:true require_contract_hint:true` follow-up before treating it as explorer-backed. It then overlays requested high-breakout windows, defaulting to `1D,2D,3D,4D,5D,20D`, so a slow insider-style lift is visible after the hard gates; set `require_breakout_high:true` when you only want rows that already broke one of those highs. Set `require_whale_origin_flow:true` when you only want confirmed target-CEX flow whose sender matched a scanned top-holder wallet and cleared the whale-flow floor. RAVE-like rows lean cap-table concentration, hidden/opaque float, and low-float FDV gaps; LAB-like rows lean controlled float plus labelled Binance/Bitget/Gate flow or venue-inventory stress. Use `style:rave` or `style:lab` to focus the screen; use `/cexdiag`, `/flowhealth`, `/earlyflow`, and `/whales` for broader coverage diagnostics.

Use `/pumpwatch` as the fastest catch board after the same hard gates: observed top-10 holder concentration at or above 90%, ETH/BNB/ARB chain+contract explorer holder-source snapshot evidence, Binance+Bitget trading evidence, pinned 60D no-pump/dormancy proof, low-float/high-FDV structure, short-squeeze fuel, and not-late tape. High short-account percentage alone is no longer enough here; it has to pair with build/OI/liquidation/funding/forced-buying fuel, or the row is treated as a blocked near-signal. It does not force every row to have confirmed transfer evidence by default; after those gates it rank-orders target-CEX flow, whale/control, low float, short-squeeze fuel, timing, venue support, archetype match, and not-late quality into one watch state. Set `require_target_flow:true` when you only want verified Binance/Gate/Bitget transfer rows.

Use `/setupscore` as the strict full-thesis ranking. It requires confirmed recent transfer evidence into Binance, Gate.io, or Bitget, observed top-10 holder concentration at or above 90%, ETH/BNB/ARB chain+contract explorer holder-source snapshot evidence, Binance+Bitget trading evidence, short crowd plus squeeze fuel, low-float/high-FDV evidence, and a not-late/dormant structure. Nearest misses are still printed when nothing passes, but the hard gates are no longer slash-command toggles.

Use `/flowproof` when a transfer claim needs audit detail. It prints the verdict, transfer count, total and largest token amount, top-holder sender evidence when the sender matches a scanned holder wallet, top tx/hash, target CEX labels, source path, concentration gate, data error, and query URL. A row is only called verified when the active scan has count > 0, largest transfer above the floor, and a labelled destination. It also prints compact thesis gates (`baseThesis`, `coreSetup`, `flowSetup`, `targetFlow`, holder, `venueBnBg`, float, `shorts+fuel`, `noPump60`, and `whaleOrigin`), because a labelled Binance/Bitget/Gate transfer proves flow only and does not prove the Binance+Bitget trading-venue gate by itself.

Use `/coincheck` for one-symbol pass/fail triage across the full checklist: Binance+Bitget trading evidence, 90%+ holder dominance plus holder evidence, short crowd plus squeeze fuel, low-float/high-FDV, and dormant/not-late structure. It now separates `baseThesis`, `coreSetup`, `flowSetup`, `targetFlow`, and `whaleOrigin`, so a clean core structure can pass before a CEX-flow trigger appears, while verified CEX flow remains explicit trigger/risk evidence rather than venue proof.

Use `/cextargets` to view only confirmed Binance, Gate.io, and Bitget transfer rows. Use `/floattrap` for the low-float/high-FDV board and `/squeezeready` for short-crowded perp-book squeeze fuel. These are diagnostic context boards, so they print `Diagnostic rows`, `Transfer rows`, or `Stress rows` plus `baseThesis Y/N` and `coreThesis Y/N`; `baseThesis N` includes blockers such as `holder`, `BnBg`, or `noPump60`, while `coreThesis N` adds `float`, `shorts+fuel`, or `notLate`, so raw context points back to the missing hard gate before `/hunt` or `/coincheck` confirmation.

Use `/funding` to rank live Binance USDT perpetuals by funding carry. `side:shorts` shows positive-funding markets where longs pay shorts, `side:longs` shows negative-funding markets where shorts pay longs, and `side:both` prints both tables with 24h volume, mark price, next funding time, and the latest Binance global long/short account split when available.

Use `/shorts` only as a weak-context short-crowd board. Each row is labelled `weakCtx` and lists symbols above 50% short accounts, then overlays `baseThesis Y/N/?` from the latest scanner context when available; `Y` means the strict holder evidence, Binance+Bitget trading, and 60D no-pump gates also passed, while `?` means the live ratio row has no scanner-context overlay yet.

Use `/whales` to rank symbols by holder concentration. The default is `min_pct:90 bucket:top10`, matching the non-negotiable top-wallet control thesis; use `bucket:top100` only as a broader diagnostic context view, `bucket:either` to accept either top10 or top100, and `bucket:both` when both buckets must pass. If the fresh scan lacks holder columns, `/whales` computes holder composition from the configured contract hints and writes `data/latest_whale_dominance.csv`; use `refresh:true` to force recompute and `max_symbols` to cap the live fetch. Treat this as a diagnostic holder-concentration board, not native-chain global supply proof or a candidate queue; rows print `baseThesis Y/N` and `coreThesis Y/N` with blockers so top100-only concentration, missing explorer holder-source evidence, missing Binance+Bitget trading, weak float/FDV, weak short-fuel, or late/no-pump failures cannot masquerade as the non-negotiable candidate queue.

Use `/cexflow` when wallet-to-exchange movement is the primary event. The command accepts `min_tokens`, so `/cexflow min_tokens:20000` reruns the fresh scan with a 20k-token transfer floor instead of the default environment threshold. It now applies strict holder and venue gates by default: observed top10 holder concentration must be at least `min_whale_pct`, default 90%, and values below 90 are treated as 90. `require_holder_evidence:true` requires ETH/BNB/ARB chain+contract explorer holder-source snapshot evidence, and `require_venue_gate:true` requires Binance perp plus Bitget trading evidence before a transfer row can rank. Top100 concentration is context only for CEX-flow gating. Gate flow is still shown as supporting evidence, but Gate no longer substitutes for Bitget. Use `/cexflow min_tokens:1000 require_venue_gate:false` to inspect strict holder-gated labelled CEX flow before applying the Binance+Bitget thesis venue filter. Use `require_holder_evidence:false` only as a diagnostic mode for rows whose concentration exists numerically but still need explorer holder-source snapshot coverage. These rows are most interesting when the same symbol also shows short crowding, OI expansion, or thin visible liquidity.

Every CEX-flow card prints a `Whale sender` line. `verified top-holder origin` means the transfer sender matched a scanned top-holder wallet; `generic target-CEX flow only` means a labelled exchange deposit happened but the sender was not verified as a top holder, so it remains weaker flow context rather than the massive whale-origin trigger.

Use `/cexdiag` when `/cexflow` returns zero. It breaks the empty result into scan rows, contract hints, observed concentration rows, strict holder-evidence rows, CEX-flow attempts, no-transfer rows, explorer errors, holder-gate survival, venue-gate survival, and the attempted symbols. If explorer HTML blocks with HTTP 403 or returns no parsable transfer rows, the scanner attempts the Etherscan V2 token-transfer API with the chain ID for that network before treating the CEX-flow read as empty. Rows are still only counted as verified CEX flow when the destination can be labelled by explorer data, API labels, or a local CEX address book. If the API sees large transfers above the requested floor but cannot label the destination, Discord now prints an `unlabelled API transfers` diagnostic with the top destination addresses to research and add to `CEX_ADDRESS_LABELS` or `CEX_ADDRESS_BOOK_FILE`. Attempted rows are not transfer confirmations unless the status starts with `FLOW`.

Use `/earlyflow` as the low-float sweep. It defaults to `DISCORD_EARLY_FLOW_MIN_TOKENS`, or 20k tokens when unset, and supports the same `min_whale_pct`, `require_holder_evidence`, and `require_venue_gate` switches. Like `/cexflow`, `min_whale_pct` is a top10 holder floor with a hard minimum of 90.

Use `/flowcoin` when a specific symbol needs a custom whale-to-CEX transfer check without scanning the whole output manually.

Use `/flowstress` to rank verified CEX-flow rows by venue-inventory stress: deposit notional versus visible ask depth and 24h turnover.

Use `/flowblocked` to list rows where the HTML explorer path or API fallback could not verify labelled destination flow. These rows are source-health or address-label-coverage problems, not proof that flow is absent. When a blocked row says `unlabelled transfer(s) above floor`, treat it as a wallet-labelling lead: verify the destination externally before adding a CEX label.

Use `/flowhealth` to see API-key readiness and local CEX-address-label coverage. Configure `CEX_ADDRESS_LABELS` or `CEX_ADDRESS_BOOK_FILE` when API fallback rows need destination labels after explorer HTML blocks.

Use `/sethflow` to run the whole massive-flow checklist in one shot. If `min_tokens` is omitted, it defaults to the 10M massive-flow floor from `DISCORD_RAVELAB_MASSIVE_WHALE_FLOW_MIN_TOKENS`, not the generic CEX-flow floor. It requires verified Binance/Gate/Bitget wallet-to-CEX flow above the active transfer floor, a transfer sender matched to a scanned top-holder wallet by default, observed top-10 holder concentration at or above 90% with explorer holder evidence, low-float/FDV evidence, short crowding paired with squeeze fuel, and then a dormant/early chart-structure gate. Keep `require_whale_origin_flow:true` for the strict A-plus read; set it false only as a diagnostic mode for target-CEX flow whose sender could not be matched. The output says `RESEARCH`, `WAIT`, or `SKIP`; it is a triage state, not an execution instruction.

Use `/high days:20D` and `/low days:20D` as hard-gated breakout screens after the strict core thesis has already passed: top10 holder evidence, Binance+Bitget, 60D no-pump, low-float/high-FDV, short crowd plus squeeze fuel, and not-late structure. The bot accepts any `1D`-`1499D` lookback; common dashboard columns such as `5D`, `20D`, `90D`, and `180D` are read directly, while custom windows are computed from live Binance daily candles. Rows print `coreThesis Y` plus `baseThesis Y`; set `thesis_only:false` when you want the broad raw breakout context with failed base-gate blockers visible.

Use `/terminal` for slower structural evidence and `/timing` for current trigger quality after the base thesis gate has already passed. Both boards require observed top10 holder evidence, Binance+Bitget trading evidence, and 60D no-pump proof before showing a row, and each row prints `baseThesis Y` so they read as filtered context rather than loose diagnostics. A symbol that appears on both lists is usually more interesting than a symbol that appears on only one.

Use `/corr threshold:0.5` to surface symbols whose BTC correlation is at or below `+0.50`; every negative-correlation symbol is included, and the threshold only cuts off highly BTC-correlated names. The dashboard caps the BTC-correlation target window at 180 days; younger symbols use their available overlap and the Discord row prints that actual day count. Rows also print `baseThesis Y/N` with blockers, so low BTC correlation stays context unless the strict top10 holder-evidence, Binance+Bitget, and 60D no-pump gate also passed.

Use `/coin` for a fast symbol card and `/dossier` when the setup needs a more complete review trail.

Use `/convex_scoreboard` to check whether the signal stack is improving over time instead of relying on screenshots.

Use `/sync_commands` after deploying slash-command schema changes. If Discord returns "This command is outdated", close the command composer, wait briefly, run `/sync_commands`, and type the command again from scratch.

## Watcher Modes

`DISCORD_WATCHER_ALERT_SOURCE` controls automated posts:

```text
terminal_timing  core thesis gate plus structural evidence and timing quality
terminal         core thesis gate plus structural ranking
timing           core thesis gate plus timing ranking
cex_flow         core thesis gate plus concentration-gated wallet-to-CEX transfer flow
convex           legacy Convex Long selection after the same core thesis gates
```

Every watcher card starts with a compact `Watcher gate` line showing `coreThesis`, holder/top10, Binance+Bitget, 60D no-pump, and short-account context, so automated posts expose the hard-gate proof instead of relying on the alert-source label alone.
Dashboard-triggered Discord Convex alerts and the latest Convex cache re-score rows through the current core-thesis bucket logic before sending or writing, so stale `Convex Long` labels cannot bypass the low-float/FDV, short+squeeze-fuel, no-pump, holder, or Binance+Bitget gates. Dashboard-triggered cards start with a compact `Dashboard gate` line showing `coreThesis`, holder/top10, Binance+Bitget, 60D no-pump, and short-account context.

`/startbot` uses the same stricter candidate gate before selecting a paper/live setup: observed top10 holder control with ETH/BNB/ARB explorer evidence, explicit Binance+Bitget trading evidence, 60D no-pump proof, short crowd plus squeeze fuel, low-float/high-FDV evidence, and not-late structure. It should therefore lag `/hunt` rather than front-run weaker diagnostic rows.

Suggested starting point:

```text
DISCORD_WATCHER_ALERT_SOURCE=terminal_timing
DISCORD_WATCHER_SCAN_MODE=Deep
DISCORD_WATCHER_SCAN_INTERVAL_SECONDS=180
DISCORD_WATCHER_TOP_N=25
DISCORD_WATCHER_REALERT_HOURS=12
DISCORD_ASSUME_SYMBOLS_ARE_BINANCE_PERPS=0
DISCORD_CLEAR_GLOBAL_COMMANDS_ON_GUILD_SYNC=0
```

Fresh scans stamp `binance_perp_universe=true`, so the Binance side of the Binance+Bitget gate is explicit. Symbol text alone cannot satisfy Binance evidence, even if the deprecated `DISCORD_ASSUME_SYMBOLS_ARE_BINANCE_PERPS` variable is present. The old `DISCORD_REQUIRE_BITGET_OR_GATE` flag is also ignored by thesis gates; Binance+Bitget trading evidence is pinned on, with Gate only supporting context. Discord thesis screens such as `/hunt`, `/radar`, `/ravelab`, `/crimepump`, `/precrime`, `/pumpwatch`, `/setupscore`, `/coincheck`, `/alpha`, `/high`, and `/low` require the explicit Binance perp marker, Binance venue share, or Binance top-venue text, plus 60D no-pump proof. Candidate surfaces then add their core gates such as low-float/high-FDV, short/squeeze fuel, and not-late structure before showing rows as candidates.

For a dedicated transfer monitor:

```text
DISCORD_WATCHER_ALERT_SOURCE=cex_flow
DISCORD_WATCHER_MIN_CEX_FLOW_SCORE=35
CEX_DEPOSIT_FLOW_ENABLED=1
CEX_DEPOSIT_FLOW_MAX_SYMBOLS=0
CEX_DEPOSIT_FLOW_LOOKBACK_HOURS=24
CEX_DEPOSIT_FLOW_MIN_TRANSFER_TOKENS=500000
DISCORD_EARLY_FLOW_MIN_TOKENS=20000
DISCORD_RAVELAB_WHALE_FLOW_MIN_TOKENS=100000
DISCORD_RAVELAB_MASSIVE_WHALE_FLOW_MIN_TOKENS=10000000
ETHERSCAN_V2_API_KEY=XFYBWMNYA62ZRW6PK252CVYIYM2H5GZ6YP
ETHERSCAN_API_KEY=XFYBWMNYA62ZRW6PK252CVYIYM2H5GZ6YP
BSCSCAN_API_KEY=XFYBWMNYA62ZRW6PK252CVYIYM2H5GZ6YP
ARBISCAN_API_KEY=XFYBWMNYA62ZRW6PK252CVYIYM2H5GZ6YP
ARBSCAN_API_KEY=XFYBWMNYA62ZRW6PK252CVYIYM2H5GZ6YP
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
