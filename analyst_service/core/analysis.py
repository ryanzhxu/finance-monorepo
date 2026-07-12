from __future__ import annotations

import logging
from datetime import datetime, timezone

from shared.data_quality import FreshValue, compute_analysis_data_quality, freshness_label
from shared.enums import Freshness
from shared.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    EntryBlock,
    EntryRequest,
    Fundamentals,
    Macro,
    Sentiment,
)

from analyst_service.core.aggregator import aggregate_recommendation, fetch_analysis_context
from analyst_service.core.data_fetcher import fetch_ohlcv
from analyst_service.core.entry_engine import compute_entry
from analyst_service.core.fundamentals import normalize_fundamentals
from analyst_service.core.narrator import synthesize_narrative
from analyst_service.core.persistence import persist_analysis
from analyst_service.core.sentiment import normalize_sentiment
from analyst_service.core.settings import load_service_config
from analyst_service.core.signals import generate_signals
from analyst_service.core.technicals import compute_technicals
from backtesting.store import append_recommendation


logger = logging.getLogger(__name__)


def _freshness_value(item: FreshValue[object]) -> Freshness | str:
    label = freshness_label(item)
    return item.freshness if label == item.freshness.value else label


def _current_price(request_price: float | None, ohlcv: FreshValue[object]) -> float | None:
    if request_price is not None:
        return float(request_price)
    frame = ohlcv.value
    if hasattr(frame, "empty") and not frame.empty and "close" in frame:
        return float(frame["close"].iloc[-1])
    return None


async def analyze_symbol(request: AnalyzeRequest) -> AnalyzeResponse:
    config = load_service_config()
    ohlcv = fetch_ohlcv(request.symbol, request.current_price)
    fundamentals_fresh, sentiment_fresh, macro_fresh = fetch_analysis_context(request.symbol, ohlcv.value)
    company_name: str | None = fundamentals_fresh.value.company_name if fundamentals_fresh.value else None

    current_price = _current_price(request.current_price, ohlcv)
    technicals = compute_technicals(ohlcv.value, support_window=int(config["entry_rules"]["support_window"]))
    fundamentals = normalize_fundamentals(fundamentals_fresh.value)
    sentiment = normalize_sentiment(sentiment_fresh.value)
    macro = macro_fresh.value or Macro()

    freshness = {
        "price": _freshness_value(ohlcv),
        "technicals": _freshness_value(ohlcv),
        "fundamentals": _freshness_value(fundamentals_fresh),
        "ratings": _freshness_value(fundamentals_fresh),
        "flows": _freshness_value(sentiment_fresh) if sentiment.institutional_net_shares_last_13f is not None else Freshness.MISSING,
        "sentiment": _freshness_value(sentiment_fresh),
        "macro": _freshness_value(macro_fresh),
    }
    data_quality_score = compute_analysis_data_quality(technicals, fundamentals, sentiment, macro)
    signals = generate_signals(technicals, fundamentals, sentiment, macro, config["weights"], config["thresholds"])
    provisional = aggregate_recommendation(
        signals,
        request.horizon,
        config["thresholds"],
        data_quality_score,
        None,
        freshness,
        macro=macro,
        apply_overrides=False,
    )
    entry: EntryBlock | None = None
    if request.include_entry and current_price is not None:
        entry = compute_entry(
            current_price=current_price,
            technicals=technicals,
            fundamentals=fundamentals,
            direction=provisional.direction,
            horizon=request.horizon,
            rules=config["entry_rules"],
            risk_flags=provisional.risk_flags,
            regime=macro.market_regime.value if hasattr(macro.market_regime, "value") else macro.market_regime,
        )
    recommendation = aggregate_recommendation(
        signals,
        request.horizon,
        config["thresholds"],
        data_quality_score,
        entry,
        freshness,
        macro=macro,
        apply_overrides=True,
    )
    response = AnalyzeResponse(
        symbol=request.symbol,
        company_name=company_name,
        generated_at=datetime.now(timezone.utc),
        data_freshness=freshness,
        data_quality_score=data_quality_score,
        confidence=recommendation.confidence,
        technicals=technicals,
        fundamentals=fundamentals,
        sentiment=sentiment,
        macro=macro,
        signals=signals,
        entry=entry,
        recommendation=recommendation,
        narrative=None,
    )
    if request.include_narrative:
        response.narrative = await synthesize_narrative(response)
    _persist_analysis(response)
    return response


def _persist_analysis(response: AnalyzeResponse) -> None:
    try:
        append_recommendation(response)
    except (OSError, TypeError, ValueError) as exc:
        # Recommendation logging must not turn a completed analysis into an API failure.
        logger.warning("Could not append recommendation for %s: %s", response.symbol, exc)
    persist_analysis(response)


async def entry_for_symbol(request: EntryRequest) -> EntryBlock:
    analysis = await analyze_symbol(
        AnalyzeRequest(
            symbol=request.symbol,
            asset_type=request.asset_type,
            horizon=request.horizon,
            current_price=request.current_price,
            include_narrative=False,
            include_entry=True,
        )
    )
    if analysis.entry is None:
        raise ValueError("entry block was not generated")
    return analysis.entry
