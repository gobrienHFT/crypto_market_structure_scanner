import pandas as pd

from mechanism_engine import apply_mechanism_model


def test_mechanism_model_identifies_crowded_short_uptrend_continuation() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "VELVETUSDT",
                "carry_funding_pct": 0.018,
                "predicted_funding_pct": 0.021,
                "short_account_pct": 64.0,
                "short_account_roc_1h_pp": 1.5,
                "short_account_change_max_pp": 3.2,
                "broke_high_20d": True,
                "broke_high_90d": True,
                "range_high_break_count": 2,
                "day_return_pct": 18.0,
                "oi_delta_pct": 5.0,
                "terminal_short_pressure_score": 78.0,
                "breakout_pressure_score": 82.0,
            }
        ]
    )

    scored = apply_mechanism_model(frame)
    row = scored.iloc[0]

    assert row["mechanism_primary"] == "Crowded-short uptrend continuation"
    assert row["mechanism_stage"] == "active continuation"
    assert row["mechanism_playbook_label"] == "A: continuation watch"
    assert "VELVET lesson" in row["mechanism_playbook_rule"]
    assert row["mechanism_crowded_short_uptrend_score"] > 60.0
    assert "funding 0.0210%" in row["mechanism_evidence_note"]
    assert "shorts 64.0%" in row["mechanism_evidence_note"]


def test_mechanism_model_identifies_cex_inventory_squeeze() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "LABUSDT",
                "cex_deposit_flow_score": 88.0,
                "cex_deposit_inventory_stress_score": 92.0,
                "terminal_exchange_flow_score": 85.0,
                "terminal_float_score": 76.0,
                "centralized_ownership_score": 80.0,
                "short_account_pct": 58.0,
                "oi_delta_pct": 4.0,
                "broke_high_20d": True,
                "cex_deposit_24h_token_amount": 12_500_000.0,
                "cex_deposit_24h_target_exchanges": "Binance, Gate",
            }
        ]
    )

    scored = apply_mechanism_model(frame)
    row = scored.iloc[0]

    assert row["mechanism_primary"] == "CEX inventory squeeze"
    assert row["mechanism_playbook_label"] == "A: CEX-inventory watch"
    assert "LAB lesson" in row["mechanism_playbook_rule"]
    assert row["mechanism_inventory_squeeze_score"] > 60.0
    assert "24h deposits 12500000 tokens" in row["mechanism_evidence_note"]
    assert "targets Binance, Gate" in row["mechanism_evidence_note"]


def test_mechanism_model_keeps_late_failure_visible() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "BLOWOFFUSDT",
                "carry_funding_pct": 0.025,
                "short_account_pct": 66.0,
                "short_account_roc_1h_pp": 2.0,
                "broke_high_20d": True,
                "day_return_pct": 30.0,
                "convexity_late_penalty": 82.0,
                "crime_exhaustion_score": 75.0,
                "blowoff_risk_flag": True,
            }
        ]
    )

    scored = apply_mechanism_model(frame)
    row = scored.iloc[0]

    assert row["mechanism_late_failure_score"] >= 100.0
    assert row["mechanism_stage"] == "distribution/exhaustion risk"
    assert row["mechanism_playbook_label"] == "C: no-chase / unwind risk"
    assert "RAVE lesson" in row["mechanism_playbook_rule"]
    assert "Invalidates" in row["mechanism_invalidation"]
