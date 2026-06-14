from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from shared.config_loader import load_yaml_config, require_nested_keys

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@lru_cache
def load_screener_config() -> dict[str, Any]:
    scoring = load_yaml_config(CONFIG_DIR / "scoring_weights.yaml", {"opportunity", "regime_adjustments", "thresholds"})
    require_nested_keys(
        scoring,
        {
            "opportunity": {
                "valuation",
                "growth",
                "quality",
                "momentum",
                "analyst_revision",
                "institutional_accumulation",
                "insider_activity",
                "risk",
            },
            "regime_adjustments": {"risk_off", "risk_on"},
            "thresholds": {"buy_score", "sell_score", "analyze_deeper_score", "watch_score"},
        },
        "scoring_weights.yaml",
    )
    filters = load_yaml_config(
        CONFIG_DIR / "filters.yaml",
        {"min_market_cap_usd", "min_avg_dollar_volume_usd", "exclude_penny_stocks", "exclude_otc", "meme_behavior_guard"},
    )
    universes = load_yaml_config(CONFIG_DIR / "universes.yaml")
    trend_rules = load_yaml_config(CONFIG_DIR / "trend_rules.yaml", {"sources", "sentiment", "metrics", "classification"})
    require_nested_keys(
        trend_rules,
        {
            "sources": {"reddit", "stocktwits", "news", "yahoo_trending"},
            "sentiment": {"finbert_model", "positive_keywords", "negative_keywords"},
            "metrics": {"baseline_days", "booster_weight", "retail_fomo_cap", "institutional_share_professional_sources"},
            "classification": {
                "news_driven_min_sentiment",
                "news_driven_min_institutional_share",
                "earnings_window_days",
                "early_accumulation_min_acceleration",
                "early_accumulation_max_24h_mentions",
                "high_quality_min_sentiment",
                "meme_growth_5d_pct",
                "meme_sentiment_score",
                "pump_short_interest_pct",
                "overextended_acceleration",
                "strong_fundamental_score",
            },
        },
        "trend_rules.yaml",
    )
    return {"scoring": scoring, "filters": filters, "universes": universes, "trend_rules": trend_rules}
