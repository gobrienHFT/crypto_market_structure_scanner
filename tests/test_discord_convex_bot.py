import pandas as pd

import discord_convex_bot as bot


def test_normalize_symbol_query_accepts_fast_coin_forms() -> None:
    assert bot._normalize_symbol_query("playusdt") == "PLAYUSDT"
    assert bot._normalize_symbol_query("/PLAYUSDT") == "PLAYUSDT"
    assert bot._normalize_symbol_query("!PLAYUSDT") == "PLAYUSDT"
    assert bot._normalize_symbol_query("$playusdt") == "PLAYUSDT"
    assert bot._normalize_symbol_query("play") == "PLAYUSDT"


def test_normalize_symbol_query_rejects_bot_commands() -> None:
    assert bot._normalize_symbol_query("/convex") == ""
    assert bot._normalize_symbol_query("/convex_status") == ""
    assert bot._normalize_symbol_query("/coin") == ""


def test_shortcut_detector_only_accepts_explicit_usdt_shortcuts() -> None:
    assert bot._looks_like_symbol_shortcut("/PLAYUSDT")
    assert bot._looks_like_symbol_shortcut("!PLAYUSDT")
    assert not bot._looks_like_symbol_shortcut("PLAYUSDT")
    assert not bot._looks_like_symbol_shortcut("/PLAY")
    assert not bot._looks_like_symbol_shortcut("/convex")


def test_configured_symbol_slash_aliases_are_normalized(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_SYMBOL_SLASH_ALIASES", "playusdt, chip, /raveusdt")
    assert bot._configured_symbol_slash_aliases() == ["PLAYUSDT", "CHIPUSDT", "RAVEUSDT"]
    assert bot._symbol_slash_command_name("PLAYUSDT") == "playusdt"


def test_message_content_intent_requires_explicit_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_SYMBOL_SHORTCUTS_ENABLED", "1")
    monkeypatch.delenv("DISCORD_MESSAGE_CONTENT_INTENT_ENABLED", raising=False)
    assert bot._env_bool("DISCORD_SYMBOL_SHORTCUTS_ENABLED", False)
    assert not bot._env_bool("DISCORD_MESSAGE_CONTENT_INTENT_ENABLED", False)


def test_coin_stats_description_uses_scan_metrics_without_holder_fetch(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_HOLDER_COMPOSITION_ENABLED", "0")
    row = pd.Series(
        {
            "symbol": "PLAYUSDT",
            "last_price": 0.123456,
            "price_change_24h_pct": 12.3,
            "quote_volume_24h": 12345678,
            "trade_bucket_score": 88.1,
            "convexity_entry_score": 42.0,
            "pre_pump_precision_score": 77.0,
            "short_account_pct": 61.2,
            "long_account_pct": 38.8,
            "oi_value_usdt": 9876543,
            "trade_bucket_note": "low-volatility short crowd with rising convex setup pressure",
        }
    )

    description = bot._coin_stats_description(row, source="test cache")

    assert "**PLAYUSDT**" in description
    assert "Source: test cache" in description
    assert "Scores:" in description
    assert "short 61.2%" in description
    assert "low-volatility short crowd" in description
