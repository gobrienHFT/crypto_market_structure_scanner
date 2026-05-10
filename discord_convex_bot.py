from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from binance_futures import BinanceFuturesPublic
from holder_composition import fetch_holder_composition, format_holder_composition_for_discord


APP_DIR = Path(__file__).resolve().parent
SYMBOL_QUERY_RE = re.compile(r"^[!/]?\$?([A-Za-z0-9]{2,30})$")

if os.name == "nt" and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


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


def _env_bool(name: str, default: bool = False) -> bool:
    fallback = "1" if default else "0"
    return _env_value(name, fallback).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    try:
        parsed = int(str(_env_value(name, str(default))).strip())
    except Exception:
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    return parsed


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _format_number(value: Any, *, decimals: int = 2) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "n/a"
    sign = "-" if parsed < 0 else ""
    value_abs = abs(parsed)
    if value_abs >= 1_000_000_000:
        return f"{sign}{value_abs / 1_000_000_000:.{decimals}f}B"
    if value_abs >= 1_000_000:
        return f"{sign}{value_abs / 1_000_000:.{decimals}f}M"
    if value_abs >= 1_000:
        return f"{sign}{value_abs / 1_000:.{decimals}f}K"
    if value_abs >= 1:
        return f"{parsed:.{decimals}f}"
    return f"{parsed:.6g}"


def _format_pct(value: Any, *, decimals: int = 1) -> str:
    parsed = _safe_float(value)
    return "n/a" if parsed is None else f"{parsed:.{decimals}f}%"


def _first_present(row: pd.Series | dict[str, Any], columns: tuple[str, ...]) -> Any:
    for column in columns:
        try:
            value = row.get(column)  # type: ignore[attr-defined]
        except Exception:
            continue
        if value not in (None, "") and not pd.isna(value):
            return value
    return None


def _metric(row: pd.Series, label: str, columns: tuple[str, ...], suffix: str = "", decimals: int = 1) -> str:
    for column in columns:
        if column not in row.index:
            continue
        value = _safe_float(row.get(column))
        if value is not None:
            return f"{label} {value:.{decimals}f}{suffix}"
    return ""


def _holder_contract_hints_path() -> Path:
    return Path(_env_value("DISCORD_HOLDER_CONTRACTS_FILE", str(APP_DIR / "data" / "discord_holder_contracts.csv")))


def _holder_composition_text(row: pd.Series) -> str:
    if not _env_bool("DISCORD_HOLDER_COMPOSITION_ENABLED", True):
        return ""
    try:
        composition = fetch_holder_composition(
            row.to_dict(),
            hints_path=_holder_contract_hints_path(),
            timeout=_env_int("DISCORD_HOLDER_COMPOSITION_TIMEOUT_SECONDS", 12, minimum=3),
            max_holders=_env_int("DISCORD_HOLDER_COMPOSITION_MAX_HOLDERS", 100, minimum=10),
        )
    except Exception as exc:
        return f"Holder composition unavailable: {exc}"
    if composition.error == "no contract hint" and not _env_bool("DISCORD_HOLDER_COMPOSITION_SHOW_MISSING", False):
        return ""
    return format_holder_composition_for_discord(
        composition,
        include_top_holders=_env_int("DISCORD_HOLDER_COMPOSITION_TOP_HOLDERS", 0, minimum=0),
        max_chars=_env_int("DISCORD_HOLDER_COMPOSITION_MAX_CHARS", 520, minimum=200),
    )


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
    holder_text = _holder_composition_text(row)
    if metric_text and note:
        base = f"**{symbol}** | {metric_text}\n{note}"
    elif metric_text:
        base = f"**{symbol}** | {metric_text}"
    elif note:
        base = f"**{symbol}**\n{note}"
    else:
        base = f"**{symbol}**"
    if holder_text:
        return f"{base}\n{holder_text}"
    return base


def _cache_path() -> Path:
    return Path(_env_value("DISCORD_CONVEX_CACHE_PATH", str(APP_DIR / "data" / "latest_convex_longs.csv")))


def _snapshot_path() -> Path:
    return Path(_env_value("DISCORD_PRE_PUMP_SNAPSHOT_PATH", str(APP_DIR / "data" / "pre_pump_scan_snapshots.csv")))


def _normalize_symbol_query(raw_symbol: str) -> str:
    match = SYMBOL_QUERY_RE.fullmatch(str(raw_symbol or "").strip())
    if not match:
        return ""
    symbol = match.group(1).upper()
    if symbol in {"CONVEX", "CONVEX_STATUS", "COIN"}:
        return ""
    if not symbol.endswith("USDT"):
        symbol = f"{symbol}USDT"
    return symbol


def _looks_like_symbol_shortcut(raw_content: str) -> bool:
    token = str(raw_content or "").strip()
    if not token or " " in token:
        return False
    if not token.startswith(("/", "!")):
        return False
    symbol = _normalize_symbol_query(token)
    raw_symbol = token.lstrip("/!$").upper()
    return bool(symbol) and raw_symbol.endswith("USDT")


def _configured_symbol_slash_aliases() -> list[str]:
    raw = _env_value("DISCORD_SYMBOL_SLASH_ALIASES", "PLAYUSDT")
    symbols: list[str] = []
    for chunk in re.split(r"[,;\s]+", raw):
        symbol = _normalize_symbol_query(chunk)
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols[:75]


def _symbol_slash_command_name(symbol: str) -> str:
    normalized = _normalize_symbol_query(symbol)
    if not normalized:
        return ""
    name = normalized.lower()
    return name if re.fullmatch(r"[a-z0-9_-]{1,32}", name) else ""


def _read_csv_if_exists(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _latest_snapshot_frame() -> pd.DataFrame:
    frame = _read_csv_if_exists(_snapshot_path())
    if frame.empty or "symbol" not in frame.columns:
        return pd.DataFrame()
    time_column = "snapshot_ts" if "snapshot_ts" in frame.columns else "scanned_at_utc" if "scanned_at_utc" in frame.columns else ""
    if time_column:
        parsed_time = pd.to_datetime(frame[time_column], errors="coerce", utc=True)
        if parsed_time.notna().any():
            latest = parsed_time.max()
            frame = frame[parsed_time.eq(latest)].copy()
    return frame


def _row_for_symbol(frame: pd.DataFrame, symbol: str) -> pd.Series | None:
    if frame.empty or "symbol" not in frame.columns:
        return None
    matches = frame[frame["symbol"].astype(str).str.upper().eq(symbol)]
    if matches.empty:
        return None
    return matches.iloc[0]


def _load_coin_scan_row(symbol: str) -> tuple[pd.Series | None, str]:
    cache_row = _row_for_symbol(_read_csv_if_exists(_cache_path()), symbol)
    if cache_row is not None:
        return cache_row, "latest Convex cache"
    snapshot_row = _row_for_symbol(_latest_snapshot_frame(), symbol)
    if snapshot_row is not None:
        return snapshot_row, "latest pre-pump snapshot"
    return None, ""


def _live_binance_row(symbol: str) -> tuple[pd.Series | None, str]:
    client = BinanceFuturesPublic(timeout=_env_int("DISCORD_COIN_LIVE_TIMEOUT_SECONDS", 10, minimum=3), requests_per_second=3)
    ticker = next((item for item in client.ticker_24hr() if str(item.get("symbol", "")).upper() == symbol), None)
    if not ticker:
        return None, ""

    row: dict[str, Any] = {
        "symbol": symbol,
        "base_asset": symbol.removesuffix("USDT"),
        "last_price": ticker.get("lastPrice"),
        "price_change_24h_pct": ticker.get("priceChangePercent"),
        "quote_volume_24h": ticker.get("quoteVolume"),
        "range_24h_pct": None,
    }
    high = _safe_float(ticker.get("highPrice"))
    low = _safe_float(ticker.get("lowPrice"))
    last = _safe_float(ticker.get("lastPrice"))
    if high is not None and low is not None and last is not None and abs(last) > 1e-12:
        row["range_24h_pct"] = (high - low) / last * 100.0
    try:
        oi = client.open_interest(symbol)
        row["oi_value_usdt"] = (_safe_float(oi.get("openInterest")) or 0.0) * (last or 0.0)
    except Exception:
        pass
    try:
        ratios = client.global_long_short_account_ratio(symbol, period="1h", limit=1)
        if ratios:
            latest = ratios[-1]
            long_account = _safe_float(latest.get("longAccount"))
            short_account = _safe_float(latest.get("shortAccount"))
            if long_account is not None:
                row["long_account_pct"] = long_account * 100.0 if long_account <= 1.0 else long_account
            if short_account is not None:
                row["short_account_pct"] = short_account * 100.0 if short_account <= 1.0 else short_account
            row["long_short_account_ratio"] = latest.get("longShortRatio")
    except Exception:
        pass
    return pd.Series(row), "live Binance futures fallback"


def _coin_stats_description(row: pd.Series, *, source: str) -> str:
    symbol = str(row.get("symbol", "")).upper().strip() or "UNKNOWN"
    lines = [
        f"**{symbol}**",
        f"Source: {source}",
        (
            f"Price {_format_number(_first_present(row, ('last_price', 'price')), decimals=6)} | "
            f"24h {_format_pct(_first_present(row, ('price_change_24h_pct', 'change_24h_pct', 'day_change_pct')))} | "
            f"24h vol {_format_number(_first_present(row, ('quote_volume_24h', 'volume_24h')))}"
        ),
    ]

    score_bits = [
        _metric(row, "bucket", ("trade_bucket_score", "_discord_bucket_score")),
        _metric(row, "convex", ("convexity_entry_score", "convexity_score")),
        _metric(row, "setup", ("rave_lab_setup_score", "pre_pump_precision_score")),
        _metric(row, "pre-pump", ("pre_pump_precision_score",)),
        _metric(row, "short fuse", ("dormant_short_fuse_score",)),
    ]
    if any(score_bits):
        lines.append("Scores: " + " | ".join(bit for bit in score_bits if bit))

    account_bits = [
        f"short {_format_pct(row.get('short_account_pct'))}",
        f"long {_format_pct(row.get('long_account_pct'))}",
        f"LS ratio {_format_number(row.get('long_short_account_ratio'), decimals=2)}",
    ]
    short_change = _first_present(row, ("short_account_change_max_pp", "target_cex_share_change_pp"))
    if short_change is not None:
        account_bits.append(f"short chg {_format_pct(short_change)}")
    lines.append("Accounts: " + " | ".join(account_bits))

    market_bits = [
        f"OI {_format_number(row.get('oi_value_usdt'))}",
        f"OI delta {_format_pct(_first_present(row, ('oi_delta_pct', 'oi_value_change_since_scan_pct')))}",
        f"range {_format_pct(row.get('range_24h_pct'))}",
        f"hr vol x{_format_number(row.get('hour_volume_multiple'), decimals=2)}",
    ]
    lines.append("Market: " + " | ".join(market_bits))

    structure_bits = [
        f"central ownership {_format_number(row.get('centralized_ownership_score'), decimals=1)}",
        f"low float {_format_number(row.get('low_float_score'), decimals=1)}",
        f"top10 holders {_format_pct(row.get('top10_holder_pct'))}",
        f"holders {_format_number(row.get('holder_count'), decimals=0)}",
    ]
    lines.append("Structure: " + " | ".join(structure_bits))

    note = str(_first_present(row, ("trade_bucket_note", "rave_lab_setup_note", "pre_pump_precision_note")) or "").strip()
    if note:
        lines.append(f"Read: {note[:320]}")
    holder_text = _holder_composition_text(row)
    if holder_text:
        lines.append(holder_text)
    text = "\n".join(lines)
    return text if len(text) <= 3900 else f"{text[:3890]}\n..."


def _load_coin_stats(symbol_query: str) -> tuple[str, str]:
    symbol = _normalize_symbol_query(symbol_query)
    if not symbol:
        return "Coin stats", "Use `/coin symbol:PLAYUSDT` or type `/PLAYUSDT` in the configured channel."
    row, source = _load_coin_scan_row(symbol)
    if row is None:
        row, source = _live_binance_row(symbol)
    if row is None:
        return f"{symbol} stats", "No latest scan row or live Binance futures symbol found yet."
    return f"{symbol} stats", _coin_stats_description(row, source=source)


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


def main(*, force_disable_symbol_shortcuts: bool = False) -> None:
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
    announce_online = _env_value("DISCORD_ANNOUNCE_ONLINE", "0").strip().lower() in {"1", "true", "yes", "on"}
    message_content_intent_enabled = _env_bool("DISCORD_MESSAGE_CONTENT_INTENT_ENABLED", False)
    symbol_shortcuts_enabled = _env_bool("DISCORD_SYMBOL_SHORTCUTS_ENABLED", False) and message_content_intent_enabled
    if force_disable_symbol_shortcuts:
        symbol_shortcuts_enabled = False
    symbol_slash_aliases = _configured_symbol_slash_aliases()
    guild = discord.Object(id=int(guild_id_raw)) if guild_id_raw.strip().isdigit() else None
    allowed_channel_id = int(allowed_channel_raw) if allowed_channel_raw.strip().isdigit() else None

    intents = discord.Intents.default()
    if symbol_shortcuts_enabled:
        intents.message_content = True
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

    coin_kwargs = {"name": "coin", "description": "Show latest scan/live stats for one futures symbol."}
    if guild is not None:
        coin_kwargs["guild"] = guild

    @tree.command(**coin_kwargs)
    @app_commands.describe(symbol="Symbol to inspect, for example PLAYUSDT or PLAY")
    async def coin(interaction: discord.Interaction, symbol: str) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, description = await asyncio.to_thread(_load_coin_stats, symbol)
        embed = discord.Embed(title=title, description=description, color=0x38BDF8)
        embed.set_footer(text="Latest scan row when available; live Binance fallback otherwise. Structural-risk screen only.")
        await interaction.followup.send(embed=embed)

    def _make_symbol_alias_command(alias_symbol: str):
        async def symbol_alias(interaction: discord.Interaction) -> None:
            if not _channel_allowed(interaction):
                await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
                return
            await interaction.response.defer(thinking=True)
            title, description = await asyncio.to_thread(_load_coin_stats, alias_symbol)
            embed = discord.Embed(title=title, description=description, color=0x38BDF8)
            embed.set_footer(text=f"/{alias_symbol.lower()} alias. Latest scan/live stats. Structural-risk screen only.")
            await interaction.followup.send(embed=embed)

        return symbol_alias

    for alias_symbol in symbol_slash_aliases:
        alias_name = _symbol_slash_command_name(alias_symbol)
        if not alias_name:
            continue
        alias_kwargs = {"name": alias_name, "description": f"Show {alias_symbol} scan/live stats."}
        if guild is not None:
            alias_kwargs["guild"] = guild
        tree.command(**alias_kwargs)(_make_symbol_alias_command(alias_symbol))

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
    async def on_message(message: discord.Message) -> None:
        if not symbol_shortcuts_enabled or message.author.bot:
            return
        if allowed_channel_id is not None and message.channel.id != allowed_channel_id:
            return
        if not _looks_like_symbol_shortcut(message.content):
            return
        symbol = _normalize_symbol_query(message.content)
        async with message.channel.typing():
            title, description = await asyncio.to_thread(_load_coin_stats, symbol)
        embed = discord.Embed(title=title, description=description, color=0x38BDF8)
        embed.set_footer(text="Shortcut lookup. Use /coin if Discord blocks raw /SYMBOL messages.")
        await message.reply(embed=embed, mention_author=False)

    @client.event
    async def on_ready() -> None:
        guilds = ", ".join(f"{connected_guild.name} ({connected_guild.id})" for connected_guild in client.guilds)
        print(f"Connected guilds: {guilds or 'none'}")
        print(f"Configured DISCORD_GUILD_ID: {guild_id_raw or 'not set'}")
        print(f"Configured DISCORD_ALLOWED_CHANNEL_ID: {allowed_channel_raw or 'not set'}")
        print(
            "Raw text symbol shortcuts: "
            f"{'enabled' if symbol_shortcuts_enabled else 'disabled'} "
            "(requires DISCORD_MESSAGE_CONTENT_INTENT_ENABLED=1 and Discord Developer Portal > Bot > Message Content Intent)."
        )
        if force_disable_symbol_shortcuts:
            print("Symbol shortcuts were forced off because Discord rejected privileged intents.")
        print(
            "Symbol slash aliases: "
            + (", ".join(f"/{_symbol_slash_command_name(symbol)}" for symbol in symbol_slash_aliases) or "none")
        )

        if guild is not None:
            commands = await tree.sync(guild=guild)
            scope = f"guild {guild.id}"
        else:
            commands = await tree.sync()
            scope = "global"
        command_names = ", ".join(f"/{command.name}" for command in commands) or "none"
        print(f"Discord Convex bot logged in as {client.user}. Slash commands synced to {scope}: {command_names}.")

        if allowed_channel_id is None:
            print("DISCORD_ALLOWED_CHANNEL_ID is not set; commands are allowed in any channel.")
            return

        channel = client.get_channel(allowed_channel_id)
        if channel is None:
            try:
                channel = await client.fetch_channel(allowed_channel_id)
            except Exception as exc:
                print(f"Could not access DISCORD_ALLOWED_CHANNEL_ID {allowed_channel_id}: {exc}")
                print("Check that the bot is invited to the server and can view that channel.")
                return

        print(f"Allowed channel resolved: #{getattr(channel, 'name', 'unknown')} ({allowed_channel_id})")
        if announce_online:
            try:
                await channel.send(
                    "Convex bot online. Use `/convex_status`, `/convex`, `/coin PLAYUSDT`, or `/playusdt` in this channel."
                )
            except Exception as exc:
                print(f"Bot is online but could not post to allowed channel {allowed_channel_id}: {exc}")

    client.run(token)


def run_with_backoff() -> None:
    _load_local_env()
    retry_seconds = max(15, int(_env_value("DISCORD_LOGIN_RETRY_SECONDS", "90")))
    max_retry_seconds = max(retry_seconds, int(_env_value("DISCORD_LOGIN_MAX_RETRY_SECONDS", "600")))
    force_disable_symbol_shortcuts = False

    while True:
        try:
            main(force_disable_symbol_shortcuts=force_disable_symbol_shortcuts)
            return
        except KeyboardInterrupt:
            raise
        except SystemExit:
            raise
        except Exception as exc:
            status = getattr(exc, "status", None)
            code = getattr(exc, "code", None)
            is_privileged_intent_error = exc.__class__.__name__ == "PrivilegedIntentsRequired"
            if is_privileged_intent_error and not force_disable_symbol_shortcuts:
                print(
                    "Discord rejected the Message Content Intent. Restarting without raw /SYMBOL shortcuts; "
                    "`/coin PLAYUSDT` and configured lowercase aliases such as `/playusdt` will still work."
                )
                force_disable_symbol_shortcuts = True
                continue
            is_rate_limited = status == 429 or code == 40062 or "429 Too Many Requests" in str(exc)
            if not is_rate_limited:
                raise
            print(f"Discord login is rate-limited. Waiting {retry_seconds}s before retrying instead of exiting.")
            time.sleep(retry_seconds)
            retry_seconds = min(max_retry_seconds, retry_seconds * 2)


if __name__ == "__main__":
    run_with_backoff()
