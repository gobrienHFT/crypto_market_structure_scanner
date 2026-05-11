Overview

crypto_market_structure_scanner is a research and monitoring framework for identifying structurally unusual crypto assets across Binance perpetual markets and public on-chain data.

The project combines:

market structure analytics
liquidity and float analysis
holder concentration modelling
futures/open-interest screening
Discord-based alerting and monitoring
interactive Streamlit dashboards

The repository is designed for research, monitoring, and signal discovery workflows rather than automated execution.

Core Features
Market Structure Scanner

The scanner evaluates Binance perpetual markets using a range of structural and liquidity-based metrics, including:

relative volume expansion
open-interest changes
volatility compression/expansion
float-adjusted activity
futures-versus-spot participation
liquidity asymmetry
concentration-adjusted turnover
structural squeeze conditions

Results are surfaced through an interactive Streamlit dashboard and can be exported or distributed through Discord integrations.

On-Chain Concentration Analytics

The platform includes a dedicated on-chain concentration engine for evaluating token distribution quality and tradable float characteristics across ERC-20 and BEP-20 assets.

Features include:

contract and token metadata resolution
top-holder analysis
holder classification heuristics
linked-wallet clustering
adjusted float estimation
concentration scoring
liquidity and custody filtering
thin-float detection
structural risk ranking

The system distinguishes between:

exchange wallets
liquidity pools
treasury/reserve wallets
bridges/wrappers
vesting contracts
multisigs
unresolved whale clusters

This allows concentration metrics to focus more directly on potentially tradable circulating supply rather than nominal supply figures.

The scanner stores outputs locally in:

data/concentration_scanner.sqlite

Supported optional API integrations:

COINGECKO_API_KEY
ETHERSCAN_API_KEY
BSCSCAN_API_KEY

The repository uses probabilistic and structural classification methods only and does not make legal or compliance assertions.

Streamlit Dashboard

The Streamlit interface provides:

live scanner controls
ranked candidate tables
concentration overlays
holder composition summaries
contract inspection
scan persistence
cached historical comparisons

The dashboard is designed for rapid discretionary review and iterative market monitoring.

Discord Integrations

The repository includes optional Discord integrations for automated scan distribution and remote monitoring workflows.

Webhook Alerts

Scanner results can be automatically posted to Discord channels using webhooks.

Supported features:

ranked scan summaries
configurable cooldowns
top-N filtering
threshold-based alerting
automated monitoring loops
holder composition attachments

Example environment configuration:

DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
DISCORD_CONVEX_ALERTS_ENABLED=1
DISCORD_CONVEX_ALERT_TOP_N=10
DISCORD_CONVEX_ALERT_COOLDOWN_MINUTES=240
Discord Bot Commands

The repository also supports a lightweight Discord bot interface for querying cached scanner outputs directly from Discord.

Supported commands include:

/convex
/convex_status
/coin <symbol>

The bot can retrieve:

latest scanner rankings
symbol-level structural metrics
holder composition summaries
cached contract metadata

Example environment configuration:

DISCORD_BOT_TOKEN=your_bot_token
DISCORD_GUILD_ID=your_server_id
DISCORD_ALLOWED_CHANNEL_ID=your_channel_id
Automated Monitoring Runner

The watcher service supports scheduled rescanning and automatic reposting of newly detected candidates.

Example configuration:

DISCORD_WATCHER_SCAN_INTERVAL_SECONDS=180
DISCORD_WATCHER_TOP_N=25
DISCORD_WATCHER_REALERT_HOURS=12

State persistence prevents repeated reposting of unchanged candidates.

Holder Contract Resolution

The repository includes tooling for maintaining local token contract mappings used by the scanner and Discord integrations.

Bulk contract resolution utility:

python .\scripts\build_discord_holder_contracts.py --limit 6000

Generated outputs include:

data/discord_holder_contracts.csv
data/discord_holder_contracts_spreadsheet_safe.csv
data/discord_holder_contracts_full.csv

Manual overrides are also supported.

Example:

symbol,chain,contract_address
CHIPUSDT,arbitrum,0x...
Design Philosophy

The repository focuses on:

structural market analysis
observable liquidity conditions
float dynamics
positioning asymmetry
concentration-adjusted participation
operational monitoring workflows

The emphasis is on transparent research tooling, reproducible scans, and practical monitoring infrastructure rather than predictive claims or opaque signal generation.

Technology Stack
Python
Streamlit
SQLite
Discord API
Binance market data APIs
Etherscan-family explorers
GoPlus token-security integrations
Local Setup

Example environment variables:

COINGECKO_API_KEY=
ETHERSCAN_API_KEY=
BSCSCAN_API_KEY=

DISCORD_WEBHOOK_URL=
DISCORD_BOT_TOKEN=
DISCORD_GUILD_ID=
DISCORD_ALLOWED_CHANNEL_ID=

Launch the dashboard:

streamlit run dashboard.py

Run the Discord watcher:

run_discord_convex_watcher.bat

Run the Discord bot:

run_discord_convex_bot.bat
