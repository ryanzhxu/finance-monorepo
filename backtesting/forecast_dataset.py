from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, timedelta

import pandas as pd

from backtesting.forecast import ForecastObservation, load_forecast_config
from backtesting.historical_dataset import HistoricalFeatureSnapshot

PriceLoader = Callable[[str, date, date], pd.Series | pd.DataFrame]


def build_forecast_observations(
    snapshots: Iterable[HistoricalFeatureSnapshot],
    *,
    price_loader: PriceLoader,
    include_path_timing: bool = False,
) -> tuple[list[ForecastObservation], dict[str, int]]:
    """Turn point-in-time features into forward outcomes without look-ahead.

    ``include_path_timing`` writes a separate v3 label with threshold timing.
    It preserves the legacy v2 label for existing experiments and never infers
    intraday ordering from a daily OHLC bar.
    """

    horizon_sessions = int(load_forecast_config()["horizon_sessions"])
    observations: list[ForecastObservation] = []
    skipped: dict[str, int] = {}
    eligible: dict[str, list[tuple[HistoricalFeatureSnapshot, float]]] = {}
    for snapshot in snapshots:
        score = _signal_score(snapshot)
        if score is None:
            _increment(skipped, "missing_signal_score")
            continue
        eligible.setdefault(snapshot.symbol, []).append((snapshot, score))

    for symbol, items in eligible.items():
        start = min(snapshot.as_of.date() for snapshot, _ in items)
        end = max(snapshot.as_of.date() for snapshot, _ in items) + timedelta(days=round(horizon_sessions * 1.8))
        prices = _normalize_ohlcv(price_loader(symbol, start, end))
        if prices.empty:
            for _ in items:
                _increment(skipped, "price_history_unavailable")
            continue
        for snapshot, score in items:
            as_of = snapshot.as_of.date()
            # The signal is known only after the as-of close, so execution begins
            # at the next tradable session rather than an unfillable same-day close.
            entry_position = prices.index.searchsorted(pd.Timestamp(as_of), side="right")
            exit_position = entry_position + horizon_sessions - 1
            if entry_position >= len(prices) or exit_position >= len(prices):
                _increment(skipped, "insufficient_forward_history")
                continue
            if include_path_timing and "high" not in prices:
                _increment(skipped, "missing_high_for_path_timing")
                continue

            path = prices.iloc[entry_position : exit_position + 1]
            entry_price = float(path["open"].iloc[0])
            if entry_price <= 0:
                _increment(skipped, "invalid_entry_price")
                continue
            drawdown_position = int(path["low"].to_numpy().argmin())
            timing = _path_timing_labels(path, entry_price) if include_path_timing else {}
            observations.append(
                ForecastObservation(
                    as_of=as_of,
                    symbol=snapshot.symbol,
                    signal_score=score,
                    forward_return_3m=float(path["close"].iloc[-1] / entry_price - 1),
                    max_drawdown_3m=float(path["low"].min() / entry_price - 1),
                    label_version="next_open_ohlc_path_v3" if include_path_timing else "next_open_low_v2",
                    entry_date=path.index[0].date(),
                    exit_date=path.index[-1].date(),
                    entry_price=entry_price,
                    exit_price=float(path["close"].iloc[-1]),
                    max_drawdown_date=path.index[drawdown_position].date(),
                    **timing,
                )
            )
    return observations, skipped


def _signal_score(snapshot: HistoricalFeatureSnapshot) -> float | None:
    for key in ("signal_score", "opportunity_score", "weighted_score", "confidence"):
        metric = snapshot.values.get(key)
        if metric is None or metric.value is None:
            continue
        try:
            value = float(metric.value)
        except (TypeError, ValueError):
            continue
        if key == "confidence" and 0 <= value <= 1:
            value *= 100
        if 0 <= value <= 100:
            return value
    return None


def _normalize_ohlcv(values: pd.Series | pd.DataFrame) -> pd.DataFrame:
    if isinstance(values, pd.DataFrame):
        lowered = values.copy()
        lowered.columns = [str(column).lower() for column in lowered.columns]
        if not {"open", "low", "close"}.issubset(lowered.columns):
            return pd.DataFrame(columns=["open", "low", "close"])
        columns = ["open", "low", "close"]
        if "high" in lowered.columns:
            columns.append("high")
        frame = lowered[columns].apply(pd.to_numeric, errors="coerce").dropna()
    else:
        series = pd.to_numeric(values, errors="coerce").dropna().astype(float)
        frame = pd.DataFrame({"open": series, "low": series, "close": series})
    if frame.empty:
        return pd.DataFrame(columns=["open", "low", "close"])
    index = pd.DatetimeIndex(frame.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    frame.index = index.normalize()
    return frame[~frame.index.duplicated(keep="last")].sort_index()


def _path_timing_labels(path: pd.DataFrame, entry_price: float) -> dict[str, object]:
    """Describe threshold timing from daily bars without inventing intraday order."""

    config = load_forecast_config()
    upside_threshold = float(config["upside_return_threshold"])
    downside_threshold = float(config["downside_drawdown_threshold"])
    upside_hits = (path["high"].to_numpy(dtype=float) / entry_price - 1 >= upside_threshold).nonzero()[0]
    downside_hits = (path["low"].to_numpy(dtype=float) / entry_price - 1 <= downside_threshold).nonzero()[0]
    upside_position = int(upside_hits[0]) if len(upside_hits) else None
    downside_position = int(downside_hits[0]) if len(downside_hits) else None

    if upside_position is None and downside_position is None:
        order = "neither"
    elif downside_position is None:
        order = "upside_only"
    elif upside_position is None:
        order = "downside_only"
    elif upside_position == downside_position:
        order = "same_session"
    elif upside_position < downside_position:
        order = "upside_first"
    else:
        order = "downside_first"

    return {
        "first_upside_threshold_date": path.index[upside_position].date() if upside_position is not None else None,
        "first_upside_threshold_sessions": upside_position if upside_position is not None else None,
        "first_downside_threshold_date": path.index[downside_position].date() if downside_position is not None else None,
        "first_downside_threshold_sessions": downside_position if downside_position is not None else None,
        "path_event_order": order,
    }


def _increment(values: dict[str, int], key: str) -> None:
    values[key] = values.get(key, 0) + 1
