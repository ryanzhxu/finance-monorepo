from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtesting.data_coverage_report import build_stock_coverage_bias_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a cache-only stock data coverage and bias report")
    parser.add_argument("--free-price-cache-dir", type=Path, required=True)
    parser.add_argument("--free-price-run-id", required=True)
    parser.add_argument("--sec-cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-limit", type=int, default=25)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_stock_coverage_bias_report(
        free_price_cache_dir=args.free_price_cache_dir,
        free_price_run_id=args.free_price_run_id,
        sec_cache_dir=args.sec_cache_dir,
        sample_limit=args.sample_limit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
