# Demo Walkthrough

This is the fastest path for a reviewer to understand the project without needing production API keys.

## 1. Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 2. Run Tests

```powershell
python -m pytest
```

The suite covers the scoring engines, concentration scanner, Discord formatter, Discord bot helpers, watcher candidate selection, CEX-flow parser, proof engine, timing model, and trade setup pipeline.

## 3. Launch Dashboard

```powershell
streamlit run app.py
```

Use the dashboard to inspect ranked scanner rows, concentration overlays, holder summaries, CEX-flow fields, and terminal/timing scores.

## 4. Configure Discord Locally

Copy the template and fill only what you need:

```powershell
Copy-Item .env.example .env
```

Minimum webhook watcher fields:

```text
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
DISCORD_WATCHER_SCAN_MODE=Deep
DISCORD_WATCHER_ALERT_SOURCE=terminal_timing
```

Minimum bot fields:

```text
DISCORD_BOT_TOKEN=
DISCORD_GUILD_ID=
DISCORD_ALLOWED_CHANNEL_ID=
```

## 5. Run Discord Surfaces

Webhook watcher:

```powershell
run_discord_convex_watcher.bat
```

Bot:

```powershell
run_discord_convex_bot.bat
```

Recommended command sequence:

```text
/alpha
/radar
/cexflow min_tokens:20000
/earlyflow
/flowcoin symbol:FLOWUSDT min_tokens:20000
/terminal
/timing
/coin FLOWUSDT
/dossier FLOWUSDT
/convex_scoreboard
```

See [sample Discord output](sample-discord-output.md) for representative command and alert text.

## 6. Review Proof Loop

Alerts are archived locally:

```text
data/archive/flags/YYYY-MM-DD.jsonl
```

Outcome refreshes are written to:

```text
data/archive/outcomes/YYYY-MM-DD_outcomes.jsonl
```

The scoreboard command summarizes whether the rules are producing useful follow-through, not just visually exciting alerts.

## 7. What To Point Out In An Interview

- The thesis is narrow: concentrated float plus derivatives crowding plus venue-flow stress.
- The architecture separates research scoring, Discord operations, and proof measurement.
- The bot avoids trade-call language and keeps risk/execution responsibility explicit.
- The proof engine creates a feedback loop for improving the signal stack.
- Tests exercise edge cases around Discord length limits, CEX-flow rows, venue gating, and timing filters.
