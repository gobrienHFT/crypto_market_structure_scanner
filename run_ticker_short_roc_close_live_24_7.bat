@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo Binance Futures short-ROC live close monitor
echo Enter a ticker such as TAG, TAGUSDT, TAG-USDT, or TAG/USDT.
set /p "TARGET_SYMBOL=Ticker: "

if not defined TARGET_SYMBOL (
    echo No ticker entered. Nothing started.
    pause
    exit /b 1
)

for /f "usebackq delims=" %%S in (`powershell -NoProfile -Command "$env:TARGET_SYMBOL.ToUpperInvariant().Replace('-', '').Replace('/', '').Replace(' ', '')"`) do set "SYMBOL=%%S"

if /I not "%SYMBOL:~-4%"=="USDT" set "SYMBOL=%SYMBOL%USDT"

echo.
echo Starting LIVE close monitor for %SYMBOL%.
echo A close can only be submitted when its existing profit and short-ROC rules are met.
echo Press Ctrl+C to stop it.
echo.

set SHORT_ROC_CLOSE_LIVE=1
python short_roc_position_close.py --symbol %SYMBOL% --live --trigger-short-roc-pct 4 --trigger-short-roc-pp 999 --short-exit-level-pct 65 --short-peak-drawdown-pp 5 --oi-drop-confirmation-pct 8 --volume-spike-confirmation-pct 50 --confirmation-readings 2 --short-rebound-tolerance-pp 0.5 --execution-profit-floor-pct 0.25 --output-dir ticker_short_roc_close_output
pause
