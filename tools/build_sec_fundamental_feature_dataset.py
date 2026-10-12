from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtesting.forecast import ForecastObservation
from backtesting.sec_edgar import SecFundamentalObservation
from backtesting.sec_fundamental_features import attach_sec_fundamental_features, build_sec_fundamental_feature_snapshots


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Join filing-date-aware SEC fundamentals onto v3 forecast observations")
    parser.add_argument("--forecast-observations", type=Path, required=True)
    parser.add_argument("--sec-observations", type=Path, required=True)
    parser.add_argument("--features-output", type=Path, required=True)
    parser.add_argument("--joined-output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    forecast_observations = _load_forecast_observations(args.forecast_observations)
    sec_observations = _load_sec_observations(args.sec_observations)
    by_symbol: dict[str, list[ForecastObservation]] = defaultdict(list)
    for observation in forecast_observations:
        by_symbol[observation.symbol].append(observation)
    sec_by_symbol: dict[str, list[SecFundamentalObservation]] = defaultdict(list)
    for observation in sec_observations:
        if observation.symbol:
            sec_by_symbol[observation.symbol].append(observation)
    snapshots = [
        snapshot
        for symbol, rows in sorted(by_symbol.items())
        for snapshot in build_sec_fundamental_feature_snapshots(symbol, [row.as_of for row in rows], sec_by_symbol[symbol])
    ]
    joined, skipped = attach_sec_fundamental_features(forecast_observations, snapshots)
    _write_jsonl(args.features_output, snapshots)
    _write_jsonl(args.joined_output, joined)
    print(
        json.dumps(
            {
                "forecast_observations": len(forecast_observations),
                "sec_observations": len(sec_observations),
                "feature_snapshots": len(snapshots),
                "joined_observations": len(joined),
                "skipped": skipped,
            },
            indent=2,
        )
    )
    return 0


def _load_forecast_observations(path: Path) -> list[ForecastObservation]:
    return [ForecastObservation.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _load_sec_observations(path: Path) -> list[SecFundamentalObservation]:
    return [SecFundamentalObservation.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(row.model_dump_json() + "\n" for row in rows), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
