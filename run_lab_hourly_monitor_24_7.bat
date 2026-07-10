@echo off
cd /d "%~dp0"
python inx_hourly_monitor.py --symbol LABUSDT --output-dir lab_hourly_monitor_output
pause
