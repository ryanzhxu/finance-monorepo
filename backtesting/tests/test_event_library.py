from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from backtesting.event_library import (
    EventType,
    MarketImpact,
    MarketShockEvent,
    ProvenanceStatus,
    load_event_fixtures,
)


def test_event_fixtures_are_unique_and_reproducible() -> None:
    first = load_event_fixtures()
    second = load_event_fixtures()

    assert len(first) == 5
    assert len({event.event_id for event in first}) == 5
    assert [event.model_dump(mode="json") for event in first] == [event.model_dump(mode="json") for event in second]
    assert {event.provenance_status for event in first} == {ProvenanceStatus.FIXTURE}
    assert all(event.event_type in set(EventType) for event in first)


def test_fixture_impact_is_explicitly_unmeasured() -> None:
    events = load_event_fixtures()

    assert all(event.impact.measurement_status == "unmeasured" for event in events)
    assert all(event.impact.peak_drawdown_pct is None for event in events)
    assert all(event.impact.benchmark == "SPY" for event in events)


def test_event_rejects_invalid_date_window() -> None:
    with pytest.raises(ValidationError, match="end_date must not precede start_date"):
        MarketShockEvent(
            event_id="invalid-event",
            version=1,
            event_type=EventType.CYBER_INFRASTRUCTURE,
            title="Invalid event",
            start_date=date(2024, 2, 1),
            end_date=date(2024, 1, 1),
            geography=["US"],
            affected_sectors=["broad_market"],
            trigger_description="Invalid fixture.",
            transmission_channels=["unknown"],
            impact=MarketImpact(window_start=date(2024, 1, 1), window_end=date(2024, 2, 1)),
            evidence=[
                {
                    "source_url": "https://example.com/event",
                    "publisher": "Example",
                    "source_type": "academic",
                    "retrieved_at": "2026-08-03T00:00:00Z",
                }
            ],
            provenance_status=ProvenanceStatus.FIXTURE,
        )


def test_unmeasured_impact_cannot_contain_metrics() -> None:
    with pytest.raises(ValidationError, match="unmeasured impact cannot contain measured metrics"):
        MarketImpact(
            window_start=date(2024, 1, 1),
            window_end=date(2024, 1, 2),
            peak_drawdown_pct=-10.0,
        )
