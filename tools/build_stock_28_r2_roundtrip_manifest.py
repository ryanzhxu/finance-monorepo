from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtesting.stock_28_roundtrip_manifest import build_stock_28_r2_roundtrip_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a private STOCK-28 R2 round-trip manifest from local artifacts")
    parser.add_argument("--key-prefix", required=True)
    parser.add_argument("--download-root", type=Path, required=True)
    parser.add_argument("--free-price-manifest", type=Path, required=True)
    parser.add_argument("--coverage-report", type=Path, required=True)
    parser.add_argument("--sec-cache-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build_stock_28_r2_roundtrip_manifest(
        key_prefix=args.key_prefix,
        download_root=args.download_root,
        free_price_manifest_path=args.free_price_manifest,
        coverage_report_path=args.coverage_report,
        sec_cache_audit_path=args.sec_cache_audit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
