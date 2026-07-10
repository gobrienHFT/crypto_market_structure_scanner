@echo off
cd /d "%~dp0"
python short_roc_position_close.py --symbol LABUSDT --output-dir lab_short_roc_close_output
pause
