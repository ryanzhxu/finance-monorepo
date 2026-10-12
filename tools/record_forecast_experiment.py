from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtesting.forecast_experiments import build_experiment_manifest, compare_challenger_to_champion, compare_selection_candidate_to_champion


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record and compare an offline forecast experiment")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--hypothesis", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--champion", type=Path)
    parser.add_argument("--selection-only", action="store_true", help="Compare offline selection experiments without numeric forecast promotion")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report_bytes = args.report.read_bytes()
    manifest = build_experiment_manifest(
        json.loads(report_bytes),
        name=args.name,
        hypothesis=args.hypothesis,
        observations_sha256=_sha256_file(args.observations),
        report_sha256=sha256(report_bytes).hexdigest(),
    )
    result: dict[str, object] = {"experiment": manifest}
    if args.champion is not None:
        champion = _load_champion(args.champion)
        decision = (
            compare_selection_candidate_to_champion(champion, manifest)
            if args.selection_only
            else compare_challenger_to_champion(champion, manifest)
        )
        result["selection_champion_decision" if args.selection_only else "champion_decision"] = decision
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_champion(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("champion file must contain an experiment manifest")
    wrapped = payload.get("experiment")
    if isinstance(wrapped, dict):
        return wrapped
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
