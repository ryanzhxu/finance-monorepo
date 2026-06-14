from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from shared.config_loader import load_yaml_config, require_nested_keys

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"

REQUIRED_WEIGHTS = {
    "RSI_14",
    "MACD",
    "Bollinger_Bands",
    "Volume",
    "MA_50_200",
    "RSI_Weekly",
    "Support_Resistance",
    "EPS_Surprise",
    "Analyst_Ratings",
    "PE_Percentile",
    "Institutional_13F",
    "Put_Call_Ratio",
    "IV_Rank",
    "Short_Interest",
    "FOMC_Proximity",
    "Reddit_Sentiment",
    "News_Sentiment",
}

REQUIRED_ENTRY_RULES = {
    "support_window",
    "cluster_atr_multiple",
    "ideal_zone_low_atr_multiple",
    "zone_atr_mult",
    "ma20_proximity_atr_tolerance",
    "breakout_buffer",
    "breakout_volume_ratio",
    "extension_threshold_pct",
    "overbought_rsi",
    "mild_strength_ma20_pct",
    "aggressive_max_rsi",
    "oversold_reclaim_rsi",
    "conservative_min_rsi",
    "strong_trend_ma200_distance_pct",
    "reasonable_pe_percentile",
    "rr_min",
}


@lru_cache
def load_service_config() -> dict[str, Any]:
    weights = load_yaml_config(CONFIG_DIR / "signal_weights.yaml", REQUIRED_WEIGHTS)
    thresholds = load_yaml_config(CONFIG_DIR / "signal_thresholds.yaml", {"vote", "signals", "quality"})
    require_nested_keys(
        thresholds,
        {
            "vote": {"buy_above", "sell_below"},
            "signals": {
                "rsi_buy_below",
                "rsi_sell_above",
                "weekly_rsi_buy_above",
                "volume_buy_above",
                "eps_buy_above",
                "eps_sell_below",
                "pe_sell_above",
                "pe_buy_below",
                "analyst_net_buy_above",
                "put_call_buy_below",
                "put_call_sell_above",
                "iv_hold_below",
                "short_interest_sell_above",
            },
            "quality": {"group_penalty"},
        },
        "signal_thresholds.yaml",
    )
    entry_rules = load_yaml_config(CONFIG_DIR / "entry_rules.yaml", REQUIRED_ENTRY_RULES)
    return {"weights": weights, "thresholds": thresholds, "entry_rules": entry_rules}
