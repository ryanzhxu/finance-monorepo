from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from analyst_service.core.technicals import compute_technicals, rsi
from backtesting.historical_dataset import HistoricalFeatureSnapshot, HistoricalMetric
from shared.config_loader import load_yaml_config
from shared.enums import Freshness

FREE_PRICE_SIGNAL_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "free_price_signal.yaml"


@lru_cache
def load_free_price_signal_config() -> dict[str, Any]:
    return load_yaml_config(FREE_PRICE_SIGNAL_CONFIG_PATH, {"minimum_history_sessions", "signal_score", "entry_timing"})


def fetch_free_adjusted_ohlcv(symbol: str, start: date, end: date, *, timeout_seconds: float = 30.0) -> pd.DataFrame:
    """Fetch a prototype-only adjusted OHLCV history from yfinance."""

    import yfinance as yf

    history = yf.Ticker(symbol).history(
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        auto_adjust=True,
        timeout=timeout_seconds,
    )
    return normalize_ohlcv(history)


def build_price_only_snapshots(symbol: str, history: pd.DataFrame) -> list[HistoricalFeatureSnapshot]:
    """Create daily, point-in-time technical snapshots from an adjusted OHLCV frame."""

    frame = normalize_ohlcv(history)
    config = load_free_price_signal_config()
    minimum_history = int(config["minimum_history_sessions"])
    if len(frame) < minimum_history:
        return []

    scores = _technical_signal_scores(frame, config)
    snapshots: list[HistoricalFeatureSnapshot] = []
    for index in range(minimum_history - 1, len(frame)):
        as_of = _as_of_datetime(frame.index[index])
        score = float(scores.iloc[index])
        snapshots.append(
            HistoricalFeatureSnapshot(
                as_of=as_of,
                symbol=symbol,
                values={
                    "signal_score": HistoricalMetric(value=score, available_at=as_of, freshness=Freshness.LAST_CLOSE),
                    "price": HistoricalMetric(value=float(frame["close"].iloc[index]), available_at=as_of, freshness=Freshness.LAST_CLOSE),
                },
            )
        )
    return snapshots


def _technical_signal_scores(frame: pd.DataFrame, config: dict[str, Any]) -> pd.Series:
    """Calculate every as-of score in one pass; each value uses only prior rows."""

    weights = config["signal_score"]
    close = frame["close"].astype(float)
    ma_20 = close.rolling(20, min_periods=1).mean().round(4)
    ma_50 = close.rolling(50, min_periods=1).mean().round(4)
    ma_200 = close.rolling(200, min_periods=1).mean().round(4)
    macd_line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    macd_histogram = (macd_line - macd_line.ewm(span=9, adjust=False).mean()).round(4)
    volume_ratio = (frame["volume"].astype(float) / frame["volume"].astype(float).rolling(90, min_periods=1).mean().replace(0, float("nan"))).round(4)
    rsi_14 = rsi(close).round(4)
    score = pd.Series(float(weights["base"]), index=frame.index, dtype=float)
    score += (close > ma_20).astype(float) * float(weights["price_above_ma20"])
    score += (ma_20 > ma_50).astype(float) * float(weights["ma20_above_ma50"])
    score += (ma_50 > ma_200).astype(float) * float(weights["ma50_above_ma200"])
    score += (macd_histogram > 0).astype(float) * float(weights["positive_macd_histogram"])
    score += (volume_ratio >= 1).astype(float) * float(weights["above_average_volume"])
    score -= ((rsi_14 >= 75) | (rsi_14 <= 25)).astype(float) * float(weights["extreme_rsi_penalty"])
    return score.clip(lower=0.0, upper=100.0).round(4)


def technical_signal_score(history: pd.DataFrame, config: dict[str, Any] | None = None) -> float:
    config = config or load_free_price_signal_config()
    weights = config["signal_score"]
    frame = normalize_ohlcv(history)
    if frame.empty:
        return 0.0
    technicals = compute_technicals(frame)
    current_price = float(frame["close"].iloc[-1])
    score = float(weights["base"])
    if technicals.ma_20 is not None and current_price > technicals.ma_20:
        score += float(weights["price_above_ma20"])
    if technicals.ma_20 is not None and technicals.ma_50 is not None and technicals.ma_20 > technicals.ma_50:
        score += float(weights["ma20_above_ma50"])
    if technicals.ma_50 is not None and technicals.ma_200 is not None and technicals.ma_50 > technicals.ma_200:
        score += float(weights["ma50_above_ma200"])
    if technicals.macd.histogram is not None and technicals.macd.histogram > 0:
        score += float(weights["positive_macd_histogram"])
    if technicals.volume_ratio_90d is not None and technicals.volume_ratio_90d >= 1:
        score += float(weights["above_average_volume"])
    if technicals.rsi_14 is not None and (technicals.rsi_14 >= 75 or technicals.rsi_14 <= 25):
        score -= float(weights["extreme_rsi_penalty"])
    return round(max(0.0, min(100.0, score)), 4)


def normalize_ohlcv(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    frame = history.copy()
    frame.columns = [str(column).lower() for column in frame.columns]
    required = ["open", "high", "low", "close", "volume"]
    if any(column not in frame for column in required):
        return pd.DataFrame(columns=required)
    frame = frame[required].apply(pd.to_numeric, errors="coerce").dropna(subset=["open", "high", "low", "close"])
    index = pd.DatetimeIndex(frame.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    frame.index = index.normalize()
    return frame[~frame.index.duplicated(keep="last")].sort_index()


def _as_of_datetime(value: object) -> datetime:
    return pd.Timestamp(value).to_pydatetime().replace(tzinfo=None)
