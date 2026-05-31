import pandas as pd
import pytest

import discord_convex_bot as bot
from holder_composition import HolderComposition, HolderRow


@pytest.fixture(autouse=True)
def disable_live_command_scans(monkeypatch):
    monkeypatch.setenv("DISCORD_COMMAND_LIVE_SCAN_ENABLED", "0")


def _holder_evidence(chain: str = "ethereum", contract: str = "0x1111111111111111111111111111111111111111") -> dict[str, object]:
    source = {"ethereum": "Etherscan", "bsc": "BscScan", "arbitrum": "Arbiscan"}.get(chain, "Explorer")
    return {
        "token_platform": chain,
        "token_contract": contract,
        "holder_source": f"{source} holder endpoint",
        "holder_count": 6_000,
        "top10_holder_pct": 91.0,
        "top100_holder_pct": 99.0,
        "history_days": 180,
        "recent_max_pump_60d_pct": 6.0,
        "recent_pump_60d_days": 60,
        "no_large_pump_60d_flag": True,
    }


def test_normalize_symbol_query_accepts_fast_coin_forms() -> None:
    assert bot._normalize_symbol_query("playusdt") == "PLAYUSDT"
    assert bot._normalize_symbol_query("/PLAYUSDT") == "PLAYUSDT"
    assert bot._normalize_symbol_query("!PLAYUSDT") == "PLAYUSDT"
    assert bot._normalize_symbol_query("$playusdt") == "PLAYUSDT"
    assert bot._normalize_symbol_query("play") == "PLAYUSDT"


def test_normalize_symbol_query_rejects_bot_commands() -> None:
    assert bot._normalize_symbol_query("/convex") == ""
    assert bot._normalize_symbol_query("/commands") == ""
    assert bot._normalize_symbol_query("/convex_status") == ""
    assert bot._normalize_symbol_query("/coin") == ""
    assert bot._normalize_symbol_query("/whales") == ""
    assert bot._normalize_symbol_query("/funding") == ""
    assert bot._normalize_symbol_query("/fundingrates") == ""
    assert bot._normalize_symbol_query("/setupscore") == ""
    assert bot._normalize_symbol_query("/precrime") == ""
    assert bot._normalize_symbol_query("/ravelab") == ""
    assert bot._normalize_symbol_query("/radar") == ""
    assert bot._normalize_symbol_query("/prime") == ""
    assert bot._normalize_symbol_query("/crimepump") == ""
    assert bot._normalize_symbol_query("/flowproof") == ""
    assert bot._normalize_symbol_query("/coincheck") == ""
    assert bot._normalize_symbol_query("/floattrap") == ""
    assert bot._normalize_symbol_query("/squeezeready") == ""
    assert bot._normalize_symbol_query("/cextargets") == ""
    assert bot._normalize_symbol_query("/high") == ""
    assert bot._normalize_symbol_query("/low") == ""
    assert bot._normalize_symbol_query("/timing") == ""
    assert bot._normalize_symbol_query("/corr") == ""
    assert bot._normalize_symbol_query("/dossier") == ""
    assert bot._normalize_symbol_query("/cexflow") == ""
    assert bot._normalize_symbol_query("/cex_flow") == ""
    assert bot._normalize_symbol_query("/cexdiag") == ""
    assert bot._normalize_symbol_query("/earlyflow") == ""
    assert bot._normalize_symbol_query("/flowcoin") == ""
    assert bot._normalize_symbol_query("/flowstress") == ""
    assert bot._normalize_symbol_query("/flowblocked") == ""
    assert bot._normalize_symbol_query("/flowhealth") == ""
    assert bot._normalize_symbol_query("/sethflow") == ""
    assert bot._normalize_symbol_query("/alpha") == ""
    assert bot._normalize_symbol_query("/sync_commands") == ""


def test_load_command_guide_names_primary_and_diagnostic_paths() -> None:
    title, chunks = bot._load_command_guide()
    output = "\n".join(chunks)

    assert title == "Discord command guide"
    assert "/commands - this operator map" in output
    assert "Use /radar first" in output
    assert "/ravelab - diagnostic microscope" in output
    assert "/cexdiag" in output
    assert "/flowhealth" in output
    assert "Rule of thumb: /radar for candidates" in output


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


def test_load_funding_leaderboard_splits_long_and_short_carry(monkeypatch) -> None:
    now_ms = int(bot.time.time() * 1000)

    class FakeFundingClient:
        def __init__(self, **_kwargs):
            pass

        def mark_price(self):
            return [
                {"symbol": "POSUSDT", "lastFundingRate": "0.0012", "nextFundingTime": now_ms + 7_200_000, "markPrice": "1.23"},
                {"symbol": "SMALLPOSUSDT", "lastFundingRate": "0.0004", "nextFundingTime": now_ms + 7_200_000, "markPrice": "0.0123"},
                {"symbol": "NEGUSDT", "lastFundingRate": "-0.0008", "nextFundingTime": now_ms + 3_600_000, "markPrice": "0.00001234"},
                {"symbol": "BTCUSDC", "lastFundingRate": "0.0099", "nextFundingTime": now_ms + 3_600_000, "markPrice": "100"},
            ]

        def ticker_24hr(self):
            return [
                {"symbol": "POSUSDT", "priceChangePercent": "4.2", "quoteVolume": "12300000"},
                {"symbol": "SMALLPOSUSDT", "priceChangePercent": "-1.5", "quoteVolume": "250000"},
                {"symbol": "NEGUSDT", "priceChangePercent": "-2.5", "quoteVolume": "9900000"},
            ]

        def funding_info(self):
            return [{"symbol": "NEGUSDT", "fundingIntervalHours": 4}]

        def global_long_short_account_ratio(self, symbol, *, period="1h", limit=1):
            assert period == "1h"
            ratios = {
                "POSUSDT": {"longAccount": "0.4", "shortAccount": "0.6"},
                "SMALLPOSUSDT": {"longAccount": "0.51", "shortAccount": "0.49"},
                "NEGUSDT": {"longAccount": "0.7", "shortAccount": "0.3"},
            }
            return [ratios[symbol]]

    monkeypatch.setattr(bot, "BinanceFuturesPublic", FakeFundingClient)

    title, chunks = bot._load_funding_leaderboard(2, side="both", period="1h")
    output = "\n".join(chunks)

    assert title == "Funding carry leaderboard"
    assert "positive funding = longs pay shorts" in output
    assert "negative funding = shorts pay longs" in output
    assert "Short-carry candidates (positive funding; shorts receive)" in output
    assert "Long-carry candidates (negative funding; longs receive)" in output
    assert output.index("/POSUSDT | funding +0.1200%/8h") < output.index("/SMALLPOSUSDT | funding +0.0400%/8h")
    assert "/NEGUSDT | funding -0.0800%/4h" in output
    assert "vol 12.30M" in output
    assert "shorts 60.0% | longs 40.0%" in output
    assert "BTCUSDC" not in output


def test_load_funding_leaderboard_can_show_only_long_carry(monkeypatch) -> None:
    class FakeFundingClient:
        def __init__(self, **_kwargs):
            pass

        def mark_price(self):
            return [
                {"symbol": "POSUSDT", "lastFundingRate": "0.0012", "nextFundingTime": 0, "markPrice": "1"},
                {"symbol": "NEGUSDT", "lastFundingRate": "-0.0008", "nextFundingTime": 0, "markPrice": "1"},
            ]

        def ticker_24hr(self):
            return []

        def funding_info(self):
            return []

        def global_long_short_account_ratio(self, symbol, *, period="1h", limit=1):
            return []

    monkeypatch.setattr(bot, "BinanceFuturesPublic", FakeFundingClient)

    _, chunks = bot._load_funding_leaderboard(10, side="longs", min_abs_funding_pct=0.05)
    output = "\n".join(chunks)

    assert "Long-carry candidates (negative funding; longs receive)" in output
    assert "Short-carry candidates" not in output
    assert "/NEGUSDT | funding -0.0800%/8h" in output
    assert "POSUSDT" not in output


def test_load_whale_dominance_list_ranks_top100_holder_concentration(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "LOWUSDT",
                "top10_holder_pct": 82.0,
                "top100_holder_pct": 89.9,
                "holder_count": 1000,
                "short_account_pct": 55.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "WHALEUSDT",
                "top10_holder_pct": 70.0,
                "top100_holder_pct": 94.0,
                "holder_count": 420,
                "short_account_pct": 61.2,
                "cex_deposit_flow_score": 30,
                "token_platform": "base",
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "MEGAUSDT",
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 98.0,
                "holder_count": 120,
                "short_account_pct": 49.0,
                "terminal_edge_score": 80,
                "cex_deposit_flow_score": 72,
                "token_platform": "ethereum",
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    title, chunks = bot._load_whale_dominance_list(10, min_pct=90)
    output = "\n".join(chunks)

    assert title == "Whale dominance ranking"
    assert "Bucket: top100" in output
    assert "Matches: 2 | Base thesis gate: 0 | Showing: 2" in output
    assert "Diagnostic rows: /MEGAUSDT /WHALEUSDT" in output
    assert output.index("/MEGAUSDT | top100 98.0% | top10 91.0%") < output.index("/WHALEUSDT | top100 94.0% | top10 70.0%")
    assert "baseThesis N" in output
    assert "/LOWUSDT" not in output
    assert "diagnostic holder-concentration rows" in output


def test_load_whale_dominance_list_supports_top10_bucket(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {"symbol": "TOP100USDT", "top10_holder_pct": 55.0, "top100_holder_pct": 99.0, "scan_mode": "Deep", "scanned_at_utc": "now"},
            {"symbol": "TOP10USDT", "top10_holder_pct": 92.0, "top100_holder_pct": 96.0, "scan_mode": "Deep", "scanned_at_utc": "now"},
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    _, chunks = bot._load_whale_dominance_list(10, min_pct=90, bucket="top10")
    output = "\n".join(chunks)

    assert "Bucket: top10" in output
    assert "/TOP10USDT" in output
    assert "TOP100USDT" not in output


def test_load_whale_dominance_list_computes_top100_when_scan_columns_missing(monkeypatch, tmp_path) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "CALCUSDT",
                "token_platform": "base",
                "token_contract": "0x1111111111111111111111111111111111111111",
                "short_account_pct": 64.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "LOWUSDT",
                "token_platform": "bsc",
                "token_contract": "0x2222222222222222222222222222222222222222",
                "short_account_pct": 55.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
        ]
    )
    monkeypatch.setenv("DISCORD_WHALES_CACHE_PATH", str(tmp_path / "whales.csv"))
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    def fake_fetch(row, **_kwargs):
        symbol = str(row.get("symbol", "")).upper()
        pct = 0.95 if symbol == "CALCUSDT" else 0.50
        return HolderComposition(
            symbol=symbol,
            chain=str(row.get("token_platform", "")),
            contract_address=str(row.get("token_contract", "")),
            holder_count=123,
            top_holders=[
                HolderRow(
                    rank=index,
                    address=f"0x{index:040x}",
                    percent=pct,
                )
                for index in range(1, 101)
            ],
            source="test holder scan",
        )

    monkeypatch.setattr(bot, "fetch_holder_composition", fake_fetch)

    title, chunks = bot._load_whale_dominance_list(10, min_pct=90, bucket="top100", refresh=True)
    output = "\n".join(chunks)

    assert title == "Whale dominance ranking"
    assert "computed holder composition" in output
    assert "Matches: 1 | Base thesis gate: 0 | Showing: 1" in output
    assert "Diagnostic rows: /CALCUSDT" in output
    assert "/CALCUSDT | top100 95.0% | top10 9.5%" in output
    assert "baseThesis N" in output
    assert "/LOWUSDT" not in output
    assert (tmp_path / "whales.csv").exists()


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
                    "binance_volume_share_pct": 3.0,
                    "bitget_volume_share_pct": 7.5,
                    **_holder_evidence("ethereum", "0x2222222222222222222222222222222222222222"),
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


def test_load_high_breakout_list_uses_requested_window(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
                {
                    "symbol": "FASTUSDT",
                    "broke_high_20d": True,
                    "broke_low_20d": False,
                    "price_change_24h_pct": 8.2,
                "last_price": 0.1234,
                    "range_high_break_count": 2,
                    "range_low_break_count": 0,
                    "short_account_pct": 61.0,
                    "binance_volume_share_pct": 3.0,
                    "bitget_volume_share_pct": 2.0,
                    **_holder_evidence("ethereum", "0x9999999999999999999999999999999999999999"),
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "SLOWUSDT",
                "broke_high_20d": True,
                "broke_low_20d": False,
                "price_change_24h_pct": 2.1,
                "range_high_break_count": 1,
                "range_low_break_count": 0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "LOWUSDT",
                "broke_high_20d": False,
                "broke_low_20d": True,
                "price_change_24h_pct": -6.5,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    title, chunks = bot._load_breakout_list("high", days="20D")
    output = "\n".join(chunks)

    assert title == "HIGH breakout screen"
    assert "20D high breakout screen" in output
    assert "Filter: `broke_high_20d` is true" in output
    assert "Thesis breakout matches: 1" in output
    assert "Matches: 2" in output
    assert "/FASTUSDT | broke 20D high | 24h +8.2% | price 0.12 | breaks H2/L0 | shorts 61.0% | thesis Y" in output
    assert "/SLOWUSDT | broke 20D high | 24h +2.1% | breaks H1/L0 | thesis N" in output
    assert output.index("/FASTUSDT") < output.index("/SLOWUSDT")
    assert "/LOWUSDT" not in output

    _, thesis_chunks = bot._load_breakout_list("high", days="20D", thesis_only=True)
    thesis_output = "\n".join(thesis_chunks)
    assert "Thesis-only: True" in thesis_output
    assert "Matches: 1 | Strict thesis matches: 1" in thesis_output
    assert "/FASTUSDT" in thesis_output
    assert "/SLOWUSDT" not in thesis_output


def test_load_low_breakout_list_uses_numeric_days(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "LOWERUSDT",
                "broke_low_90d": True,
                "broke_high_90d": False,
                "price_change_24h_pct": -9.5,
                "range_high_break_count": 0,
                "range_low_break_count": 2,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "BOUNCEUSDT",
                "broke_low_90d": True,
                "broke_high_90d": False,
                "price_change_24h_pct": -2.0,
                "range_high_break_count": 0,
                "range_low_break_count": 1,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "HIGHERUSDT",
                "broke_low_90d": False,
                "broke_high_90d": True,
                "price_change_24h_pct": 5.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    title, chunks = bot._load_breakout_list("low", days="90")
    output = "\n".join(chunks)

    assert title == "LOW breakout screen"
    assert "90D low breakout screen" in output
    assert "Filter: `broke_low_90d` is true" in output
    assert "Matches: 2" in output
    assert output.index("/LOWERUSDT") < output.index("/BOUNCEUSDT")
    assert "/LOWERUSDT | broke 90D low | 24h -9.5% | breaks H0/L2" in output
    assert "HIGHERUSDT" not in output


def test_load_breakout_list_computes_arbitrary_high_window(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "DYNUSDT",
                "high_24h": 15.0,
                "low_24h": 9.0,
                "price_change_24h_pct": 4.2,
                "last_price": 14.8,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "YOUNGUSDT",
                "high_24h": 5.0,
                "low_24h": 1.0,
                "price_change_24h_pct": 2.0,
                "last_price": 4.9,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "MISSUSDT",
                "high_24h": 10.0,
                "low_24h": 8.0,
                "price_change_24h_pct": 1.0,
                "last_price": 9.5,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
        ]
    )

    class FakeBinance:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def klines_1d(self, symbol: str, limit: int = 200, **kwargs):
            if symbol == "DYNUSDT":
                closed = [[0, 0, high, 1, 0] for high in range(1, 14)]
                return [*closed, [0, 0, 15, 9, 0]]
            if symbol == "YOUNGUSDT":
                return [[0, 0, 2, 1, 0], [0, 0, 3, 1, 0], [0, 0, 4, 1, 0], [0, 0, 5, 1, 0]]
            if symbol == "MISSUSDT":
                closed = [[0, 0, high, 1, 0] for high in range(1, 14)]
                return [*closed, [0, 0, 10, 8, 0]]
            return []

    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))
    monkeypatch.setattr(bot, "BinanceFuturesPublic", FakeBinance)

    title, chunks = bot._load_breakout_list("high", days="13D")
    output = "\n".join(chunks)

    assert title == "HIGH breakout screen"
    assert "13D high breakout screen" in output
    assert "computed prior 13D high from Binance daily klines" in output
    assert "Matches: 2" in output
    assert "/DYNUSDT | broke 13D high | 24h +4.2% | price 14.8 | prior high 13" in output
    assert "/YOUNGUSDT | broke 13D high | 24h +2.0% | price 4.9 | used 3d | prior high 4" in output
    assert "/MISSUSDT" not in output


def test_load_breakout_list_computes_arbitrary_low_window(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "DUMPUSDT",
                "high_24h": 6.0,
                "low_24h": 0.8,
                "price_change_24h_pct": -8.4,
                "last_price": 0.9,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "BOUNCEUSDT",
                "high_24h": 8.0,
                "low_24h": 5.2,
                "price_change_24h_pct": -1.0,
                "last_price": 5.7,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
        ]
    )

    class FakeBinance:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def klines_1d(self, symbol: str, limit: int = 200, **kwargs):
            if symbol == "DUMPUSDT":
                return [[0, 0, 10, low, 0] for low in range(14, 1, -1)] + [[0, 0, 6, 0.8, 0]]
            if symbol == "BOUNCEUSDT":
                return [[0, 0, 10, low, 0] for low in range(14, 1, -1)] + [[0, 0, 8, 5.2, 0]]
            return []

    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))
    monkeypatch.setattr(bot, "BinanceFuturesPublic", FakeBinance)

    title, chunks = bot._load_breakout_list("low", days="13")
    output = "\n".join(chunks)

    assert title == "LOW breakout screen"
    assert "13D low breakout screen" in output
    assert "computed prior 13D low from Binance daily klines" in output
    assert "Matches: 1" in output
    assert "/DUMPUSDT | broke 13D low | 24h -8.4% | price 0.9 | prior low 2" in output
    assert "/BOUNCEUSDT" not in output


def test_load_breakout_list_rejects_unsupported_window(monkeypatch) -> None:
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (pd.DataFrame(), "unused"))

    title, chunks = bot._load_breakout_list("high", days="0D")

    assert title == "HIGH breakout screen"
    assert "Unsupported breakout window `0D`" in "\n".join(chunks)
    assert "1D-1499D" in "\n".join(chunks)


def test_load_corr_list_filters_high_btc_correlation(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "YOUNGUSDT",
                "corr_to_btc_6m": -0.82,
                "corr_window_days": 37,
                "short_account_pct": 61.2,
                "price_change_24h_pct": 4.5,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "INVERSEUSDT",
                "corr_to_btc_6m": -0.61,
                "corr_window_days": 180,
                "short_account_pct": 54.0,
                "price_change_24h_pct": -2.1,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "WEAKUSDT",
                "corr_to_btc_6m": -0.21,
                "corr_window_days": 180,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "POSUSDT",
                "corr_to_btc_6m": 0.42,
                "corr_window_days": 180,
                "price_change_24h_pct": 1.1,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "HIGHUSDT",
                "corr_to_btc_6m": 0.72,
                "corr_window_days": 180,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    title, chunks = bot._load_corr_list(threshold=0.5)
    output = "\n".join(chunks)

    assert title == "BTC low-correlation screen"
    assert "Threshold: corr <= 0.50" in output
    assert "Target window: max 180d" in output
    assert "Matches: 4" in output
    assert "/YOUNGUSDT | corr -0.820 | used 37d (max available)" in output
    assert "/INVERSEUSDT | corr -0.610 | used 180d" in output
    assert "/WEAKUSDT | corr -0.210 | used 180d" in output
    assert "/POSUSDT | corr 0.420 | used 180d" in output
    assert "shorts 61.2%" in output
    assert "24h 4.5%" in output
    assert "HIGHUSDT" not in output


def test_load_corr_list_without_threshold_shows_all_negative_rows(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {"symbol": "NEGUSDT", "corr_to_btc_6m": -0.01, "corr_window_days": 12, "scan_mode": "Deep", "scanned_at_utc": "now"},
            {"symbol": "POSUSDT", "corr_to_btc_6m": 0.01, "corr_window_days": 12, "scan_mode": "Deep", "scanned_at_utc": "now"},
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    _, chunks = bot._load_corr_list()
    output = "\n".join(chunks)

    assert "Threshold: corr < 0.00" in output
    assert "/NEGUSDT | corr -0.010 | used 12d (max available)" in output
    assert "POSUSDT" not in output


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
                "token_platform": "ethereum",
                "token_contract": "0x1111111111111111111111111111111111111111",
                "holder_source": "Etherscan holder endpoint",
                "holder_count": 6_000,
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 99.0,
                "binance_volume_share_pct": 3.0,
                "bitget_volume_share_pct": 1.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "GATEONLYUSDT",
                "cex_deposit_flow_score": 77,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 1,
                "cex_deposit_24h_token_amount": 900_000,
                "cex_deposit_24h_max_amount": 900_000,
                "cex_deposit_24h_target_exchanges": "Gate",
                "cex_deposit_concentration_gate": "top10 92.0% / top100 98.0%",
                "token_platform": "bsc",
                "token_contract": "0x2222222222222222222222222222222222222222",
                "holder_source": "BscScan holder endpoint",
                "holder_count": 5_000,
                "top10_holder_pct": 92.0,
                "top100_holder_pct": 98.0,
                "gate_volume_share_pct": 2.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "TOP100ONLYUSDT",
                "cex_deposit_flow_score": 79,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 1,
                "cex_deposit_24h_token_amount": 750_000,
                "cex_deposit_24h_max_amount": 750_000,
                "cex_deposit_24h_target_exchanges": "Bitget",
                "cex_deposit_concentration_gate": "top10 55.0% / top100 99.0%",
                "token_platform": "ethereum",
                "token_contract": "0x4444444444444444444444444444444444444444",
                "holder_source": "Etherscan holder endpoint",
                "holder_count": 5_000,
                "top10_holder_pct": 55.0,
                "top100_holder_pct": 99.0,
                "binance_volume_share_pct": 3.0,
                "bitget_volume_share_pct": 1.0,
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
    captured: dict[str, object] = {}

    def fake_fresh_scan(scan_mode=None, **kwargs):
        captured.update(kwargs)
        return fresh, "fresh Deep scan at now"

    monkeypatch.setattr(bot, "_fresh_scanner_frame", fake_fresh_scan)

    title, chunks = bot._load_cex_flow_list(10, min_tokens=20_000, lookback_hours=24)
    output = "\n".join(chunks)

    assert title == "Wallet-to-CEX flow monitor"
    assert "Wallet-to-CEX flow monitor" in output
    assert "Min transfer: 20.00K tokens" in output
    assert "Holder gate: observed top10 holder >= 90.0%" in output
    assert "Holder evidence required: True" in output
    assert "Flow rows before holder gate: 3 | After holder gate: 2 | After venue gate: 1" in output
    assert "observed top10 >= 90.0% rows 2" in output
    assert "Candidates: /PLAYUSDT" in output
    assert "Source: fresh Deep scan" in output
    assert "PLAYUSDT" in output
    assert "CEX Flow Score: 88/100" in output
    assert "Venue-flow read:" in output
    assert "Next check:" in output
    assert "Bitget" in output
    assert "GATEONLYUSDT" not in output
    assert "TOP100ONLYUSDT" not in output
    assert "LOWUSDT" not in output
    assert "OLDUSDT" not in output
    assert captured["cex_min_transfer_tokens"] == 20_000
    assert captured["cex_lookback_hours"] == 24


def test_load_early_flow_uses_low_default_threshold(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "EARLYUSDT",
                "cex_deposit_flow_score": 52,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 1,
                "cex_deposit_24h_token_amount": 25_000,
                "cex_deposit_24h_max_amount": 25_000,
                "cex_deposit_24h_target_exchanges": "Bitget",
                "cex_deposit_concentration_gate": "top10 91.0% / top100 99.0%",
                "token_platform": "bsc",
                "token_contract": "0x2222222222222222222222222222222222222222",
                "holder_source": "BscScan holder endpoint",
                "holder_count": 4_000,
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 99.0,
                "binance_volume_share_pct": 3.0,
                "bitget_volume_share_pct": 1.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            }
        ]
    )
    captured: dict[str, object] = {}

    def fake_fresh_scan(scan_mode=None, **kwargs):
        captured.update(kwargs)
        return fresh, "fresh Deep scan at now"

    monkeypatch.delenv("DISCORD_EARLY_FLOW_MIN_TOKENS", raising=False)
    monkeypatch.setattr(bot, "_fresh_scanner_frame", fake_fresh_scan)

    title, chunks = bot._load_early_flow_list(10)
    output = "\n".join(chunks)

    assert title == "Early wallet-to-CEX flow sweep"
    assert "Min transfer: 20.00K tokens" in output
    assert "Candidates: /EARLYUSDT" in output
    assert captured["cex_min_transfer_tokens"] == 20_000


def test_cex_flow_holder_floor_stays_top10_90_when_user_passes_lower_floor(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "TOP100ONLYUSDT",
                "cex_deposit_flow_score": 80,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 1,
                "cex_deposit_24h_token_amount": 50_000,
                "cex_deposit_24h_max_amount": 50_000,
                "cex_deposit_24h_target_exchanges": "Bitget",
                "token_platform": "ethereum",
                "token_contract": "0x4444444444444444444444444444444444444444",
                "holder_source": "Etherscan holder endpoint",
                "holder_count": 3_000,
                "top10_holder_pct": 70.0,
                "top100_holder_pct": 99.0,
                "binance_volume_share_pct": 3.0,
                "bitget_volume_share_pct": 1.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            }
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    _, chunks = bot._load_cex_flow_list(10, min_tokens=20_000, min_whale_pct=50, require_venue_gate=False)
    output = "\n".join(chunks)

    assert "Holder gate: observed top10 holder >= 90.0%" in output
    assert "Flow rows before holder gate: 1 | After holder gate: 0 | After venue gate: 0" in output
    assert "observed top10 >= 90.0% rows 0" in output
    assert "/TOP100ONLYUSDT | holder gate not met" in output
    assert "/TOP100ONLYUSDT | FLOW" not in output


def test_load_cex_flow_list_can_disable_venue_gate(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "KRAKENUSDT",
                "cex_deposit_flow_score": 61,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 1,
                "cex_deposit_24h_token_amount": 1_500,
                "cex_deposit_24h_max_amount": 1_500,
                "cex_deposit_24h_target_exchanges": "Kraken",
                "cex_deposit_concentration_gate": "top10 91.0% / top100 99.0%",
                "token_platform": "ethereum",
                "token_contract": "0x3333333333333333333333333333333333333333",
                "holder_source": "Etherscan holder endpoint",
                "holder_count": 3_000,
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 99.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            }
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    gated_title, gated_chunks = bot._load_cex_flow_list(10, min_tokens=1_000, require_venue_gate=True)
    ungated_title, ungated_chunks = bot._load_cex_flow_list(10, min_tokens=1_000, require_venue_gate=False)
    gated_output = "\n".join(gated_chunks)
    ungated_output = "\n".join(ungated_chunks)

    assert gated_title == "Wallet-to-CEX flow monitor"
    assert "Flow rows before holder gate: 1 | After holder gate: 1 | After venue gate: 0" in gated_output
    assert "require_venue_gate:false" in gated_output
    assert ungated_title == "Wallet-to-CEX flow monitor"
    assert "Venue gate: disabled for this command" in ungated_output
    assert "Candidates: /KRAKENUSDT" in ungated_output


def test_load_cex_flow_list_explains_zero_raw_flow(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "HINTUSDT",
                "token_platform": "bsc",
                "token_contract": "0x1111111111111111111111111111111111111111",
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 96.0,
                "holder_source": "BscScan holder endpoint",
                "holder_count": 1_000,
                "cex_deposit_flow_score": 0,
                "cex_deposit_flow_flag": False,
                "cex_deposit_concentration_gate": "top10 91.0% / top100 96.0%",
                "cex_deposit_flow_error": "advanced filter HTTP 403",
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "NOHINTUSDT",
                "cex_deposit_flow_score": 0,
                "cex_deposit_flow_flag": False,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    title, chunks = bot._load_cex_flow_list(10, min_tokens=1_000, require_venue_gate=False)
    output = "\n".join(chunks)

    assert title == "Wallet-to-CEX flow monitor"
    assert "Flow rows before holder gate: 0 | After holder gate: 0 | After venue gate: 0" in output
    assert "Coverage: scan rows 2 | contract hints 1" in output
    assert "precomputed concentration rows 1 | observed top10 >= 90.0% rows 1" in output
    assert "holder evidence rows 1 | strict holder gate pass 1" in output
    assert "CEX-flow attempts 1" in output
    assert "errors 1 | raw flow 0" in output
    assert "Status: explorer blocked 1 CEX-flow attempts with HTTP 403; API fallback/label coverage decides" in output
    assert "Top CEX-flow errors: advanced filter HTTP 403 x1" in output
    assert "not confirmed transfers" in output
    assert "Attempted symbols (not confirmed transfers unless status starts FLOW):" in output
    assert "/HINTUSDT | blocked/error: advanced filter HTTP 403" in output
    assert "query floor was >= 1.00K tokens; no confirmed CEX transfer parsed" in output


def test_load_cex_flow_diagnostics_reports_bottlenecks(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "EMPTYUSDT",
                "token_platform": "bsc",
                "token_contract": "0x2222222222222222222222222222222222222222",
                "top10_holder_pct": 92.0,
                "top100_holder_pct": 97.0,
                "holder_source": "BscScan holder endpoint",
                "holder_count": 2_000,
                "cex_deposit_flow_score": 0,
                "cex_deposit_flow_flag": False,
                "cex_deposit_concentration_gate": "top10 92.0% / top100 97.0%",
                "cex_deposit_flow_note": "concentration gate met; no large labelled CEX deposits found in last 24h.",
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            }
        ]
    )
    captured: dict[str, object] = {}

    def fake_fresh_scan(scan_mode=None, **kwargs):
        captured.update(kwargs)
        return fresh, "fresh Deep scan at now"

    monkeypatch.setattr(bot, "_fresh_scanner_frame", fake_fresh_scan)

    title, description = bot._load_cex_flow_diagnostics(min_tokens=1_000, lookback_hours=48, require_venue_gate=False)

    assert title == "CEX-flow scan diagnostics"
    assert "Min transfer: 1.00K tokens | Lookback: 48h" in description
    assert "Venue gate: disabled for this command" in description
    assert "Coverage: scan rows 1 | contract hints 1" in description
    assert "observed top10 >= 90.0% rows 1" in description
    assert "holder evidence rows 1 | strict holder gate pass 1" in description
    assert "no-transfer rows 1" in description
    assert "Attempted symbols (not confirmed transfers unless status starts FLOW):" in description
    assert "/EMPTYUSDT | checked: no labelled CEX transfer met threshold/lookback" in description
    assert "Read: zero raw flow" in description
    assert "When HTTP 403 dominates, the scanner tries Etherscan V2 token-transfer APIs" in description
    assert "Blocked attempted-symbol rows are query attempts" in description
    assert captured["cex_min_transfer_tokens"] == 1_000
    assert captured["cex_lookback_hours"] == 48


def test_load_cex_flow_diagnostics_lists_blocked_symbols(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "BLOCKEDUSDT",
                "token_platform": "bsc",
                "token_contract": "0x3333333333333333333333333333333333333333",
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 96.0,
                "holder_source": "BscScan holder endpoint",
                "holder_count": 3_000,
                "cex_deposit_flow_score": 0,
                "cex_deposit_flow_flag": False,
                "cex_deposit_concentration_gate": "top10 91.0% / top100 96.0%",
                "cex_deposit_flow_error": "advanced filter HTTP 403",
                "cex_deposit_24h_source_url": "https://bscscan.com/advanced-filter?tkn=0x333",
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "FLOWUSDT",
                "token_platform": "arbitrum",
                "token_contract": "0x4444444444444444444444444444444444444444",
                "top10_holder_pct": 92.0,
                "top100_holder_pct": 97.0,
                "holder_source": "Arbiscan holder endpoint",
                "holder_count": 4_000,
                "cex_deposit_flow_score": 67,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 2,
                "cex_deposit_24h_token_amount": 75_000,
                "cex_deposit_24h_max_amount": 50_000,
                "cex_deposit_24h_target_exchanges": "Bitget",
                "cex_deposit_concentration_gate": "top10 92.0% / top100 97.0%",
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    _, description = bot._load_cex_flow_diagnostics(min_tokens=1_000, require_venue_gate=False, symbol_limit=10)

    assert "Attempted symbols (not confirmed transfers unless status starts FLOW):" in description
    assert "/FLOWUSDT | FLOW 67/100 -> Bitget | 2 tx | total 75.00K tokens | max 50.00K" in description
    assert "/BLOCKEDUSDT | blocked/error: advanced filter HTTP 403" in description
    assert "query floor was >= 1.00K tokens; no confirmed CEX transfer parsed" in description
    assert "query URL available" in description


def test_load_symbol_cex_flow_uses_custom_threshold(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "PLAYUSDT",
                "cex_deposit_flow_score": 64,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 2,
                "cex_deposit_24h_token_amount": 42_000,
                "cex_deposit_24h_max_amount": 22_000,
                "cex_deposit_24h_target_exchanges": "Bitget",
                "cex_deposit_concentration_gate": "top10 91.0% / top100 99.0%",
                "bitget_volume_share_pct": 1.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            }
        ]
    )
    captured: dict[str, object] = {}

    def fake_fresh_scan(scan_mode=None, **kwargs):
        captured.update(kwargs)
        return fresh, "fresh Deep scan at now"

    monkeypatch.setattr(bot, "_fresh_scanner_frame", fake_fresh_scan)

    title, description = bot._load_symbol_cex_flow("PLAY", min_tokens=20_000, lookback_hours=12)

    assert title == "PLAYUSDT CEX flow"
    assert "Min transfer: 20.00K tokens | Lookback: 12h" in description
    assert "CEX Flow Score: 64/100" in description
    assert captured["cex_min_transfer_tokens"] == 20_000
    assert captured["cex_lookback_hours"] == 12


def test_load_flow_stress_list_ranks_inventory_stress(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "STRESSUSDT",
                "cex_deposit_flow_score": 72,
                "cex_deposit_flow_flag": True,
                "cex_deposit_inventory_stress_score": 91,
                "cex_deposit_inventory_stress_note": "venue-inventory stress 91/100; total notional $900.00K",
                "cex_deposit_24h_notional_usd": 900_000,
                "cex_deposit_24h_notional_to_ask_depth_pct": 310.0,
                "cex_deposit_24h_target_exchanges": "Bitget",
                "cex_deposit_flow_source": "token_transfer_api",
                "binance_volume_share_pct": 3.0,
                "bitget_volume_share_pct": 2.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "QUIETUSDT",
                "cex_deposit_inventory_stress_score": 0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    title, chunks = bot._load_flow_stress_list(10, min_tokens=20_000)
    output = "\n".join(chunks)

    assert title == "CEX inventory-stress monitor"
    assert "Stress rows: /STRESSUSDT" in output
    assert "/STRESSUSDT | stress 91/100 | flow 72/100 | Bitget | notional 900.00K | deposits/ask 310.0% | baseThesis N | source token_transfer_api" in output
    assert "QUIETUSDT" not in output


def test_load_flow_blocked_list_shows_api_fallback_errors(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "BLOCKEDUSDT",
                "cex_deposit_flow_error": "advanced filter HTTP 403; token-transfer API fallback found no labelled CEX destination matches",
                "cex_deposit_flow_source": "advanced_filter_blocked_api_fallback",
                "cex_deposit_24h_source_url": "https://api.etherscan.io/v2/api?chainid=8453&module=account&action=tokentx",
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            }
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    title, chunks = bot._load_flow_blocked_list(10, min_tokens=20_000)
    output = "\n".join(chunks)

    assert title == "CEX-flow blocked/error rows"
    assert "/BLOCKEDUSDT | advanced filter HTTP 403; token-transfer API fallback found no labelled CEX destination matches" in output
    assert "advanced_filter_blocked_api_fallback" in output
    assert "not proof that CEX flow is absent" in output


def test_load_flow_health_reports_api_keys_and_address_labels(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "HINTUSDT",
                "token_platform": "base",
                "token_contract": "0x1111111111111111111111111111111111111111",
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 96.0,
                "cex_deposit_flow_error": "advanced filter HTTP 403; token-transfer API fallback found no labelled CEX destination matches",
                "cex_deposit_flow_source": "advanced_filter_blocked_api_fallback",
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            }
        ]
    )
    monkeypatch.setenv("ETHERSCAN_API_KEY", "test-key")
    monkeypatch.setenv("CEX_ADDRESS_LABELS", "base:0x9999999999999999999999999999999999999999=Bitget Deposit")
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    title, description = bot._load_flow_health(min_tokens=1_000, symbol_limit=5)

    assert title == "CEX-flow health"
    assert "API fallback readiness:" in description
    assert "- arbitrum: key present (ETHERSCAN_V2_API_KEY or ETHERSCAN_API_KEY or ARBISCAN_API_KEY or ARBSCAN_API_KEY)" in description
    assert "- base: key present (ETHERSCAN_V2_API_KEY or ETHERSCAN_API_KEY or BASESCAN_API_KEY)" in description
    assert "CEX address labels loaded: 1" in description
    assert "Configure CEX_ADDRESS_LABELS or CEX_ADDRESS_BOOK_FILE" in description


def test_load_seth_flow_playbook_runs_whale_short_dormant_checklist(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "SETUPUSDT",
                "cex_deposit_flow_score": 88,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 2,
                "cex_deposit_24h_token_amount": 22_000_000,
                "cex_deposit_24h_max_amount": 12_000_000,
                "cex_deposit_24h_target_exchanges": "Bitget",
                "token_platform": "ethereum",
                "token_contract": "0x1111111111111111111111111111111111111111",
                "holder_source": "Etherscan holder endpoint",
                "holder_count": 6_000,
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 99.0,
                "low_float_score": 82.0,
                "fdv_to_market_cap": 8.0,
                "short_account_pct": 63.0,
                "range_24h_pct": 8.0,
                "day_return_pct": 2.0,
                "history_days": 180,
                "recent_max_pump_60d_pct": 6.0,
                "recent_pump_60d_days": 60,
                "no_large_pump_60d_flag": True,
                "dormant_short_fuse_score": 78.0,
                "pre_pump_precision_score": 72.0,
                "binance_volume_share_pct": 3.0,
                "bitget_volume_share_pct": 1.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "VOLUSDT",
                "cex_deposit_flow_score": 80,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 1,
                "cex_deposit_24h_token_amount": 15_000_000,
                "cex_deposit_24h_max_amount": 15_000_000,
                "cex_deposit_24h_target_exchanges": "Binance",
                "token_platform": "bsc",
                "token_contract": "0x2222222222222222222222222222222222222222",
                "holder_source": "BscScan holder endpoint",
                "holder_count": 7_000,
                "top10_holder_pct": 92.0,
                "top100_holder_pct": 97.0,
                "low_float_score": 80.0,
                "fdv_to_market_cap": 7.5,
                "short_account_pct": 61.0,
                "range_24h_pct": 55.0,
                "day_return_pct": 42.0,
                "history_days": 180,
                "recent_max_pump_60d_pct": 6.0,
                "recent_pump_60d_days": 60,
                "no_large_pump_60d_flag": True,
                "dormant_short_fuse_score": 85.0,
                "binance_volume_share_pct": 5.0,
                "bitget_volume_share_pct": 1.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "NOSHORTUSDT",
                "cex_deposit_flow_score": 70,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 1,
                "cex_deposit_24h_token_amount": 11_000_000,
                "cex_deposit_24h_max_amount": 11_000_000,
                "cex_deposit_24h_target_exchanges": "Gate",
                "token_platform": "arbitrum",
                "token_contract": "0x3333333333333333333333333333333333333333",
                "holder_source": "Arbiscan holder endpoint",
                "holder_count": 4_000,
                "top10_holder_pct": 93.0,
                "top100_holder_pct": 98.0,
                "short_account_pct": 49.0,
                "range_24h_pct": 6.0,
                "dormant_short_fuse_score": 80.0,
                "gate_volume_share_pct": 1.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "SMALLUSDT",
                "cex_deposit_flow_score": 90,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 1,
                "cex_deposit_24h_token_amount": 9_000_000,
                "cex_deposit_24h_max_amount": 9_000_000,
                "cex_deposit_24h_target_exchanges": "Bitget",
                "top10_holder_pct": 95.0,
                "top100_holder_pct": 99.0,
                "short_account_pct": 70.0,
                "dormant_short_fuse_score": 90.0,
                "bitget_volume_share_pct": 1.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "COINBASEUSDT",
                "cex_deposit_flow_score": 90,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 1,
                "cex_deposit_24h_token_amount": 20_000_000,
                "cex_deposit_24h_max_amount": 20_000_000,
                "cex_deposit_24h_target_exchanges": "Coinbase",
                "top10_holder_pct": 95.0,
                "top100_holder_pct": 99.0,
                "short_account_pct": 70.0,
                "dormant_short_fuse_score": 90.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    title, chunks = bot._load_seth_flow_playbook(10, min_tokens=10_000_000)
    output = "\n".join(chunks)

    assert title == "Seth flow checklist"
    assert "Confirmed target-CEX flow rows: 2 | Whale+float+short+dormant pass: 1" in output
    assert "Whale gate: top10 holder >= 90.0%" in output
    assert "Float gate: low-float/FDV evidence required" in output
    assert "Holder evidence required: True" in output
    assert "/SETUPUSDT | RESEARCH: dormant candidate" in output
    assert "2 tx into Bitget | total 22.00M, max 12.00M" in output
    assert "top10 91.0%, top100 99.0% | holderEv Y | float 82/100 | noPump60 Y | shorts 63.0%" in output
    assert "VOLUSDT" not in output
    assert "NOSHORTUSDT" not in output
    assert "SMALLUSDT" not in output
    assert "COINBASEUSDT" not in output
    assert "not a trade instruction" in output


def test_load_seth_flow_playbook_ignores_relaxed_dormant_toggle(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "VOLUSDT",
                "cex_deposit_flow_score": 80,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 1,
                "cex_deposit_24h_token_amount": 15_000_000,
                "cex_deposit_24h_max_amount": 15_000_000,
                "cex_deposit_24h_target_exchanges": "Binance",
                "token_platform": "ethereum",
                "token_contract": "0x4444444444444444444444444444444444444444",
                "holder_source": "Etherscan holder endpoint",
                "holder_count": 8_000,
                "top10_holder_pct": 92.0,
                "top100_holder_pct": 97.0,
                "low_float_score": 80.0,
                "fdv_to_market_cap": 7.5,
                "short_account_pct": 61.0,
                "range_24h_pct": 55.0,
                "day_return_pct": 42.0,
                "history_days": 180,
                "recent_max_pump_60d_pct": 6.0,
                "recent_pump_60d_days": 60,
                "no_large_pump_60d_flag": True,
                "dormant_short_fuse_score": 85.0,
                "binance_volume_share_pct": 5.0,
                "bitget_volume_share_pct": 1.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            }
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    _, chunks = bot._load_seth_flow_playbook(10, min_tokens=10_000_000, require_dormant=False)
    output = "\n".join(chunks)

    assert "Structure gate: dormant/early only" in output
    assert "/VOLUSDT | SKIP: already volatile/late" in output
    assert "structure volatile/late" in output
    assert "24h range 55.0%" in output


def test_load_seth_flow_playbook_requires_low_float_gate(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "NOFLOATUSDT",
                "cex_deposit_flow_score": 88,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 2,
                "cex_deposit_24h_token_amount": 22_000_000,
                "cex_deposit_24h_max_amount": 12_000_000,
                "cex_deposit_24h_target_exchanges": "Bitget",
                "token_platform": "ethereum",
                "token_contract": "0x1111111111111111111111111111111111111111",
                "holder_source": "Etherscan holder endpoint",
                "holder_count": 6_000,
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 99.0,
                "short_account_pct": 63.0,
                "range_24h_pct": 8.0,
                "day_return_pct": 2.0,
                "history_days": 180,
                "recent_max_pump_60d_pct": 6.0,
                "recent_pump_60d_days": 60,
                "no_large_pump_60d_flag": True,
                "dormant_short_fuse_score": 78.0,
                "pre_pump_precision_score": 72.0,
                "binance_volume_share_pct": 3.0,
                "bitget_volume_share_pct": 1.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            }
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    _, chunks = bot._load_seth_flow_playbook(10, min_tokens=10_000_000)
    output = "\n".join(chunks)

    assert "Whale+float+short+dormant pass: 0" in output
    assert "No rows passed every gate" in output
    assert "/NOFLOATUSDT | WAIT: low-float/FDV gate failed" in output
    assert "float 10/100" in output


def test_load_setup_score_list_ranks_full_goal_stack(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "PRIMEUSDT",
                "cex_deposit_flow_score": 92,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 3,
                "cex_deposit_24h_token_amount": 26_000_000,
                "cex_deposit_24h_max_amount": 12_000_000,
                "cex_deposit_24h_target_exchanges": "Bitget, GateIO",
                "token_platform": "ethereum",
                "token_contract": "0x5555555555555555555555555555555555555555",
                "holder_source": "Etherscan holder endpoint",
                "holder_count": 9_000,
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 99.0,
                "short_account_pct": 64.0,
                "low_float_score": 82.0,
                "float_trap_score": 78.0,
                "fdv_to_market_cap": 8.0,
                "locked_supply_pct": 70.0,
                "history_days": 180,
                "recent_max_pump_60d_pct": 6.0,
                "recent_pump_60d_days": 60,
                "no_large_pump_60d_flag": True,
                "dormant_short_fuse_score": 80.0,
                "pre_pump_precision_score": 75.0,
                "range_24h_pct": 8.0,
                "day_return_pct": 3.0,
                "oi_delta_pct": 4.2,
                "binance_volume_share_pct": 6.0,
                "bitget_volume_share_pct": 1.5,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "GATEONLYUSDT",
                "cex_deposit_flow_score": 94,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 3,
                "cex_deposit_24h_token_amount": 26_000_000,
                "cex_deposit_24h_max_amount": 12_000_000,
                "cex_deposit_24h_target_exchanges": "GateIO",
                "token_platform": "ethereum",
                "token_contract": "0x7777777777777777777777777777777777777777",
                "holder_source": "Etherscan holder endpoint",
                "holder_count": 9_000,
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 99.0,
                "short_account_pct": 64.0,
                "low_float_score": 82.0,
                "float_trap_score": 78.0,
                "fdv_to_market_cap": 8.0,
                "locked_supply_pct": 70.0,
                "history_days": 180,
                "recent_max_pump_60d_pct": 6.0,
                "recent_pump_60d_days": 60,
                "no_large_pump_60d_flag": True,
                "dormant_short_fuse_score": 80.0,
                "pre_pump_precision_score": 75.0,
                "range_24h_pct": 8.0,
                "day_return_pct": 3.0,
                "oi_delta_pct": 4.2,
                "gate_volume_share_pct": 2.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "KRAKENUSDT",
                "cex_deposit_flow_score": 95,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 2,
                "cex_deposit_24h_token_amount": 30_000_000,
                "cex_deposit_24h_max_amount": 15_000_000,
                "cex_deposit_24h_target_exchanges": "Kraken",
                "top10_holder_pct": 95.0,
                "top100_holder_pct": 99.0,
                "short_account_pct": 70.0,
                "low_float_score": 90.0,
                "dormant_short_fuse_score": 90.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    title, chunks = bot._load_setup_score_list(10, min_score=60, min_tokens=10_000_000, strict=True)
    output = "\n".join(chunks)

    assert title == "Insider-structure setup score"
    assert "Target CEX: Binance, Gate.io, Bitget" in output
    assert "Gates: top10 holder >= 90.0%, holder evidence required True" in output
    assert "Binance+Bitget required True" in output
    assert "Candidates: /PRIMEUSDT" in output
    assert "/PRIMEUSDT | PASS | score" in output
    assert "whale 91.0% | holderEv Y | venueBnBg Y" in output
    assert "flow 92 Bitget, GateIO 3tx max 12.00M" in output
    assert "shorts 64.0%" in output
    assert "GATEONLYUSDT" not in output
    assert "KRAKENUSDT" not in output


def test_goal_score_requires_explicit_binance_bitget_evidence(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_ASSUME_SYMBOLS_ARE_BINANCE_PERPS", "1")
    base = {
        "cex_deposit_flow_score": 92,
        "cex_deposit_flow_flag": True,
        "cex_deposit_24h_count": 1,
        "cex_deposit_24h_max_amount": 30_000,
        "cex_deposit_24h_target_exchanges": "Binance",
        **_holder_evidence(),
        "top10_holder_pct": 92.0,
        "short_account_pct": 64.0,
        "low_float_score": 82.0,
        "fdv_to_market_cap": 8.0,
        "dormant_short_fuse_score": 80.0,
        "pre_pump_precision_score": 75.0,
        "bitget_volume_share_pct": 1.5,
    }
    scored = bot._goal_score_frame(
        pd.DataFrame(
            [
                {**base, "symbol": "SYMBOLONLYUSDT"},
                {**base, "symbol": "MARKEDUSDT", "binance_perp_universe": True},
                {**base, "symbol": "SHAREUSDT", "binance_volume_share_pct": 0.5},
            ]
        ),
        min_transfer_tokens=20_000,
    ).set_index("symbol")

    assert not bool(scored.loc["SYMBOLONLYUSDT", "_goal_venue_pass"])
    assert not bool(scored.loc["SYMBOLONLYUSDT", "_goal_all_pass"])
    assert bool(scored.loc["MARKEDUSDT", "_goal_venue_pass"])
    assert bool(scored.loc["MARKEDUSDT", "_goal_all_pass"])
    assert bool(scored.loc["SHAREUSDT", "_goal_venue_pass"])
    assert bool(scored.loc["SHAREUSDT", "_goal_all_pass"])


def test_goal_score_hard_floors_top10_whale_gate() -> None:
    base = {
        "cex_deposit_flow_score": 92,
        "cex_deposit_flow_flag": True,
        "cex_deposit_24h_count": 1,
        "cex_deposit_24h_max_amount": 30_000,
        "cex_deposit_24h_target_exchanges": "Binance",
        **_holder_evidence(),
        "short_account_pct": 64.0,
        "low_float_score": 82.0,
        "fdv_to_market_cap": 8.0,
        "dormant_short_fuse_score": 80.0,
        "pre_pump_precision_score": 75.0,
        "binance_volume_share_pct": 2.0,
        "bitget_volume_share_pct": 1.5,
    }
    scored = bot._goal_score_frame(
        pd.DataFrame(
            [
                {**base, "symbol": "TOP100ONLYUSDT", "top10_holder_pct": 55.0, "top100_holder_pct": 99.0},
                {**base, "symbol": "TOP10USDT", "top10_holder_pct": 91.0, "top100_holder_pct": 94.0},
            ]
        ),
        min_transfer_tokens=20_000,
        min_whale_pct=50.0,
    ).set_index("symbol")

    assert float(scored.loc["TOP100ONLYUSDT", "_goal_min_whale_pct"]) == 90.0
    assert not bool(scored.loc["TOP100ONLYUSDT", "_goal_whale_concentration_pass"])
    assert not bool(scored.loc["TOP100ONLYUSDT", "_goal_whale_pass"])
    assert bool(scored.loc["TOP10USDT", "_goal_whale_concentration_pass"])


def test_goal_score_requires_60d_no_pump_proof() -> None:
    base = {
        "cex_deposit_flow_score": 92,
        "cex_deposit_flow_flag": True,
        "cex_deposit_24h_count": 1,
        "cex_deposit_24h_max_amount": 30_000,
        "cex_deposit_24h_target_exchanges": "Binance",
        **_holder_evidence(),
        "top10_holder_pct": 92.0,
        "short_account_pct": 64.0,
        "low_float_score": 82.0,
        "fdv_to_market_cap": 8.0,
        "dormant_short_fuse_score": 80.0,
        "pre_pump_precision_score": 75.0,
        "binance_volume_share_pct": 2.0,
        "bitget_volume_share_pct": 1.5,
    }
    scored = bot._goal_score_frame(
        pd.DataFrame(
            [
                {**base, "symbol": "CLEANUSDT"},
                {
                    **base,
                    "symbol": "PUMPEDUSDT",
                    "recent_max_pump_60d_pct": 82.0,
                    "recent_pump_60d_days": 60,
                    "no_large_pump_60d_flag": False,
                },
                {
                    **base,
                    "symbol": "MISSINGUSDT",
                    "history_days": pd.NA,
                    "recent_max_pump_60d_pct": pd.NA,
                    "recent_pump_60d_days": pd.NA,
                    "no_large_pump_60d_flag": pd.NA,
                },
            ]
        ),
        min_transfer_tokens=20_000,
    ).set_index("symbol")

    assert bool(scored.loc["CLEANUSDT", "_goal_no_recent_pump_pass"])
    assert bool(scored.loc["CLEANUSDT", "_goal_all_pass"])
    assert not bool(scored.loc["PUMPEDUSDT", "_goal_no_recent_pump_pass"])
    assert not bool(scored.loc["PUMPEDUSDT", "_goal_all_pass"])
    assert not bool(scored.loc["MISSINGUSDT", "_goal_no_recent_pump_pass"])
    assert not bool(scored.loc["MISSINGUSDT", "_goal_all_pass"])


def test_goal_score_ignores_relaxed_holder_and_venue_flags() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "BYPASSUSDT",
                "cex_deposit_flow_score": 92,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 1,
                "cex_deposit_24h_max_amount": 30_000,
                "cex_deposit_24h_target_exchanges": "Binance",
                "token_platform": "ethereum",
                "token_contract": "0x1111111111111111111111111111111111111111",
                "top10_holder_pct": 92.0,
                "top100_holder_pct": 99.0,
                "short_account_pct": 64.0,
                "low_float_score": 82.0,
                "fdv_to_market_cap": 8.0,
                "dormant_short_fuse_score": 80.0,
                "pre_pump_precision_score": 75.0,
            }
        ]
    )

    scored = bot._goal_score_frame(
        frame,
        min_transfer_tokens=20_000,
        require_holder_evidence=False,
        require_binance_bitget=False,
    ).iloc[0]

    assert bool(scored["_goal_holder_evidence_required"])
    assert bool(scored["_goal_venue_required"])
    assert not bool(scored["_goal_holder_evidence_pass"])
    assert not bool(scored["_goal_whale_pass"])
    assert not bool(scored["_goal_venue_pass"])
    assert not bool(scored["_goal_all_pass"])


def test_pumpwatch_holder_gate_requires_top10_even_when_min_whale_lowered(monkeypatch) -> None:
    base = {
        **_holder_evidence(),
        "cex_deposit_flow_score": 70,
        "cex_deposit_flow_flag": True,
        "cex_deposit_24h_count": 1,
        "cex_deposit_24h_token_amount": 40_000,
        "cex_deposit_24h_max_amount": 40_000,
        "cex_deposit_24h_target_exchanges": "Binance",
        "centralized_ownership_score": 86.0,
        "low_float_score": 82.0,
        "float_trap_score": 78.0,
        "fdv_to_market_cap": 8.0,
        "short_account_pct": 64.0,
        "short_dominance_score": 80.0,
        "short_account_build_score": 74.0,
        "dormant_short_fuse_score": 82.0,
        "pre_pump_precision_score": 76.0,
        "binance_volume_share_pct": 6.0,
        "bitget_volume_share_pct": 2.4,
        "scan_mode": "Deep",
        "scanned_at_utc": "now",
    }
    fresh = pd.DataFrame(
        [
            {**base, "symbol": "TOP100ONLYUSDT", "top10_holder_pct": 55.0, "top100_holder_pct": 99.0},
            {**base, "symbol": "TOP10USDT", "top10_holder_pct": 91.0, "top100_holder_pct": 94.0},
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    title, chunks = bot._load_pump_watch_list(
        10,
        min_score=0,
        min_tokens=20_000,
        min_whale_pct=50.0,
        require_venue_gate=False,
    )
    output = "\n".join(chunks)

    assert title == "Early pump watch"
    assert "Holder gate: top10 >= 90.0%" in output
    assert "Gate rows: strict holder 1 | Binance+Bitget 1" in output
    assert "/TOP10USDT" in output
    assert "/TOP100ONLYUSDT" not in output


def test_load_pump_watch_list_collapses_goal_stack_and_keeps_binance_targets(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "PRIMEUSDT",
                "cex_deposit_flow_score": 94,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 3,
                "cex_deposit_24h_token_amount": 26_000_000,
                "cex_deposit_24h_max_amount": 12_000_000,
                "cex_deposit_24h_target_exchanges": "Binance",
                "cex_deposit_inventory_stress_score": 86,
                "token_platform": "ethereum",
                "token_contract": "0x1111111111111111111111111111111111111111",
                "holder_source": "Etherscan holder endpoint",
                "holder_count": 6_000,
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 99.0,
                "centralized_ownership_score": 86.0,
                "low_float_score": 82.0,
                "float_trap_score": 78.0,
                "fdv_to_market_cap": 8.0,
                "history_days": 180,
                "recent_max_pump_60d_pct": 6.0,
                "recent_pump_60d_days": 60,
                "no_large_pump_60d_flag": True,
                "short_account_pct": 64.0,
                "short_dominance_score": 80.0,
                "short_account_build_score": 74.0,
                "dormant_short_fuse_score": 82.0,
                "pre_pump_precision_score": 76.0,
                "oi_delta_pct": 3.2,
                "hour_return_pct": 1.6,
                "day_return_pct": 6.0,
                "hour_volume_multiple": 1.8,
                "hour_trade_count_multiple": 1.5,
                "hour_close_location_pct": 72.0,
                "binance_volume_share_pct": 6.0,
                "bitget_volume_share_pct": 2.4,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "WEAKUSDT",
                "cex_deposit_flow_score": 92,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 2,
                "cex_deposit_24h_max_amount": 12_000_000,
                "cex_deposit_24h_target_exchanges": "Kraken",
                "top100_holder_pct": 99.0,
                "short_account_pct": 68.0,
                "low_float_score": 90.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    title, chunks = bot._load_pump_watch_list(10, min_score=55, min_tokens=10_000_000, require_target_flow=True)
    output = "\n".join(chunks)

    assert title == "Early pump watch"
    assert "Target CEX: Binance, Gate.io, Bitget" in output
    assert "Holder gate: top10 >= 90.0%" in output
    assert "Holder evidence required: True" in output
    assert "Binance+Bitget required: True" in output
    assert "Gate rows: strict holder 1 | Binance+Bitget 1" in output
    assert "Candidates: /PRIMEUSDT" in output
    assert "/PRIMEUSDT | Prime early squeeze" in output
    assert "flow 94 Binance 3tx max 12.00M" in output
    assert "WEAKUSDT" not in output


def test_pumpwatch_target_flow_respects_min_transfer_floor(monkeypatch) -> None:
    base = {
        **_holder_evidence(),
        "cex_deposit_flow_score": 92,
        "cex_deposit_flow_flag": True,
        "cex_deposit_24h_count": 1,
        "cex_deposit_24h_target_exchanges": "Binance",
        "cex_deposit_inventory_stress_score": 84,
        "top10_holder_pct": 92.0,
        "centralized_ownership_score": 86.0,
        "low_float_score": 82.0,
        "float_trap_score": 78.0,
        "fdv_to_market_cap": 8.0,
        "short_account_pct": 64.0,
        "short_dominance_score": 80.0,
        "short_account_build_score": 74.0,
        "dormant_short_fuse_score": 82.0,
        "pre_pump_precision_score": 76.0,
        "bitget_volume_share_pct": 2.4,
        "binance_volume_share_pct": 12.0,
        "scan_mode": "Deep",
        "scanned_at_utc": "now",
    }
    fresh = pd.DataFrame(
        [
            {**base, "symbol": "BIGFLOWUSDT", "cex_deposit_24h_max_amount": 30_000},
            {**base, "symbol": "LOWFLOWUSDT", "cex_deposit_24h_max_amount": 10_000},
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    title, chunks = bot._load_pump_watch_list(10, min_score=0, min_tokens=20_000, require_target_flow=True)
    output = "\n".join(chunks)

    assert title == "Early pump watch"
    assert "Transfer floor: 20.00K tokens" in output
    assert "Confirmed target-flow rows: 1" in output
    assert "/BIGFLOWUSDT" in output
    assert "/LOWFLOWUSDT" not in output


def test_load_precrime_list_prioritizes_quiet_latent_target_flow(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "SLEEPUSDT",
                "cex_deposit_flow_score": 92,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 2,
                "cex_deposit_24h_token_amount": 420_000,
                "cex_deposit_24h_max_amount": 240_000,
                "cex_deposit_24h_target_exchanges": "Binance, Gate.io",
                "cex_deposit_inventory_stress_score": 95,
                "inventory_transfer_risk_score": 92,
                "terminal_distribution_pressure_score": 95,
                "terminal_control_plane_score": 88,
                "venue_support_score": 70,
                "token_platform": "bsc",
                "token_contract": "0x2222222222222222222222222222222222222222",
                "holder_source": "BscScan holder endpoint",
                "top10_holder_pct": 90.0,
                "top100_holder_pct": 99.0,
                "holder_count": 7_500,
                "centralized_ownership_score": 88.0,
                "low_float_score": 86.0,
                "float_trap_score": 82.0,
                "fdv_to_market_cap": 11.0,
                "locked_supply_pct": 70.0,
                "history_days": 180,
                "recent_max_pump_60d_pct": 6.0,
                "recent_pump_60d_days": 60,
                "no_large_pump_60d_flag": True,
                "short_account_pct": 48.0,
                "short_dominance_score": 30.0,
                "short_account_build_score": 25.0,
                "short_account_change_max_pp": 0.1,
                "oi_to_24h_volume_pct": 3.0,
                "ask_depth_1pct_usdt": 45_000,
                "ask_depth_to_24h_volume_pct": 0.03,
                "binance_bitget_gate_share_pct": 35.0,
                "binance_volume_share_pct": 6.0,
                "bitget_volume_share_pct": 1.8,
                "pre_pump_precision_score": 35.0,
                "low_volatility_coil_score": 82.0,
                "hour_return_pct": 0.2,
                "day_return_pct": 0.8,
                "price_change_24h_pct": 0.8,
                "range_24h_pct": 3.0,
                "hour_volume_multiple": 1.0,
                "hour_trade_count_multiple": 1.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "HOTUSDT",
                "cex_deposit_flow_score": 96,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 2,
                "cex_deposit_24h_max_amount": 240_000,
                "cex_deposit_24h_target_exchanges": "Binance",
                "top10_holder_pct": 92.0,
                "top100_holder_pct": 99.0,
                "low_float_score": 90.0,
                "history_days": 180,
                "recent_max_pump_60d_pct": 6.0,
                "recent_pump_60d_days": 60,
                "no_large_pump_60d_flag": True,
                "short_account_pct": 66.0,
                "ask_depth_1pct_usdt": 40_000,
                "ask_depth_to_24h_volume_pct": 0.03,
                "hour_return_pct": 16.0,
                "day_return_pct": 80.0,
                "price_change_24h_pct": 80.0,
                "range_24h_pct": 60.0,
                "hour_volume_multiple": 12.0,
                "hour_trade_count_multiple": 10.0,
                "broke_high_20d": True,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    title, chunks = bot._load_precrime_list(10, min_score=58, min_tokens=20_000)
    output = "\n".join(chunks)

    assert title == "Pre-activity radar"
    assert "Quiet required: True" in output
    assert "Holder gate: top10 >= 90.0%" in output
    assert "Holder evidence required: True" in output
    assert "Binance+Bitget required: True" in output
    assert "Gate rows: strict holder 1 | Binance+Bitget 1" in output
    assert "Candidates: /SLEEPUSDT" in output
    assert "/SLEEPUSDT | Stealth inventory setup" in output
    assert "CEX-tell" in output
    assert "Binance, Gate.io 2tx max 240.00K" in output
    assert "anchor LABUSDT 2026-05-11" in output
    assert "/HOTUSDT" not in output


def test_precrime_target_flow_respects_min_transfer_floor(monkeypatch) -> None:
    base = {
        **_holder_evidence(chain="bsc", contract="0x2222222222222222222222222222222222222222"),
        "cex_deposit_flow_score": 92,
        "cex_deposit_flow_flag": True,
        "cex_deposit_24h_count": 1,
        "cex_deposit_24h_target_exchanges": "Binance",
        "cex_deposit_inventory_stress_score": 84,
        "inventory_transfer_risk_score": 74,
        "top10_holder_pct": 92.0,
        "centralized_ownership_score": 88.0,
        "low_float_score": 86.0,
        "float_trap_score": 82.0,
        "fdv_to_market_cap": 11.0,
        "locked_supply_pct": 70.0,
        "short_account_pct": 62.0,
        "short_account_change_max_pp": 1.8,
        "oi_to_24h_volume_pct": 9.0,
        "ask_depth_1pct_usdt": 42_000,
        "ask_depth_to_24h_volume_pct": 0.03,
        "binance_bitget_gate_share_pct": 35.0,
        "bitget_volume_share_pct": 1.8,
        "binance_volume_share_pct": 12.0,
        "day_return_pct": 0.9,
        "price_change_24h_pct": 0.9,
        "hour_return_pct": 0.2,
        "range_24h_pct": 3.2,
        "scan_mode": "Deep",
        "scanned_at_utc": "now",
    }
    fresh = pd.DataFrame(
        [
            {**base, "symbol": "BIGFLOWUSDT", "cex_deposit_24h_max_amount": 30_000},
            {**base, "symbol": "LOWFLOWUSDT", "cex_deposit_24h_max_amount": 10_000},
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    title, chunks = bot._load_precrime_list(
        10,
        min_score=0,
        min_tokens=20_000,
        require_target_flow=True,
        require_quiet=False,
        require_behavior_gate=False,
    )
    output = "\n".join(chunks)

    assert title == "Pre-activity radar"
    assert "Transfer floor: 20.00K tokens" in output
    assert "Target-flow rows: 1" in output
    assert "/BIGFLOWUSDT" in output
    assert "/LOWFLOWUSDT" not in output


def test_load_ravelab_list_finds_early_historical_analogues(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "CAPUSDT",
                "history_days": 180,
                "token_platform": "ethereum",
                "token_contract": "0x1111111111111111111111111111111111111111",
                "holder_source": "Etherscan holder endpoint",
                "top10_holder_pct": 94.0,
                "top100_holder_pct": 99.8,
                "holder_count": 6_000,
                "terminal_hidden_float_reflexivity_score": 92,
                "terminal_control_plane_score": 90,
                "centralized_ownership_score": 88,
                "low_float_score": 88,
                "float_trap_score": 84,
                "fdv_to_market_cap": 12.0,
                "locked_supply_pct": 74.0,
                "ath_multiple": 35.0,
                "terminal_distribution_pressure_score": 62,
                "short_account_pct": 54.0,
                "short_dominance_score": 62.0,
                "short_account_build_score": 52.0,
                "short_liquidation_fuel_score": 48.0,
                "binance_volume_share_pct": 8.0,
                "bitget_volume_share_pct": 2.0,
                "ask_depth_1pct_usdt": 35_000,
                "ask_depth_to_24h_volume_pct": 0.04,
                "low_volatility_coil_score": 84.0,
                "hour_return_pct": 0.1,
                "day_return_pct": 0.6,
                "price_change_24h_pct": 0.6,
                "range_24h_pct": 2.5,
                "hour_volume_multiple": 0.9,
                "hour_trade_count_multiple": 0.95,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "LABXUSDT",
                "history_days": 160,
                "token_platform": "arbitrum",
                "token_contract": "0x2222222222222222222222222222222222222222",
                "holder_source": "Arbiscan holder endpoint",
                "cex_deposit_flow_score": 94,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 2,
                "cex_deposit_24h_token_amount": 620_000,
                "cex_deposit_24h_max_amount": 360_000,
                "cex_deposit_24h_whale_sender_count": 1,
                "cex_deposit_24h_whale_sender_token_amount": 360_000,
                "cex_deposit_24h_top_sender_address": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "cex_deposit_24h_top_sender_rank": 1,
                "cex_deposit_24h_top_sender_pct": 91.0,
                "cex_deposit_24h_target_exchanges": "Binance, Gate.io",
                "cex_deposit_inventory_stress_score": 96,
                "inventory_transfer_risk_score": 94,
                "terminal_distribution_pressure_score": 92,
                "terminal_control_plane_score": 86,
                "venue_support_score": 74,
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 99.2,
                "holder_count": 8_000,
                "centralized_ownership_score": 88.0,
                "low_float_score": 84.0,
                "float_trap_score": 80.0,
                "fdv_to_market_cap": 9.0,
                "locked_supply_pct": 65.0,
                "short_account_pct": 51.0,
                "short_dominance_score": 58.0,
                "short_account_build_score": 25.0,
                "silent_oi_accumulation_score": 56.0,
                "ask_depth_1pct_usdt": 50_000,
                "ask_depth_to_24h_volume_pct": 0.05,
                "binance_volume_share_pct": 9.0,
                "bitget_volume_share_pct": 2.0,
                "binance_bitget_gate_share_pct": 36.0,
                "pre_pump_precision_score": 38.0,
                "low_volatility_coil_score": 80.0,
                "hour_return_pct": 0.3,
                "day_return_pct": 1.0,
                "price_change_24h_pct": 1.0,
                "range_24h_pct": 3.5,
                "hour_volume_multiple": 1.0,
                "hour_trade_count_multiple": 1.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "HOTRAVEUSDT",
                "history_days": 180,
                "top10_holder_pct": 95.0,
                "top100_holder_pct": 99.9,
                "terminal_hidden_float_reflexivity_score": 96,
                "terminal_control_plane_score": 95,
                "low_float_score": 90,
                "ath_multiple": 60,
                "fdv_to_market_cap": 15,
                "day_return_pct": 120.0,
                "price_change_24h_pct": 120.0,
                "range_24h_pct": 85.0,
                "hour_volume_multiple": 15.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "NOBITGETUSDT",
                "history_days": 180,
                "top10_holder_pct": 96.0,
                "top100_holder_pct": 99.9,
                "terminal_hidden_float_reflexivity_score": 96,
                "terminal_control_plane_score": 95,
                "centralized_ownership_score": 94,
                "low_float_score": 90,
                "ath_multiple": 60,
                "fdv_to_market_cap": 15,
                "short_account_pct": 66.0,
                "short_dominance_score": 85.0,
                "short_account_build_score": 58.0,
                "binance_volume_share_pct": 12.0,
                "day_return_pct": 0.4,
                "price_change_24h_pct": 0.4,
                "range_24h_pct": 2.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "YOUNGUSDT",
                "history_days": 21,
                "top10_holder_pct": 96.0,
                "top100_holder_pct": 99.9,
                "terminal_hidden_float_reflexivity_score": 96,
                "terminal_control_plane_score": 95,
                "centralized_ownership_score": 94,
                "low_float_score": 90,
                "ath_multiple": 60,
                "fdv_to_market_cap": 15,
                "short_account_pct": 66.0,
                "short_dominance_score": 85.0,
                "short_account_build_score": 58.0,
                "binance_volume_share_pct": 12.0,
                "bitget_volume_share_pct": 2.0,
                "day_return_pct": 0.4,
                "price_change_24h_pct": 0.4,
                "range_24h_pct": 2.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "PCTONLYUSDT",
                "history_days": 180,
                "top10_holder_pct": 96.0,
                "top100_holder_pct": 99.9,
                "terminal_hidden_float_reflexivity_score": 96,
                "terminal_control_plane_score": 95,
                "centralized_ownership_score": 94,
                "low_float_score": 90,
                "ath_multiple": 60,
                "fdv_to_market_cap": 15,
                "short_account_pct": 66.0,
                "short_dominance_score": 85.0,
                "short_account_build_score": 58.0,
                "binance_volume_share_pct": 12.0,
                "bitget_volume_share_pct": 2.0,
                "day_return_pct": 0.4,
                "price_change_24h_pct": 0.4,
                "range_24h_pct": 2.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "COUNTONLYUSDT",
                "history_days": 180,
                "top10_holder_pct": 96.0,
                "top100_holder_pct": 99.9,
                "holder_count": 5_000,
                "terminal_hidden_float_reflexivity_score": 96,
                "terminal_control_plane_score": 95,
                "centralized_ownership_score": 94,
                "low_float_score": 90,
                "ath_multiple": 60,
                "fdv_to_market_cap": 15,
                "short_account_pct": 66.0,
                "short_dominance_score": 85.0,
                "short_account_build_score": 58.0,
                "binance_volume_share_pct": 12.0,
                "bitget_volume_share_pct": 2.0,
                "day_return_pct": 0.4,
                "price_change_24h_pct": 0.4,
                "range_24h_pct": 2.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "TARGETONLYUSDT",
                "history_days": 180,
                "token_platform": "bsc",
                "token_contract": "0x3333333333333333333333333333333333333333",
                "holder_source": "BscScan holder endpoint",
                "top10_holder_pct": 96.0,
                "top100_holder_pct": 99.9,
                "terminal_hidden_float_reflexivity_score": 96,
                "terminal_control_plane_score": 95,
                "centralized_ownership_score": 94,
                "low_float_score": 90,
                "ath_multiple": 60,
                "fdv_to_market_cap": 15,
                "short_account_pct": 66.0,
                "short_dominance_score": 85.0,
                "short_account_build_score": 58.0,
                "binance_volume_share_pct": 12.0,
                "cex_deposit_flow_score": 90,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 1,
                "cex_deposit_24h_max_amount": 1_000_000,
                "cex_deposit_24h_target_exchanges": "Bitget",
                "day_return_pct": 0.4,
                "price_change_24h_pct": 0.4,
                "range_24h_pct": 2.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "RECENTPUMPUSDT",
                "history_days": 180,
                "token_platform": "ethereum",
                "token_contract": "0x4444444444444444444444444444444444444444",
                "holder_source": "Etherscan holder endpoint",
                "top10_holder_pct": 96.0,
                "top100_holder_pct": 99.9,
                "holder_count": 9_000,
                "terminal_hidden_float_reflexivity_score": 96,
                "terminal_control_plane_score": 95,
                "centralized_ownership_score": 94,
                "low_float_score": 90,
                "ath_multiple": 60,
                "fdv_to_market_cap": 15,
                "short_account_pct": 66.0,
                "short_dominance_score": 85.0,
                "short_account_build_score": 58.0,
                "binance_volume_share_pct": 12.0,
                "bitget_volume_share_pct": 2.0,
                "recent_max_pump_60d_pct": 82.0,
                "recent_pump_60d_days": 60,
                "no_large_pump_60d_flag": False,
                "day_return_pct": 0.4,
                "price_change_24h_pct": 0.4,
                "range_24h_pct": 2.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "MISSINGPUMPUSDT",
                "history_days": 180,
                "token_platform": "ethereum",
                "token_contract": "0x5555555555555555555555555555555555555555",
                "holder_source": "Etherscan holder endpoint",
                "top10_holder_pct": 96.0,
                "top100_holder_pct": 99.9,
                "holder_count": 9_000,
                "terminal_hidden_float_reflexivity_score": 96,
                "terminal_control_plane_score": 95,
                "centralized_ownership_score": 94,
                "low_float_score": 90,
                "ath_multiple": 60,
                "fdv_to_market_cap": 15,
                "short_account_pct": 66.0,
                "short_dominance_score": 85.0,
                "short_account_build_score": 58.0,
                "binance_volume_share_pct": 12.0,
                "bitget_volume_share_pct": 2.0,
                "day_return_pct": 0.4,
                "price_change_24h_pct": 0.4,
                "range_24h_pct": 2.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "SHORTONLYUSDT",
                "history_days": 180,
                "token_platform": "ethereum",
                "token_contract": "0x7777777777777777777777777777777777777777",
                "holder_source": "Etherscan holder endpoint",
                "top10_holder_pct": 96.0,
                "top100_holder_pct": 99.9,
                "holder_count": 9_000,
                "terminal_hidden_float_reflexivity_score": 96,
                "terminal_control_plane_score": 95,
                "centralized_ownership_score": 94,
                "low_float_score": 90,
                "ath_multiple": 60,
                "fdv_to_market_cap": 15,
                "short_account_pct": 72.0,
                "binance_volume_share_pct": 12.0,
                "bitget_volume_share_pct": 2.0,
                "day_return_pct": 0.4,
                "price_change_24h_pct": 0.4,
                "range_24h_pct": 2.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    class FakeBinance:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def klines_1d(self, symbol: str, limit: int = 200, **kwargs):
            if symbol == "CAPUSDT":
                closed = [[0, 100, 100 + (idx % 6), 98, 100] for idx in range(max(limit - 1, 1))]
                return [*closed, [0, 100, 110, 98, 108]]
            if symbol == "LABXUSDT":
                closed = [[0, 100, 102, 98, 100] for _ in range(max(limit - 1, 1))]
                return [*closed, [0, 50, 50, 49, 50]]
            if symbol in {"PCTONLYUSDT", "COUNTONLYUSDT", "TARGETONLYUSDT", "YOUNGUSDT"}:
                closed = [[0, 100, 102, 98, 100] for _ in range(max(limit - 1, 1))]
                return [*closed, [0, 100, 101, 99, 100]]
            return []

    monkeypatch.setattr(bot, "BinanceFuturesPublic", FakeBinance)

    title, chunks = bot._load_ravelab_list(10, min_score=58, min_archetype=0, min_tokens=20_000)
    output = "\n".join(chunks)

    assert title == "RAVE/LAB early radar"
    assert "Anchors: RAVEUSDT 2026-04-18" in output
    assert "Whale gate: top10 >= 90.0%" in output
    assert "History gate: >= 60d" in output
    assert "Max recent pump: < 35% over 60d" in output
    assert "Holder evidence required: True" in output
    assert "Whale-origin CEX required: False" in output
    assert "No-pump proof: requires 60D closed daily-candle pump history" in output
    assert "Core gates: top10 whale-control threshold with chain+contract holder-source snapshot evidence" in output
    assert "High breakout windows: 1D,2D,3D,4D,5D,20D" in output
    assert "Near misses: 5" in output
    assert "Trigger filter: all" in output
    assert "Gate funnel:" in output
    assert "-> float " in output
    assert output.index("-> float ") < output.index("-> squeeze")
    assert "holderSrc" in output
    assert "shown 2" in output
    assert "Trigger lanes: triggered 2 | whale-CEX 1 | target-CEX 1 | breakout 1 | core-watch 0 | shown 2" in output
    assert "Core 6/6: 2" in output
    assert "Whale-origin CEX rows: 1" in output
    assert "Near misses shown: 2" in output
    assert "Holder evidence rows:" in output
    assert "Breakout high checks:" in output
    assert "Daily pump checks:" in output
    assert "All shown rows passed top10 whale-control >= 90.0%, holder-source snapshot evidence, Binance+Bitget, float/FDV trap, no recent pump >= 35%, history >= 60d and dormant2m, squeeze stack >= 50." in output
    assert "Candidates:" in output
    assert "Trigger queue:" in output
    assert "/LABXUSDT A3 (whale-CEX 360.00K)" in output
    assert "/CAPUSDT A2 (breakout 1D,2D,3D,4D,5D,20D)" in output
    assert output.index("Trigger queue:") < output.index("Holder evidence rows:")
    assert "/CAPUSDT" in output
    assert "highs 1D,2D,3D,4D,5D,20D" in output
    assert "holder chain ethereum, holders 6000, top10 94.0% / top100 99.8%, src Etherscan holder endpoint, contract 0x1111...1111" in output
    assert "venue Bn 8.0%; Bg 2.0%; Gate no" in output
    assert "/LABXUSDT" in output
    assert "holder chain arbitrum, holders 8000, top10 91.0% / top100 99.2%, src Arbiscan holder endpoint, contract 0x2222...2222" in output
    assert "venue Bn 9.0%,target; Bg 2.0%; Gate target" in output
    assert "/LABXUSDT | LAB-like" in output
    assert "A3 WHALE-CEX PRIME" in output
    assert "core 6/6 | trigger whale-CEX 360.00K | thesis" in output
    assert "trigger breakout 1D,2D,3D,4D,5D,20D" in output
    assert "blockers none" in output
    assert "whale-CEX 1 top-holder sender tx | whale-origin 360.00K | r1 91.0% 0xaaaa...aaaa" in output
    assert "proof: whale 91.0% holderEv Y | venues Bn Y/Bg Y/Gate Y | float" in output
    assert "FDV/MC 9.0x | noPump Y pump60 2.0%/60d binance60d" in output
    assert "anchor LABUSDT 2026-05-11" in output
    assert "/CAPUSDT | RAVE-like" in output
    assert "anchor RAVEUSDT 2026-04-18" in output
    assert "Near misses (blocked, not eligible yet; failed gates are shown as blockers):" in output
    assert "/RECENTPUMPUSDT | RAVE-like | B1 BLOCKED" in output
    assert "blockers 2mo no-pump" in output
    assert "pump60 82.0%/60d scan60d" in output
    assert "/MISSINGPUMPUSDT | RAVE-like | B1 BLOCKED" in output
    assert "insufficient 0d" in output
    assert "/HOTRAVEUSDT" not in output
    assert "/NOBITGETUSDT" not in output
    assert "/YOUNGUSDT" not in output
    assert "/PCTONLYUSDT" not in output
    assert "/COUNTONLYUSDT" not in output
    assert "/TARGETONLYUSDT" not in output
    assert "/SHORTONLYUSDT" not in output

    _, rave_chunks = bot._load_ravelab_list(10, min_score=58, min_archetype=0, min_tokens=20_000, style="rave")
    rave_output = "\n".join(rave_chunks)
    assert "/CAPUSDT | RAVE-like" in rave_output
    assert "/LABXUSDT" not in rave_output

    _, breakout_chunks = bot._load_ravelab_list(
        10,
        min_score=58,
        min_archetype=0,
        min_tokens=20_000,
        require_breakout_high=True,
        near_miss_limit=0,
    )
    breakout_output = "\n".join(breakout_chunks)
    assert "/CAPUSDT | RAVE-like" in breakout_output
    assert "/LABXUSDT" not in breakout_output

    _, whale_flow_chunks = bot._load_ravelab_list(
        10,
        min_score=58,
        min_archetype=0,
        min_tokens=20_000,
        require_whale_origin_flow=True,
        near_miss_limit=0,
    )
    whale_flow_output = "\n".join(whale_flow_chunks)
    assert "Whale-origin CEX required: True" in whale_flow_output
    assert "/LABXUSDT | LAB-like" in whale_flow_output
    assert "/CAPUSDT" not in whale_flow_output

    _, trigger_flow_chunks = bot._load_ravelab_list(
        10,
        min_score=58,
        min_archetype=0,
        min_tokens=20_000,
        trigger_filter="flow",
        near_miss_limit=0,
    )
    trigger_flow_output = "\n".join(trigger_flow_chunks)
    assert "Trigger filter: flow" in trigger_flow_output
    assert "trigger:flow 1" in trigger_flow_output
    assert "Trigger lanes before filter: triggered 2 | whale-CEX 1 | target-CEX 1 | breakout 1 | core-watch 0 | shown 1" in trigger_flow_output
    assert "/LABXUSDT | LAB-like" in trigger_flow_output
    assert "/CAPUSDT" not in trigger_flow_output

    _, diagnostic_chunks = bot._load_ravelab_list(
        10,
        min_score=58,
        min_archetype=0,
        min_tokens=20_000,
        require_holder_evidence=False,
        require_binance_bitget=False,
        require_dormant_2m=False,
    )
    diagnostic_output = "\n".join(diagnostic_chunks)
    assert "Holder evidence required: True" in diagnostic_output
    assert "Binance+Bitget required: True | Dormant 2m required: True" in diagnostic_output
    assert "/PCTONLYUSDT" not in diagnostic_output
    assert "/COUNTONLYUSDT" not in diagnostic_output

    crime_title, crime_chunks = bot._load_crimepump_list(10, min_tokens=20_000)
    crime_output = "\n".join(crime_chunks)
    assert crime_title == "Crime-pump early queue"
    assert "Crime-pump early queue" in crime_output
    assert "Hard gates: top10 whale-control threshold with ETH/BNB/ARB chain+contract holder-source snapshot evidence; Binance+Bitget; float/FDV trap; 60D no-pump/dormant; squeeze stack; early/no-chase." in crime_output
    assert "Trigger: all" in crime_output
    assert "Gate funnel:" in crime_output
    assert "Trigger lanes: triggered 2" in crime_output
    assert "Matches: 2 | Core 6/6: 2 | Triggered: 2 | Whale-origin CEX: 1 | Target-flow: 1 | Breakout highs: 1" in crime_output
    assert "Trigger queue:" in crime_output
    assert "/CAPUSDT | A2 BREAKOUT | RAVE-like" in crime_output
    assert "venues Bn/Bg/Gate Y/Y/N | float" in crime_output
    assert "FDV/MC 12.0x | hist 180d pump60" in crime_output
    assert "/LABXUSDT | A3 WHALE-CEX | LAB-like" in crime_output
    assert "CEX Binance, Gate.io max 360.00K | 1 top-holder sender tx | whale-origin 360.00K" in crime_output
    assert "Strict RAVE/LAB crime-pump early radar" not in crime_output
    assert "Near misses (blocked" not in crime_output

    radar_title, radar_chunks = bot._load_radar_list(10, min_tokens=20_000)
    radar_output = "\n".join(radar_chunks)
    assert radar_title == "Early structure radar"
    assert "Early structure radar" in radar_output
    assert "Crime-pump early queue" not in radar_output
    assert "Matches: 2 | Core 6/6: 2 | Triggered: 2 | Whale-origin CEX: 1 | Target-flow: 1 | Breakout highs: 1" in radar_output
    assert "/CAPUSDT | A2 BREAKOUT | RAVE-like" in radar_output
    assert "/LABXUSDT | A3 WHALE-CEX | LAB-like" in radar_output

    prime_title, prime_chunks = bot._load_prime_list(10, min_tokens=20_000)
    prime_output = "\n".join(prime_chunks)
    assert prime_title == "Prime crime-pump queue"
    assert "Prime crime-pump queue" in prime_output
    assert "Crime-pump early queue" not in prime_output
    assert "Strict RAVE/LAB crime-pump early radar" not in prime_output

    _, prime_flow_chunks = bot._load_prime_list(10, min_tokens=20_000, trigger="flow")
    prime_flow_output = "\n".join(prime_flow_chunks)
    assert "Trigger: flow" in prime_flow_output
    assert "/LABXUSDT | A3 WHALE-CEX | LAB-like" in prime_flow_output
    assert "/CAPUSDT" not in prime_flow_output


def test_ravelab_squeeze_gate_requires_fuel_not_short_pct_alone() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "STACKUSDT",
                "short_account_pct": 54.0,
                "short_dominance_score": 62.0,
                "short_account_build_score": 52.0,
            },
            {
                "symbol": "SHORTONLYUSDT",
                "short_account_pct": 72.0,
            },
        ]
    )

    scored = bot._score_ravelab_early_frame(frame)
    scored = bot._ravelab_apply_thesis_columns(scored, min_squeeze_score=50.0).set_index("symbol")

    assert bool(scored.loc["STACKUSDT", "_ravelab_squeeze_gate"])
    assert not bool(scored.loc["SHORTONLYUSDT", "_ravelab_squeeze_gate"])
    assert float(scored.loc["SHORTONLYUSDT", "_ravelab_squeeze_score"]) >= 50.0
    assert float(scored.loc["SHORTONLYUSDT", "_ravelab_squeeze_fuel_score"]) < 40.0


def test_ravelab_core_gate_requires_float_fdv_evidence() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "NOFLOATUSDT",
                "history_days": 180,
                **_holder_evidence("ethereum", "0x1111111111111111111111111111111111111111"),
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 92.0,
                "holder_count": 6_000,
                "binance_volume_share_pct": 8.0,
                "bitget_volume_share_pct": 2.0,
                "short_account_pct": 54.0,
                "short_dominance_score": 62.0,
                "short_account_build_score": 52.0,
                "recent_max_pump_60d_pct": 4.0,
                "recent_pump_60d_days": 60,
                "day_return_pct": 0.4,
                "price_change_24h_pct": 0.4,
                "fdv_to_market_cap": 1.1,
                "locked_supply_pct": 0.0,
            }
        ]
    )

    scored = bot._score_ravelab_early_frame(frame, min_whale_pct=90)
    holder_evidence_mask, _ = bot._ravelab_holder_evidence_masks(scored)
    scored["_ravelab_holder_evidence_gate"] = holder_evidence_mask
    scored = bot._ravelab_apply_thesis_columns(scored, min_squeeze_score=50.0)
    row = scored.iloc[0]

    assert bool(row["_ravelab_whale_gate"])
    assert bool(row["_ravelab_venue_gate"])
    assert bool(row["_ravelab_squeeze_gate"])
    assert not bool(row["_ravelab_float_gate"])
    assert row["_ravelab_core_gate_count"] == 5
    assert row["_ravelab_core_gate_total"] == 6
    assert row["_ravelab_missing_core_gates"] == "float/FDV"
    assert "blockers float/FDV" in bot._ravelab_line(row)


def test_ravelab_whale_gate_requires_top10_control_not_top100_only() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "TOP100ONLYUSDT",
                "history_days": 180,
                **_holder_evidence("ethereum", "0x1111111111111111111111111111111111111111"),
                "top10_holder_pct": 55.0,
                "top100_holder_pct": 99.0,
                "holder_count": 6_000,
                "binance_volume_share_pct": 8.0,
                "bitget_volume_share_pct": 2.0,
                "short_account_pct": 58.0,
                "short_dominance_score": 65.0,
                "short_account_build_score": 58.0,
                "low_float_score": 88.0,
                "fdv_to_market_cap": 8.0,
                "recent_max_pump_60d_pct": 4.0,
                "recent_pump_60d_days": 60,
                "day_return_pct": 0.4,
                "price_change_24h_pct": 0.4,
            },
            {
                "symbol": "TOP10CONTROLUSDT",
                "history_days": 180,
                **_holder_evidence("ethereum", "0x2222222222222222222222222222222222222222"),
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 94.0,
                "holder_count": 6_000,
                "binance_volume_share_pct": 8.0,
                "bitget_volume_share_pct": 2.0,
                "short_account_pct": 58.0,
                "short_dominance_score": 65.0,
                "short_account_build_score": 58.0,
                "low_float_score": 88.0,
                "fdv_to_market_cap": 8.0,
                "recent_max_pump_60d_pct": 4.0,
                "recent_pump_60d_days": 60,
                "day_return_pct": 0.4,
                "price_change_24h_pct": 0.4,
            },
        ]
    )

    scored = bot._score_ravelab_early_frame(frame, min_whale_pct=90).set_index("symbol")

    assert not bool(scored.loc["TOP100ONLYUSDT", "_ravelab_whale_gate"])
    assert float(scored.loc["TOP100ONLYUSDT", "_ravelab_whale_pct"]) == 55.0
    assert bool(scored.loc["TOP10CONTROLUSDT", "_ravelab_whale_gate"])


def test_ravelab_dormant_gate_allows_slow_high_break_without_large_pump() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "SLOWBREAKUSDT",
                "history_days": 180,
                **_holder_evidence("ethereum", "0x1111111111111111111111111111111111111111"),
                "top10_holder_pct": 92.0,
                "top100_holder_pct": 99.0,
                "holder_count": 6_000,
                "binance_volume_share_pct": 8.0,
                "bitget_volume_share_pct": 2.0,
                "short_account_pct": 58.0,
                "short_dominance_score": 65.0,
                "short_account_build_score": 58.0,
                "silent_oi_accumulation_score": 56.0,
                "low_float_score": 88.0,
                "float_trap_score": 82.0,
                "fdv_to_market_cap": 8.0,
                "recent_max_pump_60d_pct": 6.0,
                "recent_pump_60d_days": 60,
                "broke_high_20d": True,
                "broke_high_90d": True,
                "broke_high_180d": True,
                "day_return_pct": 1.2,
                "price_change_24h_pct": 1.2,
                "hour_return_pct": 0.2,
                "range_24h_pct": 4.0,
                "hour_volume_multiple": 1.1,
                "hour_trade_count_multiple": 1.0,
            }
        ]
    )

    scored = bot._score_ravelab_early_frame(frame, min_whale_pct=90, min_history_days=60, max_recent_pump_pct=35)
    holder_evidence_mask, _ = bot._ravelab_holder_evidence_masks(scored)
    scored["_ravelab_holder_evidence_gate"] = holder_evidence_mask
    scored = bot._ravelab_apply_thesis_columns(scored, min_squeeze_score=50.0)
    row = scored.iloc[0]

    assert bool(row["_ravelab_no_large_pump_gate"])
    assert bool(row["_ravelab_dormant_2m_gate"])
    assert float(row["_ravelab_heat_score"]) < 62.0
    assert float(row["pre_activity_heat_score"]) >= 100.0
    assert int(row["_ravelab_core_gate_count"]) == 6

    refreshed = bot._ravelab_refresh_activity_gates(scored, min_history_days=60, max_recent_pump_pct=35)
    assert bool(refreshed.iloc[0]["_ravelab_dormant_2m_gate"])


def test_ravelab_squeeze_gate_uses_funding_flip_model() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "FLIPUSDT",
                "history_days": 180,
                **_holder_evidence("ethereum", "0x1111111111111111111111111111111111111111"),
                "top10_holder_pct": 94.0,
                "short_account_pct": 54.0,
                "long_short_account_ratio": 0.82,
                "predicted_funding_pct": 0.014,
                "carry_funding_pct": 0.012,
                "last_settled_funding_pct": -0.016,
                "prior_settled_funding_pct": -0.012,
                "funding_flip_delta_pct": 0.030,
                "premium_index_pct": 0.08,
                "basis_rate_pct": 0.06,
                "broke_high_5d": True,
                "broke_high_20d": True,
                "upside_to_ath_pct": 200.0,
                "oi_delta_pct": 7.0,
                "oi_to_24h_volume_pct": 40.0,
                "oi_to_market_cap_pct": 12.0,
                "terminal_hidden_float_reflexivity_score": 92,
                "terminal_control_plane_score": 90,
                "centralized_ownership_score": 88,
                "low_float_score": 88,
                "fdv_to_market_cap": 12.0,
                "locked_supply_pct": 74.0,
                "binance_volume_share_pct": 8.0,
                "bitget_volume_share_pct": 2.0,
            }
        ]
    )

    scored = bot._score_ravelab_early_frame(frame)
    holder_evidence_mask, _ = bot._ravelab_holder_evidence_masks(scored)
    scored["_ravelab_holder_evidence_gate"] = holder_evidence_mask
    scored = bot._ravelab_apply_thesis_columns(scored, min_squeeze_score=50.0)
    row = scored.iloc[0]

    assert float(row["funding_flip_score"]) > 50.0
    assert float(row["short_squeeze_score"]) > 40.0
    assert bool(row["_ravelab_squeeze_gate"])
    line = bot._ravelab_line(row)
    assert "crime " in line
    assert "ssq " in line
    assert "flip N" in line


def test_ravelab_queue_summary_splits_triggers_and_core_watch() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "FLOWUSDT",
                "_ravelab_core_gate_count": 5,
                "_ravelab_core_gate_total": 5,
                "_ravelab_whale_origin_flow": True,
                "_ravelab_breakout_any": False,
                "cex_deposit_24h_whale_sender_token_amount": 2_500_000,
            },
            {
                "symbol": "COREUSDT",
                "_ravelab_core_gate_count": 5,
                "_ravelab_core_gate_total": 5,
            },
            {
                "symbol": "TARGETUSDT",
                "_ravelab_core_gate_count": 5,
                "_ravelab_core_gate_total": 5,
                "_ravelab_target_flow": True,
                "cex_deposit_24h_target_exchanges": "Binance",
                "cex_deposit_24h_max_amount": 42_000,
            },
        ]
    )

    lines = bot._ravelab_queue_summary_lines(frame)

    assert lines == [
        "Trigger queue: /FLOWUSDT A3 (whale-CEX 2.50M) | /TARGETUSDT A1 (target-CEX Binance 42.00K)",
        "Core watch: /COREUSDT A1 (core watch)",
    ]


def test_ravelab_trigger_text_prioritizes_whale_flow_then_breakout() -> None:
    row = pd.Series(
        {
            "_ravelab_whale_origin_flow": True,
            "_ravelab_breakout_any": True,
            "_ravelab_breakout_windows": "1D,2D",
            "cex_deposit_24h_whale_sender_token_amount": 1_500_000,
            "cex_deposit_24h_target_exchanges": "Binance",
            "cex_deposit_24h_max_amount": 900_000,
        }
    )

    assert bot._ravelab_trigger_text(row) == "whale-CEX 1.50M, breakout 1D,2D"


def test_ravelab_whale_origin_flow_uses_separate_massive_floor(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_RAVELAB_WHALE_FLOW_MIN_TOKENS", raising=False)
    frame = pd.DataFrame(
        [
            {
                "symbol": "SMALLWHALEUSDT",
                "_ravelab_whale_gate": True,
                "_ravelab_holder_evidence_gate": True,
                "_ravelab_venue_gate": True,
                "_ravelab_float_gate": True,
                "_ravelab_no_large_pump_gate": True,
                "_ravelab_dormant_2m_gate": True,
                "_ravelab_early_gate": True,
                "_ravelab_target_flow": True,
                "_ravelab_breakout_any": False,
                "_ravelab_squeeze_score": 72.0,
                "_ravelab_squeeze_fuel_score": 68.0,
                "_ravelab_short_crowd_score": 62.0,
                "short_account_pct": 54.0,
                "cex_deposit_24h_count": 1,
                "cex_deposit_24h_max_amount": 30_000,
                "cex_deposit_24h_whale_sender_count": 1,
                "cex_deposit_24h_whale_sender_token_amount": 30_000,
                "cex_deposit_24h_top_sender_rank": 1,
                "cex_deposit_24h_top_sender_pct": 91.0,
                "cex_deposit_24h_target_exchanges": "Binance",
            },
            {
                "symbol": "BIGWHALEUSDT",
                "_ravelab_whale_gate": True,
                "_ravelab_holder_evidence_gate": True,
                "_ravelab_venue_gate": True,
                "_ravelab_float_gate": True,
                "_ravelab_no_large_pump_gate": True,
                "_ravelab_dormant_2m_gate": True,
                "_ravelab_early_gate": True,
                "_ravelab_target_flow": True,
                "_ravelab_breakout_any": False,
                "_ravelab_squeeze_score": 72.0,
                "_ravelab_squeeze_fuel_score": 68.0,
                "_ravelab_short_crowd_score": 62.0,
                "short_account_pct": 54.0,
                "cex_deposit_24h_count": 1,
                "cex_deposit_24h_max_amount": 150_000,
                "cex_deposit_24h_whale_sender_count": 1,
                "cex_deposit_24h_whale_sender_token_amount": 150_000,
                "cex_deposit_24h_top_sender_rank": 1,
                "cex_deposit_24h_top_sender_pct": 91.0,
                "cex_deposit_24h_target_exchanges": "Binance",
            },
        ]
    )

    scored = bot._ravelab_apply_thesis_columns(frame, min_squeeze_score=50.0, min_transfer_tokens=20_000)
    scored = scored.set_index("symbol")

    assert float(scored.loc["SMALLWHALEUSDT", "_ravelab_whale_flow_floor_tokens"]) == 100_000.0
    assert bool(scored.loc["SMALLWHALEUSDT", "_ravelab_target_flow"])
    assert not bool(scored.loc["SMALLWHALEUSDT", "_ravelab_whale_origin_flow"])
    assert scored.loc["SMALLWHALEUSDT", "_ravelab_state"] == "A1 CORE PRIME"
    assert bot._ravelab_trigger_text(scored.loc["SMALLWHALEUSDT"]) == "target-CEX Binance 30.00K"
    assert bool(scored.loc["BIGWHALEUSDT", "_ravelab_whale_origin_flow"])
    assert scored.loc["BIGWHALEUSDT", "_ravelab_state"] == "A3 WHALE-CEX PRIME"


def test_ravelab_flow_triggers_respect_min_transfer_floor(monkeypatch) -> None:
    def flow_row(symbol: str, amount: float, contract: str) -> dict[str, object]:
        return {
            "symbol": symbol,
            "history_days": 160,
            "token_platform": "ethereum",
            "token_contract": contract,
            "holder_source": "Etherscan holder endpoint",
            "cex_deposit_flow_score": 94,
            "cex_deposit_flow_flag": True,
            "cex_deposit_24h_count": 1,
            "cex_deposit_24h_token_amount": amount,
            "cex_deposit_24h_max_amount": amount,
            "cex_deposit_24h_whale_sender_count": 1,
            "cex_deposit_24h_whale_sender_token_amount": amount,
            "cex_deposit_24h_top_sender_rank": 1,
            "cex_deposit_24h_top_sender_pct": 91.0,
            "cex_deposit_24h_target_exchanges": "Binance, Gate.io",
            "cex_deposit_inventory_stress_score": 96,
            "inventory_transfer_risk_score": 94,
            "terminal_distribution_pressure_score": 92,
            "terminal_control_plane_score": 86,
            "top10_holder_pct": 91.0,
            "top100_holder_pct": 99.2,
            "holder_count": 8_000,
            "centralized_ownership_score": 88.0,
            "low_float_score": 84.0,
            "float_trap_score": 80.0,
            "fdv_to_market_cap": 9.0,
            "locked_supply_pct": 65.0,
            "short_account_pct": 51.0,
            "short_dominance_score": 58.0,
            "short_account_build_score": 52.0,
            "silent_oi_accumulation_score": 56.0,
            "binance_volume_share_pct": 9.0,
            "bitget_volume_share_pct": 2.0,
            "pre_pump_precision_score": 38.0,
            "low_volatility_coil_score": 80.0,
            "hour_return_pct": 0.3,
            "day_return_pct": 1.0,
            "price_change_24h_pct": 1.0,
            "range_24h_pct": 3.5,
            "scan_mode": "Deep",
            "scanned_at_utc": "now",
        }

    fresh = pd.DataFrame(
        [
            flow_row("LOWFLOWUSDT", 10_000, "0x1111111111111111111111111111111111111111"),
            flow_row("BIGFLOWUSDT", 30_000, "0x2222222222222222222222222222222222222222"),
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    class FakeBinance:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def klines_1d(self, symbol: str, limit: int = 200, **kwargs):
            closed = [[0, 100, 102, 98, 100] for _ in range(max(limit - 1, 1))]
            return [*closed, [0, 100, 101, 99, 100]]

    monkeypatch.setattr(bot, "BinanceFuturesPublic", FakeBinance)

    _, chunks = bot._load_ravelab_list(
        10,
        min_score=0,
        min_archetype=0,
        min_tokens=20_000,
        whale_flow_min_tokens=20_000,
        trigger_filter="flow",
        near_miss_limit=0,
    )
    output = "\n".join(chunks)

    assert "trigger:flow 1" in output
    assert "Trigger lanes before filter: triggered 1 | whale-CEX 1 | target-CEX 1" in output
    assert "/BIGFLOWUSDT" in output
    assert "/LOWFLOWUSDT" not in output


def test_ravelab_whale_origin_flow_requires_qualified_top_holder_sender() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "TINYTOP100USDT",
                "_ravelab_whale_gate": True,
                "_ravelab_holder_evidence_gate": True,
                "_ravelab_venue_gate": True,
                "_ravelab_float_gate": True,
                "_ravelab_no_large_pump_gate": True,
                "_ravelab_dormant_2m_gate": True,
                "_ravelab_early_gate": True,
                "_ravelab_target_flow": True,
                "_ravelab_breakout_any": False,
                "_ravelab_squeeze_score": 72.0,
                "_ravelab_squeeze_fuel_score": 68.0,
                "_ravelab_short_crowd_score": 62.0,
                "short_account_pct": 54.0,
                "cex_deposit_24h_count": 1,
                "cex_deposit_24h_max_amount": 2_000_000,
                "cex_deposit_24h_whale_sender_count": 1,
                "cex_deposit_24h_whale_sender_token_amount": 2_000_000,
                "cex_deposit_24h_top_sender_rank": 25,
                "cex_deposit_24h_top_sender_pct": 0.2,
                "cex_deposit_24h_target_exchanges": "Binance",
            }
        ]
    )

    scored = bot._ravelab_apply_thesis_columns(frame, min_squeeze_score=50.0, min_transfer_tokens=20_000)
    row = scored.iloc[0]

    assert bool(row["_ravelab_target_flow"])
    assert not bool(row["_ravelab_whale_origin_flow"])
    assert row["_ravelab_state"] == "A1 CORE PRIME"
    assert bot._ravelab_trigger_text(row) == "target-CEX Binance 2.00M"
    assert bot._whale_sender_text(row, include_amount=True) == ""


def test_ravelab_exhaustion_blocks_core_prime() -> None:
    base = {
        "history_days": 160,
        **_holder_evidence("ethereum", "0x1111111111111111111111111111111111111111"),
        "top10_holder_pct": 92.0,
        "centralized_ownership_score": 88.0,
        "terminal_control_plane_score": 86.0,
        "low_float_score": 84.0,
        "float_trap_score": 80.0,
        "fdv_to_market_cap": 9.0,
        "locked_supply_pct": 65.0,
        "short_account_pct": 58.0,
        "short_dominance_score": 62.0,
        "short_account_build_score": 58.0,
        "silent_oi_accumulation_score": 56.0,
        "oi_delta_pct": 4.0,
        "binance_volume_share_pct": 9.0,
        "bitget_volume_share_pct": 2.0,
        "pre_pump_precision_score": 40.0,
        "low_volatility_coil_score": 80.0,
        "hour_return_pct": 0.3,
        "day_return_pct": 1.0,
        "price_change_24h_pct": 1.0,
        "range_24h_pct": 3.5,
    }
    frame = pd.DataFrame(
        [
            {**base, "symbol": "CLEANUSDT", "crime_exhaustion_score": 18.0},
            {**base, "symbol": "EXHAUSTUSDT", "crime_exhaustion_score": 82.0},
        ]
    )

    scored = bot._score_ravelab_early_frame(frame)
    holder_evidence_mask, _ = bot._ravelab_holder_evidence_masks(scored)
    scored["_ravelab_holder_evidence_gate"] = holder_evidence_mask
    scored = bot._ravelab_apply_thesis_columns(scored, min_squeeze_score=50.0).set_index("symbol")

    assert bool(scored.loc["CLEANUSDT", "_ravelab_early_gate"])
    assert int(scored.loc["CLEANUSDT", "_ravelab_core_gate_count"]) == 6
    assert bot._ravelab_stage_label(scored.loc["CLEANUSDT"]) == "A1 CORE PRIME"
    assert not bool(scored.loc["EXHAUSTUSDT", "_ravelab_early_gate"])
    assert int(scored.loc["EXHAUSTUSDT", "_ravelab_core_gate_count"]) == 5
    assert scored.loc["EXHAUSTUSDT", "_ravelab_missing_core_gates"] == "early/no-chase"
    assert bot._ravelab_stage_label(scored.loc["EXHAUSTUSDT"]) == "B1 BLOCKED"
    assert "avoid chase/late risk" in bot._ravelab_next_check(scored.loc["EXHAUSTUSDT"])


def test_ravelab_requires_explicit_binance_trading_evidence(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_ASSUME_SYMBOLS_ARE_BINANCE_PERPS", "1")
    base = {
        "history_days": 160,
        **_holder_evidence("ethereum", "0x1111111111111111111111111111111111111111"),
        "top10_holder_pct": 92.0,
        "centralized_ownership_score": 88.0,
        "terminal_control_plane_score": 86.0,
        "low_float_score": 84.0,
        "float_trap_score": 80.0,
        "fdv_to_market_cap": 9.0,
        "locked_supply_pct": 65.0,
        "short_account_pct": 58.0,
        "short_dominance_score": 62.0,
        "short_account_build_score": 58.0,
        "silent_oi_accumulation_score": 56.0,
        "oi_delta_pct": 4.0,
        "bitget_volume_share_pct": 2.0,
        "pre_pump_precision_score": 40.0,
        "low_volatility_coil_score": 80.0,
        "hour_return_pct": 0.3,
        "day_return_pct": 1.0,
        "price_change_24h_pct": 1.0,
        "range_24h_pct": 3.5,
    }
    frame = pd.DataFrame(
        [
            {**base, "symbol": "SYMBOLONLYUSDT"},
            {**base, "symbol": "MARKEDUSDT", "binance_perp_universe": True},
            {**base, "symbol": "SHAREUSDT", "binance_volume_share_pct": 0.5},
        ]
    )

    scored = bot._score_ravelab_early_frame(frame)
    holder_evidence_mask, _ = bot._ravelab_holder_evidence_masks(scored)
    scored["_ravelab_holder_evidence_gate"] = holder_evidence_mask
    scored = bot._ravelab_apply_thesis_columns(scored, min_squeeze_score=50.0).set_index("symbol")

    assert not bool(scored.loc["SYMBOLONLYUSDT", "_ravelab_has_binance"])
    assert not bool(scored.loc["SYMBOLONLYUSDT", "_ravelab_venue_gate"])
    assert scored.loc["SYMBOLONLYUSDT", "_ravelab_missing_core_gates"] == "Binance+Bitget"
    assert bool(scored.loc["MARKEDUSDT", "_ravelab_has_binance"])
    assert bool(scored.loc["MARKEDUSDT", "_ravelab_venue_gate"])
    assert bool(scored.loc["SHAREUSDT", "_ravelab_has_binance"])
    assert bool(scored.loc["SHAREUSDT", "_ravelab_venue_gate"])


def test_ravelab_line_handles_missing_target_exchange_text() -> None:
    row = pd.Series(
        {
            "symbol": "MISSUSDT",
            "_ravelab_early_score": 61.0,
            "_ravelab_side": "RAVE-like",
            "_ravelab_rave_score": 58.0,
            "_ravelab_lab_score": 22.0,
            "_ravelab_early_gate": True,
            "_ravelab_whale_gate": True,
            "_ravelab_venue_gate": True,
            "_ravelab_float_gate": True,
            "_ravelab_float_score": 72.0,
            "_ravelab_dormant_2m_gate": pd.NA,
            "_ravelab_structure_gate": True,
            "_ravelab_target_flow": False,
            "_ravelab_has_binance": pd.NA,
            "_ravelab_has_bitget": pd.NA,
            "_ravelab_has_gate": pd.NA,
            "_ravelab_min_history_days": 42,
            "cex_deposit_24h_target_exchanges": pd.NA,
            "cex_deposit_24h_count": pd.NA,
            "cex_deposit_24h_max_amount": pd.NA,
            "top10_holder_pct": 94.0,
            "top100_holder_pct": 99.8,
        }
    )

    output = bot._ravelab_line(row, detail=True)

    assert "/MISSUSDT | RAVE-like" in output
    assert "CEX no target flow 0tx max n/a" in output
    assert "venues Bn N/Bg N/Gate N" in output
    assert "needs 42d history" in output
    assert "anchor RAVEUSDT 2026-04-18" in output


def test_clip_text_treats_pandas_na_as_empty_text() -> None:
    assert bot._clip_text(pd.NA, 12) == ""


def test_ravelab_line_prints_forced_flow_mechanics_and_exhaustion() -> None:
    row = pd.Series(
        {
            "symbol": "MECHUSDT",
            "_ravelab_early_score": 78.0,
            "_ravelab_thesis_score": 84.0,
            "_ravelab_side": "LAB-like",
            "_ravelab_rave_score": 45.0,
            "_ravelab_lab_score": 80.0,
            "_ravelab_core_gate_count": 6,
            "_ravelab_core_gate_total": 6,
            "_ravelab_whale_gate": True,
            "_ravelab_holder_evidence_gate": True,
            "_ravelab_venue_gate": True,
            "_ravelab_float_gate": True,
            "_ravelab_float_score": 82.0,
            "_ravelab_fdv_to_mcap": 8.0,
            "_ravelab_has_binance": True,
            "_ravelab_has_bitget": True,
            "_ravelab_has_gate": False,
            "_ravelab_no_large_pump_gate": True,
            "_ravelab_dormant_2m_gate": True,
            "_ravelab_squeeze_gate": True,
            "_ravelab_short_majority_gate": True,
            "_ravelab_early_gate": True,
            "_ravelab_target_flow": True,
            "_ravelab_history_days": 120,
            "_ravelab_recent_max_pump_pct": 8.0,
            "_ravelab_recent_pump_days": 60,
            "_ravelab_forced_flow_score": 76.0,
            "_ravelab_exhaustion_score": 18.0,
            "_ravelab_short_build_pp": 2.4,
            "_ravelab_short_drop_pp": 0.0,
            "_ravelab_oi_delta_pct": 5.1,
            "_ravelab_volume_multiple": 2.2,
            "_ravelab_squeeze_score": 72.0,
            "_ravelab_squeeze_fuel_score": 68.0,
            "short_account_pct": 64.0,
            "cex_deposit_24h_target_exchanges": "Binance",
            "cex_deposit_24h_count": 1,
            "cex_deposit_24h_max_amount": 250_000,
            "top10_holder_pct": 94.0,
            "top100_holder_pct": 99.4,
            "token_platform": "ethereum",
            "token_contract": "0x1111111111111111111111111111111111111111",
            "holder_source": "Etherscan holder endpoint",
            "bitget_volume_share_pct": 1.2,
            "binance_volume_share_pct": 10.0,
        }
    )

    output = bot._ravelab_line(row)

    assert "flowMech FORCED 76/100 exh 18 shorts 64.0% +short 2.4pp OI +5.1% volx 2.2" in output
    assert "next: watch for absorption after target-CEX inventory movement and first perp response" in output


def test_ravelab_line_marks_short_fade_as_exhaustion_context() -> None:
    row = pd.Series(
        {
            "symbol": "FADEUSDT",
            "_ravelab_early_score": 70.0,
            "_ravelab_thesis_score": 80.0,
            "_ravelab_side": "RAVE-like",
            "_ravelab_rave_score": 78.0,
            "_ravelab_lab_score": 42.0,
            "_ravelab_core_gate_count": 6,
            "_ravelab_core_gate_total": 6,
            "_ravelab_whale_gate": True,
            "_ravelab_holder_evidence_gate": True,
            "_ravelab_venue_gate": True,
            "_ravelab_float_gate": True,
            "_ravelab_float_score": 82.0,
            "_ravelab_fdv_to_mcap": 8.0,
            "_ravelab_has_binance": True,
            "_ravelab_has_bitget": True,
            "_ravelab_has_gate": False,
            "_ravelab_no_large_pump_gate": True,
            "_ravelab_dormant_2m_gate": True,
            "_ravelab_squeeze_gate": True,
            "_ravelab_short_majority_gate": False,
            "_ravelab_history_days": 120,
            "_ravelab_recent_max_pump_pct": 8.0,
            "_ravelab_recent_pump_days": 60,
            "_ravelab_forced_flow_score": 40.0,
            "_ravelab_exhaustion_score": 74.0,
            "_ravelab_short_build_pp": 0.0,
            "_ravelab_short_drop_pp": 4.2,
            "_ravelab_oi_delta_pct": -1.0,
            "_ravelab_volume_multiple": 6.0,
            "_ravelab_squeeze_score": 55.0,
            "_ravelab_squeeze_fuel_score": 50.0,
            "short_account_pct": 44.0,
            "top10_holder_pct": 94.0,
            "top100_holder_pct": 99.4,
        }
    )

    output = bot._ravelab_line(row)

    assert "flowMech EXHAUST 40/100 exh 74 shorts 44.0% shorts fade 4.2pp OI -1.0% volx 6.0" in output
    assert "next: avoid chase/late risk until short crowd, OI, funding, and volume reset" in output


def test_load_flow_proof_and_coincheck_show_confirmed_transfer_details(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "PROOFUSDT",
                "cex_deposit_flow_score": 88,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 2,
                "cex_deposit_24h_token_amount": 20_500_000,
                "cex_deposit_24h_max_amount": 12_000_000,
                "cex_deposit_24h_notional_usd": 4_100_000,
                "cex_deposit_24h_total_pct_supply": 2.5,
                "cex_deposit_24h_max_pct_supply": 1.4,
                "cex_deposit_24h_whale_sender_count": 1,
                "cex_deposit_24h_whale_sender_token_amount": 12_000_000,
                "cex_deposit_24h_top_sender_address": "0x1111111111111111111111111111111111111111",
                "cex_deposit_24h_top_sender_rank": 1,
                "cex_deposit_24h_top_sender_pct": 91.0,
                "cex_deposit_24h_target_exchanges": "Binance",
                "cex_deposit_24h_top_tx": "0xprime",
                "cex_deposit_flow_source": "token_transfer_api",
                "cex_deposit_concentration_gate": "top10 91.0% / top100 99.0%",
                "cex_deposit_flow_note": "API fallback concentration-gated CEX deposit flow",
                "cex_deposit_24h_source_url": "https://api.etherscan.io/v2/api?chainid=1&action=tokentx",
                "token_platform": "ethereum",
                "token_contract": "0x6666666666666666666666666666666666666666",
                "holder_source": "Etherscan holder endpoint",
                "holder_count": 8_500,
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 99.0,
                "short_account_pct": 63.0,
                "low_float_score": 80.0,
                "float_trap_score": 76.0,
                "fdv_to_market_cap": 7.0,
                "history_days": 180,
                "recent_max_pump_60d_pct": 6.0,
                "recent_pump_60d_days": 60,
                "no_large_pump_60d_flag": True,
                "dormant_short_fuse_score": 78.0,
                "binance_volume_share_pct": 6.0,
                "bitget_volume_share_pct": 1.2,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "GATECHECKUSDT",
                "cex_deposit_flow_score": 90,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 2,
                "cex_deposit_24h_token_amount": 20_500_000,
                "cex_deposit_24h_max_amount": 12_000_000,
                "cex_deposit_24h_target_exchanges": "GateIO",
                "token_platform": "ethereum",
                "token_contract": "0x7777777777777777777777777777777777777777",
                "holder_source": "Etherscan holder endpoint",
                "holder_count": 8_500,
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 99.0,
                "short_account_pct": 63.0,
                "low_float_score": 80.0,
                "float_trap_score": 76.0,
                "fdv_to_market_cap": 7.0,
                "history_days": 180,
                "recent_max_pump_60d_pct": 6.0,
                "recent_pump_60d_days": 60,
                "no_large_pump_60d_flag": True,
                "dormant_short_fuse_score": 78.0,
                "gate_volume_share_pct": 2.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "TARGETONLYUSDT",
                "cex_deposit_flow_score": 86,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 1,
                "cex_deposit_24h_token_amount": 15_000_000,
                "cex_deposit_24h_max_amount": 15_000_000,
                "cex_deposit_24h_target_exchanges": "Bitget",
                "token_platform": "ethereum",
                "token_contract": "0x8888888888888888888888888888888888888888",
                "holder_source": "Etherscan holder endpoint",
                "holder_count": 8_500,
                "top10_holder_pct": 91.0,
                "top100_holder_pct": 99.0,
                "short_account_pct": 63.0,
                "low_float_score": 80.0,
                "float_trap_score": 76.0,
                "fdv_to_market_cap": 7.0,
                "history_days": 180,
                "recent_max_pump_60d_pct": 6.0,
                "recent_pump_60d_days": 60,
                "no_large_pump_60d_flag": True,
                "dormant_short_fuse_score": 78.0,
                "binance_perp_universe": True,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            }
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    proof_title, proof = bot._load_flow_proof("PROOF", min_tokens=10_000_000)
    check_title, check = bot._load_coin_check("PROOF", min_tokens=10_000_000)

    assert proof_title == "PROOFUSDT flow proof"
    assert "Verdict: VERIFIED target-CEX transfer evidence" in proof
    assert "Top tx/hash: 0xprime" in proof
    assert "Total token amount: 20.50M" in proof
    assert "Largest transfer: 12.00M" in proof
    assert "Whale sender: 1 top-holder sender tx | whale-origin 12.00M | r1 91.0% 0x1111...1111" in proof
    assert "Transfer labels prove flow only; they do not prove the Binance+Bitget trading-venue gate." in proof
    assert "Thesis gates: baseThesis Y | holder Y | venueBnBg Y | float Y | shorts Y | noPump60 Y | whaleOrigin Y" in proof
    assert "Flow source: token_transfer_api" in proof
    assert check_title == "PROOFUSDT checklist"
    assert "Verdict: PASS" in check
    assert "PASS target CEX flow" in check
    assert "PASS Binance+Bitget trading venue" in check
    assert "PASS top10 whale dominance" in check
    assert "holder chain ethereum, holders 8500" in check

    gate_title, gate_check = bot._load_coin_check("GATECHECK", min_tokens=10_000_000)

    assert gate_title == "GATECHECKUSDT checklist"
    assert "Verdict: WATCH" in gate_check
    assert "FAIL Binance+Bitget trading venue" in gate_check
    assert "Gate 2.0%,target" in gate_check

    target_title, target_proof = bot._load_flow_proof("TARGETONLY", min_tokens=10_000_000)

    assert target_title == "TARGETONLYUSDT flow proof"
    assert "Verdict: VERIFIED target-CEX transfer evidence" in target_proof
    assert "Thesis gates: baseThesis N | holder Y | venueBnBg N | float Y | shorts Y | noPump60 Y | whaleOrigin N" in target_proof


def test_load_cex_targets_list_only_counts_target_exchanges(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "BITGETUSDT",
                "cex_deposit_flow_score": 90,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 2,
                "cex_deposit_24h_token_amount": 50_000,
                "cex_deposit_24h_max_amount": 30_000,
                "cex_deposit_24h_target_exchanges": "Bitget",
                "cex_deposit_24h_top_tx": "0xbitget",
                "cex_deposit_flow_source": "advanced_filter",
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "KRAKENUSDT",
                "cex_deposit_flow_score": 99,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 2,
                "cex_deposit_24h_token_amount": 80_000,
                "cex_deposit_24h_max_amount": 40_000,
                "cex_deposit_24h_target_exchanges": "Kraken",
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    title, chunks = bot._load_cex_targets_list(10, min_tokens=20_000)
    output = "\n".join(chunks)

    assert title == "Target CEX transfer board"
    assert "Bitget 1" in output
    assert "Transfer rows: /BITGETUSDT" in output
    assert "baseThesis N | noPump60 N" in output
    assert "/BITGETUSDT | Bitget | flow 90/100 | 2 tx | total 50.00K | max 30.00K | top tx 0xbitget" in output
    assert "KRAKENUSDT" not in output


def test_load_float_trap_list_ranks_low_float_high_fdv(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "FLOATYUSDT",
                "low_float_score": 92,
                "float_trap_score": 88,
                "fdv_usd": 1_200_000_000,
                "market_cap_usd": 80_000_000,
                "fdv_to_market_cap": 15.0,
                "circulating_supply_pct": 6.0,
                "locked_supply_pct": 94.0,
                "top100_holder_pct": 98.0,
                "short_account_pct": 62.0,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {"symbol": "NORMALUSDT", "low_float_score": 20, "float_trap_score": 10, "scan_mode": "Deep", "scanned_at_utc": "now"},
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    title, chunks = bot._load_float_trap_list(10, min_score=60)
    output = "\n".join(chunks)

    assert title == "Low-float / high-FDV trap ranking"
    assert "Diagnostic rows: /FLOATYUSDT" in output
    assert "/FLOATYUSDT | float" in output
    assert "FDV/MC 15x" in output
    assert "baseThesis N" in output
    assert "NORMALUSDT" not in output


def test_load_squeeze_ready_list_ranks_short_crowded_names(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "SQUEEZEUSDT",
                "short_account_pct": 68.0,
                "short_dominance_score": 82.0,
                "short_account_build_score": 75.0,
                "short_liquidation_fuel_score": 70.0,
                "oi_delta_pct": 5.5,
                "oi_to_market_cap_pct": 18.0,
                "carry_funding_pct": -0.015,
                "top100_holder_pct": 96.0,
                "low_float_score": 80.0,
                "dormant_short_fuse_score": 70.0,
                "cex_deposit_flow_score": 60,
                "cex_deposit_flow_flag": True,
                "cex_deposit_24h_count": 1,
                "cex_deposit_24h_max_amount": 25_000,
                "cex_deposit_24h_target_exchanges": "Gate",
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {"symbol": "LONGUSDT", "short_account_pct": 42.0, "scan_mode": "Deep", "scanned_at_utc": "now"},
        ]
    )
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    title, chunks = bot._load_squeeze_ready_list(10, min_short_pct=50, min_score=40)
    output = "\n".join(chunks)

    assert title == "Squeeze-ready short-crowd ranking"
    assert "Diagnostic rows: /SQUEEZEUSDT" in output
    assert "/SQUEEZEUSDT | squeeze" in output
    assert "shorts 68.0%" in output
    assert "target CEX flow" in output
    assert "baseThesis N" in output
    assert "LONGUSDT" not in output


def test_load_alpha_brief_blends_structure_timing_and_cex_flow(monkeypatch) -> None:
    fresh = pd.DataFrame(
        [
            {
                "symbol": "FLOWUSDT",
                "bitget_volume_share_pct": 5.0,
                **_holder_evidence("ethereum", "0x3333333333333333333333333333333333333333"),
                "trade_bucket_score": 82,
                "centralized_ownership_score": 85,
                "low_float_score": 80,
                "float_trap_score": 78,
                "short_dominance_score": 82,
                "short_account_build_score": 72,
                "short_liquidation_fuel_score": 70,
                "price_volume_ignition_score": 68,
                "convexity_preignition_score": 66,
                "convexity_runway_score": 75,
                "short_account_pct": 63,
                "oi_delta_pct": 3.1,
                "binance_volume_share_pct": 3.0,
                "hour_return_pct": 2.0,
                "hour_volume_multiple": 2.2,
                "hour_trade_count_multiple": 1.8,
                "hour_close_location_pct": 78,
                "distance_to_high_5d_pct": 1.2,
                "cex_deposit_flow_score": 88,
                "cex_deposit_24h_count": 3,
                "cex_deposit_24h_target_exchanges": "Bitget",
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
            {
                "symbol": "NOGATEUSDT",
                "trade_bucket_score": 99,
                "centralized_ownership_score": 95,
                "low_float_score": 95,
                "float_trap_score": 95,
                "short_account_pct": 70,
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
        ]
    )
    monkeypatch.setenv("DISCORD_ALPHA_BRIEF_MIN_SCORE", "0")
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

    title, chunks = bot._load_alpha_brief(10)
    output = "\n".join(chunks)

    assert title == "Alpha brief"
    assert "Alpha brief - strict thesis-gated convex watchlist" in output
    assert "Thesis gate: observed top10 holder >= 90.0%" in output
    assert "FLOWUSDT | brief" in output
    assert "evidence:" in output
    assert "next:" in output
    assert "CEX 88" in output
    assert "NOGATEUSDT" not in output


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
                    "binance_volume_share_pct": 3.0,
                    "bitget_volume_share_pct": 4.2,
                    **_holder_evidence("bsc", "0x4444444444444444444444444444444444444444"),
                    "scan_mode": "Deep",
                    "scanned_at_utc": "2026-05-14 18:00:00 UTC",
                }
        ]
    )
    monkeypatch.setenv("DISCORD_CONVEX_CACHE_PATH", str(cache))
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at 2026-05-14 18:00:00 UTC"))

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
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at 2026-05-14 18:00:00 UTC"))

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
                    "binance_volume_share_pct": 3.0,
                    "bitget_volume_share_pct": 5.0,
                    **_holder_evidence("arbitrum", "0x5555555555555555555555555555555555555555"),
                "scan_mode": "Deep",
                "scanned_at_utc": "now",
            },
        ]
    )
    monkeypatch.setenv("DISCORD_CONVEX_CACHE_PATH", str(cache))
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at now"))

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
    monkeypatch.setattr(bot, "_fresh_scanner_frame", lambda scan_mode=None, **kwargs: (fresh, "fresh Deep scan at 2026-05-14 18:00:00 UTC"))

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
    assert "Research constraint: user owns entries, sizing, stops, and execution" in description


def test_convex_candidates_require_binance_bitget_by_default(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_REQUIRE_BITGET_OR_GATE", raising=False)
    frame = pd.DataFrame(
        [
            {"symbol": "NOGATEUSDT", "trade_bucket": "Convex Long", "trade_bucket_score": 99},
            {
                "symbol": "PCTONLYUSDT",
                "trade_bucket": "Convex Long",
                "trade_bucket_score": 95,
                "bitget_volume_share_pct": 0.1,
                "top100_holder_pct": 99.0,
            },
                {
                    "symbol": "BITGETUSDT",
                    "trade_bucket": "Convex Long",
                    "trade_bucket_score": 90,
                    "binance_volume_share_pct": 0.2,
                    "bitget_volume_share_pct": 0.1,
                    **_holder_evidence("ethereum", "0x6666666666666666666666666666666666666666"),
                },
            {
                "symbol": "GATEUSDT",
                "trade_bucket": "Convex Long",
                "trade_bucket_score": 88,
                "gate_volume_share_pct": 2.0,
                **_holder_evidence("ethereum", "0x7777777777777777777777777777777777777777"),
            },
        ]
    )

    selected = bot._convex_candidates_from_frame(frame)

    assert selected["symbol"].tolist() == ["BITGETUSDT"]


def test_discord_venue_gate_requires_explicit_binance_evidence_by_default(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_REQUIRE_BITGET_OR_GATE", raising=False)
    monkeypatch.delenv("DISCORD_ASSUME_SYMBOLS_ARE_BINANCE_PERPS", raising=False)
    frame = pd.DataFrame(
        [
            {"symbol": "SYMBOLONLYUSDT", "bitget_volume_share_pct": 1.0},
            {"symbol": "MARKEDUSDT", "binance_perp_universe": True, "bitget_volume_share_pct": 1.0},
            {"symbol": "SHAREUSDT", "binance_volume_share_pct": 0.1, "bitget_volume_share_pct": 1.0},
            {"symbol": "TARGETUSDT", "binance_perp_universe": True, "cex_deposit_24h_target_exchanges": "Bitget"},
        ]
    )

    selected = frame[bot._binance_bitget_trading_gate_mask(frame)]

    assert selected["symbol"].tolist() == ["MARKEDUSDT", "SHAREUSDT"]


def test_discord_legacy_venue_gate_can_assume_binance_perp_universe(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_REQUIRE_BITGET_OR_GATE", raising=False)
    monkeypatch.setenv("DISCORD_ASSUME_SYMBOLS_ARE_BINANCE_PERPS", "1")
    frame = pd.DataFrame(
        [
            {"symbol": "SYMBOLONLYUSDT", "bitget_volume_share_pct": 1.0},
            {"symbol": "NOBITGETUSDT", "binance_perp_universe": True},
        ]
    )

    selected = frame[bot._binance_bitget_trading_gate_mask(frame)]

    assert selected["symbol"].tolist() == ["SYMBOLONLYUSDT"]


def test_discord_thesis_venue_gate_ignores_disabled_generic_env(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_REQUIRE_BITGET_OR_GATE", "0")
    frame = pd.DataFrame(
        [
            {"symbol": "GATEONLYUSDT", "gate_volume_share_pct": 4.0},
            {"symbol": "BITGETUSDT", "binance_perp_universe": True, "bitget_volume_share_pct": 1.0},
        ]
    )

    selected = bot._apply_thesis_venue_gate(frame)

    assert selected["symbol"].tolist() == ["BITGETUSDT"]


def test_strict_holder_evidence_requires_holder_source() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "GOODUSDT",
                "token_platform": "ethereum",
                "token_contract": "0x1111111111111111111111111111111111111111",
                "holder_source": "Etherscan holder endpoint",
                "holder_count": 6_000,
                "top100_holder_pct": 99.0,
            },
            {
                "symbol": "SOURCELESSUSDT",
                "token_platform": "ethereum",
                "token_contract": "0x2222222222222222222222222222222222222222",
                "holder_count": 6_000,
                "top100_holder_pct": 99.0,
            },
            {
                "symbol": "PCTSNAPUSDT",
                "token_platform": "ethereum",
                "token_contract": "0x3333333333333333333333333333333333333333",
                "holder_source": "Etherscan holder endpoint",
                "top100_holder_pct": 98.0,
            },
            {
                "symbol": "METADATAUSDT",
                "token_platform": "ethereum",
                "token_contract": "0x4444444444444444444444444444444444444444",
                "holder_source": "Etherscan holder endpoint",
            },
        ]
    )

    mask, _ = bot._strict_holder_evidence_masks(frame)

    assert mask.tolist() == [True, False, True, False]
    source_less_text = bot._holder_evidence_text(frame.iloc[1])
    assert "needs source" in source_less_text
    pct_snapshot_text = bot._holder_evidence_text(frame.iloc[2])
    assert "top100 98.0%" in pct_snapshot_text
    metadata_only_text = bot._holder_evidence_text(frame.iloc[3])
    assert "needs holder snapshot" in metadata_only_text


def test_thesis_candidate_gate_ignores_disabled_venue_env(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_REQUIRE_BITGET_OR_GATE", "0")
    frame = pd.DataFrame(
        [
            {"symbol": "PCTONLYUSDT", "trade_bucket": "Convex Long", "trade_bucket_score": 100, "top100_holder_pct": 99.0},
            {
                "symbol": "NOGATEUSDT",
                "trade_bucket": "Convex Long",
                "trade_bucket_score": 99,
                **_holder_evidence("bsc", "0x8888888888888888888888888888888888888888"),
            },
            {
                "symbol": "STRICTUSDT",
                "trade_bucket": "Convex Long",
                "trade_bucket_score": 98,
                "binance_perp_universe": True,
                "bitget_volume_share_pct": 1.0,
                **_holder_evidence("bsc", "0x9999999999999999999999999999999999999999"),
            },
        ]
    )

    selected = bot._convex_candidates_from_frame(frame)

    assert selected["symbol"].tolist() == ["STRICTUSDT"]
