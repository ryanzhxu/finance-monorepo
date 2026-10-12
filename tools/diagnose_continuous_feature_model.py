from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtesting.forecast import ForecastObservation
from backtesting.forecast_feature_model import fit_continuous_feature_model
from backtesting.forecast_provenance import load_forecast_data_provenance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write fold/regime diagnostics for the continuous forecast baseline")
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    observations = [
        ForecastObservation.model_validate_json(line)
        for line in args.observations.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    provenance = load_forecast_data_provenance(args.provenance)
    model = fit_continuous_feature_model(observations, point_in_time_certified=provenance.point_in_time_certified)
    diagnostics = dict(model.diagnostics)
    diagnostics["provenance"] = provenance.model_dump(mode="json")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(diagnostics, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"continuous feature diagnostics calibration_status={model.status} observations={len(observations)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
