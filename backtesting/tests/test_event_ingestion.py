from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from backtesting.event_ingestion import (
    EvidencePayload,
    EventIngestionStore,
    IngestionStatus,
    MarketPriceWindow,
    MissingEvidenceError,
    ProviderFailureError,
    calculate_market_impact,
    ingest_events,
)
from backtesting.event_library import EventEvidence, load_event_fixtures


FIXED_ATTEMPT = datetime(2026, 8, 4, tzinfo=timezone.utc)


def _evidence(event):
    return [
        EvidencePayload(
            evidence=event.evidence[0],
            raw_payload=f"primary evidence for {event.event_id}".encode("utf-8"),
            as_of=event.end_date or event.start_date,
            revision="fixture-v1",
        )
    ]


def _price_window(event) -> MarketPriceWindow:
    current = event.impact.window_start - timedelta(days=7)
    dates: list[date] = []
    while current <= event.impact.window_end:
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    return MarketPriceWindow(
        symbol="QQQ",
        prices={observed_on: 100.0 + position for position, observed_on in enumerate(dates)},
        benchmark="SPY",
        benchmark_prices={observed_on: 100.0 + position * 0.5 for position, observed_on in enumerate(dates)},
        provenance=EvidencePayload(
            evidence=EventEvidence(
                source_url="https://prices.example/fixture.csv",
                publisher="Fixture exchange",
                source_type="exchange",
                retrieved_at=FIXED_ATTEMPT,
                published_on=event.end_date,
            ),
            raw_payload=f"price fixture for {event.event_id}".encode("utf-8"),
            as_of=event.end_date,
            revision="fixture-v1",
        ),
    )


def test_five_fixture_events_ingest_reproducibly_with_private_manifests(tmp_path) -> None:
    events = load_event_fixtures()

    first = ingest_events(
        events,
        batch_id="fixture-batch",
        evidence_loader=_evidence,
        price_loader=_price_window,
        store=EventIngestionStore(tmp_path / "first"),
        attempted_at=FIXED_ATTEMPT,
    )
    second = ingest_events(
        events,
        batch_id="fixture-batch",
        evidence_loader=_evidence,
        price_loader=_price_window,
        store=EventIngestionStore(tmp_path / "second"),
        attempted_at=FIXED_ATTEMPT,
    )

    assert len(first.records) == 5
    assert all(record.event.impact.measurement_status == "measured" for record in first.records)
    assert all(len(record.manifest.sources) == 2 for record in first.records)
    assert [record.event.model_dump(mode="json") for record in first.records] == [
        record.event.model_dump(mode="json") for record in second.records
    ]
    assert [record.manifest.manifest_sha256 for record in first.records] == [
        record.manifest.manifest_sha256 for record in second.records
    ]


def test_ingestion_resumes_from_completed_checkpoint(tmp_path) -> None:
    events = load_event_fixtures()
    calls: list[str] = []

    def evidence_loader(event):
        calls.append(event.event_id)
        return _evidence(event)

    store = EventIngestionStore(tmp_path)
    ingest_events(
        events[:2],
        batch_id="resume-batch",
        evidence_loader=evidence_loader,
        price_loader=_price_window,
        store=store,
        attempted_at=FIXED_ATTEMPT,
    )
    result = ingest_events(
        events,
        batch_id="resume-batch",
        evidence_loader=evidence_loader,
        price_loader=_price_window,
        store=store,
        attempted_at=FIXED_ATTEMPT,
    )

    assert result.skipped_event_ids == tuple(event.event_id for event in events[:2])
    assert calls == [event.event_id for event in events]
    assert result.completed_event_ids == tuple(sorted(event.event_id for event in events))


def test_missing_evidence_does_not_create_complete_event(tmp_path) -> None:
    event = load_event_fixtures()[0]
    store = EventIngestionStore(tmp_path)

    result = ingest_events(
        [event],
        batch_id="missing-evidence",
        evidence_loader=lambda _: [],
        price_loader=_price_window,
        store=store,
        attempted_at=FIXED_ATTEMPT,
    )

    assert result.records == ()
    assert result.failures[0].status == IngestionStatus.MISSING_EVIDENCE
    assert result.completed_event_ids == ()
    assert not list((tmp_path / "events").glob("*.json"))


def test_systemic_provider_failure_is_retryable_and_not_completed(tmp_path) -> None:
    event = load_event_fixtures()[0]

    def failing_loader(_):
        raise ProviderFailureError("SEC unavailable")

    result = ingest_events(
        [event],
        batch_id="provider-failure",
        evidence_loader=failing_loader,
        price_loader=_price_window,
        store=EventIngestionStore(tmp_path),
        attempted_at=FIXED_ATTEMPT,
    )

    assert result.failures[0].status == IngestionStatus.SYSTEMIC_PROVIDER_FAILURE
    assert result.completed_event_ids == ()


def test_duplicate_event_ids_are_rejected_before_source_calls(tmp_path) -> None:
    event = load_event_fixtures()[0]

    with pytest.raises(ValueError, match="duplicate event IDs"):
        ingest_events(
            [event, event],
            batch_id="duplicates",
            evidence_loader=_evidence,
            price_loader=_price_window,
            store=EventIngestionStore(tmp_path),
        )


def test_market_impact_is_benchmark_relative_and_deterministic() -> None:
    days = [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 4)]
    impact = calculate_market_impact(
        load_event_fixtures()[1].impact.model_copy(
            update={"window_start": days[1], "window_end": days[-1]}
        ),
        MarketPriceWindow(
            symbol="QQQ",
            prices=dict(zip(days, [100.0, 90.0, 95.0, 100.0])),
            benchmark="SPY",
            benchmark_prices=dict(zip(days, [100.0, 95.0, 100.0, 105.0])),
        ),
    )

    assert impact.measurement_status == "measured"
    assert impact.benchmark_relative_return_pct == round(((100 / 90) - (105 / 95)) * 100, 6)
    assert impact.peak_drawdown_pct == -10.0
    assert impact.recovery_days == 2
    assert impact.volatility_peak is not None


def test_price_history_without_pre_event_baseline_is_missing_evidence() -> None:
    with pytest.raises(MissingEvidenceError, match="pre-event baseline"):
        calculate_market_impact(
            load_event_fixtures()[1].impact,
            MarketPriceWindow(
                symbol="QQQ",
                prices={date(2010, 5, 6): 90.0},
                benchmark="SPY",
                benchmark_prices={date(2010, 5, 6): 95.0},
            ),
        )
