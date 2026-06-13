@echo off
cd /d "%~dp0"
python inx_hourly_monitor.py --symbol COAIUSDT --output-dir coai_hourly_monitor_output
pause
