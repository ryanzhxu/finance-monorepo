from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtesting.forecast_audit import build_continuous_feature_audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit continuous forecast diagnostics without refitting")
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    diagnostics = json.loads(args.diagnostics.read_text(encoding="utf-8"))
    audit = build_continuous_feature_audit(diagnostics)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(f"continuous feature audit promotion_decision={audit['promotion_decision']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
