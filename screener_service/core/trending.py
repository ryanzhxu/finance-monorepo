from __future__ import annotations

import asyncio
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import httpx

from shared.data_quality import compute_data_quality
from shared.enums import Freshness, MarketRegime, ScreenType, TrendQuality, TrendSource
from shared.models import TrendingResultItem, TrendingScreenRequest

from screener_service.core.fundamentals_bulk import ScreenerMetrics

HISTORY_PATH = Path(__file__).resolve().parents[1] / "cache" / "trending_history.jsonl"
CATALYST_KEYWORDS = {
    "earnings": ["earnings", "eps", "guidance", "beat", "miss"],
    "analyst_upgrade": ["upgrade", "downgrade", "price target", "coverage"],
    "partnership": ["partnership", "deal", "agreement", "collaboration"],
    "sec_investigation": ["sec", "investigation", "probe"],
    "recall": ["recall"],
    "macro": ["fed", "fomc", "rates", "tariff", "inflation"],
    "approval": ["approval", "fda"],
}
FINBERT = None
FINBERT_FAILED = False


@dataclass
class TrendEvent:
    symbol: str
    source: str
    occurred_at: str
    text: str
    url: str | None
    sentiment_score: float
    sentiment_label: str
    catalyst: str
    professional_source: bool

    def as_datetime(self) -> datetime:
        return datetime.fromisoformat(self.occurred_at)


async def build_trending_results(
    request: TrendingScreenRequest,
    metrics_by_symbol: dict[str, ScreenerMetrics],
    market_regime: MarketRegime,
    trend_rules: dict[str, Any],
) -> tuple[list[TrendingResultItem], dict[str, TrendingResultItem], list[str]]:
    symbols = sorted(metrics_by_symbol)
    if not symbols:
        return [], {}, []
    source_events, source_freshness, notes = await _collect_source_events(symbols, request.sources, trend_rules)
    baseline_days = int(trend_rules["metrics"]["baseline_days"])
    current_events = _score_events(source_events, trend_rules)
    history = _load_history(baseline_days)
    merged_history = _merge_history(history, current_events, baseline_days)
    _write_history(merged_history)

    results: list[TrendingResultItem] = []
    result_map: dict[str, TrendingResultItem] = {}
    for symbol in symbols:
        result = _build_symbol_result(symbol, merged_history, current_events, metrics_by_symbol[symbol], source_freshness, market_regime, trend_rules)
        if result is None:
            continue
        results.append(result)
        result_map[symbol] = result
    results.sort(key=lambda item: item.score_breakdown["trend_score"], reverse=True)
    return results[: request.limit], result_map, notes


async def _collect_source_events(
    symbols: list[str],
    sources: list[TrendSource],
    trend_rules: dict[str, Any],
) -> tuple[list[TrendEvent], dict[str, Freshness], list[str]]:
    tasks = []
    for source in sources:
        if source == TrendSource.REDDIT:
            tasks.append(_fetch_reddit_events(symbols, trend_rules["sources"]["reddit"]))
        elif source == TrendSource.STOCKTWITS:
            tasks.append(_fetch_stocktwits_events(symbols, trend_rules["sources"]["stocktwits"]))
        elif source == TrendSource.NEWS:
            tasks.append(_fetch_news_events(symbols, trend_rules["sources"]["news"]))
        elif source == TrendSource.YAHOO_TRENDING:
            tasks.append(_fetch_yahoo_trending_events(symbols, trend_rules["sources"]["yahoo_trending"]))
    gathered = await asyncio.gather(*tasks)
    events: list[TrendEvent] = []
    freshness: dict[str, Freshness] = {}
    notes: list[str] = []
    for source_name, source_events, source_freshness, note in gathered:
        events.extend(source_events)
        freshness[source_name] = source_freshness
        if note:
            notes.append(note)
    return events, freshness, notes


async def _fetch_reddit_events(symbols: list[str], config: dict[str, Any]) -> tuple[str, list[TrendEvent], Freshness, str | None]:
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    if not (client_id and client_secret):
        return TrendSource.REDDIT.value, [], Freshness.MISSING, "Reddit credentials missing; skipped reddit source."
    symbol_set = set(symbols)
    subreddits = config["subreddits"]
    limit = int(config["limit"])
    events: list[TrendEvent] = []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token_response = await client.post(
                "https://www.reddit.com/api/v1/access_token",
                auth=(client_id, client_secret),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": "finance-monorepo/phase3"},
            )
            token_response.raise_for_status()
            token = token_response.json()["access_token"]
            headers = {"Authorization": f"bearer {token}", "User-Agent": "finance-monorepo/phase3"}
            for subreddit in subreddits:
                response = await client.get(
                    f"https://oauth.reddit.com/r/{subreddit}/new",
                    params={"limit": limit},
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
                for child in payload.get("data", {}).get("children", []):
                    data = child.get("data", {})
                    text = f"{data.get('title', '')} {data.get('selftext', '')}".strip()
                    occurred_at = datetime.fromtimestamp(float(data.get("created_utc", 0)), tz=timezone.utc)
                    matched = _extract_symbols(text, symbol_set)
                    for symbol in matched:
                        events.append(
                            TrendEvent(
                                symbol=symbol,
                                source=TrendSource.REDDIT.value,
                                occurred_at=occurred_at.isoformat(),
                                text=text,
                                url=f"https://reddit.com{data.get('permalink', '')}",
                                sentiment_score=0.0,
                                sentiment_label="neutral",
                                catalyst="none",
                                professional_source=False,
                            )
                        )
        return TrendSource.REDDIT.value, events, Freshness.DELAYED, None
    except Exception:
        return TrendSource.REDDIT.value, [], Freshness.MISSING, "Reddit source unavailable; skipped reddit source."


async def _fetch_stocktwits_events(symbols: list[str], config: dict[str, Any]) -> tuple[str, list[TrendEvent], Freshness, str | None]:
    api_key = os.getenv("STOCKTWITS_API_KEY")
    if not api_key:
        return TrendSource.STOCKTWITS.value, [], Freshness.MISSING, "StockTwits credentials missing; skipped stocktwits source."
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                "https://api.stocktwits.com/api/2/trending/symbols.json",
                params={"access_token": api_key},
            )
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return TrendSource.STOCKTWITS.value, [], Freshness.MISSING, "StockTwits source unavailable; skipped stocktwits source."

    now = datetime.now(timezone.utc)
    symbol_set = set(symbols)
    events: list[TrendEvent] = []
    for symbol in payload.get("symbols", [])[: int(config["limit"])]:
        ticker = str(symbol.get("symbol", "")).upper()
        if ticker in symbol_set:
            events.append(
                TrendEvent(
                    symbol=ticker,
                    source=TrendSource.STOCKTWITS.value,
                    occurred_at=now.isoformat(),
                    text=f"StockTwits trending symbol {ticker}",
                    url=None,
                    sentiment_score=0.0,
                    sentiment_label="neutral",
                    catalyst="none",
                    professional_source=False,
                )
            )
    return TrendSource.STOCKTWITS.value, events, Freshness.DELAYED, None


async def _fetch_news_events(symbols: list[str], config: dict[str, Any]) -> tuple[str, list[TrendEvent], Freshness, str | None]:
    symbol_set = set(symbols)
    feeds = config["feeds"]
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)
    events: list[TrendEvent] = []
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            responses = await asyncio.gather(*(client.get(feed) for feed in feeds), return_exceptions=True)
        for response in responses:
            if isinstance(response, Exception):
                continue
            for item in _parse_rss_items(response.text):
                occurred_at = item["published_at"]
                if occurred_at < cutoff:
                    continue
                matched = _extract_symbols(item["text"], symbol_set)
                for symbol in matched:
                    events.append(
                        TrendEvent(
                            symbol=symbol,
                            source=TrendSource.NEWS.value,
                            occurred_at=occurred_at.isoformat(),
                            text=item["text"],
                            url=item["url"],
                            sentiment_score=0.0,
                            sentiment_label="neutral",
                            catalyst="none",
                            professional_source=True,
                            )
                    )
        if not events and len(symbols) <= 25:
            events.extend(_fetch_symbol_news_events(symbols, cutoff))
        freshness = Freshness.DELAYED if events else Freshness.MISSING
        note = None if events else "News feeds returned no matching articles for the requested symbols."
        return TrendSource.NEWS.value, events, freshness, note
    except Exception:
        return TrendSource.NEWS.value, [], Freshness.MISSING, "News source unavailable; skipped RSS source."


def _fetch_symbol_news_events(symbols: list[str], cutoff: datetime) -> list[TrendEvent]:
    try:
        import yfinance as yf
    except Exception:
        return []

    events: list[TrendEvent] = []
    for symbol in symbols:
        try:
            for item in (yf.Ticker(symbol).news or [])[:25]:
                content = item.get("content", {})
                pub_date = content.get("pubDate")
                if pub_date:
                    occurred_at = datetime.fromisoformat(str(pub_date).replace("Z", "+00:00"))
                else:
                    occurred_at = datetime.fromtimestamp(float(item.get("providerPublishTime", 0)), tz=timezone.utc)
                if occurred_at < cutoff:
                    continue
                title = str(content.get("title", item.get("title", ""))).strip()
                summary = str(content.get("summary", content.get("description", item.get("summary", "")))).strip()
                if not title and not summary:
                    continue
                click_through = content.get("clickThroughUrl", {}) or {}
                canonical = content.get("canonicalUrl", {}) or {}
                link = click_through.get("url") or canonical.get("url") or item.get("link")
                events.append(
                    TrendEvent(
                        symbol=symbol,
                        source=TrendSource.NEWS.value,
                        occurred_at=occurred_at.isoformat(),
                        text=f"{title} {summary}".strip(),
                        url=str(link) if link else None,
                        sentiment_score=0.0,
                        sentiment_label="neutral",
                        catalyst="none",
                        professional_source=True,
                    )
                )
        except Exception:
            continue
    return events


async def _fetch_yahoo_trending_events(symbols: list[str], config: dict[str, Any]) -> tuple[str, list[TrendEvent], Freshness, str | None]:
    symbol_set = set(symbols)
    now = datetime.now(timezone.utc)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get("https://query1.finance.yahoo.com/v1/finance/trending/US")
            response.raise_for_status()
            payload = response.json()
        quotes = payload.get("finance", {}).get("result", [{}])[0].get("quotes", [])
        events: list[TrendEvent] = []
        weight = max(1, int(config["count_weight"]))
        for quote in quotes:
            symbol = str(quote.get("symbol", "")).upper()
            if symbol in symbol_set:
                for _ in range(weight):
                    events.append(
                        TrendEvent(
                            symbol=symbol,
                            source=TrendSource.YAHOO_TRENDING.value,
                            occurred_at=now.isoformat(),
                            text=f"Yahoo trending symbol {symbol}",
                            url=None,
                            sentiment_score=0.0,
                            sentiment_label="neutral",
                            catalyst="none",
                            professional_source=True,
                        )
                    )
        freshness = Freshness.DELAYED if events else Freshness.MISSING
        note = None if events else "Yahoo trending returned no matching symbols for the requested universe."
        return TrendSource.YAHOO_TRENDING.value, events, freshness, note
    except Exception:
        return TrendSource.YAHOO_TRENDING.value, [], Freshness.MISSING, "Yahoo trending source unavailable; skipped source."


def _parse_rss_items(xml_text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return items
    for item in root.findall(".//item"):
        title = _text(item.find("title"))
        description = _text(item.find("description"))
        link = _text(item.find("link"))
        pub_date = _text(item.find("pubDate"))
        published_at = _parse_pub_date(pub_date)
        items.append({"text": f"{title} {description}".strip(), "url": link, "published_at": published_at})
    return items


def _parse_pub_date(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = parsedate_to_datetime(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _score_events(events: list[TrendEvent], trend_rules: dict[str, Any]) -> list[TrendEvent]:
    scored: list[TrendEvent] = []
    for event in events:
        score, label = _sentiment_for_text(event.text, trend_rules["sentiment"])
        catalyst = _detect_catalyst(event.text)
        scored.append(
            TrendEvent(
                symbol=event.symbol,
                source=event.source,
                occurred_at=event.occurred_at,
                text=event.text,
                url=event.url,
                sentiment_score=score,
                sentiment_label=label,
                catalyst=catalyst,
                professional_source=event.professional_source,
            )
        )
    return scored


def _load_history(baseline_days: int) -> list[TrendEvent]:
    if not HISTORY_PATH.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=baseline_days + 5)
    events: list[TrendEvent] = []
    for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            event = TrendEvent(**data)
            if event.as_datetime() >= cutoff:
                events.append(event)
        except Exception:
            continue
    return events


def _merge_history(existing: list[TrendEvent], current: list[TrendEvent], baseline_days: int) -> list[TrendEvent]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=baseline_days + 5)
    merged = { _event_key(event): event for event in existing if event.as_datetime() >= cutoff }
    for event in current:
        merged[_event_key(event)] = event
    return sorted(merged.values(), key=lambda item: item.occurred_at)


def _write_history(events: list[TrendEvent]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(asdict(event), sort_keys=True) + "\n")


def _build_symbol_result(
    symbol: str,
    history: list[TrendEvent],
    current_events: list[TrendEvent],
    metrics: ScreenerMetrics,
    source_freshness: dict[str, Freshness],
    market_regime: MarketRegime,
    trend_rules: dict[str, Any],
) -> TrendingResultItem | None:
    symbol_history = [event for event in history if event.symbol == symbol]
    if not symbol_history:
        return None
    now = datetime.now(timezone.utc)
    within_24h = [event for event in symbol_history if event.as_datetime() >= now - timedelta(days=1)]
    within_3d = [event for event in symbol_history if event.as_datetime() >= now - timedelta(days=3)]
    within_5d = [event for event in symbol_history if event.as_datetime() >= now - timedelta(days=5)]
    baseline_days = int(trend_rules["metrics"]["baseline_days"])
    baseline = _baseline_daily_mentions(symbol_history, baseline_days)
    growth_3d = _growth_pct(len(within_3d) / 3 if within_3d else 0.0, baseline)
    growth_5d = _growth_pct(len(within_5d) / 5 if within_5d else 0.0, baseline)
    acceleration = _acceleration(len(within_24h), len(within_5d), baseline)
    sentiment_score = round(_average([event.sentiment_score for event in within_5d], 0.0), 4)
    prior_events = [event for event in symbol_history if now - timedelta(days=30) <= event.as_datetime() < now - timedelta(days=5)]
    sentiment_change = round(sentiment_score - _average([event.sentiment_score for event in prior_events], 0.0), 4) if within_5d else None
    ratio = _pos_neu_neg_ratio(within_5d)
    catalyst = _most_common([event.catalyst for event in within_5d if event.catalyst != "none"])
    pro_share = _professional_share(within_5d)
    retail_fomo = _retail_fomo_risk(growth_5d, sentiment_score, pro_share, catalyst == "none")
    trend_score = _trend_score(growth_3d, growth_5d, acceleration, sentiment_score, pro_share, retail_fomo)
    fundamental_support = _fundamental_support(metrics)
    trend_quality = _classify_trend(
        catalyst,
        sentiment_score,
        pro_share,
        len(within_24h),
        acceleration,
        fundamental_support,
        retail_fomo,
        metrics,
        trend_rules["classification"],
    )
    risk_flags = _trend_risk_flags(trend_quality, retail_fomo, metrics)
    freshness_map = {source: freshness.value for source, freshness in source_freshness.items()}
    quality = compute_data_quality(freshness_map)
    confidence = round((quality / 100) * min(1.0, trend_score / 100), 4)
    reason = _trend_reason(trend_quality, growth_5d, sentiment_score, catalyst, pro_share, retail_fomo)
    return TrendingResultItem(
        symbol=symbol,
        mention_count_24h=len(within_24h),
        mention_count_3d=len(within_3d),
        mention_count_5d=len(within_5d),
        mention_growth_3d_pct=growth_3d,
        mention_growth_5d_pct=growth_5d,
        baseline_daily_mentions_30d=round(baseline, 4) if baseline is not None else None,
        acceleration=acceleration,
        sentiment_score=sentiment_score,
        sentiment_change=sentiment_change,
        pos_neu_neg_ratio=ratio,
        retail_fomo_risk=retail_fomo,
        news_catalyst=catalyst,
        trend_quality=trend_quality,
        institutional_account_participation=round(pro_share, 4) if pro_share is not None else None,
        data_freshness=freshness_map,
        data_quality_score=quality,
        confidence=confidence,
        risk_flags=risk_flags,
        reason=reason,
        score_breakdown={
            "trend_score": round(trend_score, 2),
            "fundamental_support": round(fundamental_support, 2),
            "market_regime": market_regime.value if isinstance(market_regime, MarketRegime) else str(market_regime),
            "source_freshness": freshness_map,
            "pro_share": round(pro_share, 4) if pro_share is not None else None,
            "retail_fomo_risk": retail_fomo,
        },
    )


def _baseline_daily_mentions(events: list[TrendEvent], baseline_days: int) -> float:
    now = datetime.now(timezone.utc).date()
    daily_counts: dict[datetime.date, int] = defaultdict(int)
    for event in events:
        day = event.as_datetime().date()
        if 0 <= (now - day).days < baseline_days:
            daily_counts[day] += 1
    return sum(daily_counts.values()) / baseline_days


def _growth_pct(current_daily_mentions: float, baseline_daily_mentions: float) -> float | None:
    if baseline_daily_mentions <= 0:
        return 999.0 if current_daily_mentions > 0 else 0.0
    return round(((current_daily_mentions - baseline_daily_mentions) / baseline_daily_mentions) * 100, 2)


def _acceleration(mentions_24h: int, mentions_5d: int, baseline_daily_mentions: float) -> float:
    recent_average = (mentions_5d - mentions_24h) / 4 if mentions_5d > mentions_24h else 0.0
    denominator = baseline_daily_mentions if baseline_daily_mentions > 0 else 1.0
    return round((mentions_24h - recent_average) / denominator, 4)


def _pos_neu_neg_ratio(events: list[TrendEvent]) -> list[float]:
    if not events:
        return [0.0, 1.0, 0.0]
    counts = Counter(event.sentiment_label for event in events)
    total = len(events)
    return [round(counts.get("positive", 0) / total, 4), round(counts.get("neutral", 0) / total, 4), round(counts.get("negative", 0) / total, 4)]


def _professional_share(events: list[TrendEvent]) -> float | None:
    if not events:
        return None
    professional = sum(1 for event in events if event.professional_source)
    return professional / len(events)


def _retail_fomo_risk(growth_5d: float | None, sentiment_score: float, pro_share: float | None, no_catalyst: bool) -> float:
    growth_component = min(max((growth_5d or 0.0) / 4, 0.0), 100.0)
    sentiment_component = min(max(((sentiment_score + 1) / 2) * 100, 0.0), 100.0)
    retail_share = 100.0 if pro_share is None else (1 - pro_share) * 100
    catalyst_penalty = 100.0 if no_catalyst else 0.0
    score = (0.4 * growth_component) + (0.3 * sentiment_component) + (0.2 * retail_share) + (0.1 * catalyst_penalty)
    return round(min(max(score, 0.0), 100.0), 2)


def _trend_score(growth_3d: float | None, growth_5d: float | None, acceleration: float | None, sentiment_score: float, pro_share: float | None, retail_fomo: float) -> float:
    sentiment_component = ((sentiment_score + 1) / 2) * 100
    pro_component = 50.0 if pro_share is None else pro_share * 100
    acceleration_component = min(max((acceleration or 0.0) * 20, 0.0), 100.0)
    growth_component = min(max((((growth_3d or 0.0) + (growth_5d or 0.0)) / 2) / 4, 0.0), 100.0)
    score = (0.30 * growth_component) + (0.25 * acceleration_component) + (0.20 * sentiment_component) + (0.15 * pro_component) + (0.10 * (100 - retail_fomo))
    return round(min(max(score, 0.0), 100.0), 2)


def _fundamental_support(metrics: ScreenerMetrics) -> float:
    scores = []
    revenue = metrics.get_float("revenue_growth_yoy_pct")
    gross = metrics.get_float("gross_margin_pct")
    short_interest = metrics.get_float("short_percent_float")
    if revenue is not None:
        scores.append(min(max((revenue / 30) * 100, 0.0), 100.0))
    if gross is not None:
        scores.append(min(max((gross / 75) * 100, 0.0), 100.0))
    if short_interest is not None:
        scores.append(100 - min(max((short_interest / 20) * 100, 0.0), 100.0))
    return round(sum(scores) / len(scores), 2) if scores else 50.0


def _classify_trend(
    catalyst: str,
    sentiment_score: float,
    pro_share: float | None,
    mentions_24h: int,
    acceleration: float | None,
    fundamental_support: float,
    retail_fomo: float,
    metrics: ScreenerMetrics,
    thresholds: dict[str, Any],
) -> TrendQuality:
    pro_share = pro_share or 0.0
    short_interest = metrics.get_float("short_percent_float") or 0.0
    price = metrics.get_float("price") or 0.0
    ma50 = metrics.get_float("fifty_day_average") or price
    thin_liquidity = (metrics.avg_dollar_volume or 0.0) < 5_000_000
    vertical_price = ma50 > 0 and ((price - ma50) / ma50) * 100 > 15

    if catalyst != "none" and sentiment_score >= float(thresholds["news_driven_min_sentiment"]) and pro_share >= float(thresholds["news_driven_min_institutional_share"]):
        return TrendQuality.NEWS_DRIVEN
    if catalyst == "earnings":
        return TrendQuality.EARNINGS_DRIVEN
    if (acceleration or 0.0) >= float(thresholds["early_accumulation_min_acceleration"]) and mentions_24h <= int(thresholds["early_accumulation_max_24h_mentions"]) and fundamental_support >= float(thresholds["strong_fundamental_score"]):
        return TrendQuality.EARLY_ACCUMULATION
    if catalyst != "none" and sentiment_score >= float(thresholds["high_quality_min_sentiment"]) and pro_share >= float(thresholds["news_driven_min_institutional_share"]) and fundamental_support >= float(thresholds["strong_fundamental_score"]):
        return TrendQuality.HIGH_QUALITY
    if retail_fomo >= float(thresholds["meme_growth_5d_pct"]) / 3 and sentiment_score >= float(thresholds["meme_sentiment_score"]) and catalyst == "none":
        return TrendQuality.MEME_FOMO
    if retail_fomo >= 70 and thin_liquidity and vertical_price and short_interest >= float(thresholds["pump_short_interest_pct"]):
        return TrendQuality.PUMP_RISK
    if vertical_price and (acceleration or 0.0) >= float(thresholds["overextended_acceleration"]):
        return TrendQuality.OVEREXTENDED
    return TrendQuality.HIGH_QUALITY if fundamental_support >= float(thresholds["strong_fundamental_score"]) else TrendQuality.NEWS_DRIVEN


def _trend_risk_flags(trend_quality: TrendQuality, retail_fomo: float, metrics: ScreenerMetrics) -> list[str]:
    flags: list[str] = []
    if trend_quality in {TrendQuality.MEME_FOMO, TrendQuality.PUMP_RISK}:
        flags.append("meme_behavior")
    if trend_quality == TrendQuality.OVEREXTENDED:
        flags.append("overextended")
    if (metrics.avg_dollar_volume or 0.0) < 5_000_000:
        flags.append("low_liquidity")
    if retail_fomo >= 75:
        flags.append("gap_risk")
    return flags


def _trend_reason(
    trend_quality: TrendQuality,
    growth_5d: float | None,
    sentiment_score: float,
    catalyst: str,
    pro_share: float | None,
    retail_fomo: float,
) -> str:
    catalyst_text = catalyst if catalyst != "none" else "no clear catalyst"
    pro_text = "unknown pro participation" if pro_share is None else f"{pro_share:.0%} pro participation"
    return (
        f"{trend_quality.value} with 5D growth {growth_5d or 0:.0f}%, sentiment {sentiment_score:.2f}, "
        f"{pro_text}, {catalyst_text}, retail fomo risk {retail_fomo:.0f}."
    )


def _sentiment_for_text(text: str, sentiment_config: dict[str, Any]) -> tuple[float, str]:
    score = _finbert_sentiment(text, sentiment_config.get("finbert_model"))
    if score is None:
        score = _keyword_sentiment(text, sentiment_config)
    if score > 0.15:
        return round(score, 4), "positive"
    if score < -0.15:
        return round(score, 4), "negative"
    return round(score, 4), "neutral"


def _finbert_sentiment(text: str, model_name: str | None) -> float | None:
    global FINBERT, FINBERT_FAILED
    if FINBERT_FAILED:
        return None
    if FINBERT is None:
        try:
            from transformers import pipeline

            FINBERT = pipeline("text-classification", model=model_name or "ProsusAI/finbert", tokenizer=model_name or "ProsusAI/finbert")
        except Exception:
            FINBERT_FAILED = True
            return None
    try:
        result = FINBERT(text[:512])[0]
        label = str(result["label"]).lower()
        score = float(result["score"])
        if "positive" in label:
            return score
        if "negative" in label:
            return -score
        return 0.0
    except Exception:
        FINBERT_FAILED = True
        return None


def _keyword_sentiment(text: str, sentiment_config: dict[str, Any]) -> float:
    lowered = text.lower()
    positive = sum(1 for keyword in sentiment_config["positive_keywords"] if keyword in lowered)
    negative = sum(1 for keyword in sentiment_config["negative_keywords"] if keyword in lowered)
    if positive == negative == 0:
        return 0.0
    return max(-1.0, min(1.0, (positive - negative) / max(positive + negative, 1)))


def _detect_catalyst(text: str) -> str:
    lowered = text.lower()
    for catalyst, keywords in CATALYST_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return catalyst
    return "none"


def _extract_symbols(text: str, symbols: set[str]) -> list[str]:
    if not text:
        return []
    cashtags = {match.group(1).upper() for match in re.finditer(r"\$([A-Za-z]{1,5})\b", text)}
    tokens = set(re.findall(r"\b[A-Z]{1,5}\b", text.upper()))
    matched = sorted((cashtags | tokens) & symbols)
    return matched


def _event_key(event: TrendEvent) -> str:
    return "|".join([event.symbol, event.source, event.occurred_at, event.text[:120]])


def _most_common(values: list[str]) -> str:
    if not values:
        return "none"
    return Counter(values).most_common(1)[0][0]


def _average(values: list[float], default: float) -> float:
    return sum(values) / len(values) if values else default


def _text(element: ElementTree.Element | None) -> str:
    return "" if element is None or element.text is None else element.text.strip()
