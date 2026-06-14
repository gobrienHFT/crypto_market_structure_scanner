@echo off
cd /d "%~dp0"
python inx_hourly_monitor.py --symbol EVAAUSDT --output-dir evaa_hourly_monitor_output
pause
