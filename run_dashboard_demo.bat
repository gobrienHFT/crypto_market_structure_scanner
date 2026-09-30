@echo off
setlocal
cd /d "%~dp0"

python market_dashboard_demo.py
if errorlevel 1 exit /b 1

set "MARKET_DASHBOARD_DEMO=1"
set "MARKET_WORKSPACE_DB_PATH=%CD%\artifacts\dashboard_demo\market_workspace.sqlite"
set "DASHBOARD_URL=http://localhost:8502"
start "Crypto Market Scanner Demo" /min python -m streamlit run app.py --server.headless true --server.port 8502

for /l %%I in (1,1,30) do (
    powershell -NoProfile -Command "try { $response = Invoke-WebRequest -UseBasicParsing -Uri '%DASHBOARD_URL%/_stcore/health' -TimeoutSec 1; if ($response.StatusCode -eq 200) { exit 0 } } catch {} exit 1" >nul 2>&1
    if not errorlevel 1 goto :open_dashboard
    timeout /t 1 /nobreak >nul
)

echo Demo dashboard did not become ready. Check the server window for the startup error.
pause
exit /b 1

:open_dashboard
set "CHROME_EXE="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if defined CHROME_EXE (
    start "" "%CHROME_EXE%" --new-tab "%DASHBOARD_URL%"
) else (
    start "" "%DASHBOARD_URL%"
)
endlocal
