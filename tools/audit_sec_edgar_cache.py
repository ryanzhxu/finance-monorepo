from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtesting.sec_edgar_audit import audit_sec_edgar_cache


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit cached SEC companyfacts coverage without downloading data")
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--universe", type=Path, help="Optional universe.json reference used to measure cached-vs-uncached symbol coverage")
    parser.add_argument("--sample-limit", type=int, default=25)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit_sec_edgar_cache(args.cache_dir, universe_path=args.universe, sample_limit=args.sample_limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
