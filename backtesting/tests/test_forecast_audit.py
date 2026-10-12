from backtesting.forecast_audit import build_continuous_feature_audit


def test_audit_blocks_uncertified_model_and_summarizes_regime_failures() -> None:
    audit = build_continuous_feature_audit(
        {
            "schema_version": "forecast_continuous_regime_diagnostics_v1",
            "model_version": "forecast_continuous_regime_v1",
            "calibration_status": "unavailable",
            "point_in_time_certified": False,
            "aggregate_metrics": {"upside_brier_improvement": -0.01, "downside_brier_improvement": 0.0005},
            "regimes": [
                {
                    "regime": "risk_on",
                    "count": 5,
                    "upside": {"event_rate": 0.3, "improvement_over_flat": 0.002},
                    "downside": {"event_rate": 0.1, "improvement_over_flat": -0.1},
                }
            ],
            "folds": [
                {
                    "upside": {"improvement_over_flat": -0.01, "coefficients": {"stock_return_63d": 0.5}},
                    "downside": {"improvement_over_flat": -0.1, "coefficients": {"stock_return_63d": -0.2}},
                }
            ],
        }
    )

    assert audit["promotion_decision"] == "block"
    assert len(audit["blockers"]) == 3
    assert audit["regimes"][0]["upside"]["diagnosis"] == "meets_local_brier_gate_only"
    assert audit["regimes"][0]["downside"]["diagnosis"] == "worse_than_flat_baseline"
    assert audit["coefficient_summary"]["upside"][0]["median_coefficient"] == 0.5
    assert audit["worst_folds"]["upside"][0]["improvement_over_flat"] == -0.01


def test_audit_accepts_the_current_v3_diagnostics_schema() -> None:
    audit = build_continuous_feature_audit(
        {
            "schema_version": "forecast_continuous_regime_diagnostics_v3",
            "aggregate_metrics": {"upside_brier_improvement": 0.01, "downside_brier_improvement": 0.01},
            "regimes": [],
            "folds": [],
        }
    )

    assert audit["schema_version"] == "forecast_continuous_feature_audit_v1"
