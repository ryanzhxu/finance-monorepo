from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtesting.forecast import ForecastObservation, fit_forecast_model
from backtesting.forecast_artifact import build_forecast_run_report
from backtesting.forecast_provenance import load_forecast_data_provenance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fit the point-in-time forecast baseline and write its report")
    parser.add_argument("--observations", type=Path, required=True, help="JSONL ForecastObservation file")
    parser.add_argument("--output", type=Path, required=True, help="Output JSON report path")
    parser.add_argument("--provenance", type=Path, help="Price-data provenance JSON; missing provenance fails closed")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    observations = [
        ForecastObservation.model_validate_json(line)
        for line in args.observations.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    provenance = load_forecast_data_provenance(args.provenance) if args.provenance is not None else None
    model = fit_forecast_model(
        observations,
        point_in_time_certified=provenance.point_in_time_certified if provenance is not None else False,
    )
    report = build_forecast_run_report(model, as_of=args.as_of)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"forecast calibration_status={report.calibration_status} observations={len(observations)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
