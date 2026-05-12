from __future__ import annotations

import pandas as pd

from terminal_engine import apply_terminal_model, build_setup_dossier, infer_liquidity_reality


def test_terminal_model_scores_thin_float_short_pressure() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "PLAYUSDT",
                "centralized_ownership_score": 85,
                "low_float_score": 80,
                "float_trap_score": 70,
                "short_dominance_score": 75,
                "short_account_build_score": 65,
                "short_liquidation_fuel_score": 60,
                "price_volume_ignition_score": 55,
                "convexity_preignition_score": 60,
                "convexity_runway_score": 80,
                "ath_runway_confluence_score": 70,
                "exit_fragility_score": 25,
                "no_chase_penalty_score": 20,
                "pre_pump_precision_flag": True,
                "short_account_pct": 62.5,
                "oi_delta_pct": 4.2,
                "daily_quote_volume_multiple": 2.1,
                "top10_holder_pct": 82,
                "ath_multiple": 35,
            }
        ]
    )

    scored = apply_terminal_model(frame)
    row = scored.iloc[0]

    assert row["terminal_edge_score"] > 60
    assert row["terminal_setup_archetype"] == "pre-ignition compression"
    assert "short accounts 62.5%" in row["terminal_evidence_summary"]
    assert "top10 holders 82.0%" in row["terminal_evidence_summary"]


def test_terminal_dossier_uses_research_language() -> None:
    row = apply_terminal_model(pd.DataFrame([{"symbol": "RAVEUSDT", "short_account_pct": 55}])).iloc[0]
    dossier = build_setup_dossier(row)

    assert "# RAVEUSDT Market-Structure Dossier" in dossier
    assert "Research tooling only" in dossier
    assert "trade instruction" in dossier


def test_liquidity_reality_flags_cap_table_supply() -> None:
    assert infer_liquidity_reality({"top100_holder_pct": 99.5}) == "cap-table supply; exits can gap"
