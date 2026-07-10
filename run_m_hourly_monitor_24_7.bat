@echo off
cd /d "%~dp0"
python inx_hourly_monitor.py --symbol MUSDT --output-dir m_hourly_monitor_output
pause
