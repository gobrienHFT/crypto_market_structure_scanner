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
from discord_flag_formatter import (
    DISCORD_EMBED_DESCRIPTION_LIMIT,
    DISCORD_FOOTER,
    DISCORD_PRODUCT_IDENTITY,
    build_discord_flag_card,
    join_discord_flag_cards,
)
from holder_composition import fetch_holder_composition, format_holder_composition_for_discord
from proof_engine import proof_archive_path, refresh_outcomes, weekly_scoreboard_text, write_weekly_report


APP_DIR = Path(__file__).resolve().parent
SYMBOL_QUERY_RE = re.compile(r"^[!/]?\$?([A-Za-z0-9]{2,30})$")
ACCESS_LEVELS = {"free": 0, "paid": 1, "pro": 2}

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


def _env_csv_ints(name: str) -> set[int]:
    values: set[int] = set()
    for chunk in re.split(r"[,;\s]+", _env_value(name, "")):
        chunk = chunk.strip()
        if chunk.isdigit():
            values.add(int(chunk))
    return values


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _normalize_tier(raw_tier: str) -> str:
    tier = str(raw_tier or "").strip().lower()
    return tier if tier in ACCESS_LEVELS else "pro"


def _tier_rank(tier: str) -> int:
    return ACCESS_LEVELS.get(_normalize_tier(tier), ACCESS_LEVELS["pro"])


def _tier_for_role_ids(role_ids: set[int]) -> str:
    pro_roles = _env_csv_ints("DISCORD_PRO_ROLE_IDS")
    paid_roles = _env_csv_ints("DISCORD_PAID_ROLE_IDS")
    if role_ids & pro_roles:
        return "pro"
    if role_ids & paid_roles:
        return "paid"
    return _normalize_tier(_env_value("DISCORD_DEFAULT_USER_TIER", "pro"))


def _role_ids_from_subject(subject: Any) -> set[int]:
    roles = getattr(subject, "roles", []) or []
    role_ids: set[int] = set()
    for role in roles:
        role_id = getattr(role, "id", None)
        if role_id is not None:
            try:
                role_ids.add(int(role_id))
            except Exception:
                pass
    return role_ids


def _interaction_role_ids(interaction: Any) -> set[int]:
    return _role_ids_from_subject(getattr(interaction, "user", None))


def _interaction_tier(interaction: Any) -> str:
    return _tier_for_role_ids(_interaction_role_ids(interaction))


def _tier_allows(tier: str, required: str) -> bool:
    return _tier_rank(tier) >= _tier_rank(required)


def _feature_required_tier(feature: str) -> str:
    defaults = {
        "convex": "free",
        "coin": "paid",
        "scoreboard": "paid",
        "archive": "pro",
        "shortcut": "paid",
        "shorts": "free",
    }
    env_name = f"DISCORD_{feature.upper()}_MIN_TIER"
    return _normalize_tier(_env_value(env_name, defaults.get(feature, "paid")))


def _free_sample_limit() -> int:
    return _env_int("DISCORD_FREE_SAMPLE_TOP_N", 3, minimum=1)


def _access_denied_message(feature: str) -> str:
    required = _feature_required_tier(feature)
    return f"This command is available for {required}+ access in this server."


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
    holder_text = _holder_composition_text(row)
    return build_discord_flag_card(row, holder_text=holder_text)


def _cache_path() -> Path:
    return Path(_env_value("DISCORD_CONVEX_CACHE_PATH", str(APP_DIR / "data" / "latest_convex_longs.csv")))


def _snapshot_path() -> Path:
    return Path(_env_value("DISCORD_PRE_PUMP_SNAPSHOT_PATH", str(APP_DIR / "data" / "pre_pump_scan_snapshots.csv")))


def _normalize_symbol_query(raw_symbol: str) -> str:
    match = SYMBOL_QUERY_RE.fullmatch(str(raw_symbol or "").strip())
    if not match:
        return ""
    symbol = match.group(1).upper()
    if symbol in {"CONVEX", "CONVEX_STATUS", "CONVEX_SCOREBOARD", "CONVEX_ARCHIVE", "COIN", "SHORTS"}:
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
    holder_text = _holder_composition_text(row)
    prefix = f"{DISCORD_PRODUCT_IDENTITY}\n\nScan source: {source}\n\n"
    card = build_discord_flag_card(row, holder_text=holder_text, max_chars=DISCORD_EMBED_DESCRIPTION_LIMIT - len(prefix))
    return f"{prefix}{card}"


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
            "No market-structure scan cache yet",
            "Run the Streamlit dashboard and click **Scan now** once. The bot reads the latest scanner sample cache.",
        )
    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        return ("Could not read scanner sample cache", f"`{exc}`")
    if frame.empty:
        return ("No market-structure candidates in the latest scan", f"Cache: `{path}`")

    score_col = "trade_bucket_score" if "trade_bucket_score" in frame.columns else None
    if score_col:
        frame[score_col] = pd.to_numeric(frame[score_col], errors="coerce").fillna(0.0)
        frame = frame.sort_values([score_col, "symbol"], ascending=[False, True])
    else:
        frame = frame.sort_values("symbol")

    scanned_at = str(frame.get("scanned_at_utc", pd.Series(["unknown"])).iloc[0])
    scan_mode = str(frame.get("scan_mode", pd.Series(["unknown"])).iloc[0])
    lines = [_candidate_line(row) for _, row in frame.head(limit).iterrows()]
    card_budget = DISCORD_EMBED_DESCRIPTION_LIMIT - len(DISCORD_PRODUCT_IDENTITY) - 2
    description = f"{DISCORD_PRODUCT_IDENTITY}\n\n{join_discord_flag_cards(lines, max_chars=card_budget)}"
    title = f"Latest scanner sample - market-structure candidates ({scan_mode}, {scanned_at})"
    return title, description


def _load_shorts_list() -> tuple[str, list[str]]:
    path = _cache_path()
    if not path.exists():
        return "Short-account majority list", [f"No scanner cache yet: `{path}`"]
    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        return "Short-account majority list", [f"Could not read scanner cache: `{exc}`"]
    if frame.empty or "short_account_pct" not in frame.columns:
        return "Short-account majority list", ["No short-account percentage data exists in the latest cache."]

    frame = frame.copy()
    frame["short_account_pct"] = pd.to_numeric(frame["short_account_pct"], errors="coerce")
    matches = frame[frame["short_account_pct"].gt(50.0)].copy()
    if matches.empty:
        return "Short-account majority list", ["No tokens in the latest cache have more than 50% of accounts short."]
    matches["symbol"] = matches["symbol"].astype(str).str.upper().str.strip()
    matches = matches[matches["symbol"].ne("")].drop_duplicates(subset=["symbol"], keep="first")
    matches = matches.sort_values(["short_account_pct", "symbol"], ascending=[False, True])
    scanned_at = str(frame.get("scanned_at_utc", pd.Series(["unknown"])).iloc[0])
    scan_mode = str(frame.get("scan_mode", pd.Series(["unknown"])).iloc[0])
    symbols = matches["symbol"].tolist()
    header = (
        f"Short-account majority tokens ({len(symbols)})\n"
        f"Threshold: >50% accounts short | Scan: {scan_mode} | Cache: {scanned_at}\n\n"
    )
    chunks: list[str] = []
    current = header
    for symbol in symbols:
        addition = f"{symbol}\n"
        if len(current) + len(addition) > 1850:
            chunks.append(current.rstrip())
            current = addition
        else:
            current += addition
    if current.strip():
        chunks.append(current.rstrip())
    return "Short-account majority list", chunks


def _cache_status() -> str:
    path = _cache_path()
    if not path.exists():
        return f"No cache file yet: `{path}`"
    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        return f"Cache exists but could not be read: `{exc}`"
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    archive = proof_archive_path()
    archive_rows = len(pd.read_csv(archive)) if archive.exists() else 0
    return f"Cache: `{path}`\nRows: `{len(frame)}`\nModified: `{modified}`\nProof archive rows: `{archive_rows}`"


def _scoreboard_text() -> str:
    if _env_bool("DISCORD_SCOREBOARD_REFRESH_OUTCOMES", True):
        refresh_outcomes(max_rows=_env_int("DISCORD_SCOREBOARD_REFRESH_MAX_ROWS", 20, minimum=1))
    if _env_bool("DISCORD_WEEKLY_REPORT_WRITE_ENABLED", True):
        write_weekly_report()
    return weekly_scoreboard_text()


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

    command_kwargs = {"name": "convex", "description": "Show the latest market-structure scanner sample."}
    if guild is not None:
        command_kwargs["guild"] = guild

    @tree.command(**command_kwargs)
    async def convex(interaction: discord.Interaction, limit: int = default_top_n) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        tier = _interaction_tier(interaction)
        if not _tier_allows(tier, _feature_required_tier("convex")):
            await interaction.response.send_message(_access_denied_message("convex"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        capped_limit = min(max(int(limit), 1), 25)
        if tier == "free":
            capped_limit = min(capped_limit, _free_sample_limit())
        title, description = await asyncio.to_thread(_load_candidates, capped_limit)
        embed = discord.Embed(title=title, description=description, color=0x22C55E)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)

    shorts_kwargs = {"name": "shorts", "description": "List every cached token with more than 50% of accounts short."}
    if guild is not None:
        shorts_kwargs["guild"] = guild

    @tree.command(**shorts_kwargs)
    async def shorts(interaction: discord.Interaction) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("shorts")):
            await interaction.response.send_message(_access_denied_message("shorts"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(_load_shorts_list)
        if not chunks:
            chunks = ["No short-account majority tokens found."]
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0xF59E0B)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    coin_kwargs = {"name": "coin", "description": "Show latest scan/live stats for one futures symbol."}
    if guild is not None:
        coin_kwargs["guild"] = guild

    @tree.command(**coin_kwargs)
    @app_commands.describe(symbol="Symbol to inspect, for example PLAYUSDT or PLAY")
    async def coin(interaction: discord.Interaction, symbol: str) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("coin")):
            await interaction.response.send_message(_access_denied_message("coin"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, description = await asyncio.to_thread(_load_coin_stats, symbol)
        embed = discord.Embed(title=title, description=description, color=0x38BDF8)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)

    def _make_symbol_alias_command(alias_symbol: str):
        async def symbol_alias(interaction: discord.Interaction) -> None:
            if not _channel_allowed(interaction):
                await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
                return
            if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("coin")):
                await interaction.response.send_message(_access_denied_message("coin"), ephemeral=True)
                return
            await interaction.response.defer(thinking=True)
            title, description = await asyncio.to_thread(_load_coin_stats, alias_symbol)
            embed = discord.Embed(title=title, description=description, color=0x38BDF8)
            embed.set_footer(text=DISCORD_FOOTER)
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

    scoreboard_kwargs = {"name": "convex_scoreboard", "description": "Show trailing proof-engine outcome stats."}
    if guild is not None:
        scoreboard_kwargs["guild"] = guild

    @tree.command(**scoreboard_kwargs)
    async def convex_scoreboard(interaction: discord.Interaction) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("scoreboard")):
            await interaction.response.send_message(_access_denied_message("scoreboard"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        text = await asyncio.to_thread(_scoreboard_text)
        await interaction.followup.send(f"```text\n{text[:1800]}\n```")

    archive_kwargs = {"name": "convex_archive", "description": "Export archived scanner flags and outcomes."}
    if guild is not None:
        archive_kwargs["guild"] = guild

    @tree.command(**archive_kwargs)
    async def convex_archive(interaction: discord.Interaction) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("archive")):
            await interaction.response.send_message(_access_denied_message("archive"), ephemeral=True)
            return
        path = proof_archive_path()
        if not path.exists():
            await interaction.response.send_message("No proof archive exists yet.")
            return
        await interaction.response.defer(thinking=True)
        await interaction.followup.send("Proof archive export.", file=discord.File(str(path), filename=path.name))

    @client.event
    async def on_message(message: discord.Message) -> None:
        if not symbol_shortcuts_enabled or message.author.bot:
            return
        if allowed_channel_id is not None and message.channel.id != allowed_channel_id:
            return
        if not _tier_allows(_tier_for_role_ids(_role_ids_from_subject(message.author)), _feature_required_tier("shortcut")):
            return
        if not _looks_like_symbol_shortcut(message.content):
            return
        symbol = _normalize_symbol_query(message.content)
        async with message.channel.typing():
            title, description = await asyncio.to_thread(_load_coin_stats, symbol)
        embed = discord.Embed(title=title, description=description, color=0x38BDF8)
        embed.set_footer(text=DISCORD_FOOTER)
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
                    "Convex bot online. Use `/convex_status`, `/convex`, `/shorts`, `/coin PLAYUSDT`, or `/playusdt` in this channel."
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
