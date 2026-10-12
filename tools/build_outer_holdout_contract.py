from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtesting.forecast import ForecastObservation
from backtesting.forecast_holdout import DEFAULT_FINAL_HOLDOUT_START, build_outer_holdout_contract, split_outer_holdout


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build immutable selection and final-holdout forecast artifacts")
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--selection-output", type=Path, required=True)
    parser.add_argument("--holdout-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    parser.add_argument("--holdout-start", type=date.fromisoformat, default=DEFAULT_FINAL_HOLDOUT_START)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    observations = [
        ForecastObservation.model_validate_json(line)
        for line in args.observations.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    split = split_outer_holdout(observations, holdout_start=args.holdout_start)
    report = build_outer_holdout_contract(split)
    _write_jsonl(args.selection_output, split.selection)
    _write_jsonl(args.holdout_output, split.final_holdout)
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(
        f"outer holdout status={report['status']} selection={len(split.selection)} final={len(split.final_holdout)}",
        file=sys.stderr,
    )
    return 0


def _write_jsonl(path: Path, observations: tuple[ForecastObservation, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(item.model_dump_json() + "\n" for item in observations),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
