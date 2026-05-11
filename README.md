# crypto_market_structure_scanner

Research and monitoring framework for identifying structurally unusual crypto assets using market microstructure, liquidity, derivatives activity, and on-chain concentration analysis.

The repository combines a Streamlit research dashboard, Binance perpetual-market screening, on-chain holder concentration analytics, Discord alerting, and contract-resolution tooling into one practical monitoring workflow.

It is designed for research, screening, and discretionary review. It is not presented as an automated trading system.

---

## Overview

`crypto_market_structure_scanner` helps surface crypto assets with unusual structural conditions across market data and on-chain holder data.

The project combines:

- Binance perpetual market screening
- on-chain holder concentration analytics
- float and liquidity analysis
- futures/open-interest monitoring
- holder composition analysis
- Discord webhook alerts
- Discord bot query commands
- Streamlit dashboards
- contract-resolution tooling
- persistent local scan storage and ranking

The goal is to identify assets worth further review by combining observable market behaviour with token-distribution structure.

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
- concentration-adjusted turnover
- abnormal participation relative to recent baseline
- structural squeeze conditions

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
ETHERSCAN_API_KEY=
BSCSCAN_API_KEY=
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
streamlit run dashboard.py
```

---

## 4. Discord Webhook Alerts

The repository supports Discord webhook alerts for distributing scanner results to a Discord channel.

Webhook alerts support:

- ranked scan summaries
- configurable top-N filtering
- configurable score thresholds
- per-symbol cooldowns
- optional holder composition summaries
- scheduled monitoring workflows

Example `.env` configuration:

```text
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
DISCORD_CONVEX_ALERTS_ENABLED=1
DISCORD_CONVEX_ALERT_TOP_N=10
DISCORD_CONVEX_ALERT_MIN_SCORE=0
DISCORD_CONVEX_ALERT_COOLDOWN_MINUTES=240
```

Per-symbol cooldown state is stored locally in:

```text
data/discord_convex_alert_state.csv
```

---

## 5. Discord Bot Commands

The repository also includes a lightweight Discord bot interface for querying cached scanner results directly from Discord.

Supported commands include:

```text
/convex
/convex_status
/coin <symbol>
```

The bot can retrieve:

- latest cached scanner rankings
- symbol-level market structure metrics
- live scan context
- holder composition summaries
- contract metadata when available

Example `.env` configuration:

```text
DISCORD_BOT_TOKEN=
DISCORD_GUILD_ID=
DISCORD_ALLOWED_CHANNEL_ID=
DISCORD_CONVEX_COMMAND_TOP_N=10
DISCORD_LOGIN_RETRY_SECONDS=90
```

`DISCORD_GUILD_ID` is recommended because guild slash commands usually sync faster than global Discord commands.

Run the bot with:

```powershell
run_discord_convex_bot.bat
```

---

## 6. Automated Discord Watcher

The watcher service supports scheduled rescanning and automatic posting of newly detected scanner candidates.

Example configuration:

```text
DISCORD_WATCHER_SCAN_MODE=Deep
DISCORD_WATCHER_SCAN_INTERVAL_SECONDS=180
DISCORD_WATCHER_TOP_N=25
DISCORD_WATCHER_REALERT_HOURS=12
DISCORD_HOLDER_COMPOSITION_ENABLED=1
```

The watcher stores state locally so unchanged candidates are not reposted every scan:

```text
data/discord_convex_watcher_state.csv
```

Run the watcher with:

```powershell
run_discord_convex_watcher.bat
```

---

## 7. Holder Composition Summaries

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

## 8. Contract Resolution Tooling

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
- Discord API
- Etherscan-family explorers
- GoPlus token-security data
- local CSV and SQLite persistence

---

## Local Setup

Install dependencies using the repository's Python environment setup, then configure optional environment variables as needed.

Example `.env` template:

```text
COINGECKO_API_KEY=
ETHERSCAN_API_KEY=
BSCSCAN_API_KEY=

DISCORD_WEBHOOK_URL=
DISCORD_BOT_TOKEN=
DISCORD_GUILD_ID=
DISCORD_ALLOWED_CHANNEL_ID=
```

Run the dashboard:

```powershell
streamlit run dashboard.py
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

## Disclaimer

This repository is for research and educational purposes only. It does not provide financial advice, trading advice, legal conclusions, or compliance determinations.
