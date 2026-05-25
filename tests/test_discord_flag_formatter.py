import pandas as pd

from discord_flag_formatter import (
    build_discord_flag_card,
    infer_convex_thesis,
    infer_convex_trigger,
    infer_evidence_stack,
    infer_next_check,
    infer_why_flagged,
    infer_liquidity_warning,
    infer_perp_positioning,
    infer_risk_level,
    join_discord_flag_cards,
    sanitize_discord_language,
)


REQUIRED_LABELS = [
    "Convex Score:",
    "Structure:",
    "Convex thesis:",
    "Evidence stack:",
    "Perp positioning:",
    "Why flagged:",
    "Observed trigger:",
    "Next check:",
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


def test_range_breakout_event_is_included_in_flag_evidence() -> None:
    row = pd.Series(
        {
            "symbol": "RANGEUSDT",
            "trade_bucket_score": 78,
            "range_breakout_event": "20D high, 90D high hit",
            "oi_delta_pct": 0.5,
        }
    )

    assert "20D high, 90D high hit" in infer_why_flagged(row)
    assert "20D high, 90D high hit" in infer_convex_trigger(row)


def test_convex_thesis_and_next_check_prioritize_cex_flow_plus_float_control() -> None:
    row = pd.Series(
        {
            "symbol": "FLOWUSDT",
            "trade_bucket_score": 86,
            "short_account_pct": 63,
            "oi_delta_pct": 2.1,
            "cex_deposit_flow_score": 88,
            "cex_deposit_24h_count": 3,
            "cex_deposit_24h_target_exchanges": "Bitget",
            "top10_holder_pct": 91,
            "terminal_edge_score": 78,
            "terminal_structure_edge_score": 83,
            "terminal_control_plane_score": 78,
            "terminal_distribution_pressure_score": 76,
            "terminal_pre_ignition_quality_score": 68,
            "timing_score": 64,
            "low_float_score": 82,
            "cex_deposit_inventory_stress_score": 71,
            "cex_deposit_24h_notional_usd": 650_000,
        }
    )

    thesis = infer_convex_thesis(row)
    stack = infer_evidence_stack(row)
    next_check = infer_next_check(row)

    assert "fresh CEX-flow" in thesis
    assert "structure edge 83" in stack
    assert "CEX flow 88" in stack
    assert "inventory stress 71" in stack
    assert "float control 91" in stack
    assert "venue inventory" in next_check


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


def test_language_sanitizer_rewrites_trade_call_terms() -> None:
    dirty = "pump call with buy signal and worth holding longer because taker buyers appeared"

    clean = sanitize_discord_language(dirty)

    assert "pump call" not in clean.lower()
    assert "buy signal" not in clean.lower()
    assert "worth holding longer" not in clean.lower()
    assert "buyers" not in clean.lower()
    assert "market-structure flag" in clean


def test_opaque_supply_pattern_uses_neutral_structural_language() -> None:
    row = pd.Series(
        {
            "symbol": "LABUSDT",
            "trade_bucket_score": 91,
            "short_account_pct": 54,
            "long_account_pct": 46,
            "terminal_hidden_float_reflexivity_score": 84,
            "terminal_exchange_flow_score": 76,
            "terminal_private_unlock_score": 88,
            "terminal_structural_opacity_note": "opaque public float; private supply paths require review",
        }
    )

    card = build_discord_flag_card(row)
    lowered = card.lower()

    assert "opaque supply/unlock risk" in card
    assert "concentration-gated CEX-flow signal" in card
    assert "reported float may not capture private unlock/OTC supply" in card
    for forbidden in ("crime", "scam", "fraud", "illegal", "manipulation"):
        assert forbidden not in lowered


def test_recent_cex_flow_line_is_included_when_concentration_gate_triggers() -> None:
    row = pd.Series(
        {
            "symbol": "PLAYUSDT",
            "trade_bucket_score": 80,
            "cex_deposit_flow_score": 88,
            "cex_deposit_24h_count": 2,
            "cex_deposit_24h_target_exchanges": "Bitget, Kraken",
            "cex_deposit_concentration_gate": "top10 91.0% / top100 99.0%",
            "cex_deposit_24h_token_amount": 2_500_000,
            "cex_deposit_24h_notional_usd": 500_000,
            "cex_deposit_inventory_stress_score": 66,
        }
    )

    card = build_discord_flag_card(row)

    assert "Recent CEX flow:" in card
    assert "Bitget, Kraken" in card
    assert "top10 91.0%" in card
    assert "2.50M tokens" in card
    assert "500.00K notional" in card
    assert "inventory stress 66/100" in card


def test_accumulation_absorption_line_uses_neutral_language() -> None:
    row = pd.Series(
        {
            "symbol": "PLAYUSDT",
            "trade_bucket_score": 82,
            "short_account_pct": 52.3,
            "long_account_pct": 47.7,
            "long_short_account_ratio": 0.91,
            "accumulation_absorption_score": 74,
            "accumulation_absorption_flag": True,
            "accumulation_absorption_note": (
                "aggressive taker demand absorbed with muted price response; "
                "absorption 74/100; requires source/holder review"
            ),
        }
    )

    card = build_discord_flag_card(row)
    lowered = card.lower()

    assert "Accumulation read:" in card
    assert "aggressive taker demand absorbed" in card
    assert "insider" not in lowered
    assert "pump call" not in lowered


def test_case_study_analogue_line_is_included_when_available() -> None:
    row = pd.Series(
        {
            "symbol": "LABUSDT",
            "trade_bucket_score": 84,
            "archetype_match_score": 87,
            "archetype_best_match": "LAB-style venue-inventory stress",
            "archetype_match_note": (
                "LAB-style venue-inventory stress 87/100; controlled float, "
                "concentration-gated CEX flow, and venue-inventory pressure"
            ),
        }
    )

    card = build_discord_flag_card(row)

    assert "Case-study analogue:" in card
    assert "LAB-style venue-inventory stress 87/100" in card
    assert "archetype 87" in card


def test_early_radar_line_is_included_when_available() -> None:
    row = pd.Series(
        {
            "symbol": "STOUSDT",
            "trade_bucket_score": 81,
            "early_pump_radar_score": 88,
            "early_pump_state": "Prime early squeeze",
            "early_pump_primary_signal": "target CEX flow 91/100",
            "early_pump_next_check": "check whether deposited inventory is absorbed while OI expands",
        }
    )

    card = build_discord_flag_card(row)

    assert "Early radar: Prime early squeeze 88/100" in card
    assert "early radar 88" in card
    assert "target CEX flow 91/100" in card
