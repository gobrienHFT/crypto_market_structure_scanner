# crypto_market_structure_scanner

[![tests](https://img.shields.io/badge/tests-pytest-green)](.github/workflows/tests.yml)

Research and monitoring framework for finding asymmetric crypto market structures before they become obvious on price alone.

The system combines perpetual-market positioning, Binance+Bitget venue participation with Gate as optional evidence, on-chain holder concentration, wallet-to-CEX flow, timing quality, Discord alerting, and proof-of-signal tracking. The practical goal is to surface low-float or concentrated-holder structures where short crowding, thin liquidity, and exchange inventory movement can create convex payoff conditions.

It is built as research infrastructure, not as an automated trading system. Alerts are designed to accelerate discretionary review, sizing discipline, and post-alert measurement.

---

## Overview

`crypto_market_structure_scanner` helps surface crypto assets with unusual structural conditions across market data, venue flow, derivatives positioning, and holder data.

The project combines:

- Binance perpetual market screening
- Binance+Bitget thesis venue gating, with Gate as optional supporting evidence
- on-chain holder concentration analytics
- float and liquidity analysis
- futures/open-interest monitoring
- short-account crowding and squeeze-fuel scoring
- wallet-to-CEX transfer monitoring
- holder composition analysis
- Discord webhook alerts
- Discord bot query commands
- Discord alpha brief / triage workflow
- Streamlit dashboards
- contract-resolution tooling
- persistent local scan storage and ranking

The goal is to identify assets worth further review by combining observable market behaviour with token-distribution structure.

---

## Research Thesis

The scanner is aimed at a specific class of market structure:

- low tradable float or highly concentrated observed holder distribution
- visible participation on venues where orderflow hedging and market making can matter
- crowded short-account positioning on perpetual markets
- rising open interest, volume, or trade count before price fully extends
- recent large token movements from concentrated wallets into labelled exchange wallets
- enough ATH/runway or liquidity asymmetry for payoff to become nonlinear

No single signal is treated as proof. The product value comes from stacking independent evidence into a fast review queue, then archiving outcomes so the rules can be judged empirically.

---

## What This Demonstrates

For engineering review, this repo shows:

- production-style data ingestion from exchange, explorer, and market-data APIs
- modular scoring engines with focused tests
- Streamlit product/dashboard work
- Discord bot and webhook operations
- local persistence, cache fallbacks, cooldown state, and proof archives
- careful language boundaries around research signals, risk, and user execution responsibility

---

## Core Features

## 1. Market Structure Scanner

The market scanner evaluates Binance perpetual markets using structural and liquidity-based indicators.

It screens for conditions such as:

- relative volume expansion
- open-interest acceleration
- volatility compression and expansion
- futures-versus-spot activity
- float-adjusted participation
- liquidity asymmetry
- CEX deposit notional versus visible ask depth
- concentration-gated venue-inventory stress
- concentration-adjusted turnover
- abnormal participation relative to recent baseline
- structural squeeze conditions
- case-study analogue matching for RAVE/LAB/SIREN/RIVER/STO-style structures, with RAVEUSDT on 2026-04-18 and LABUSDT on 2026-05-11 treated as historical anchors
- dashboard `Convex Long` buckets that only promote rows after the hard holder, Binance+Bitget, and 60D no-pump thesis gates pass; raw convex setup signals stay visible as watchlist context with the missing gate printed inline

The output is intended to help prioritize markets for further research rather than produce standalone trade instructions.

Results are surfaced through the Streamlit dashboard and can also be distributed through Discord integrations.

---

## 2. On-Chain Concentration Analytics

The repository includes a dedicated concentration-analysis engine for evaluating token distribution quality and tradable-float characteristics across ERC-20 and BEP-20 assets.

The concentration engine supports:

- contract and token metadata resolution
- top-holder concentration analysis
- holder classification heuristics
- linked-wallet clustering
- adjusted float estimation
- raw and adjusted concentration metrics
- Gini-style concentration analysis
- HHI-style concentration analysis
- liquidity and custody filtering
- thin-float detection
- structural-risk ranking

The scanner distinguishes between different holder types, including:

- centralized exchange wallets
- custody wallets
- liquidity pools
- bridges and wrapped-token contracts
- staking contracts
- vesting contracts
- treasury and reserve wallets
- multisig wallets
- burn addresses
- owner/admin-linked wallets
- unresolved whale clusters

This helps separate nominal supply concentration from potentially relevant tradable-float concentration.

Local scan outputs are stored in:

```text
data/concentration_scanner.sqlite
```

Optional API keys are read from environment variables:

```text
COINGECKO_API_KEY=
ETHERSCAN_V2_API_KEY=XFYBWMNYA62ZRW6PK252CVYIYM2H5GZ6YP
ETHERSCAN_API_KEY=XFYBWMNYA62ZRW6PK252CVYIYM2H5GZ6YP
BSCSCAN_API_KEY=XFYBWMNYA62ZRW6PK252CVYIYM2H5GZ6YP
ARBISCAN_API_KEY=XFYBWMNYA62ZRW6PK252CVYIYM2H5GZ6YP
ARBSCAN_API_KEY=XFYBWMNYA62ZRW6PK252CVYIYM2H5GZ6YP
```

The scanner uses structural and probabilistic classification methods only. It does not make legal, regulatory, or compliance assertions from on-chain data alone.

---

## 3. Streamlit Dashboard

The Streamlit dashboard provides an interactive research interface for reviewing scanner results.

Dashboard functionality includes:

- live scan controls
- ranked candidate tables
- concentration overlays
- holder composition summaries
- token contract inspection
- cached scan comparison
- local persistence of scanner outputs
- discretionary review of structural market conditions

The dashboard is intended for fast review, filtering, and monitoring of markets that show unusual activity or concentration patterns.

Run the dashboard with:

```powershell
streamlit run app.py
```

---

## 4. Discord Webhook Alerts

The repository supports Discord webhook alerts for distributing scanner results to a Discord channel.

Webhook alerts support:

- ranked scan summaries
- configurable top-N filtering
- configurable score thresholds
- per-symbol cooldowns
- strict 90%+ holder-concentration evidence gate with ETH/BNB/ARB chain, contract, and explorer holder-source snapshot backing
- Binance+Bitget thesis venue gating by default, with Gate treated as optional supporting evidence
- dedicated CEX-flow alert source for concentrated wallet-to-exchange movement
- venue-inventory stress notes when CEX deposits are large versus visible liquidity
- case-study analogue lines for fast pattern triage, including the RAVE 2026-04-18 and LAB 2026-05-11 historical anchors when matched
- optional holder composition summaries
- compact thesis, evidence stack, next-check, invalidation, and liquidity-risk lines
- scheduled monitoring workflows

Example `.env` configuration:

```text
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
DISCORD_CONVEX_ALERTS_ENABLED=1
DISCORD_CONVEX_ALERT_TOP_N=10
DISCORD_CONVEX_ALERT_MIN_SCORE=0
DISCORD_CONVEX_ALERT_COOLDOWN_MINUTES=240
DISCORD_REQUIRE_BITGET_OR_GATE=1
DISCORD_ASSUME_SYMBOLS_ARE_BINANCE_PERPS=0
```

Fresh scans write `binance_perp_universe=true` before Discord gates run. Keep `DISCORD_ASSUME_SYMBOLS_ARE_BINANCE_PERPS=0` so Binance evidence must come from an explicit marker, Binance venue share, or Binance top-venue text. Set it to `1` only for legacy Binance-only cache files that lack the marker. Discord thesis screens such as `/radar`, `/ravelab`, `/crimepump`, `/precrime`, `/pumpwatch`, `/setupscore`, `/coincheck`, `/alpha`, `/high thesis_only:true`, and `/low thesis_only:true` always require explicit Binance evidence and 60D no-pump proof; candidate surfaces add their core gates such as low-float/high-FDV, short/squeeze fuel, and not-late structure before showing rows. They do not use symbol text as proof.

Per-symbol cooldown state is stored locally in:

```text
data/discord_convex_alert_state.csv
```

---

## 5. Discord Bot Commands

The repository also includes a lightweight Discord bot interface for querying cached scanner results directly from Discord.

Supported commands include:

```text
/commands
/help
/alpha [limit]
/convex [limit]
/shorts
/funding [side] [limit] [period] [min_abs_funding_pct]
/radar [min_tokens] [whale_flow_min_tokens] [limit] [lookback_hours] [trigger] [breakout_windows]
/precrime [min_score] [min_tokens] [limit] [lookback_hours] [min_whale_pct] [require_target_flow] [require_quiet] [require_behavior_gate] [require_dormant_60d]
/crimepump [min_tokens] [whale_flow_min_tokens] [limit] [lookback_hours] [trigger] [breakout_windows]
/ravelab [min_score] [min_archetype] [min_whale_pct] [min_squeeze_score] [min_history_days] [max_recent_pump_pct] [min_tokens] [whale_flow_min_tokens] [limit] [lookback_hours] [breakout_windows] [style] [require_quiet] [require_target_flow] [require_breakout_high] [require_whale_origin_flow] [trigger_filter] [near_miss_limit] [detail]
/prime [min_tokens] [whale_flow_min_tokens] [limit] [lookback_hours] [trigger] [breakout_windows]
/pumpwatch [min_score] [min_tokens] [limit] [lookback_hours] [min_whale_pct] [require_target_flow] [require_dormant_60d]
/setupscore [min_score] [min_tokens] [limit] [lookback_hours] [min_short_pct] [min_whale_pct]
/flowproof <symbol> [min_tokens] [lookback_hours]
/coincheck <symbol> [min_score] [min_tokens] [lookback_hours] [min_short_pct] [min_whale_pct]
/floattrap [min_score] [limit]
/squeezeready [min_short_pct] [min_score] [limit]
/cextargets [min_tokens] [limit] [lookback_hours]
/whales [min_pct] [bucket] [limit] [require_contract_hint] [max_symbols] [refresh]
/high [days] [limit] [thesis_only]
/low [days] [limit] [thesis_only]
/terminal
/timing
/corr [threshold] [limit]
/cexflow [min_tokens] [limit] [lookback_hours] [min_whale_pct] [require_holder_evidence] [require_venue_gate]
/cexdiag [min_tokens] [lookback_hours] [min_whale_pct] [require_holder_evidence] [require_venue_gate] [symbol_limit]
/earlyflow [min_tokens] [limit] [lookback_hours] [min_whale_pct] [require_holder_evidence] [require_venue_gate]
/flowcoin <symbol> [min_tokens] [lookback_hours]
/flowstress [min_tokens] [limit] [lookback_hours] [require_venue_gate]
/flowblocked [min_tokens] [limit] [lookback_hours]
/flowhealth [min_tokens] [lookback_hours] [symbol_limit]
/sethflow [min_tokens] [limit] [lookback_hours] [min_short_pct] [min_whale_pct] [require_whale_origin_flow]
/dossier <symbol>
/coin <symbol>
/startbot [mode] [scan_mode]
/stopbot
/tradebot_status
/convex_status
/convex_scoreboard
/convex_archive
/sync_commands
/<configured-symbol-alias>
```

Use `/help` or `/commands` inside Discord when you want the operator map. It labels `/radar` as the primary hard-gated queue, `/ravelab` as the diagnostic microscope, and the flow/holder commands as diagnostics rather than candidate lists.

The bot can retrieve:

- a strict core-thesis alpha brief across structure, timing, CEX flow, scanner score, and short-account fuel after 90%+ top-10 holder control with ETH/BNB/ARB chain+contract explorer holder-source snapshot evidence, Binance+Bitget, 60D no-pump, low-float/high-FDV, short crowd plus squeeze fuel, and not-late gates
- latest cached scanner rankings
- full cached list of symbols where more than 50% of accounts are short
- live Binance funding-carry rankings split into shorts-receive-positive and longs-receive-negative sides
- a `/precrime` radar for quiet latent setups after the hard explorer holder-source snapshot, Binance+Bitget thesis gates, default 60D no-pump/dormancy proof, and low-float/high-FDV structure proof: holder/control concentration, target-CEX inventory tells, short-fuse perps, thin books as amplifiers, and no-chase low activity
- a primary `/radar` operator queue for the main thesis: top-10 whale-control threshold with ETH/BNB/ARB chain+contract explorer holder-source snapshot evidence, Binance+Bitget, float/FDV trap evidence, 60D no-pump/dormancy, squeeze fuel, early/no-chase, and optional trigger filters for massive top-holder-origin whale-CEX flow, generic target-CEX flow, breakout highs, triggered-only, or core-watch rows
- `/crimepump` as a legacy blunt-name alias and `/prime` as a short alias for the same compact hard-gated queue
- a dedicated `/ravelab` strict early-structure microscope requiring observed top-10 whale-control concentration at the requested threshold with ETH/BNB/ARB chain+contract explorer holder-source snapshot evidence, Binance+Bitget trading evidence, float/FDV trap evidence, at least 60 days of history plus verified 60D closed-candle no-pump/no-chase dormancy, and a squeeze stack that pairs short crowding with perp/OI/liquidation/funding-flip/build fuel before ranking RAVE/LAB analogues by hard-gate completion first; it reapplies lifecycle and short-squeeze models in the Discord path, then prints a hard-gate funnel, trigger-lane counts, a trigger/core-watch queue, compact stage labels, blocker text, `crime`/`ssq` model reads, a `flowMech` forced-flow/exhaustion read for short crowd, short-build/fade, OI, and volume, holder source, count, chain, contract, float-score, and FDV/MC details, 60D pump-proof source, venue provenance, optional top-holder-origin CEX-flow filtering that respects `whale_flow_min_tokens` while generic target-CEX flow still respects `min_tokens`, optional 1D/2D/3D/4D/etc high-breakout filtering after those hard gates, a blocked high-signal near-miss tail controlled by `near_miss_limit`, and `detail:true` for the full evidence stack
- a single `/pumpwatch` board that rank-orders early pump candidates across target-CEX flow, whale/control, low float, short-squeeze fuel, timing, venue support, and not-late risk after the same default 90%+ explorer holder-source snapshot, Binance+Bitget, 60D no-pump/dormancy, low-float/high-FDV, squeeze-fuel, and not-late gates
- a strict full-thesis `/setupscore` ranking for target-CEX flow, 90%+ top-10 holder dominance with ETH/BNB/ARB chain+contract explorer holder-source snapshot evidence, mandatory Binance+Bitget trading evidence, 60D no-pump proof, low float/high FDV, short crowd plus squeeze fuel, and not-late structure
- symbol-level `/flowproof`, `/coincheck`, `/coin`, and `/dossier` views that separate base thesis, core setup, and CEX-flow triggers; transfer labels cannot masquerade as venue proof, and a clean core structure no longer looks rejected merely because the CEX-flow trigger has not appeared yet
- low-float/high-FDV, squeeze-ready, and Binance/Gate/Bitget target-transfer diagnostic boards that label raw rows separately from `baseThesis Y` rows
- top terminal market-structure evidence rows
- top timing-quality rows
- BTC low-correlation rows with the actual correlation window used per symbol plus `baseThesis Y/N`
- concentration-gated wallet-to-CEX flow rows
- CEX-flow coverage diagnostics for missing hints, holder-gate attempts, explorer errors, empty explorer HTML parses, venue-gate filtering, and attempted-symbol review
- lower-threshold early wallet-to-CEX transfer sweeps, for low-float names where 500k tokens is too blunt
- symbol-specific wallet-to-CEX flow checks with a custom transfer floor
- CEX deposit inventory-stress rankings versus visible ask depth and 24h turnover
- Etherscan V2 token-transfer API fallback when explorer HTML is blocked or returns no parsable transfer rows, with unlabelled-transfer diagnostics that surface destination addresses needing CEX wallet labels before rows count as verified flow
- CEX-flow health checks covering API keys and local address-label coverage
- a full massive target-CEX flow -> top-holder sender -> 90%+ top-10 holder concentration/evidence -> low-float/FDV -> short crowd plus squeeze fuel -> dormant-structure checklist via `/sethflow`
- top-10-first whale-dominance rankings, with top100 retained as diagnostic context
- high/low breakout rows for any 1D-1499D lookback, using dashboard columns when present and live Binance daily candles for custom windows; `thesis_only:true` keeps only rows that also pass top10 holder evidence, Binance+Bitget, 60D no-pump proof, low-float/high-FDV, short crowd plus squeeze fuel, and not-late structure
- symbol-level market structure metrics
- live scan context
- holder composition summaries
- contract metadata when available
- trailing proof-engine outcome summaries
- local proof-archive exports
- trade-bot candidate selection that reuses the strict thesis plus core setup gates before any paper/live setup is chosen

Example `.env` configuration:

```text
DISCORD_BOT_TOKEN=
DISCORD_GUILD_ID=
DISCORD_ALLOWED_CHANNEL_ID=
DISCORD_CLEAR_GLOBAL_COMMANDS_ON_GUILD_SYNC=0
DISCORD_CONVEX_COMMAND_TOP_N=10
DISCORD_ALPHA_TOP_N=15
DISCORD_ALPHA_BRIEF_MIN_SCORE=35
DISCORD_EARLY_FLOW_MIN_TOKENS=20000
DISCORD_RAVELAB_WHALE_FLOW_MIN_TOKENS=100000
DISCORD_LOGIN_RETRY_SECONDS=90
DISCORD_DEFAULT_USER_TIER=pro
DISCORD_FREE_SAMPLE_TOP_N=3
DISCORD_PAID_ROLE_IDS=
DISCORD_PRO_ROLE_IDS=
```

`DISCORD_GUILD_ID` is recommended because guild slash commands usually sync faster than global Discord commands.

Run the bot with:

```powershell
run_discord_convex_bot.bat
```

See [Discord alpha workflow](docs/discord-alpha-workflow.md) for the alert taxonomy, operator loop, and recommended command sequence.

---

## 6. Proof Archive and Outcome Tracking

Discord alerts are archived locally so scanner quality can be measured over time instead of judged by screenshots.

The append-only archive writes one JSON line per alert:

```text
data/archive/flags/YYYY-MM-DD.jsonl
```

Each record includes the ticker, timestamp, flagged price, scanner score, scan mode, reason tags, holder concentration metrics, OI/volume state, liquidity/risk tags, source URL when available, the raw bot output, and a `research_tooling_only` status field.

Outcome refreshes append versioned JSONL records:

```text
data/archive/outcomes/YYYY-MM-DD_outcomes.jsonl
```

Outcomes track max upside after 1h, 4h, 24h, and 7d, max drawdown after the flag, time to +20%, time to +50%, time to 2x, whether OI/volume confirmed, and whether the structure invalidated by the current rules.

Weekly report generation writes:

```text
data/archive/reports/weekly_YYYY-WW.md
data/archive/reports/weekly_YYYY-WW.csv
```

The legacy CSV summary remains available at:

```text
data/discord_convex_alert_archive.csv
```

Useful configuration:

```text
DISCORD_PROOF_ARCHIVE_ROOT=data/archive
DISCORD_PROOF_REFRESH_ENABLED=1
DISCORD_PROOF_REFRESH_MAX_ROWS=12
DISCORD_SCOREBOARD_REFRESH_OUTCOMES=1
DISCORD_WEEKLY_REPORT_WRITE_ENABLED=1
```

---

## 7. Automated Discord Watcher

The watcher service supports scheduled rescanning and automatic posting of newly detected scanner candidates.

Example configuration:

```text
DISCORD_WATCHER_SCAN_MODE=Deep
DISCORD_WATCHER_ALERT_SOURCE=terminal_timing
DISCORD_WATCHER_SCAN_INTERVAL_SECONDS=180
DISCORD_WATCHER_TOP_N=25
DISCORD_WATCHER_REALERT_HOURS=12
DISCORD_WATCHER_MIN_TERMINAL_SCORE=60
DISCORD_WATCHER_MIN_TIMING_SCORE=55
DISCORD_WATCHER_ALLOWED_TIMING_STATES=Coiling,Triggering,Confirmed
DISCORD_HOLDER_COMPOSITION_ENABLED=1
```

`DISCORD_WATCHER_ALERT_SOURCE` controls what the automatic watcher posts:

- `terminal_timing` requires the core thesis gate plus both structural evidence and current timing quality.
- `terminal` alerts from the core-gated structural evidence ranking only.
- `timing` alerts from the core-gated timing ranking only.
- `cex_flow` alerts from core-gated, concentration-gated wallet-to-CEX token-transfer flow.
- `convex` keeps the older Convex Long source, but rows still pass the core thesis gates before posting.

The watcher stores state locally so unchanged candidates are not reposted every scan:

```text
data/discord_convex_watcher_state.csv
```

Run the watcher with:

```powershell
run_discord_convex_watcher.bat
```

---

## 8. Holder Composition Summaries

Discord alerts and dashboard views can attach compact holder-composition summaries when token contract data is available.

Holder summaries may include:

- top-holder concentration
- top 5 / top 10 observed concentration
- holder count
- total supply context
- whale / shark / dolphin / shrimp-style holder buckets
- known holder categories
- unresolved wallet concentration
- adjusted float indicators

Contract resolution uses, where available:

- scan result columns
- local contract hint files
- environment variable overrides
- explorer-compatible token metadata
- public token lists

Failures in holder composition retrieval are non-blocking. Scanner alerts can still post even if holder data is temporarily unavailable.

---

## 9. Contract Resolution Tooling

The repository includes utilities for maintaining local contract mappings used by the scanner, dashboard, and Discord integrations.

Bulk-fill local contract hints with:

```powershell
python .\scripts\build_discord_holder_contracts.py --limit 6000
```

Generated files:

```text
data/discord_holder_contracts.csv
data/discord_holder_contracts_spreadsheet_safe.csv
data/discord_holder_contracts_full.csv
```

Manual contract hints can be added by copying:

```text
discord_holder_contracts.example.csv
```

to:

```text
data/discord_holder_contracts.csv
```

Example row:

```text
symbol,chain,contract_address
CHIPUSDT,arbitrum,0x0C1c1C109FE34733fca54b82d7B46B75CFb71F6e
```

Quick one-line hints can also be provided through `.env`:

```text
DISCORD_HOLDER_CONTRACTS=CHIPUSDT:arbitrum:0x0C1c1C109FE34733fca54b82d7B46B75CFb71F6e
DISCORD_HOLDER_COMPOSITION_MAX_HOLDERS=100
DISCORD_HOLDER_COMPOSITION_TOP_HOLDERS=0
```

When opening contract CSVs in Excel or Google Sheets, import `contract_address` as text. If a contract address is converted into scientific notation, the address has been corrupted and should be reloaded from the generated CSV.

---

## Technology Stack

The project uses:

- Python
- Streamlit
- SQLite
- Binance market-data APIs
- Discord.py and Discord webhooks
- Etherscan-family explorers and Etherscan V2 token-transfer APIs
- GoPlus token-security data
- local CSV and SQLite persistence

---

## Local Setup

Install dependencies using the repository's Python environment setup, then configure optional environment variables as needed.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Example `.env` template:

```text
COINGECKO_API_KEY=
ETHERSCAN_V2_API_KEY=XFYBWMNYA62ZRW6PK252CVYIYM2H5GZ6YP
ETHERSCAN_API_KEY=XFYBWMNYA62ZRW6PK252CVYIYM2H5GZ6YP
BSCSCAN_API_KEY=XFYBWMNYA62ZRW6PK252CVYIYM2H5GZ6YP
ARBISCAN_API_KEY=XFYBWMNYA62ZRW6PK252CVYIYM2H5GZ6YP
ARBSCAN_API_KEY=XFYBWMNYA62ZRW6PK252CVYIYM2H5GZ6YP
CEX_ADDRESS_BOOK_FILE=data/cex_address_book.csv
CEX_ADDRESS_LABELS=

DISCORD_WEBHOOK_URL=
DISCORD_BOT_TOKEN=
DISCORD_GUILD_ID=
DISCORD_ALLOWED_CHANNEL_ID=
```

Run the dashboard:

```powershell
streamlit run app.py
```

Run the Discord bot:

```powershell
run_discord_convex_bot.bat
```

Run the Discord watcher:

```powershell
run_discord_convex_watcher.bat
```

---

## Design Philosophy

The project focuses on observable structure rather than black-box prediction.

Core design priorities:

- transparent scanner logic
- reproducible local outputs
- practical dashboard review
- persistent monitoring workflows
- clear separation between market data and on-chain data
- conservative language around structural risk
- no unsupported legal or predictive claims

The repository is intended to demonstrate practical crypto market-data engineering, research workflow design, dashboard development, and real-time monitoring infrastructure.

---

## Reviewer Guide

- [Demo walkthrough](docs/demo-walkthrough.md): install, test, dashboard, Discord, proof loop.
- [Architecture](docs/architecture.md): module map and data flow.
- [Discord alpha workflow](docs/discord-alpha-workflow.md): operator loop and alert taxonomy.
- [Sample Discord output](docs/sample-discord-output.md): representative `/alpha`, alert, `/cexflow`, and scoreboard text.

Continuous test coverage is configured in [.github/workflows/tests.yml](.github/workflows/tests.yml).

---

## Disclaimer

This repository is for research and educational purposes only. It does not provide financial advice, trading advice, legal conclusions, or compliance determinations.
