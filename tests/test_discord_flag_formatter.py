import pandas as pd

from discord_flag_formatter import (
    build_discord_flag_card,
    infer_convex_trigger,
    infer_liquidity_warning,
    infer_risk_level,
)


REQUIRED_LABELS = [
    "Convex Score:",
    "Structure:",
    "Why flagged:",
    "Observed trigger:",
    "Invalidation:",
    "Liquidity warning:",
    "Risk level:",
    "Failure condition:",
    "Structure remains relevant while:",
    "Research constraint:",
    "Principle:",
]


def test_high_short_pressure_and_rising_oi_produces_convex_trigger() -> None:
    row = pd.Series(
        {
            "symbol": "PLAYUSDT",
            "trade_bucket_score": 82,
            "short_account_pct": 68.5,
            "oi_delta_pct": 3.2,
            "trade_bucket_note": "forced-buying fuel | short-account skew",
        }
    )

    assert "short crowd remains crowded" in infer_convex_trigger(row)


def test_low_holder_data_still_builds_valid_card() -> None:
    row = pd.Series({"symbol": "PLAYUSDT", "trade_bucket_score": 64, "trade_bucket_note": "trend/breakout pressure"})
    card = build_discord_flag_card(row, holder_text="")

    assert card.startswith("/PLAYUSDT")
    for label in REQUIRED_LABELS:
        assert card.count(label) == 1
    assert "Risk level: Elevated" in card


def test_extreme_concentration_adds_liquidity_warning_and_upgrades_risk() -> None:
    row = pd.Series({"symbol": "RAVEUSDT", "trade_bucket_score": 84})
    holder_text = "Holder composition\nTop1 79.32% | Top5 95.84% | Top10 97.57% | Top100 99.97%"

    warning = infer_liquidity_warning(row, holder_text)

    assert "top 100 holders control 100.0%" in warning
    assert infer_risk_level(row, holder_text) == "Extreme"


def test_weak_score_maps_to_watch_only() -> None:
    row = pd.Series({"symbol": "TESTUSDT", "trade_bucket_score": 44})

    assert infer_risk_level(row) == "Watch only"


def test_card_stays_under_discord_safe_length() -> None:
    row = pd.Series(
        {
            "symbol": "LONGUSDT",
            "trade_bucket_score": 95,
            "short_account_pct": 72,
            "oi_delta_pct": 4,
            "trade_bucket_note": "controlled float | " * 80,
        }
    )
    card = build_discord_flag_card(row, holder_text="Holder composition " + "Top100 99.9% " * 80, max_chars=1200)

    assert len(card) <= 1200
    for label in REQUIRED_LABELS:
        assert card.count(label) == 1
