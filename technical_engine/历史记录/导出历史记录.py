#!/usr/bin/env python3
"""Export offline EOD Decision History without involving the Dashboard."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from 历史记录数据库 import export_rows, resolve_db_path


def main() -> int:
    parser = argparse.ArgumentParser(description="导出每日盘后 Decision History")
    parser.add_argument("--db", help="SQLite path; defaults to DECISION_HISTORY_DB_PATH / Render disk / local fallback")
    parser.add_argument("--from", dest="date_from", help="起始 market_date, YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", help="结束 market_date, YYYY-MM-DD")
    parser.add_argument("--format", choices=("csv", "json", "jsonl"), default="csv")
    parser.add_argument("--output", help="输出文件；默认 历史记录/导出/decision-history.<format>")
    args = parser.parse_args()
    rows = export_rows(args.db, args.date_from, args.date_to)
    output = Path(args.output) if args.output else Path(__file__).resolve().parent / "导出" / f"decision-history.{args.format}"
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "json":
        output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    elif args.format == "jsonl":
        output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    else:
        fieldnames = list(rows[0].keys()) if rows else []
        with output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            if fieldnames:
                writer.writeheader()
                writer.writerows(rows)
    print(f"Exported {len(rows)} rows from {resolve_db_path(args.db)} to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
