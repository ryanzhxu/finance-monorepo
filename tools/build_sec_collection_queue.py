from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtesting.sec_collection_queue import build_sec_collection_queue_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a cache-only ranked SEC collection queue")
    parser.add_argument("--free-price-cache-dir", type=Path, required=True)
    parser.add_argument("--free-price-run-id", required=True)
    parser.add_argument("--sec-cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=100)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_sec_collection_queue_report(
        free_price_cache_dir=args.free_price_cache_dir,
        free_price_run_id=args.free_price_run_id,
        sec_cache_dir=args.sec_cache_dir,
        batch_size=args.batch_size,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
