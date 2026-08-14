@echo off
setlocal
cd /d "%~dp0"

echo ================================================================
echo LIVE AUTOMATED BINANCE FUTURES TRADING
echo.
echo This process can open and close real positions.
echo Planned risk: 0.25%% of futures equity per position.
echo Stress-risk ceiling: 0.50%%. Leverage: 2x isolated.
echo Only one open account position is permitted.
echo Stop other entry and short-ROC close BATs before running this manager.
echo ================================================================
echo.

set /p "CONFIRM=Type LIVE to enable real orders: "
if /I not "%CONFIRM%"=="LIVE" (
  echo Live trading was not enabled.
  pause
  exit /b 1
)

set "AUTO_SHORT_UPTREND_LIVE=1"
set "AUTO_SHORT_UPTREND_LIVE_ACK=I_ACCEPT_LIVE_ORDERS"

python auto_short_uptrend_trader.py ^
  --live ^
  --scan-mode Deep ^
  --risk-pct 0.25 ^
  --max-stress-risk-pct 0.50 ^
  --leverage 2 ^
  --manage-interval-seconds 60 ^
  --flat-scan-interval-seconds 900

set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo LIVE automated trader stopped with exit code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
