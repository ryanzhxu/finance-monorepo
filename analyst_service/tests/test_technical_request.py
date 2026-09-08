from __future__ import annotations

from shared.enums import Direction, TechnicalSource
from shared.models import AnalyzeRequest, ExternalTechnicalVerdict

from analyst_service.core.technical_provider import resolve_technical_verdict


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


def test_resolve_returns_none_and_no_flags_when_absent() -> None:
    verdict, risk_flags = resolve_technical_verdict(None)

    assert verdict is None
    assert risk_flags == []


def test_resolve_normalizes_a_valid_verdict() -> None:
    verdict, risk_flags = resolve_technical_verdict(_verdict())

    assert verdict is not None
    assert verdict.source is TechnicalSource.EXTERNAL
    assert verdict.direction is Direction.BUY
    assert verdict.confidence == 0.7
    assert risk_flags == []


def test_contract_violation_falls_back_to_local_with_a_visible_flag() -> None:
    # buy inside a reduce zone is illegal under the decision.v1 legality table.
    verdict, risk_flags = resolve_technical_verdict(_verdict(action="buy", priceState="IN_REDUCE_ZONE"))

    assert verdict is None, "a rejected verdict must not become a technical opinion"
    assert "external_technical_rejected" in risk_flags


def test_rejection_is_never_silent() -> None:
    # The caller must be able to tell "Vincent's engine was used" from
    # "Vincent's engine was ignored", otherwise the fallback misleads.
    _, risk_flags = resolve_technical_verdict(
        _verdict(
            action="buy",
            opportunityRange={"low": 100.0, "high": 150.0},
            reduceRange={"low": 140.0, "high": 160.0},
        )
    )

    assert risk_flags != []
