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


def test_discord_access_tier_resolves_from_roles_and_defaults(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_DEFAULT_USER_TIER", "free")
    monkeypatch.setenv("DISCORD_PAID_ROLE_IDS", "111,222")
    monkeypatch.setenv("DISCORD_PRO_ROLE_IDS", "333")

    assert bot._tier_for_role_ids(set()) == "free"
    assert bot._tier_for_role_ids({222}) == "paid"
    assert bot._tier_for_role_ids({333}) == "pro"
    assert bot._tier_allows("paid", "free")
    assert bot._tier_allows("pro", "paid")
    assert not bot._tier_allows("free", "paid")


def test_feature_tier_defaults_keep_existing_server_permissive(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_DEFAULT_USER_TIER", raising=False)
    monkeypatch.delenv("DISCORD_COIN_MIN_TIER", raising=False)

    assert bot._tier_for_role_ids(set()) == "pro"
    assert bot._feature_required_tier("coin") == "paid"
    assert bot._tier_allows(bot._tier_for_role_ids(set()), bot._feature_required_tier("coin"))


def test_load_shorts_list_returns_every_symbol_over_50pct(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "latest.csv"
    pd.DataFrame(
        [
            {"symbol": "AAAUSDT", "short_account_pct": 49.9, "scan_mode": "Deep", "scanned_at_utc": "2026-01-01T00:00:00Z"},
            {"symbol": "BBBUSDT", "short_account_pct": 50.1, "scan_mode": "Deep", "scanned_at_utc": "2026-01-01T00:00:00Z"},
            {"symbol": "CCCUSDT", "short_account_pct": 72.5, "scan_mode": "Deep", "scanned_at_utc": "2026-01-01T00:00:00Z"},
        ]
    ).to_csv(cache, index=False)
    monkeypatch.setenv("DISCORD_CONVEX_CACHE_PATH", str(cache))
    monkeypatch.setattr(bot, "_load_live_shorts_frame", lambda: (pd.DataFrame(), "live unavailable"))

    title, chunks = bot._load_shorts_list()
    output = "\n".join(chunks)

    assert title == "Short-account majority list"
    assert "CCCUSDT" in output
    assert "BBBUSDT" in output
    assert "AAAUSDT" not in output


def test_load_shorts_list_prefers_live_binance_rows(monkeypatch) -> None:
    live = pd.DataFrame(
        [
            {"symbol": "PLAYUSDT", "short_account_pct": 52.3, "scan_mode": "live 5m", "scanned_at_utc": "now"},
            {"symbol": "RAVEUSDT", "short_account_pct": 49.0, "scan_mode": "live 5m", "scanned_at_utc": "now"},
        ]
    )
    monkeypatch.setattr(bot, "_load_live_shorts_frame", lambda: (live, ""))

    _, chunks = bot._load_shorts_list()
    output = "\n".join(chunks)

    assert "Source: live Binance account-ratio scan" in output
    assert "PLAYUSDT" in output
    assert "RAVEUSDT" not in output


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

    assert "/PLAYUSDT" in description
    assert "Scan source: test cache" in description
    assert "Convex Score: 88/100" in description
    assert "Structure:" in description
    assert "Perp positioning: short accounts 61.2% | long accounts 38.8%" in description
    assert "Observed trigger:" in description
    assert "Risk level: High" in description
    assert "Research constraint: entries, sizing, stops, and execution are your own responsibility" in description
