@echo off
cd /d "%~dp0"
python short_roc_position_close.py --symbol LABUSDT --trigger-short-roc-pct 4 --trigger-short-roc-pp 999 --short-exit-level-pct 65 --short-peak-drawdown-pp 5 --oi-drop-confirmation-pct 8 --volume-spike-confirmation-pct 50 --confirmation-readings 2 --short-rebound-tolerance-pp 0.5 --short-history-limit 12 --partial-close-pct 50 --runner-confirmation-readings 2 --runner-oi-drop-pct 3 --runner-volume-deceleration-pct 20 --output-dir lab_short_roc_close_output
pause
