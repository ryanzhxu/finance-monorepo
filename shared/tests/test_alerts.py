from __future__ import annotations

from datetime import datetime, timedelta, timezone

from shared.alerts import (
    AlertLedger,
    AlertLifecycle,
    AlertTrigger,
    WatchlistState,
    evaluate_watchlist_change,
)
from shared.enums import Freshness


def _state(**changes) -> WatchlistState:
    values = {
        "symbol": "NVDA",
        "observed_at": datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
        "entry_assessment": "buy_now",
        "in_ideal_buy_zone": False,
        "risk_flags": (),
        "data_quality_score": 92,
        "data_freshness": {"price": Freshness.LAST_CLOSE},
        "verified_event_ids": (),
        "regime": "neutral",
    }
    values.update(changes)
    return WatchlistState(**values)


def test_dry_run_emits_state_change_alerts_with_evidence_free_contract() -> None:
    current = _state(
        entry_assessment="wait_for_pullback",
        in_ideal_buy_zone=True,
        risk_flags=("gap_risk",),
        data_quality_score=60,
        data_freshness={"price": Freshness.STALE},
        verified_event_ids=("flash-crash-2010",),
        regime="risk_off",
    )

    alerts = evaluate_watchlist_change(_state(), current)
    triggers = {alert.trigger for alert in alerts}

    assert triggers == {
        AlertTrigger.ENTRY_ASSESSMENT_CHANGED,
        AlertTrigger.IDEAL_BUY_ZONE_CHANGED,
        AlertTrigger.RISK_FLAG_CHANGED,
        AlertTrigger.DATA_QUALITY_BELOW_THRESHOLD,
        AlertTrigger.VERIFIED_EVENT_CONTEXT_ADDED,
        AlertTrigger.REGIME_CHANGED,
        AlertTrigger.STALE_ANALYSIS,
    }
    assert all("position" not in alert.model_dump_json() for alert in alerts)
    assert all(alert.suppression_until > alert.generated_at for alert in alerts)


def test_ledger_deduplicates_and_supports_mute_acknowledge_dismiss() -> None:
    current = _state(entry_assessment="wait_for_pullback")
    alerts = evaluate_watchlist_change(_state(), current)
    ledger = AlertLedger()

    first = ledger.emit(alerts)
    second = ledger.emit(alerts)
    assert len(first) == 1
    assert second == ()

    ledger.acknowledge(first[0].alert_id)
    assert ledger.lifecycle(first[0].alert_id) == AlertLifecycle.ACKNOWLEDGED
    ledger.dismiss(first[0].alert_id)
    assert ledger.lifecycle(first[0].alert_id) == AlertLifecycle.DISMISSED

    ledger.mute("NVDA")
    changed_again = evaluate_watchlist_change(
        current,
        current.model_copy(
            update={
                "observed_at": current.observed_at + timedelta(hours=2),
                "entry_assessment": "avoid",
            }
        ),
    )
    assert ledger.emit(changed_again) == ()


def test_ledger_allows_same_state_alert_after_suppression_window() -> None:
    initial = _state()
    changed = initial.model_copy(
        update={
            "observed_at": initial.observed_at + timedelta(minutes=1),
            "entry_assessment": "wait_for_pullback",
        }
    )
    repeated = changed.model_copy(
        update={"observed_at": changed.observed_at + timedelta(minutes=61)}
    )
    prior_to_repeated = initial.model_copy(
        update={"observed_at": repeated.observed_at - timedelta(minutes=1)}
    )
    ledger = AlertLedger()

    first = ledger.emit(evaluate_watchlist_change(initial, changed))
    second = ledger.emit(evaluate_watchlist_change(prior_to_repeated, repeated))

    assert len(first) == 1
    assert len(second) == 1
    assert second[0].deduplication_key == first[0].deduplication_key


def test_unchanged_state_does_not_alert() -> None:
    assert evaluate_watchlist_change(_state(), _state()) == ()
