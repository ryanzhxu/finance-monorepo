from __future__ import annotations

import pytest

from shared.enums import Direction, TechnicalSource
from shared.models import AnalyzeRequest, ExternalTechnicalVerdict

from analyst_service.core.technical_provider import TechnicalVerdictError, resolve_technical_verdict


def _verdict(**overrides: object) -> ExternalTechnicalVerdict:
    payload: dict[str, object] = {
        "producer": "vincent-stock-decision-dashboard",
        "action": "buy",
        "confidence": 70,
        "priceState": "IN_OPPORTUNITY_ZONE",
    }
    payload.update(overrides)
    return ExternalTechnicalVerdict.model_validate(payload)


def test_analyze_request_accepts_an_external_technical_block() -> None:
    request = AnalyzeRequest.model_validate(
        {
            "symbol": "nvda",
            "technical": {
                "producer": "vincent-stock-decision-dashboard",
                "action": "accumulate",
                "confidence": 62,
                "priceState": "IN_OPPORTUNITY_ZONE",
            },
        }
    )

    assert request.symbol == "NVDA"
    assert request.technical is not None
    assert request.technical.producer == "vincent-stock-decision-dashboard"


def test_analyze_request_without_technical_stays_none() -> None:
    request = AnalyzeRequest.model_validate({"symbol": "NVDA"})

    assert request.technical is None


def test_resolve_raises_when_no_verdict_supplied() -> None:
    with pytest.raises(TechnicalVerdictError):
        resolve_technical_verdict(None)


def test_resolve_normalizes_a_valid_verdict() -> None:
    verdict = resolve_technical_verdict(_verdict())

    assert verdict is not None
    assert verdict.source is TechnicalSource.EXTERNAL
    assert verdict.direction is Direction.BUY
    assert verdict.confidence == 0.7


def test_contract_violation_raises_rather_than_falling_back_to_local() -> None:
    # buy inside a reduce zone is illegal under the decision.v1 legality table.
    with pytest.raises(TechnicalVerdictError):
        resolve_technical_verdict(_verdict(action="buy", priceState="IN_REDUCE_ZONE"))


def test_rejection_message_describes_the_violation() -> None:
    # The caller must be able to tell why a verdict was rejected, otherwise the
    # failure is as opaque as the fallback it replaced.
    with pytest.raises(TechnicalVerdictError, match=".+"):
        resolve_technical_verdict(
            _verdict(
                action="buy",
                opportunityRange={"low": 100.0, "high": 150.0},
                reduceRange={"low": 140.0, "high": 160.0},
            )
        )
