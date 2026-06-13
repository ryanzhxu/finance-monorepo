from __future__ import annotations

from collections import defaultdict
from math import isfinite
from typing import Any

from shared.data_quality import compute_data_quality
from shared.enums import Direction, Freshness, MarketRegime, ScreenType
from shared.models import ScreenResultItem

from screener_service.core.fundamentals_bulk import ScreenerMetrics

MISSING_NEUTRAL = 50.0


def score_universe(
    metrics: list[ScreenerMetrics],
    weights_config: dict[str, Any],
    screen_type: ScreenType,
    market_regime: MarketRegime,
    notes: list[str] | None = None,
) -> list[ScreenResultItem]:
    sector_percentiles = _sector_valuation_percentiles(metrics)
    weights = _adjusted_weights(weights_config, market_regime)
    thresholds = weights_config["thresholds"]
    results: list[ScreenResultItem] = []
    for item in metrics:
        scores, breakdown = _score_item(item, sector_percentiles.get(item.symbol))
        opportunity_score = _opportunity_score(scores, weights)
        freshness = item.freshness_map
        quality = compute_data_quality(freshness)
        risk_flags = _risk_flags(item, quality, scores["risk"])
        confidence = round((quality / 100) * min(1.0, opportunity_score / 100), 4)
        action = _action(opportunity_score, thresholds)
        reason = _reason(scores, breakdown, notes)
        results.append(
            ScreenResultItem(
                rank=0,
                symbol=item.symbol,
                screen_type=screen_type,
                opportunity_score=opportunity_score,
                valuation_score=scores["valuation"],
                growth_score=scores["growth"],
                quality_score=scores["quality"],
                momentum_score=scores["momentum"],
                analyst_revision_score=scores["analyst_revision"],
                institutional_accumulation_score=scores["institutional_accumulation"],
                insider_activity_score=scores["insider_activity"],
                risk_score=scores["risk"],
                score_breakdown=breakdown,
                data_freshness={key: value.value for key, value in freshness.items()},
                data_quality_score=quality,
                confidence=confidence,
                reason=reason,
                summary=reason,
                recommended_action=action,
                risk_flags=risk_flags,
                recommendation=_direction(opportunity_score, thresholds),
            )
        )
    results.sort(key=lambda result: result.opportunity_score, reverse=True)
    for rank, result in enumerate(results, start=1):
        result.rank = rank
    return results


def _score_item(item: ScreenerMetrics, sector_valuation_percentile: float | None) -> tuple[dict[str, float], dict[str, Any]]:
    valuation, valuation_breakdown = _valuation_score(item, sector_valuation_percentile)
    growth, growth_breakdown = _growth_score(item)
    quality, quality_breakdown = _quality_score(item)
    momentum, momentum_breakdown = _momentum_score(item)
    analyst_revision, analyst_breakdown = _analyst_revision_score(item)
    institutional, institutional_breakdown = _institutional_score(item)
    insider, insider_breakdown = _insider_score(item)
    risk, risk_breakdown = _risk_score(item)
    scores = {
        "valuation": valuation,
        "growth": growth,
        "quality": quality,
        "momentum": momentum,
        "analyst_revision": analyst_revision,
        "institutional_accumulation": institutional,
        "insider_activity": insider,
        "risk": risk,
    }
    breakdown = {
        "valuation": valuation_breakdown,
        "growth": growth_breakdown,
        "quality": quality_breakdown,
        "momentum": momentum_breakdown,
        "analyst_revision": analyst_breakdown,
        "institutional_accumulation": institutional_breakdown,
        "insider_activity": insider_breakdown,
        "risk": risk_breakdown,
    }
    return scores, breakdown


def _valuation_score(item: ScreenerMetrics, sector_valuation_percentile: float | None) -> tuple[float, dict[str, Any]]:
    self_percentile = item.get_float("self_5y_valuation_percentile")
    own_history_score = None if self_percentile is None else 100 - self_percentile
    sector_score = None if sector_valuation_percentile is None else 100 - sector_valuation_percentile
    pb = item.get_float("price_to_book")
    ps = item.get_float("price_to_sales")
    ev_ebitda = item.get_float("enterprise_to_ebitda")
    relative_multiples = [_inverse_bounded(pb, 1, 12), _inverse_bounded(ps, 1, 18), _inverse_bounded(ev_ebitda, 5, 35)]
    score = _average_available([own_history_score, sector_score, *relative_multiples])
    growth = item.get_float("revenue_growth_yoy_pct")
    if growth is not None and growth < 0:
        score = max(0.0, score - 15)
    return round(score, 2), {
        "score": round(score, 2),
        "self_5y_valuation_percentile": self_percentile,
        "sector_valuation_percentile": sector_valuation_percentile,
        "price_to_book": pb,
        "price_to_sales": ps,
        "enterprise_to_ebitda": ev_ebitda,
    }


def _growth_score(item: ScreenerMetrics) -> tuple[float, dict[str, Any]]:
    revenue = item.get_float("revenue_growth_yoy_pct")
    earnings = item.get_float("earnings_growth_yoy_pct")
    score = _average_available([_bounded(revenue, -10, 35), _bounded(earnings, -20, 40)])
    return round(score, 2), {"score": round(score, 2), "revenue_growth_yoy_pct": revenue, "earnings_growth_yoy_pct": earnings}


def _quality_score(item: ScreenerMetrics) -> tuple[float, dict[str, Any]]:
    gross = item.get_float("gross_margin_pct")
    operating = item.get_float("operating_margin_pct")
    roe = item.get_float("return_on_equity_pct")
    debt = item.get_float("debt_to_equity")
    fcf = item.get_float("free_cashflow")
    score = _average_available([
        _bounded(gross, 20, 75),
        _bounded(operating, 0, 35),
        _bounded(roe, 0, 35),
        _inverse_bounded(debt, 0, 250),
        75.0 if fcf and fcf > 0 else 25.0 if fcf is not None else None,
    ])
    return round(score, 2), {"score": round(score, 2), "gross_margin_pct": gross, "operating_margin_pct": operating, "return_on_equity_pct": roe, "debt_to_equity": debt, "free_cashflow_positive": None if fcf is None else fcf > 0}


def _momentum_score(item: ScreenerMetrics) -> tuple[float, dict[str, Any]]:
    price = item.get_float("price")
    ma50 = item.get_float("fifty_day_average")
    ma200 = item.get_float("two_hundred_day_average")
    dist50 = _distance_pct(price, ma50)
    dist200 = _distance_pct(price, ma200)
    score = _average_available([_bounded(dist50, -10, 15), _bounded(dist200, -20, 35)])
    if dist50 is not None and dist50 > 20:
        score -= 10
    return round(max(0.0, score), 2), {"score": round(max(0.0, score), 2), "dist_from_50d_pct": dist50, "dist_from_200d_pct": dist200}


def _analyst_revision_score(item: ScreenerMetrics) -> tuple[float, dict[str, Any]]:
    recommendation_mean = item.get_float("recommendation_mean")
    score = _inverse_bounded(recommendation_mean, 1, 5)
    return round(score if score is not None else MISSING_NEUTRAL, 2), {"score": round(score if score is not None else MISSING_NEUTRAL, 2), "recommendation_mean": recommendation_mean}


def _institutional_score(item: ScreenerMetrics) -> tuple[float, dict[str, Any]]:
    institutional = item.get_float("institutional_pct")
    score = _bounded(institutional, 20, 85)
    return round(score if score is not None else MISSING_NEUTRAL, 2), {"score": round(score if score is not None else MISSING_NEUTRAL, 2), "institutional_pct": institutional}


def _insider_score(item: ScreenerMetrics) -> tuple[float, dict[str, Any]]:
    insider = item.get_float("insider_pct")
    score = _bounded(insider, 0, 15)
    return round(score if score is not None else MISSING_NEUTRAL, 2), {"score": round(score if score is not None else MISSING_NEUTRAL, 2), "insider_pct": insider}


def _risk_score(item: ScreenerMetrics) -> tuple[float, dict[str, Any]]:
    beta = item.get_float("beta")
    short_interest = item.get_float("short_percent_float")
    price = item.get_float("price")
    avg_dollar_volume = item.avg_dollar_volume
    valuation_percentile = item.get_float("self_5y_valuation_percentile")
    risk_components = [
        _bounded(beta, 0.8, 2.0),
        _bounded(short_interest, 0, 20),
        _inverse_bounded(avg_dollar_volume, 5_000_000, 100_000_000),
        _bounded(valuation_percentile, 60, 100),
        95.0 if price is not None and price < 5 else 0.0 if price is not None else None,
    ]
    score = _average_available(risk_components, missing=MISSING_NEUTRAL)
    return round(score, 2), {"score": round(score, 2), "beta": beta, "short_percent_float": short_interest, "avg_dollar_volume": avg_dollar_volume, "self_5y_valuation_percentile": valuation_percentile}


def _sector_valuation_percentiles(metrics: list[ScreenerMetrics]) -> dict[str, float]:
    by_sector: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for item in metrics:
        sector = item.get_str("sector") or "UNKNOWN"
        pe = item.get_float("forward_pe") or item.get_float("trailing_pe")
        if pe is not None and isfinite(pe):
            by_sector[sector].append((item.symbol, pe))
    result: dict[str, float] = {}
    for items in by_sector.values():
        sorted_items = sorted(items, key=lambda pair: pair[1])
        if len(sorted_items) == 1:
            result[sorted_items[0][0]] = 50.0
            continue
        for index, (symbol, _) in enumerate(sorted_items):
            result[symbol] = (index / (len(sorted_items) - 1)) * 100
    return result


def _opportunity_score(scores: dict[str, float], weights: dict[str, float]) -> float:
    positive_keys = [key for key in weights if key != "risk"]
    numerator = sum(weights[key] * scores[key] for key in positive_keys) - (weights["risk"] * scores["risk"])
    denominator = sum(weights[key] for key in positive_keys)
    return round(max(0.0, min(100.0, numerator / denominator)), 2)


def _adjusted_weights(config: dict[str, Any], regime: MarketRegime) -> dict[str, float]:
    weights = {key: float(value) for key, value in config["opportunity"].items()}
    regime_key = regime.value if isinstance(regime, MarketRegime) else str(regime)
    for key, delta in config.get("regime_adjustments", {}).get(regime_key, {}).items():
        if key in weights:
            weights[key] = max(0.0, weights[key] + float(delta))
    return weights


def _risk_flags(item: ScreenerMetrics, data_quality_score: int, risk_score: float) -> list[str]:
    flags: list[str] = []
    price = item.get_float("price")
    avg_dollar_volume = item.avg_dollar_volume
    short_interest = item.get_float("short_percent_float")
    if data_quality_score < 50:
        flags.append("low_data_quality")
    if avg_dollar_volume is not None and avg_dollar_volume < 5_000_000:
        flags.append("low_liquidity")
    if price is not None and price < 5:
        flags.append("penny_stock")
    if short_interest is not None and short_interest > 20:
        flags.append("high_short_interest")
    if risk_score >= 75:
        flags.append("valuation_elevated")
    return flags


def _action(score: float, thresholds: dict[str, Any]) -> str:
    if score >= float(thresholds["analyze_deeper_score"]):
        return "analyze_deeper"
    if score >= float(thresholds["watch_score"]):
        return "watch"
    return "skip"


def _direction(score: float, thresholds: dict[str, Any]) -> Direction:
    if score >= float(thresholds["buy_score"]):
        return Direction.BUY
    if score <= float(thresholds["sell_score"]):
        return Direction.SELL
    return Direction.HOLD


def _reason(scores: dict[str, float], breakdown: dict[str, Any], notes: list[str] | None) -> str:
    best = max((key for key in scores if key != "risk"), key=lambda key: scores[key])
    base = f"Highest factor is {best.replace('_', ' ')} at {scores[best]:.0f}; risk score is {scores['risk']:.0f}."
    if notes:
        return f"{base} {' '.join(notes)}"
    valuation = breakdown["valuation"]
    if valuation.get("self_5y_valuation_percentile") is None:
        return f"{base} Self-5Y valuation history is unavailable."
    return base


def _bounded(value: float | None, low: float, high: float) -> float | None:
    if value is None or not isfinite(value):
        return None
    return max(0.0, min(100.0, ((value - low) / (high - low)) * 100))


def _inverse_bounded(value: float | None, low: float, high: float) -> float | None:
    score = _bounded(value, low, high)
    return None if score is None else 100.0 - score


def _average_available(values: list[float | None], missing: float = MISSING_NEUTRAL) -> float:
    present = [value for value in values if value is not None and isfinite(value)]
    if not present:
        return missing
    return sum(present) / len(present)


def _distance_pct(price: float | None, anchor: float | None) -> float | None:
    if price is None or anchor in (None, 0):
        return None
    return ((price - anchor) / anchor) * 100
