#!/usr/bin/env python3
"""Manual development entry point for the server-side EOD recorder.

Run `python3 历史记录/历史记录.py --run-now` locally to exercise the same
full refresh, production JS Decision Engine, and SQLite writer used on Render.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server


def main() -> int:
    parser = argparse.ArgumentParser(description="手动执行每日盘后 Decision History 记录")
    parser.add_argument("--run-now", action="store_true", help="现在运行一次；仍验证今日有效交易 session")
    args = parser.parse_args()
    if not args.run_now:
        parser.error("仅支持 --run-now；日常运行由 Render server-side scheduler 完成。")
    result = server.run_eod_history_once(reason="manual_dev_run")
    print(result)
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
