from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtesting.forecast import ForecastObservation
from backtesting.final_holdout_consumption import (
    DEFAULT_FINAL_HOLDOUT_CONSUMPTION_PATH,
    build_consumption_context,
    finalize_consumption,
    reserve_consumption,
)
from backtesting.forecast_final_holdout import (
    forecast_observation_fingerprint,
    fit_frozen_continuous_feature_artifact,
    score_final_holdout,
)
from backtesting.forecast_holdout import HOLDOUT_CONTRACT_SCHEMA
from backtesting.forecast_provenance import load_forecast_data_provenance


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train V3 on frozen selection data and score the immutable final holdout")
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--final-holdout", type=Path, required=True)
    parser.add_argument("--holdout-contract", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=500)
    parser.add_argument("--consumption-registry", type=Path, default=DEFAULT_FINAL_HOLDOUT_CONSUMPTION_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    selection = _load_observations(args.selection)
    contract = json.loads(args.holdout_contract.read_text(encoding="utf-8"))
    _validate_contract_metadata(contract, selection)
    provenance = load_forecast_data_provenance(args.provenance)
    artifact = fit_frozen_continuous_feature_artifact(
        selection,
        holdout_start=date.fromisoformat(contract["holdout_start"]),
        point_in_time_certified=provenance.point_in_time_certified,
    )
    context = build_consumption_context(
        artifact,
        holdout_contract=contract,
        provenance=provenance.model_dump(mode="json"),
        bootstrap_samples=args.bootstrap_samples,
    )
    reserve_consumption(args.consumption_registry, context)
    final_holdout = _load_observations(args.final_holdout)
    _validate_final_partition(contract, final_holdout)
    report = score_final_holdout(artifact, final_holdout, bootstrap_samples=args.bootstrap_samples)
    report["holdout_contract"] = contract
    report["provenance"] = provenance.model_dump(mode="json")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    finalize_consumption(args.consumption_registry, context, report=report, report_path=args.output)
    print(
        f"final-holdout calibration_status={report['calibration_status']} observations={report['out_of_sample_metrics']['out_of_sample_count']}",
        file=sys.stderr,
    )
    return 0


def _load_observations(path: Path) -> list[ForecastObservation]:
    with path.open(encoding="utf-8") as stream:
        return [ForecastObservation.model_validate_json(line) for line in stream if line.strip()]


def _validate_contract_metadata(contract: dict[str, Any], selection: list[ForecastObservation]) -> None:
    if contract.get("schema_version") != HOLDOUT_CONTRACT_SCHEMA:
        raise ValueError("unsupported holdout contract")
    if contract.get("status") != "ready":
        raise ValueError("holdout contract is not ready")
    selection_contract = contract.get("selection")
    final_contract = contract.get("final_holdout")
    if not isinstance(selection_contract, dict) or not isinstance(final_contract, dict):
        raise ValueError("holdout contract is missing partitions")
    if selection_contract.get("fingerprint") != forecast_observation_fingerprint(selection):
        raise ValueError("selection observations do not match the holdout contract")


def _validate_final_partition(contract: dict[str, Any], final_holdout: list[ForecastObservation]) -> None:
    final_contract = contract.get("final_holdout")
    if not isinstance(final_contract, dict):
        raise ValueError("holdout contract is missing the final holdout partition")
    if final_contract.get("fingerprint") != forecast_observation_fingerprint(final_holdout):
        raise ValueError("final holdout observations do not match the holdout contract")


if __name__ == "__main__":
    raise SystemExit(main())
