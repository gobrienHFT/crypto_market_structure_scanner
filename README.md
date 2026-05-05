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
- stores scan results in `data/concentration_scanner.sqlite`
- supports manual holder category overrides with immediate recomputation
- includes cached fixture scans for RaveDAO-like, LAB-like, BIO-like, and wrapped KAVA-like acceptance cases

API keys are read from environment variables only:

- `COINGECKO_API_KEY`
- `ETHERSCAN_API_KEY`
- `BSCSCAN_API_KEY`

The scanner uses structural-risk language only. It does not generate legal conclusions from on-chain data alone.
