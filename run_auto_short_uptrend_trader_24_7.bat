@echo off
setlocal
cd /d "%~dp0"

echo Starting PAPER automated short-uptrend trader.
echo No live orders can be placed by this launcher.
echo.

python auto_short_uptrend_trader.py ^
  --scan-mode Deep ^
  --risk-pct 0.25 ^
  --max-stress-risk-pct 0.50 ^
  --leverage 2 ^
  --manage-interval-seconds 60 ^
  --flat-scan-interval-seconds 900

set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo Automated trader stopped with exit code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
