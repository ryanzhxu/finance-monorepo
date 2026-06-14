from __future__ import annotations

import json
import os
from pathlib import Path

from shared.models import (
    AnalyzeResponse,
    RecommendationLogRecord,
    ScreenLogRecord,
    ScreenResponse,
    TrendingLogRecord,
    TrendingScreenResponse,
)


def default_store_path() -> Path:
    configured = os.getenv("BACKTESTING_STORE_PATH")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent / "recommendations.jsonl"


def append_recommendation(response: AnalyzeResponse, path: Path | None = None) -> None:
    destination = path or default_store_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    record = RecommendationLogRecord(
        symbol=response.symbol,
        timestamp=response.generated_at,
        direction=response.recommendation.direction,
        confidence=response.recommendation.confidence,
        entry=response.entry,
        scores={"weighted_score": response.recommendation.weighted_score, "signal_vote": response.recommendation.signal_vote},
        risk_flags=response.recommendation.risk_flags,
        regime=response.macro.market_regime,
        data_quality_score=response.data_quality_score,
    )
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.model_dump(mode="json"), sort_keys=True) + "\n")


def append_screen_results(response: ScreenResponse, path: Path | None = None) -> None:
    destination = path or default_store_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as handle:
        for item in response.results:
            record = ScreenLogRecord(
                screen_type=response.screen_type,
                timestamp=response.generated_at,
                symbol=item.symbol,
                rank=item.rank,
                opportunity_score=item.opportunity_score,
                recommendation=item.recommendation,
                confidence=item.confidence,
                entry_assessment=item.entry_assessment,
                ideal_buy_zone=item.ideal_buy_zone,
                scores=item.score_breakdown,
                risk_flags=item.risk_flags,
                regime=response.market_regime,
                data_quality_score=item.data_quality_score,
            )
            handle.write(json.dumps(record.model_dump(mode="json"), sort_keys=True) + "\n")


def append_trending_results(response: TrendingScreenResponse, path: Path | None = None) -> None:
    destination = path or default_store_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as handle:
        for item in response.results:
            record = TrendingLogRecord(
                screen_type=response.screen_type,
                timestamp=response.generated_at,
                symbol=item.symbol,
                confidence=item.confidence,
                trend_quality=item.trend_quality,
                retail_fomo_risk=item.retail_fomo_risk,
                sentiment_score=item.sentiment_score,
                acceleration=item.acceleration,
                buyability=item.buyability,
                scores=item.score_breakdown,
                risk_flags=item.risk_flags,
                regime=response.market_regime,
                data_quality_score=item.data_quality_score,
            )
            handle.write(json.dumps(record.model_dump(mode="json"), sort_keys=True) + "\n")
