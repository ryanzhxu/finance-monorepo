from __future__ import annotations

from datetime import date
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from backtesting.forecast import load_forecast_config
from backtesting.free_price_dataset import load_free_price_signal_config, normalize_ohlcv

EntryStrategy = Literal["close_now", "pullback"]
EntryOutcomeStatus = Literal["completed", "not_triggered", "insufficient_forward_history"]


class EntryTimingOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=20)
    as_of: date
    movement_resolution: Literal["daily_ohlcv"] = "daily_ohlcv"
    strategy: EntryStrategy
    horizon_sessions: int = Field(gt=0)
    trigger_price: float = Field(gt=0)
    filled: bool
    status: EntryOutcomeStatus
    fill_date: date | None = None
    entry_price: float | None = Field(default=None, gt=0)
    exit_price: float | None = Field(default=None, gt=0)
    forward_return: float | None = None
    max_drawdown: float | None = None
    max_drawdown_date: date | None = None
    max_drawdown_sessions: int | None = Field(default=None, ge=1)
    peak_return: float | None = None
    peak_return_date: date | None = None
    peak_return_sessions: int | None = Field(default=None, ge=1)
    first_upside_threshold_date: date | None = None
    first_upside_threshold_sessions: int | None = Field(default=None, ge=1)
    first_downside_threshold_date: date | None = None
    first_downside_threshold_sessions: int | None = Field(default=None, ge=1)


def evaluate_entry_timing(
    symbol: str,
    as_of: date,
    history: pd.DataFrame,
    *,
    horizon_sessions: int,
    pullback_pct: float | None = None,
) -> list[EntryTimingOutcome]:
    """Compare immediate-close and limit-pullback entries without look-ahead."""

    if horizon_sessions <= 0:
        raise ValueError("horizon_sessions must be positive")
    config = load_free_price_signal_config()
    configured_pullback = float(config["entry_timing"]["pullback_pct"])
    pullback_pct = configured_pullback if pullback_pct is None else pullback_pct
    if not 0 < pullback_pct < 1:
        raise ValueError("pullback_pct must be between 0 and 1")

    frame = normalize_ohlcv(history)
    as_of_timestamp = pd.Timestamp(as_of)
    if frame.empty or as_of_timestamp not in frame.index:
        return []
    as_of_position = frame.index.get_loc(as_of_timestamp)
    current_close = float(frame.iloc[as_of_position]["close"])
    outcomes = [
        _evaluate_filled_entry(
            symbol,
            as_of,
            frame,
            strategy="close_now",
            trigger_position=as_of_position,
            entry_price=current_close,
            horizon_sessions=horizon_sessions,
        )
    ]

    pullback_trigger = current_close * (1 - pullback_pct)
    pullback_position = _first_trigger_position(
        frame,
        start_position=as_of_position + 1,
        column="low",
        threshold=pullback_trigger,
        direction="at_or_below",
    )
    if pullback_position is None:
        outcomes.append(
            EntryTimingOutcome(
                symbol=symbol,
                as_of=as_of,
                strategy="pullback",
                horizon_sessions=horizon_sessions,
                trigger_price=round(pullback_trigger, 6),
                filled=False,
                status="not_triggered",
            )
        )
    else:
        pullback_open = float(frame.iloc[pullback_position]["open"])
        fill_price = min(pullback_trigger, pullback_open)
        outcomes.append(
            _evaluate_filled_entry(
                symbol,
                as_of,
                frame,
                strategy="pullback",
                trigger_position=pullback_position,
                entry_price=fill_price,
                horizon_sessions=horizon_sessions,
                trigger_price=pullback_trigger,
            )
        )
    return outcomes


def _evaluate_filled_entry(
    symbol: str,
    as_of: date,
    frame: pd.DataFrame,
    *,
    strategy: EntryStrategy,
    trigger_position: int,
    entry_price: float,
    horizon_sessions: int,
    trigger_price: float | None = None,
) -> EntryTimingOutcome:
    exit_position = trigger_position + horizon_sessions
    trigger_price = entry_price if trigger_price is None else trigger_price
    base = {
        "symbol": symbol,
        "as_of": as_of,
        "strategy": strategy,
        "horizon_sessions": horizon_sessions,
        "trigger_price": round(trigger_price, 6),
        "filled": True,
        "fill_date": frame.index[trigger_position].date(),
        "entry_price": round(entry_price, 6),
    }
    if exit_position >= len(frame):
        return EntryTimingOutcome(**base, status="insufficient_forward_history")

    # Daily OHLC cannot prove whether a same-day high or low happened before a
    # pullback limit order filled, so all post-entry movement starts next session.
    path_start = trigger_position + 1
    path = frame.iloc[path_start : exit_position + 1]
    exit_price = float(path.iloc[-1]["close"])
    max_drawdown_position = int(path["low"].to_numpy(dtype=float).argmin())
    peak_return_position = int(path["high"].to_numpy(dtype=float).argmax())
    upside_threshold = float(load_forecast_config()["upside_return_threshold"])
    downside_threshold = float(load_forecast_config()["downside_drawdown_threshold"])
    upside_hits = np.flatnonzero(path["high"].to_numpy(dtype=float) / entry_price - 1 >= upside_threshold)
    downside_hits = np.flatnonzero(path["low"].to_numpy(dtype=float) / entry_price - 1 <= downside_threshold)

    def event_date(position: int) -> date:
        return path.index[position].date()

    def sessions_after_entry(position: int) -> int:
        return position + 1

    return EntryTimingOutcome(
        **base,
        status="completed",
        exit_price=round(exit_price, 6),
        forward_return=round(exit_price / entry_price - 1, 6),
        max_drawdown=round(float(path.iloc[max_drawdown_position]["low"] / entry_price - 1), 6),
        max_drawdown_date=event_date(max_drawdown_position),
        max_drawdown_sessions=sessions_after_entry(max_drawdown_position),
        peak_return=round(float(path.iloc[peak_return_position]["high"] / entry_price - 1), 6),
        peak_return_date=event_date(peak_return_position),
        peak_return_sessions=sessions_after_entry(peak_return_position),
        first_upside_threshold_date=event_date(int(upside_hits[0])) if upside_hits.size else None,
        first_upside_threshold_sessions=sessions_after_entry(int(upside_hits[0])) if upside_hits.size else None,
        first_downside_threshold_date=event_date(int(downside_hits[0])) if downside_hits.size else None,
        first_downside_threshold_sessions=sessions_after_entry(int(downside_hits[0])) if downside_hits.size else None,
    )


def _first_trigger_position(
    frame: pd.DataFrame,
    *,
    start_position: int,
    column: str,
    threshold: float,
    direction: Literal["at_or_below", "at_or_above"],
) -> int | None:
    values = frame[column].to_numpy(dtype=float, copy=False)[start_position:]
    if direction == "at_or_below":
        matches = np.flatnonzero(values <= threshold)
    else:
        matches = np.flatnonzero(values >= threshold)
    return None if matches.size == 0 else start_position + int(matches[0])
