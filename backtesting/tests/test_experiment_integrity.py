from __future__ import annotations

from datetime import date
import json

import pytest

from backtesting.experiment_integrity import (
    HoldoutConsumptionError,
    HoldoutConsumptionKey,
    HoldoutConsumptionRegistry,
    SecBatchLedger,
    SecFailureClass,
    SecFetchResult,
    SecSymbolStatus,
    classify_sec_failure,
    execute_sec_batch,
)


def _hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()


def _key(*, model: str = "candidate-v1", start: date = date(2025, 1, 1)) -> HoldoutConsumptionKey:
    return HoldoutConsumptionKey(
        model_version=model,
        label_version="next_open_low_v2",
        feature_schema_version="features-v1",
        dataset_provenance_fingerprint=_hash("dataset"),
        selection_artifact_hash=_hash("selection"),
        evaluation_config_hash=_hash("config"),
        holdout_start=start,
        holdout_end=date(2025, 12, 31),
    )


def test_holdout_reservation_happens_before_a_loader_can_run(tmp_path) -> None:
    registry = HoldoutConsumptionRegistry(tmp_path / "consumption.json")
    key = _key()
    loader_called = False

    registry.reserve_before_load(key)

    with pytest.raises(HoldoutConsumptionError, match="identical"):
        registry.reserve_before_load(key)
    assert loader_called is False

    registry.finalize(key, report={"result": "unavailable"}, report_path=tmp_path / "report.json")
    payload = json.loads((tmp_path / "consumption.json").read_text())
    assert payload["records"][key.value]["status"] == "consumed"


def test_distinct_configuration_cannot_reuse_the_same_holdout_slot(tmp_path) -> None:
    registry = HoldoutConsumptionRegistry(tmp_path / "consumption.json")
    registry.reserve_before_load(_key(model="candidate-v1"))

    with pytest.raises(HoldoutConsumptionError, match="window"):
        registry.reserve_before_load(_key(model="candidate-v2"))


def test_legacy_2023_2024_holdout_is_blocked_before_loading_data(tmp_path) -> None:
    registry = HoldoutConsumptionRegistry(tmp_path / "consumption.json")

    with pytest.raises(HoldoutConsumptionError, match="2023-2024"):
        registry.reserve_before_load(_key(start=date(2023, 6, 1)))


def test_sec_batch_resumes_only_unresolved_symbols_and_classifies_failures(tmp_path) -> None:
    path = tmp_path / "runs" / "batch-1.json"
    ledger = SecBatchLedger(path, run_id="batch-1", requested_symbols=("AAPL", "MSFT", "MISSING"))
    calls: list[str] = []

    def first_fetch(symbol: str) -> SecFetchResult | None:
        calls.append(symbol)
        if symbol == "AAPL":
            return SecFetchResult(cik="0000320193", cache_file="companyfacts/0000320193.json", observation_count=2)
        if symbol == "MISSING":
            return None
        raise TimeoutError("SEC timed out")

    first = execute_sec_batch(ledger, first_fetch)
    assert calls == ["AAPL", "MISSING", "MSFT"]
    assert first.status == "systemic_failure"
    assert first.results["AAPL"].status == SecSymbolStatus.COMPLETED
    assert first.results["MISSING"].failure_class == SecFailureClass.MISSING_OR_UNMAPPED
    assert first.results["MSFT"].failure_class == SecFailureClass.TRANSPORT
    assert first.results["MSFT"].status == SecSymbolStatus.SYSTEMIC_FAILURE

    resumed = SecBatchLedger(path, run_id="batch-1", requested_symbols=("AAPL", "MSFT", "MISSING"), resume=True)
    second_calls: list[str] = []
    final = execute_sec_batch(
        resumed,
        lambda symbol: second_calls.append(symbol)
        or SecFetchResult(cik="0000789019", cache_file="companyfacts/0000789019.json", observation_count=1),
    )
    assert second_calls == ["MSFT"]
    assert final.status == "completed"
    assert final.results["AAPL"].status == SecSymbolStatus.COMPLETED


def test_sec_failure_classifier_keeps_missing_separate_from_systemic() -> None:
    class ResponseError(Exception):
        response = type("Response", (), {"status_code": 404})()

    assert classify_sec_failure(ResponseError()) == SecFailureClass.MISSING_OR_UNMAPPED
    assert classify_sec_failure(TimeoutError("timeout")) == SecFailureClass.TRANSPORT
