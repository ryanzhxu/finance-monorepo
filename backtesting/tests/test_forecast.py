from datetime import date, timedelta

from backtesting.forecast import ForecastObservation, estimate_shares, fit_forecast_model
from backtesting.forecast_artifact import build_forecast_run_report
from backtesting.walk_forward import WalkForwardSettings


def _observations(count: int = 720) -> list[ForecastObservation]:
    start = date(2020, 1, 1)
    rows = []
    for index in range(count):
        score = (index % 100) + 0.5
        upside = 0.35 if score >= 70 else -0.04
        drawdown = -0.08 if score >= 70 else -0.28
        rows.append(
            ForecastObservation(
                as_of=start + timedelta(days=index),
                symbol=f"S{index % 10}",
                signal_score=score,
                forward_return_3m=upside,
                max_drawdown_3m=drawdown,
            )
        )
    return rows


def test_forecast_remains_unavailable_until_out_of_sample_calibration_is_sufficient() -> None:
    model = fit_forecast_model(
        _observations(100),
        walk_forward=WalkForwardSettings(training_sessions=20, validation_sessions=5, test_sessions=5, step_sessions=5),
    )
    result = model.predict(mode="upside_discovery", as_of=date(2024, 1, 1), signal_score=90)

    assert model.status == "unavailable"
    assert result.calibration_status == "unavailable"
    assert result.upside_probability is None
    assert result.expected_return_range is None
    assert result.position_tier is None
    report = build_forecast_run_report(model, as_of=date(2024, 1, 1))
    assert report.model_version == 'forecast_baseline_close_v1'
    assert report.metrics.out_of_sample_count == model.metrics.out_of_sample_count
    assert report.upside_probability is None


def test_walk_forward_baseline_calibrates_and_sizes_only_with_capital() -> None:
    model = fit_forecast_model(
        _observations(),
        walk_forward=WalkForwardSettings(training_sessions=60, validation_sessions=10, test_sessions=20, step_sessions=20),
    )
    result = model.predict(mode="upside_discovery", as_of=date(2024, 1, 1), signal_score=90)
    sized = model.predict(
        mode="upside_discovery",
        as_of=date(2024, 1, 1),
        signal_score=90,
        capital=10_000,
        current_price=100,
    )

    assert model.status == "validated"
    assert result.upside_probability is not None
    assert result.downside_probability is not None
    assert result.expected_return_range is not None
    assert result.estimated_shares is None
    assert sized.estimated_shares is not None
    assert sized.estimated_shares > 0
    assert model.metrics.model_dump() == {
        "out_of_sample_count": 640,
        "fold_count": 32,
        "upside_brier_score": 0.077527,
        "upside_baseline_brier_score": 0.239654,
        "downside_brier_score": 0.077527,
        "downside_baseline_brier_score": 0.239654,
        "upside_brier_improvement": 0.162127,
        "downside_brier_improvement": 0.162127,
    }


def test_forecast_rejects_a_model_without_material_brier_improvement() -> None:
    observations = [item.model_copy(update={"signal_score": 50}) for item in _observations()]

    model = fit_forecast_model(
        observations,
        walk_forward=WalkForwardSettings(training_sessions=60, validation_sessions=10, test_sessions=20, step_sessions=20),
    )

    assert model.status == "unavailable"
    assert model.metrics.upside_brier_improvement == 0
    assert model.metrics.downside_brier_improvement == 0


def test_forecast_refuses_to_promote_uncertified_price_data() -> None:
    model = fit_forecast_model(
        _observations(),
        walk_forward=WalkForwardSettings(training_sessions=60, validation_sessions=10, test_sessions=20, step_sessions=20),
        point_in_time_certified=False,
    )

    result = model.predict(mode="upside_discovery", as_of=date(2024, 1, 1), signal_score=90)

    assert model.status == "unavailable"
    assert result.data_coverage["point_in_time_certified"] is False
    assert result.upside_probability is None


def test_forecast_rejects_mixed_label_versions() -> None:
    observations = _observations()
    observations[0] = observations[0].model_copy(update={"label_version": "next_open_low_v2"})

    try:
        fit_forecast_model(observations)
    except ValueError as exc:
        assert "one label version" in str(exc)
    else:
        raise AssertionError("mixed label versions must not share a model run")


def test_position_sizing_never_returns_fractional_or_negative_shares() -> None:
    assert estimate_shares(100, 101, "larger_bet") == 0
    assert estimate_shares(10_000, 100, "starter_bet") == 1
    assert estimate_shares(None, 100, "starter_bet") is None
