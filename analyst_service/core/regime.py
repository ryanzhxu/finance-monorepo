from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from shared.config_loader import load_yaml_config, require_nested_keys


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "signal_thresholds.yaml"


@lru_cache
def _load_regime_thresholds() -> dict[str, Any]:
    config = load_yaml_config(CONFIG_PATH, {"vote", "signals", "quality", "news_sentiment", "regime"})
    require_nested_keys(
        config,
        {
            "regime": {
                "vix_risk_off",
                "vix_risk_on",
                "fomc_risk_window_days",
                "spy_below_ma200_is_risk_off",
            }
        },
        "signal_thresholds.yaml",
    )
    regime = config["regime"]
    if not isinstance(regime, dict):
        raise RuntimeError("signal_thresholds.yaml regime block must be a mapping")
    return regime


def classify_regime(
    vix: float | None,
    treasury_10y: float | None,
    spy_vs_ma200_pct: float | None,
    fomc_proximity_days: int | None,
) -> str:
    """Returns "risk_off" | "neutral" | "risk_on"."""
    thresholds = _load_regime_thresholds()
    vix_risk_off = float(thresholds["vix_risk_off"])
    vix_risk_on = float(thresholds["vix_risk_on"])
    fomc_risk_window_days = int(thresholds["fomc_risk_window_days"])
    spy_below_ma200_is_risk_off = bool(thresholds["spy_below_ma200_is_risk_off"])

    del treasury_10y  # Reserved for future expansion; kept in the signature by design.

    if vix is not None and vix > vix_risk_off:
        return "risk_off"
    if spy_below_ma200_is_risk_off and spy_vs_ma200_pct is not None and spy_vs_ma200_pct < 0:
        return "risk_off"
    if fomc_proximity_days is not None and fomc_proximity_days <= fomc_risk_window_days:
        return "risk_off"

    if (
        vix is not None
        and vix < vix_risk_on
        and spy_vs_ma200_pct is not None
        and spy_vs_ma200_pct > 0
    ):
        return "risk_on"

    return "neutral"
