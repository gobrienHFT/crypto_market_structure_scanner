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


def test_terminal_evidence_includes_range_breakout_event() -> None:
    scored = apply_terminal_model(
        pd.DataFrame(
            [
                {
                    "symbol": "RANGEUSDT",
                    "terminal_edge_score": 55,
                    "range_breakout_event": "20D high, 90D high hit",
                    "range_breakout_score": 62,
                    "price_volume_ignition_score": 40,
                }
            ]
        )
    )

    assert "20D high, 90D high hit" in scored.iloc[0]["terminal_evidence_summary"]


def test_terminal_model_scores_opaque_supply_and_private_unlock_pattern() -> None:
    scored = apply_terminal_model(
        pd.DataFrame(
            [
                {
                    "symbol": "LABUSDT",
                    "centralized_ownership_score": 88,
                    "float_trap_score": 84,
                    "low_float_score": 72,
                    "short_dominance_score": 55,
                    "price_volume_ignition_score": 70,
                    "convexity_preignition_score": 60,
                    "insider_supply_control_estimate_pct": 95,
                    "insider_cex_deposit_pct": 62,
                    "cex_withdrawal_recent_pct": 28,
                    "exchange_withdrawal_cluster_count": 10,
                    "exchange_withdrawal_cluster_pct": 42,
                    "hidden_otc_discount_pct": 80,
                    "otc_unlock_cluster_score": 78,
                    "vesting_opacity_score": 82,
                    "distribution_transparency_score": 10,
                    "hidden_otc_terms_flag": True,
                    "vesting_terms_changed_flag": True,
                    "loan_default_token_repayment_flag": True,
                    "borrower_wallet_matches_buybacks_flag": True,
                    "signer_linked_cluster_flag": True,
                    "same_actor_prior_token_pattern_flag": True,
                    "top10_holder_pct": 98,
                    "daily_quote_volume_multiple": 4.5,
                }
            ]
        )
    )
    row = scored.iloc[0]

    assert row["terminal_hidden_float_reflexivity_score"] >= 70
    assert row["terminal_exchange_flow_score"] >= 50
    assert row["terminal_private_unlock_score"] >= 70
    assert row["terminal_setup_archetype"] == "opaque-float reflexivity"
    assert "opaque-float" in row["terminal_evidence_summary"]
    assert "private unlock/OTC" in row["terminal_evidence_summary"]
    assert "private supply paths require review" in row["terminal_structural_opacity_note"]
