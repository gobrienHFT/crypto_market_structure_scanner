import pandas as pd

from discord_flag_formatter import (
    build_discord_flag_card,
    infer_convex_trigger,
    infer_liquidity_warning,
    infer_perp_positioning,
    infer_risk_level,
    join_discord_flag_cards,
)


REQUIRED_LABELS = [
    "Convex Score:",
    "Structure:",
    "Perp positioning:",
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
    assert "Perp positioning: short accounts n/a" in card


def test_perp_positioning_always_shows_short_account_percentage() -> None:
    row = pd.Series(
        {
            "symbol": "RAVEUSDT",
            "short_account_pct": 24.1,
            "long_account_pct": 75.9,
            "long_short_account_ratio": 3.15,
            "oi_delta_pct": -0.8,
        }
    )

    positioning = infer_perp_positioning(row)

    assert "short accounts 24.1%" in positioning
    assert "long accounts 75.9%" in positioning
    assert "L/S acct 3.15" in positioning
    assert "OI change -0.8%" in positioning


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


def test_joined_cards_begin_with_all_candidate_names_when_details_truncate() -> None:
    cards = [
        f"/{symbol}\n\nConvex Score: 90/100\n" + ("detail " * 80)
        for symbol in ("RAVEUSDT", "EGLDUSDT", "CHIPUSDT", "LABUSDT")
    ]

    joined = join_discord_flag_cards(cards, max_chars=900)

    first_line = joined.splitlines()[0]
    assert first_line == "Candidates: /RAVEUSDT /EGLDUSDT /CHIPUSDT /LABUSDT"
    assert "detailed commentary" in joined
    assert "see Candidates line above" in joined
    assert len(joined) <= 900
