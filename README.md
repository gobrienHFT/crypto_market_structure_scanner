# practical_market_maker

## Ultra Micro Runner

`run_ultra_micro_market_maker.bat` runs the most defensive live futures loop in this repo:

- pulls from the full Binance USDT perpetual universe, excluding TradFi by default
- starts at 1x and only raises leverage when exchange minimum notional requires it
- caps leverage from recent 1-minute volatility, so violent coins are skipped instead of force-traded
- uses isolated margin, maker-only entries, tiny minimum net-profit targets, and an emergency ROE close
- persists the `F` dashboard summary to `logs/ultra_micro_stats.csv`
- persists closed-trade accounting to `logs/ultra_micro_trades.csv`
- restarts automatically if the process exits

Important: Binance USD-M futures currently enforce a 5 USDT minimum notional on listed perpetuals. With 0.02 USDT equity, even 125x leverage only gives about 2.50 USDT notional before fees, so the runner will wait/scan/log rather than place impossible or reckless orders. Rule 1 is do not blow up the account.
