from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtesting.forecast import ForecastObservation
from backtesting.forecast_feature_model import build_continuous_feature_report, fit_continuous_feature_model
from backtesting.forecast_provenance import load_forecast_data_provenance
from backtesting.sec_edgar import SecEdgarProvenance
from backtesting.sec_fundamental_features import COMBINED_FEATURE_SCHEMA


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fit the continuous price/regime forecast baseline")
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--fundamentals-provenance", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    observations = _load_observations(args.observations)
    provenance = load_forecast_data_provenance(args.provenance)
    if observations and observations[0].feature_schema_version == COMBINED_FEATURE_SCHEMA and args.fundamentals_provenance is None:
        raise SystemExit("--fundamentals-provenance is required for SEC-enriched observations")
    model = fit_continuous_feature_model(observations, point_in_time_certified=provenance.point_in_time_certified)
    report = build_continuous_feature_report(model)
    report["provenance"] = provenance.model_dump(mode="json")
    if args.fundamentals_provenance is not None:
        report["fundamentals_provenance"] = SecEdgarProvenance.model_validate_json(
            args.fundamentals_provenance.read_text(encoding="utf-8")
        ).model_dump(mode="json")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"continuous feature calibration_status={model.status} observations={len(observations)}", file=sys.stderr)
    return 0


def _load_observations(path: Path) -> list[ForecastObservation]:
    return [ForecastObservation.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
