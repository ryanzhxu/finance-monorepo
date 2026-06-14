from __future__ import annotations

import asyncio

from shared.enums import Freshness, TrendQuality

from screener_service.core.fundamentals_bulk import MetricValue, ScreenerMetrics
from screener_service.core.trending import _acceleration, _classify_trend, _fetch_reddit_events, _growth_pct


def test_growth_uses_symbol_own_baseline() -> None:
    assert _growth_pct(20.0, 10.0) == 100.0
    assert _growth_pct(5.0, 5.0) == 0.0


def test_acceleration_favors_recent_spike_over_prior_days() -> None:
    assert _acceleration(12, 20, 2.0) == 5.0


def test_classification_hits_news_driven_first_match() -> None:
    metrics = _metrics(price=100, fifty_day_average=95, short_percent_float=5, avg_volume=1_000_000, market_cap=10_000_000_000)

    result = _classify_trend(
        catalyst="analyst_upgrade",
        sentiment_score=0.4,
        pro_share=0.4,
        mentions_24h=18,
        acceleration=1.5,
        fundamental_support=80.0,
        retail_fomo=20.0,
        metrics=metrics,
        thresholds=_thresholds(),
    )

    assert result == TrendQuality.NEWS_DRIVEN


def test_classification_hits_pump_risk_branch() -> None:
    metrics = _metrics(price=120, fifty_day_average=90, short_percent_float=25, avg_volume=1_000, market_cap=2_000_000_000)

    result = _classify_trend(
        catalyst="none",
        sentiment_score=0.8,
        pro_share=0.0,
        mentions_24h=50,
        acceleration=2.0,
        fundamental_support=30.0,
        retail_fomo=85.0,
        metrics=metrics,
        thresholds=_thresholds(),
    )

    assert result == TrendQuality.MEME_FOMO


def test_reddit_source_missing_credentials_marks_missing(monkeypatch) -> None:
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)

    source, events, freshness, note = asyncio.run(_fetch_reddit_events(["NVDA"], {"subreddits": ["stocks"], "limit": 10}))

    assert source == "reddit"
    assert events == []
    assert freshness == Freshness.MISSING
    assert "credentials missing" in str(note).lower()


def _metrics(**values: float | str) -> ScreenerMetrics:
    return ScreenerMetrics(
        symbol="AAA",
        values={key: MetricValue(value, Freshness.DELAYED, None) for key, value in values.items()},
    )


def _thresholds() -> dict[str, float]:
    return {
        "news_driven_min_sentiment": 0.15,
        "news_driven_min_institutional_share": 0.20,
        "earnings_window_days": 7,
        "early_accumulation_min_acceleration": 1.20,
        "early_accumulation_max_24h_mentions": 25,
        "high_quality_min_sentiment": 0.20,
        "meme_growth_5d_pct": 250.0,
        "meme_sentiment_score": 0.50,
        "pump_short_interest_pct": 18.0,
        "overextended_acceleration": 1.20,
        "strong_fundamental_score": 65.0,
    }
