from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtesting.r2_storage import (
    DEFAULT_R2_BUCKET,
    R2StorageSettings,
    build_upload_plan,
    create_r2_client,
    download_verified_plan,
    upload_verified_plan,
)

DEFAULT_RESEARCH_STORAGE_LIMIT_BYTES = 8 * 1024**3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync selected research artifacts to private Cloudflare R2")
    parser.add_argument("--source", type=Path, required=True, help="One file or directory to sync")
    parser.add_argument("--key-prefix", required=True, help="Private R2 object key prefix")
    parser.add_argument("--storage-limit-bytes", type=int, default=DEFAULT_RESEARCH_STORAGE_LIMIT_BYTES)
    parser.add_argument("--upload", action="store_true", help="Perform the upload; without this flag, only print the plan")
    parser.add_argument(
        "--verify-download-dir",
        type=Path,
        help="Download the selected remote objects into this directory and verify their checksums",
    )
    return parser.parse_args()


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = parse_args()
    plan = build_upload_plan(args.source, args.key_prefix)
    summary = {
        "bucket": DEFAULT_R2_BUCKET,
        "upload": args.upload,
        "verify_download_dir": str(args.verify_download_dir) if args.verify_download_dir else None,
        "object_count": len(plan),
        "total_bytes": sum(item.size_bytes for item in plan),
        "objects": [{"key": item.key, "size_bytes": item.size_bytes, "sha256": item.sha256} for item in plan],
    }
    if args.upload or args.verify_download_dir:
        settings = R2StorageSettings.from_environment()
        client = create_r2_client(settings)
    else:
        client = None
    if args.upload:
        summary["uploaded"] = upload_verified_plan(
            client,
            settings.bucket,
            plan,
            storage_limit_bytes=args.storage_limit_bytes,
        )
    if args.verify_download_dir:
        summary["downloaded"] = download_verified_plan(
            client,
            settings.bucket,
            plan,
            destination_dir=args.verify_download_dir,
        )
        summary["round_trip_verified"] = True
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
