from __future__ import annotations

from analyst_service.core.regime import classify_regime


def test_regime_is_risk_off_when_vix_high_and_spy_below_ma200() -> None:
    assert classify_regime(30.0, 4.2, -2.0, None) == "risk_off"


def test_regime_is_risk_on_when_vix_low_and_spy_above_ma200() -> None:
    assert classify_regime(15.0, 4.2, 5.0, None) == "risk_on"


def test_regime_is_neutral_between_thresholds() -> None:
    assert classify_regime(20.0, 4.2, 2.0, None) == "neutral"


def test_regime_is_neutral_when_all_inputs_missing() -> None:
    assert classify_regime(None, None, None, None) == "neutral"


def test_regime_is_risk_off_near_fomc_even_if_vix_is_calm() -> None:
    assert classify_regime(15.0, 4.2, 5.0, 2) == "risk_off"
