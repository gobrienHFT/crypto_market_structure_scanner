import pandas as pd
import pytest

import discord_convex_bot as bot


@pytest.fixture(autouse=True)
def disable_live_command_scans(monkeypatch):
    monkeypatch.setenv("DISCORD_COMMAND_LIVE_SCAN_ENABLED", "0")


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
    assert bot._normalize_symbol_query("/timing") == ""
    assert bot._normalize_symbol_query("/dossier") == ""
    assert bot._normalize_symbol_query("/cexflow") == ""
    assert bot._normalize_symbol_query("/cex_flow") == ""


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


def test_trade_bot_send_failure_is_reported_without_raising(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("TRADE_BOT_DISCORD_WEBHOOK_URL", raising=False)

    class FailingChannel:
        async def send(self, _message: str) -> None:
            raise RuntimeError("missing access")

    error = bot.asyncio.run(bot._safe_trade_bot_send(FailingChannel(), "hello"))
    assert "channel RuntimeError" in error
    assert "missing access" in error


def test_trade_bot_send_prefers_webhook_by_default(monkeypatch) -> None:
    class FailingChannel:
        async def send(self, _message: str) -> None:
            raise AssertionError("channel send should not be used when webhook succeeds")

    class Response:
        status_code = 204
        text = ""

    calls = []

    def fake_post(url, json, timeout):
        calls.append((url, json, timeout))
        return Response()

    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/webhook")
    monkeypatch.delenv("TRADE_BOT_DISCORD_SEND_METHOD", raising=False)
    monkeypatch.setattr(bot.requests, "post", fake_post)

    error = bot.asyncio.run(bot._safe_trade_bot_send(FailingChannel(), "hello"))
    assert error == ""
    assert calls
    assert calls[0][0] == "https://discord.test/webhook"
    assert "hello" in calls[0][1]["content"]


def test_trade_bot_send_uses_webhook_fallback(monkeypatch) -> None:
    class FailingChannel:
        async def send(self, _message: str) -> None:
            raise RuntimeError("missing access")

    class Response:
        status_code = 204
        text = ""

    calls = []

    def fake_post(url, json, timeout):
        calls.append((url, json, timeout))
        return Response()

    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/webhook")
    monkeypatch.setenv("TRADE_BOT_DISCORD_SEND_METHOD", "channel_first")
    monkeypatch.setattr(bot.requests, "post", fake_post)

    error = bot.asyncio.run(bot._safe_trade_bot_send(FailingChannel(), "hello"))
    assert error == ""
    assert calls
    assert calls[0][0] == "https://discord.test/webhook"
    assert "hello" in calls[0][1]["content"]


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
    monkeypatch.setattr(bot, "_latest_snapshot_frame", lambda: pd.DataFrame())
    monkeypatch.setattr(bot, "_load_live_shorts_frame", lambda: (pd.DataFrame(), "live unavailable"))

    title, chunks = bot._load_shorts_list()
    output = "\n".join(chunks)

    assert title == "Short-account majority list"
    assert "CCCUSDT" in output
    assert "BBBUSDT" in output
    assert "AAAUSDT" not in output
    assert output.index("CCCUSDT 72.5%") < output.index("BBBUSDT 50.1%")


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
    assert "PLAYUSDT 52.3%" in output
    assert "RAVEUSDT" not in output


def test_load_timing_list_ranks_current_timing_cache(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "latest.csv"
    pd.DataFrame(
        [
            {
                "symbol": "AAAUSDT",
                "terminal_edge_score": 45,
                "short_account_pct": 49,
                "oi_delta_pct": 0.1,
                "hour_return_pct": 0.0,
            },
            {
                "symbol": "BBBUSDT",
                "terminal_edge_score": 72,
                "short_account_pct": 62,
                "bitget_volume_share_pct": 7.5,
                "oi_delta_pct": 3.0,
                "hour_return_pct": 2.0,
                "hour_volume_multiple": 2.0,
                "hour_trade_count_multiple": 1.8,
                "hour_close_location_pct": 80,
                "distance_to_high_5d_pct": 1.0,
            },
        ]
    ).to_csv(cache, index=False)
    monkeypatch.setenv("DISCORD_CONVEX_CACHE_PATH", str(cache))
    monkeypatch.setattr(bot, "_latest_snapshot_frame", lambda: pd.DataFrame())

    title, output = bot._load_timing_list(2)

    assert title == "Timing watchlist"
    assert "BBBUSDT" in output
    assert "AAAUSDT" not in output
    assert "timing" in output


def test_load_cex_flow_list_prefers_fresh_concentration_gated_rows(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "old_latest.csv"
    pd.DataFrame(
        [
            {
                "symbol": "OLDUSDT",
                "cex_deposit_flow_score": 99,
                "cex_deposit_flow_flag": True,
                "scan_mode": "Deep",
                "scanned_at_utc": "old",
            }
        ]
    ).to_csv(cache, index=False)
    fresh = pd.DataFrame(
        [
            {
                "symbol": "PLAYUSDT",
                "cex_deposit_flow_score": 88,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 3,
                "cex_deposit_24h_token_amount": 2_500_000,
                "cex_deposit_24h_max_amount": 1_200_000,
                "cex_deposit_24h_total_pct_supply": 2.5,
                "cex_deposit_24h_target_exchanges": "Bitget, Kraken",
                "cex_deposit_concentration_gate": "top10 91.0% / top100 99.0%",
                "cex_deposit_flow_note": "concentration-gated CEX deposit flow",
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "LOWUSDT",
                "cex_deposit_flow_score": 0,
                "cex_deposit_flow_flag": False,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
        ]
    )
    monkeypatch.setenv("DISCORD_CONVEX_CACHE_PATH", str(cache))
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None: (fresh, "fresh Deep scan at now"))

    title, chunks = bot._load_cex_flow_list(10)
    output = "\n".join(chunks)

    assert title == "Large CEX token-transfer flow"
    assert "Source: fresh Deep scan" in output
    assert "PLAYUSDT" in output
    assert "Bitget" in output
    assert "LOWUSDT" not in output
    assert "OLDUSDT" not in output


def test_load_candidates_prefers_fresh_scan_and_ignores_old_cache(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "old_latest.csv"
    pd.DataFrame(
        [
            {
                "symbol": "OLDUSDT",
                "trade_bucket": "Convex Long",
                "trade_bucket_score": 99,
                "scan_mode": "Deep",
                "scanned_at_utc": "2026-01-01T00:00:00Z",
            }
        ]
    ).to_csv(cache, index=False)
    fresh = pd.DataFrame(
        [
            {
                "symbol": "NEWUSDT",
                "trade_bucket": "Convex Long",
                "trade_bucket_score": 82,
                "gate_volume_share_pct": 4.2,
                "scan_mode": "Deep",
                "scanned_at_utc": "2026-05-14 18:00:00 UTC",
            }
        ]
    )
    monkeypatch.setenv("DISCORD_CONVEX_CACHE_PATH", str(cache))
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None: (fresh, "fresh Deep scan at 2026-05-14 18:00:00 UTC"))

    title, description = bot._load_candidates(5)

    assert title.startswith("Fresh scanner sample")
    assert "NEWUSDT" in description
    assert "OLDUSDT" not in description
    assert "Source: fresh Deep scan" in description


def test_load_candidates_no_current_candidates_does_not_show_old_cache(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "old_latest.csv"
    pd.DataFrame(
        [
            {
                "symbol": "CHIPUSDT",
                "trade_bucket": "Convex Long",
                "trade_bucket_score": 99,
                "scan_mode": "Deep",
                "scanned_at_utc": "2026-01-01T00:00:00Z",
            }
        ]
    ).to_csv(cache, index=False)
    fresh = pd.DataFrame(
        [
            {
                "symbol": "PLAINUSDT",
                "trade_bucket": "Watch",
                "trade_bucket_score": 10,
                "scan_mode": "Deep",
                "scanned_at_utc": "2026-05-14 18:00:00 UTC",
            }
        ]
    )
    monkeypatch.setenv("DISCORD_CONVEX_CACHE_PATH", str(cache))
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None: (fresh, "fresh Deep scan at 2026-05-14 18:00:00 UTC"))

    title, description = bot._load_candidates(5)

    assert "no current Convex candidates" in title
    assert "No current market-structure candidates" in description
    assert "CHIPUSDT" not in description


def test_load_terminal_list_prefers_fresh_full_universe(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "old_latest.csv"
    pd.DataFrame(
        [
            {"symbol": "OLDUSDT", "terminal_edge_score": 99, "short_account_pct": 99, "scan_mode": "Deep", "scanned_at_utc": "old"},
        ]
    ).to_csv(cache, index=False)
    fresh = pd.DataFrame(
        [
            {"symbol": "AAAUSDT", "terminal_edge_score": 10, "short_account_pct": 51, "scan_mode": "Deep", "scanned_at_utc": "now"},
            {
                "symbol": "BBBUSDT",
                "terminal_edge_score": 80,
                "short_account_pct": 61,
                "bitget_volume_share_pct": 5.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
        ]
    )
    monkeypatch.setenv("DISCORD_CONVEX_CACHE_PATH", str(cache))
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None: (fresh, "fresh Deep scan at now"))

    title, output = bot._load_terminal_list(2)

    assert title == "Market-structure evidence terminal"
    assert "Source: fresh Deep scan" in output
    assert "AAAUSDT" not in output
    assert "BBBUSDT" in output
    assert "OLDUSDT" not in output


def test_load_coin_scan_row_does_not_resurrect_cache_when_fresh_scan_misses_symbol(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "old_latest.csv"
    pd.DataFrame(
        [
            {
                "symbol": "PLAYUSDT",
                "trade_bucket_score": 99,
                "short_account_pct": 70,
                "scan_mode": "Deep",
                "scanned_at_utc": "2026-01-01T00:00:00Z",
            }
        ]
    ).to_csv(cache, index=False)
    fresh = pd.DataFrame(
        [
            {
                "symbol": "OTHERUSDT",
                "trade_bucket_score": 20,
                "scan_mode": "Deep",
                "scanned_at_utc": "2026-05-14 18:00:00 UTC",
            }
        ]
    )
    monkeypatch.setenv("DISCORD_CONVEX_CACHE_PATH", str(cache))
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None: (fresh, "fresh Deep scan at 2026-05-14 18:00:00 UTC"))

    row, source = bot._load_coin_scan_row("PLAYUSDT")

    assert row is None
    assert "fresh Deep scan" in source


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


def test_convex_candidates_require_bitget_or_gate_by_default(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_REQUIRE_BITGET_OR_GATE", raising=False)
    frame = pd.DataFrame(
        [
            {"symbol": "NOGATEUSDT", "trade_bucket": "Convex Long", "trade_bucket_score": 99},
            {"symbol": "BITGETUSDT", "trade_bucket": "Convex Long", "trade_bucket_score": 90, "bitget_volume_share_pct": 0.1},
            {"symbol": "GATEUSDT", "trade_bucket": "Convex Long", "trade_bucket_score": 88, "gate_volume_share_pct": 2.0},
        ]
    )

    selected = bot._convex_candidates_from_frame(frame)

    assert selected["symbol"].tolist() == ["BITGETUSDT", "GATEUSDT"]


def test_bitget_gate_venue_gate_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_REQUIRE_BITGET_OR_GATE", "0")
    frame = pd.DataFrame([{"symbol": "NOGATEUSDT", "trade_bucket": "Convex Long", "trade_bucket_score": 99}])

    selected = bot._convex_candidates_from_frame(frame)

    assert selected["symbol"].tolist() == ["NOGATEUSDT"]
