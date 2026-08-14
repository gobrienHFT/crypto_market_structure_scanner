@echo off
cd /d "%~dp0"
set SHORT_ROC_CLOSE_LIVE=1
python short_roc_position_close.py --symbol LABUSDT --live --trigger-short-roc-pct 4 --trigger-short-roc-pp 999 --short-exit-level-pct 65 --short-peak-drawdown-pp 5 --oi-drop-confirmation-pct 8 --volume-spike-confirmation-pct 50 --confirmation-readings 2 --short-rebound-tolerance-pp 0.5 --short-history-limit 12 --partial-close-pct 50 --runner-confirmation-readings 2 --runner-oi-drop-pct 3 --runner-volume-deceleration-pct 20 --execution-profit-floor-pct 0.25 --output-dir lab_short_roc_close_output
pause
