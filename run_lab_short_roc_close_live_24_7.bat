@echo off
cd /d "%~dp0"
set SHORT_ROC_CLOSE_LIVE=1
python short_roc_position_close.py --symbol LABUSDT --live --trigger-short-roc-pct 2.5 --output-dir lab_short_roc_close_output
pause
