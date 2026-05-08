@echo off
setlocal
cd /d "%~dp0"

python -c "import discord" >nul 2>&1
if errorlevel 1 (
  echo Installing discord.py...
  python -m pip install discord.py
)

python discord_convex_bot.py
pause
