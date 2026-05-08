from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


APP_DIR = Path(__file__).resolve().parent


def _load_local_env() -> None:
    env_path = APP_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


def _env_value(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _metric(row: pd.Series, label: str, columns: tuple[str, ...], suffix: str = "", decimals: int = 1) -> str:
    for column in columns:
        if column not in row.index:
            continue
        value = _safe_float(row.get(column))
        if value is not None:
            return f"{label} {value:.{decimals}f}{suffix}"
    return ""


def _candidate_line(row: pd.Series) -> str:
    symbol = str(row.get("symbol", "")).upper().strip() or "UNKNOWN"
    metrics = [
        _metric(row, "bucket", ("trade_bucket_score", "_discord_bucket_score")),
        _metric(row, "convex", ("convexity_entry_score", "convexity_score")),
        _metric(row, "setup", ("rave_lab_setup_score", "pre_pump_precision_score")),
        _metric(row, "short acct", ("short_account_pct",), "%"),
        _metric(row, "24h", ("price_change_24h_pct", "change_24h_pct", "day_change_pct"), "%"),
        _metric(row, "OI", ("oi_delta_pct", "oi_value_change_since_scan_pct"), "%"),
    ]
    metric_text = " | ".join(item for item in metrics if item)
    note = str(row.get("trade_bucket_note", "")).strip()
    if len(note) > 180:
        note = f"{note[:177]}..."
    if metric_text and note:
        return f"**{symbol}** | {metric_text}\n{note}"
    if metric_text:
        return f"**{symbol}** | {metric_text}"
    if note:
        return f"**{symbol}**\n{note}"
    return f"**{symbol}**"


def _cache_path() -> Path:
    return Path(_env_value("DISCORD_CONVEX_CACHE_PATH", str(APP_DIR / "data" / "latest_convex_longs.csv")))


def _load_candidates(limit: int) -> tuple[str, str]:
    path = _cache_path()
    if not path.exists():
        return (
            "No Convex Long scan cache yet",
            "Run the Streamlit dashboard and click **Scan now** once. The bot reads the latest scanned Convex Long cache.",
        )
    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        return ("Could not read Convex Long scan cache", f"`{exc}`")
    if frame.empty:
        return ("No Convex Long candidates in the latest scan", f"Cache: `{path}`")

    score_col = "trade_bucket_score" if "trade_bucket_score" in frame.columns else None
    if score_col:
        frame[score_col] = pd.to_numeric(frame[score_col], errors="coerce").fillna(0.0)
        frame = frame.sort_values([score_col, "symbol"], ascending=[False, True])
    else:
        frame = frame.sort_values("symbol")

    scanned_at = str(frame.get("scanned_at_utc", pd.Series(["unknown"])).iloc[0])
    scan_mode = str(frame.get("scan_mode", pd.Series(["unknown"])).iloc[0])
    lines = [_candidate_line(row) for _, row in frame.head(limit).iterrows()]
    description = "\n\n".join(lines)
    if len(description) > 3900:
        description = f"{description[:3890]}\n..."
    title = f"Latest Convex Long candidates ({scan_mode}, {scanned_at})"
    return title, description


def _cache_status() -> str:
    path = _cache_path()
    if not path.exists():
        return f"No cache file yet: `{path}`"
    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        return f"Cache exists but could not be read: `{exc}`"
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"Cache: `{path}`\nRows: `{len(frame)}`\nModified: `{modified}`"


def main() -> None:
    _load_local_env()
    try:
        import discord
        from discord import app_commands
    except ImportError:
        print("discord.py is not installed. Run: python -m pip install discord.py")
        raise SystemExit(1)

    token = _env_value("DISCORD_BOT_TOKEN")
    if not token:
        print("Set DISCORD_BOT_TOKEN in .env before starting the bot.")
        raise SystemExit(1)

    guild_id_raw = _env_value("DISCORD_GUILD_ID")
    allowed_channel_raw = _env_value("DISCORD_ALLOWED_CHANNEL_ID")
    default_top_n = max(1, int(_env_value("DISCORD_CONVEX_COMMAND_TOP_N", "10")))
    guild = discord.Object(id=int(guild_id_raw)) if guild_id_raw.strip().isdigit() else None
    allowed_channel_id = int(allowed_channel_raw) if allowed_channel_raw.strip().isdigit() else None

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    def _channel_allowed(interaction: discord.Interaction) -> bool:
        return allowed_channel_id is None or interaction.channel_id == allowed_channel_id

    command_kwargs = {"name": "convex", "description": "Show the latest scanned Convex Long candidates."}
    if guild is not None:
        command_kwargs["guild"] = guild

    @tree.command(**command_kwargs)
    async def convex(interaction: discord.Interaction, limit: int = default_top_n) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        capped_limit = min(max(int(limit), 1), 25)
        title, description = await asyncio.to_thread(_load_candidates, capped_limit)
        embed = discord.Embed(title=title, description=description, color=0x22C55E)
        embed.set_footer(text="Latest dashboard scan cache. Structural-risk screen only.")
        await interaction.followup.send(embed=embed)

    status_kwargs = {"name": "convex_status", "description": "Show Discord Convex cache status."}
    if guild is not None:
        status_kwargs["guild"] = guild

    @tree.command(**status_kwargs)
    async def convex_status(interaction: discord.Interaction) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        status = await asyncio.to_thread(_cache_status)
        await interaction.response.send_message(status)

    @client.event
    async def on_ready() -> None:
        if guild is not None:
            await tree.sync(guild=guild)
            scope = f"guild {guild.id}"
        else:
            await tree.sync()
            scope = "global"
        print(f"Discord Convex bot logged in as {client.user}. Slash commands synced to {scope}.")

    client.run(token)


if __name__ == "__main__":
    main()
