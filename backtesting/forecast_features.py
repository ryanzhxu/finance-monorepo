from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from analyst_service.core.technicals import rsi
from backtesting.forecast import ForecastObservation
from backtesting.free_price_dataset import normalize_ohlcv
from shared.config_loader import load_yaml_config

FEATURE_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "forecast_features.yaml"
CONTINUOUS_FEATURE_SCHEMA = "continuous_regime_v1"


@lru_cache
def load_forecast_feature_config() -> dict[str, Any]:
    return load_yaml_config(
        FEATURE_CONFIG_PATH,
        {
            "schema_version",
            "benchmark_symbols",
            "moving_average_sessions",
            "return_sessions",
            "volatility_sessions",
            "volume_ratio_sessions",
            "drawdown_sessions",
            "market_regime",
            "logistic_regression",
            "probability_shrinkage",
            "feature_selection",
            "target_calibration",
        },
    )


def classify_historical_regime(
    spy_ma200_gap_percent: float,
    qqq_ma200_gap_percent: float,
    vix_level: float | None,
    *,
    config: dict[str, Any] | None = None,
) -> str:
    """Match the live SPY/QQQ/VIX threshold classifier without live requests."""

    thresholds = (config or load_forecast_feature_config())["market_regime"]
    if vix_level is not None and vix_level > float(thresholds["risk_off_vix_level"]) and spy_ma200_gap_percent < 0:
        return "risk_off"
    if (
        spy_ma200_gap_percent < float(thresholds["risk_off_ma200_gap_percent"])
        and qqq_ma200_gap_percent < float(thresholds["risk_off_ma200_gap_percent"])
    ):
        return "risk_off"
    if (
        spy_ma200_gap_percent > float(thresholds["risk_on_ma200_gap_percent"])
        and qqq_ma200_gap_percent > float(thresholds["risk_on_ma200_gap_percent"])
        and (vix_level is None or vix_level < float(thresholds["risk_on_vix_level"]))
    ):
        return "risk_on"
    return "neutral"


class MarketFeatureProvider:
    """Historical benchmark features indexed by their observable market close."""

    def __init__(self, benchmark_histories: dict[str, pd.DataFrame], *, config: dict[str, Any] | None = None) -> None:
        self.config = config or load_forecast_feature_config()
        symbols = self.config["benchmark_symbols"]
        required = {"spy": str(symbols["spy"]), "qqq": str(symbols["qqq"]), "vix": str(symbols["vix"])}
        normalized = {name: normalize_ohlcv(benchmark_histories.get(symbol, pd.DataFrame())) for name, symbol in required.items()}
        self._features = _market_feature_frame(normalized["spy"], normalized["qqq"], normalized["vix"], self.config)

    def feature_values_for(self, as_of: date) -> tuple[dict[str, float], str] | None:
        timestamp = pd.Timestamp(as_of)
        if timestamp not in self._features.index:
            return None
        row = self._features.loc[timestamp]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[-1]
        values = {str(key): float(value) for key, value in row.items() if key != "market_regime"}
        if not values or any(not np.isfinite(value) for value in values.values()):
            return None
        regime = str(row["market_regime"])
        return values, regime


def attach_continuous_features(
    observations: Iterable[ForecastObservation],
    history: pd.DataFrame,
    market_features: MarketFeatureProvider,
) -> tuple[list[ForecastObservation], dict[str, int]]:
    """Attach an all-finite as-of feature payload, skipping incomplete histories."""

    if market_features._features.empty:
        return [], {"missing_continuous_features": sum(1 for _ in observations)}
    stock_features = _stock_feature_frame(normalize_ohlcv(history), market_features)
    featured: list[ForecastObservation] = []
    skipped: dict[str, int] = {}
    for observation in observations:
        timestamp = pd.Timestamp(observation.as_of)
        if timestamp not in stock_features.index:
            _increment(skipped, "missing_continuous_features")
            continue
        row = stock_features.loc[timestamp]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[-1]
        values = {str(key): float(value) for key, value in row.items() if key != "market_regime"}
        if not values or any(not np.isfinite(value) for value in values.values()):
            _increment(skipped, "invalid_continuous_features")
            continue
        regime = str(row["market_regime"])
        if regime not in {"risk_on", "neutral", "risk_off"}:
            _increment(skipped, "invalid_market_regime")
            continue
        featured.append(
            observation.model_copy(
                update={
                    "feature_schema_version": CONTINUOUS_FEATURE_SCHEMA,
                    "feature_values": values,
                    "market_regime": regime,
                }
            )
        )
    return featured, skipped


def _stock_feature_frame(history: pd.DataFrame, market_features: MarketFeatureProvider) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame()
    config = market_features.config
    close = history["close"].astype(float)
    volume = history["volume"].astype(float)
    frame = pd.DataFrame(index=history.index)
    for sessions in config["return_sessions"]:
        frame[f"stock_return_{sessions}d"] = close.pct_change(int(sessions))
    for sessions in config["moving_average_sessions"]:
        average = close.rolling(int(sessions), min_periods=int(sessions)).mean()
        frame[f"stock_ma{sessions}_gap"] = close.div(average).sub(1)
    frame["stock_rsi_14"] = rsi(close)
    macd_line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    frame["stock_macd_histogram"] = macd_line - macd_line.ewm(span=9, adjust=False).mean()
    for sessions in config["volatility_sessions"]:
        frame[f"stock_volatility_{sessions}d"] = close.pct_change().rolling(int(sessions), min_periods=int(sessions)).std(ddof=0)
    volume_window = int(config["volume_ratio_sessions"])
    frame[f"stock_volume_ratio_{volume_window}d"] = volume.div(volume.rolling(volume_window, min_periods=volume_window).mean().replace(0, np.nan))
    drawdown_window = int(config["drawdown_sessions"])
    frame[f"stock_drawdown_{drawdown_window}d"] = close.div(close.rolling(drawdown_window, min_periods=drawdown_window).max()).sub(1)

    market = market_features._features.reindex(frame.index)
    frame["relative_strength_63d"] = frame["stock_return_63d"] - market["spy_return_63d"]
    for key in market.columns:
        frame[key] = market[key]
    return frame


def _market_feature_frame(spy: pd.DataFrame, qqq: pd.DataFrame, vix: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    if spy.empty or qqq.empty or vix.empty:
        return pd.DataFrame()
    index = spy.index.intersection(qqq.index).intersection(vix.index)
    if index.empty:
        return pd.DataFrame()
    spy_close = spy.reindex(index)["close"].astype(float)
    qqq_close = qqq.reindex(index)["close"].astype(float)
    vix_close = vix.reindex(index)["close"].astype(float)
    frame = pd.DataFrame(index=index)
    frame["spy_return_21d"] = spy_close.pct_change(21)
    frame["spy_return_63d"] = spy_close.pct_change(63)
    spy_ma200 = spy_close.rolling(200, min_periods=200).mean()
    qqq_ma200 = qqq_close.rolling(200, min_periods=200).mean()
    frame["spy_ma200_gap"] = spy_close.div(spy_ma200).sub(1)
    frame["spy_volatility_21d"] = spy_close.pct_change().rolling(21, min_periods=21).std(ddof=0)
    frame["qqq_ma200_gap"] = qqq_close.div(qqq_ma200).sub(1)
    frame["vix_level"] = vix_close
    frame["vix_change_21d"] = vix_close.pct_change(21)
    frame["market_regime"] = [
        classify_historical_regime(
            float(spy_gap * 100),
            float(qqq_gap * 100),
            float(vix_value),
            config=config,
        )
        if np.isfinite(spy_gap) and np.isfinite(qqq_gap) and np.isfinite(vix_value)
        else ""
        for spy_gap, qqq_gap, vix_value in zip(frame["spy_ma200_gap"], frame["qqq_ma200_gap"], frame["vix_level"], strict=True)
    ]
    for regime in ("risk_on", "neutral", "risk_off"):
        frame[f"regime_{regime}"] = (frame["market_regime"] == regime).astype(float)
    return frame


def _increment(values: dict[str, int], key: str) -> None:
    values[key] = values.get(key, 0) + 1
