from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from shared.data_quality import compute_data_quality
from shared.enums import Freshness, MarketRegime
from shared.models import RegimeResponse

SECTOR_ETFS = ["XLK", "XLE", "XLF", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE", "XLC"]


def current_regime() -> RegimeResponse:
    now = datetime.now(timezone.utc)
    try:
        import yfinance as yf

        spy = yf.download("SPY", period="1y", interval="1d", progress=False, auto_adjust=False, threads=False)
        qqq = yf.download("QQQ", period="1y", interval="1d", progress=False, auto_adjust=False, threads=False)
        vix = yf.download("^VIX", period="3mo", interval="1d", progress=False, auto_adjust=False, threads=False)
        spy_close = _close(spy)
        qqq_close = _close(qqq)
        vix_close = _close(vix)
        spy_vs_ma = _distance_from_ma200(spy_close)
        qqq_vs_ma = _distance_from_ma200(qqq_close)
        vix_level = float(vix_close.iloc[-1]) if not vix_close.empty else None
        regime = _classify_regime(spy_vs_ma, qqq_vs_ma, vix_level)
        leaders, laggards = _sector_rotation(yf)
        freshness = {"price": Freshness.DELAYED.value, "sector_rotation": Freshness.DELAYED.value}
        quality = compute_data_quality(freshness)
        return RegimeResponse(
            market_regime=regime,
            generated_at=now,
            data_freshness=freshness,
            data_quality_score=quality,
            confidence=round(quality / 100, 4),
            sector_leaders=leaders,
            sector_laggards=laggards,
            reason=f"SPY vs 200D MA {spy_vs_ma:.1f}%, QQQ vs 200D MA {qqq_vs_ma:.1f}%, VIX {vix_level:.1f}." if vix_level is not None else "Market regime computed from SPY/QQQ trend; VIX unavailable.",
        )
    except Exception:
        freshness = {"price": Freshness.MISSING.value, "sector_rotation": Freshness.MISSING.value}
        quality = compute_data_quality(freshness)
        return RegimeResponse(
            market_regime=MarketRegime.NEUTRAL,
            generated_at=now,
            data_freshness=freshness,
            data_quality_score=quality,
            confidence=round(quality / 100, 4),
            sector_leaders=[],
            sector_laggards=[],
            reason="Market regime unavailable; defaulting to neutral.",
        )


def _classify_regime(spy_vs_ma: float, qqq_vs_ma: float, vix_level: float | None) -> MarketRegime:
    if vix_level is not None and vix_level > 25 and spy_vs_ma < 0:
        return MarketRegime.RISK_OFF
    if spy_vs_ma < -3 and qqq_vs_ma < -3:
        return MarketRegime.RISK_OFF
    if spy_vs_ma > 3 and qqq_vs_ma > 3 and (vix_level is None or vix_level < 22):
        return MarketRegime.RISK_ON
    return MarketRegime.NEUTRAL


def _sector_rotation(yf_module: object) -> tuple[list[str], list[str]]:
    returns: list[tuple[str, float]] = []
    for ticker in SECTOR_ETFS:
        try:
            history = yf_module.download(ticker, period="3mo", interval="1d", progress=False, auto_adjust=True, threads=False)
            close = _close(history)
            if len(close) >= 22:
                one_month = (float(close.iloc[-1]) / float(close.iloc[-22]) - 1) * 100
                three_month = (float(close.iloc[-1]) / float(close.iloc[0]) - 1) * 100
                returns.append((ticker, (one_month * 0.6) + (three_month * 0.4)))
        except Exception:
            continue
    ranked = sorted(returns, key=lambda item: item[1], reverse=True)
    return [ticker for ticker, _ in ranked[:3]], [ticker for ticker, _ in ranked[-3:]]


def _close(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=float)
    if isinstance(frame.columns, pd.MultiIndex):
        frame = frame.droplevel(-1, axis=1)
    column = "Close" if "Close" in frame else "close"
    return frame[column].dropna().astype(float)


def _distance_from_ma200(close: pd.Series) -> float:
    if close.empty:
        return 0.0
    ma200 = float(close.rolling(200, min_periods=1).mean().iloc[-1])
    if ma200 == 0:
        return 0.0
    return ((float(close.iloc[-1]) - ma200) / ma200) * 100
