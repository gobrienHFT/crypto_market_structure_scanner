@echo off
setlocal
cd /d "%~dp0"

set "DASHBOARD_URL=http://localhost:8501"

rem Start Streamlit in its own minimized window so this launcher can open Chrome.
start "Crypto Market Structure Dashboard" /min python -m streamlit run app.py --server.headless true --server.port 8501

rem Wait until Streamlit is ready instead of opening a browser against a cold server.
for /l %%I in (1,1,30) do (
    powershell -NoProfile -Command "try { $response = Invoke-WebRequest -UseBasicParsing -Uri '%DASHBOARD_URL%/_stcore/health' -TimeoutSec 1; if ($response.StatusCode -eq 200) { exit 0 } } catch {} exit 1" >nul 2>&1
    if not errorlevel 1 goto :open_dashboard
    timeout /t 1 /nobreak >nul
)

echo Dashboard did not become ready. Check the server window for the startup error.
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
    rem Fall back to the default browser if Chrome is not installed in a standard path.
    start "" "%DASHBOARD_URL%"
)

endlocal
