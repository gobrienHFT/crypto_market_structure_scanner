# practical_market_maker

## Ultra Micro Runner

`run_ultra_micro_market_maker.bat` runs the most defensive live futures loop in this repo:

- pulls from the full Binance USDT perpetual universe, excluding TradFi by default
- tuned for a roughly 20 euro account: starts at 1x and can only raise as far as 3x
- caps leverage from recent 1-minute volatility, so violent coins are skipped instead of force-traded
- uses isolated margin, maker-only entries, 50% account allocation, positive net-profit targets, and an emergency ROE close
- persists the `F` dashboard summary to `logs/ultra_micro_stats.csv`
- persists closed-trade accounting to `logs/ultra_micro_trades.csv`
- restarts automatically if the process exits

Important: Binance USD-M futures currently enforce a 5 USDT minimum notional on listed perpetuals. With about 20 euro of equity, that minimum is reachable without extreme leverage, so the runner no longer allows the 125x tiny-equity mode. Rule 1 is do not blow up the account.

## Crime Pump On-Chain Concentration Scanner

The Streamlit dashboard now includes an `On-Chain Concentration` mode for structural-risk analysis of ERC-20/BEP-20 holder distribution:

- resolves token metadata and chain contracts from CoinGecko
- fetches top holder data through Etherscan-family explorer adapters for Ethereum and BNB Chain
- classifies exchange, liquidity pool, bridge, staking, vesting, treasury, multisig, owner/admin, unexplained whale, burn, and unknown holders
- computes raw and adjusted concentration, adjusted float, Gini, HHI, RaveDAO-type thin-float metrics, controlled-float flags, wrapped-representation guardrails, and structural-risk scores
- adds a manipulable-whale filter that separates CEX/custody/storage/vesting/bridge/wrapper/LP/burn/reserve holders from unresolved wallets and linked wallet clusters that may control tradable float
- exposes a `Manipulable Whales` leaderboard sorted by largest manipulable holder, manipulable-whale score, cluster supply, and filtered top-holder control
- adds a Binance perpetual universe scanner that automatically matches futures symbols to CoinGecko IDs/contracts and ranks controlled-float squeeze candidates by insider/whale concentration, linked clusters, futures-vs-spot volume, OI pressure, adjusted-float churn, low-float/FDV gaps, and RaveDAO-type structure
- stores scan results in `data/concentration_scanner.sqlite`
- supports manual holder category overrides with immediate recomputation
- includes cached fixture scans for RaveDAO-like, LAB-like, BIO-like, and wrapped KAVA-like acceptance cases

API keys are read from environment variables only:

- `COINGECKO_API_KEY`
- `ETHERSCAN_API_KEY`
- `BSCSCAN_API_KEY`

The scanner uses structural-risk language only. It does not generate legal conclusions from on-chain data alone.

## Discord Convex Long Alerts

The breakout dashboard can post every scanned `Convex Long` setup to a Discord channel through a channel webhook.

1. In Discord, open your channel settings, choose `Integrations`, create a webhook, and copy the webhook URL.
2. Add this to your local `.env` file:

```text
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
DISCORD_CONVEX_ALERTS_ENABLED=1
DISCORD_CONVEX_ALERT_TOP_N=10
DISCORD_CONVEX_ALERT_MIN_SCORE=0
DISCORD_CONVEX_ALERT_COOLDOWN_MINUTES=240
```

The dashboard sends alerts after `Scan now` completes. Per-symbol cooldown state is stored in
`data/discord_convex_alert_state.csv`, which is ignored by git.

To call the latest scan from Discord chat, create a Discord application bot and add these to `.env`:

```text
DISCORD_BOT_TOKEN=your_bot_token
DISCORD_GUILD_ID=your_server_id
DISCORD_ALLOWED_CHANNEL_ID=your_pre_pump_channel_id
DISCORD_CONVEX_COMMAND_TOP_N=10
DISCORD_LOGIN_RETRY_SECONDS=90
```

Run `run_discord_convex_bot.bat`, then use `/convex` in Discord to pull the latest cached scan.
Use `/convex_status` to check whether the dashboard has written a cache yet. `DISCORD_GUILD_ID`
is recommended because guild slash commands sync almost immediately; global slash commands can take longer.

For automatic no-click alerts, run `run_discord_convex_watcher.bat`. It scans on a timer and posts only newly appearing
`Convex Long` names through `DISCORD_WEBHOOK_URL`.

```text
DISCORD_WATCHER_SCAN_MODE=Deep
DISCORD_WATCHER_SCAN_INTERVAL_SECONDS=180
DISCORD_WATCHER_TOP_N=25
DISCORD_WATCHER_REALERT_HOURS=12
DISCORD_HOLDER_COMPOSITION_ENABLED=1
```

The watcher stores state in `data/discord_convex_watcher_state.csv` so a coin already active as Convex is not reposted
every scan.

Discord alerts also try to attach a compact holder composition summary for every new Convex name:

- contract resolution uses scan columns when present, then `data/discord_holder_contracts.csv`, then `DISCORD_HOLDER_CONTRACTS`
- holder rows are pulled from Etherscan-family `generic-tokenholders2` pages and GoPlus token-security data, without API keys
- summaries include top 1/5/10/observed concentration, holder count, total supply, whale/shark/dolphin/shrimp-style buckets, and a few top holders
- failures are non-blocking, so a Convex alert still posts even if holder data is temporarily unavailable

To add manual contract hints, copy `discord_holder_contracts.example.csv` to `data/discord_holder_contracts.csv` and add rows:

```text
symbol,chain,contract_address
CHIPUSDT,arbitrum,0x0C1c1C109FE34733fca54b82d7B46B75CFb71F6e
```

You can also use `.env` for quick one-line hints:

```text
DISCORD_HOLDER_CONTRACTS=CHIPUSDT:arbitrum:0x0C1c1C109FE34733fca54b82d7B46B75CFb71F6e
DISCORD_HOLDER_COMPOSITION_MAX_HOLDERS=100
DISCORD_HOLDER_COMPOSITION_TOP_HOLDERS=3
```
