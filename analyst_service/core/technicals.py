from __future__ import annotations

import numpy as np
import pandas as pd

from shared.models import MacdBlock, Technicals


def _last(value: pd.Series) -> float | None:
    clean = value.dropna()
    if clean.empty:
        return None
    return round(float(clean.iloc[-1]), 4)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    result = result.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    result = result.mask((avg_gain == 0) & (avg_loss > 0), 0.0)
    return result.fillna(50.0)


def macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema_12 - ema_26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = frame["high"] - frame["low"]
    high_close = (frame["high"] - frame["close"].shift()).abs()
    low_close = (frame["low"] - frame["close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.ewm(alpha=1 / period, min_periods=period, adjust=False).mean().fillna(true_range)


def bollinger_bands(close: pd.Series, period: int = 20, stddev: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(period, min_periods=1).mean()
    std = close.rolling(period, min_periods=1).std(ddof=0).fillna(0)
    return mid + (stddev * std), mid, mid - (stddev * std)


def swing_levels(series: pd.Series, window: int, current_atr: float | None, high: bool) -> list[float]:
    if series.empty:
        return []
    rolling = series.rolling(window, center=True, min_periods=max(3, window // 2))
    candidates = series[series.eq(rolling.max() if high else rolling.min())].dropna()
    if candidates.empty:
        fallback = series.nlargest(5) if high else series.nsmallest(5)
        candidates = fallback
    current = float(series.iloc[-1])
    levels = sorted({round(float(value), 2) for value in candidates}, reverse=not high)
    relevant = [level for level in levels if (level >= current if high else level <= current)]
    if not relevant:
        relevant = levels
    clustered: list[float] = []
    merge_distance = max(float(current_atr or 0), current * 0.005)
    for level in relevant:
        if not clustered or all(abs(level - existing) > merge_distance for existing in clustered):
            clustered.append(level)
        if len(clustered) >= 3:
            break
    return clustered


def compute_technicals(frame: pd.DataFrame, support_window: int = 20) -> Technicals:
    if frame.empty:
        return Technicals(macd=MacdBlock())
    data = frame.copy()
    data.columns = [column.lower() for column in data.columns]
    close = data["close"].astype(float)
    current_price = float(close.iloc[-1])
    ma_20 = close.rolling(20, min_periods=1).mean()
    ma_50 = close.rolling(50, min_periods=1).mean()
    ma_200 = close.rolling(200, min_periods=1).mean()
    macd_line, signal_line, histogram = macd(close)
    atr_14 = atr(data, 14)
    bb_upper, bb_mid, bb_lower = bollinger_bands(close)
    weekly_close = close.resample("W-FRI").last() if isinstance(close.index, pd.DatetimeIndex) else close
    volume_avg = data["volume"].rolling(90, min_periods=1).mean().replace(0, np.nan)
    volume_ratio = data["volume"] / volume_avg
    gap = ((data["open"] - data["close"].shift()) / data["close"].shift()) * 100
    support_levels = swing_levels(data["low"], support_window, _last(atr_14), high=False)
    resistance_levels = swing_levels(data["high"], support_window, _last(atr_14), high=True)

    def dist(ma: pd.Series) -> float | None:
        value = _last(ma)
        if value in (None, 0):
            return None
        return round(((current_price - value) / value) * 100, 4)

    breakout_state = "none"
    if resistance_levels and current_price > resistance_levels[0]:
        breakout_state = "breakout"
    elif support_levels and current_price < support_levels[0]:
        breakout_state = "breakdown"

    return Technicals(
        rsi_14=_last(rsi(close)),
        rsi_weekly=_last(rsi(weekly_close)),
        macd=MacdBlock(macd_line=_last(macd_line), signal_line=_last(signal_line), histogram=_last(histogram)),
        ma_20=_last(ma_20),
        ma_50=_last(ma_50),
        ma_200=_last(ma_200),
        support_levels=support_levels,
        resistance_levels=resistance_levels,
        atr_14=_last(atr_14),
        bb_upper=_last(bb_upper),
        bb_lower=_last(bb_lower),
        bb_mid=_last(bb_mid),
        volume_ratio_90d=_last(volume_ratio.fillna(0)),
        dist_from_ma20_pct=dist(ma_20),
        dist_from_ma50_pct=dist(ma_50),
        dist_from_ma200_pct=dist(ma_200),
        recent_gap_pct=_last(gap.fillna(0)),
        recent_earnings_gap_pct=None,
        breakout_state=breakout_state,
    )
