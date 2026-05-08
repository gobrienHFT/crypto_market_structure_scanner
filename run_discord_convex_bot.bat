@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter \"name = 'python.exe'\" | Where-Object { $_.CommandLine -like '*discord_convex_bot.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

python -c "import discord" >nul 2>&1
if errorlevel 1 (
  echo Installing discord.py...
  python -m pip install discord.py
)

python discord_convex_bot.py
pause
