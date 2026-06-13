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
    return {"scoring": scoring, "filters": filters, "universes": universes}
