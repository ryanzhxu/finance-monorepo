from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backtesting.walk_forward import WalkForwardSettings, build_walk_forward_folds


def test_walk_forward_folds_respect_validation_and_test_embargoes() -> None:
    dates = [datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=index) for index in range(16)]

    folds = build_walk_forward_folds(
        dates,
        WalkForwardSettings(training_sessions=5, validation_sessions=2, test_sessions=2, step_sessions=2, embargo_sessions=1),
    )

    assert len(folds) == 3
    assert folds[0].train_end < folds[0].validation_start
    assert folds[0].validation_end < folds[0].test_start
    assert folds[0].test_start == dates[9]
