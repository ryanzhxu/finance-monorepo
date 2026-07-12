from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class WalkForwardSettings:
    training_sessions: int = 252
    validation_sessions: int = 63
    test_sessions: int = 63
    step_sessions: int = 63
    embargo_sessions: int = 5

    def __post_init__(self) -> None:
        if min(self.training_sessions, self.validation_sessions, self.test_sessions, self.step_sessions) <= 0:
            raise ValueError("training, validation, test, and step sessions must be positive")
        if self.embargo_sessions < 0:
            raise ValueError("embargo sessions cannot be negative")


@dataclass(frozen=True)
class WalkForwardFold:
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    test_start: datetime
    test_end: datetime


def build_walk_forward_folds(dates: list[datetime], settings: WalkForwardSettings) -> list[WalkForwardFold]:
    sessions = sorted(set(dates))
    folds: list[WalkForwardFold] = []
    start = 0
    while True:
        train_end = start + settings.training_sessions - 1
        validation_start = train_end + settings.embargo_sessions + 1
        validation_end = validation_start + settings.validation_sessions - 1
        test_start = validation_end + settings.embargo_sessions + 1
        test_end = test_start + settings.test_sessions - 1
        if test_end >= len(sessions):
            break
        folds.append(
            WalkForwardFold(
                train_start=sessions[start],
                train_end=sessions[train_end],
                validation_start=sessions[validation_start],
                validation_end=sessions[validation_end],
                test_start=sessions[test_start],
                test_end=sessions[test_end],
            )
        )
        start += settings.step_sessions
    return folds
