@echo off
cd /d "%~dp0"
if not exist logs mkdir logs

:loop
python ldo_roe_loop_bot.py --live --confirm-live I_UNDERSTAND_THIS_CAN_LIQUIDATE --symbol AUTO --mode flow --position-side BOTH --margin-type ISOLATED --scan-profile liquidity --scan-symbols ALL --scan-min-quote-volume-usdt 1000000 --scan-max-spread-pct 0.08 --scan-min-depth-1pct-usdt 2500 --scan-max-symbols 80 --scan-allow-against-momentum --leverage 1 --max-min-notional-leverage 125 --volatility-adjusted-leverage --volatility-window-minutes 15 --volatility-roe-budget 0.12 --allocation-pct 0.99 --fee-buffer-pct 0.002 --take-profit-mode min-viable --min-net-profit-usdt 0.0001 --min-realized-equity-profit-usdt 0 --stop-loss-roe 0.20 --emergency-stop-roe 0.08 --entry-mode maker --poll-seconds 1 --entry-requote-seconds 1 --entry-timeout-seconds 20 --entry-abandon-cooldown-seconds 60 --max-same-symbol-streak 1 --same-symbol-cooldown-seconds 300 --no-candidate-retry-seconds 5 --safety-recent-vol-minutes 5 --safety-min-recent-quote-volume-usdt 5000 --safety-min-recent-volatility-pct 0.05 --safety-max-adverse-vol-ratio 1.10 --safety-liquidity-window-seconds 8 --safety-liquidity-samples 3 --safety-max-depth-drop-pct 25 --safety-max-spread-widen-multiple 1.75 --stats-csv logs\ultra_micro_stats.csv --trades-csv logs\ultra_micro_trades.csv --stats-snapshot-seconds 10
echo Bot process exited. Restarting in 5 seconds...
timeout /t 5 /nobreak >nul
goto loop
