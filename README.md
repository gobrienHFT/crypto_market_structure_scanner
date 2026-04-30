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
