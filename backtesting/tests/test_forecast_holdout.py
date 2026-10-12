from __future__ import annotations

from datetime import date

import pytest

from backtesting.forecast import ForecastObservation
from backtesting.forecast_holdout import build_outer_holdout_contract, split_outer_holdout, validate_candidate_holdout_contract


def _observation(
    as_of: date,
    entry_date: date | None,
    exit_date: date | None,
    *,
    label_version: str = "next_open_low_v2",
    feature_schema_version: str = "continuous_regime_v1",
) -> ForecastObservation:
    return ForecastObservation(
        as_of=as_of,
        symbol="ABC",
        signal_score=70,
        forward_return_3m=0.25,
        max_drawdown_3m=-0.1,
        label_version=label_version,
        entry_date=entry_date,
        exit_date=exit_date,
        entry_price=100 if entry_date else None,
        exit_price=125 if exit_date else None,
        feature_schema_version=feature_schema_version,
        feature_values={"feature": 1.0},
        market_regime="neutral",
    )


def _ready_split():
    return split_outer_holdout(
        [
            _observation(date(2022, 9, 1), date(2022, 9, 2), date(2022, 12, 30)),
            _observation(date(2022, 12, 30), date(2023, 1, 2), date(2023, 3, 31)),
            _observation(date(2023, 1, 3), date(2023, 1, 4), date(2023, 4, 4)),
        ]
    )


def test_outer_holdout_excludes_cross_boundary_label_and_keeps_dates_disjoint() -> None:
    split = _ready_split()

    assert [item.as_of for item in split.selection] == [date(2022, 9, 1)]
    assert [item.as_of for item in split.final_holdout] == [date(2023, 1, 3)]
    assert [item.as_of for item in split.excluded_boundary] == [date(2022, 12, 30)]
    assert split.excluded_reasons == {"label_crosses_final_holdout_boundary": 1}
    assert all(item.exit_date < date(2023, 1, 1) for item in split.selection)
    assert all(item.as_of >= date(2023, 1, 1) for item in split.final_holdout)


def test_outer_holdout_excludes_missing_label_dates_and_rejects_invalid_date_order() -> None:
    missing = _observation(date(2022, 8, 1), None, None)
    split = split_outer_holdout([missing])
    assert split.excluded_reasons == {"missing_executable_label_dates": 1}

    invalid = _observation(date(2022, 8, 1), date(2022, 8, 1), date(2022, 10, 1))
    with pytest.raises(ValueError, match="next-session entry"):
        split_outer_holdout([invalid])


def test_outer_holdout_rejects_mixed_label_or_feature_schema() -> None:
    rows = [
        _observation(date(2022, 9, 1), date(2022, 9, 2), date(2022, 12, 30)),
        _observation(date(2023, 1, 3), date(2023, 1, 4), date(2023, 4, 4), label_version="next_open_ohlc_path_v3"),
    ]
    with pytest.raises(ValueError, match="label_version"):
        split_outer_holdout(rows)


def test_holdout_contract_is_stable_and_rejects_candidate_using_other_artifacts() -> None:
    contract = build_outer_holdout_contract(_ready_split())
    candidate = {
        "model_family": "l2_logistic",
        "label_version": contract["label_version"],
        "feature_schema_version": contract["feature_schema_version"],
        "selection_fingerprint": contract["selection"]["fingerprint"],
        "final_holdout_fingerprint": contract["final_holdout"]["fingerprint"],
    }

    validate_candidate_holdout_contract(contract, candidate)
    candidate["final_holdout_fingerprint"] = "wrong"
    with pytest.raises(ValueError, match="final_holdout_fingerprint"):
        validate_candidate_holdout_contract(contract, candidate)


def test_holdout_contract_stays_unavailable_without_both_partitions() -> None:
    split = split_outer_holdout([_observation(date(2022, 9, 1), date(2022, 9, 2), date(2022, 12, 30))])
    contract = build_outer_holdout_contract(split)

    assert contract["status"] == "unavailable"
    assert contract["shared_benchmark_contract"]["numeric_forecast_rule"].startswith("unavailable")
