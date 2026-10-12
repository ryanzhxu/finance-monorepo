from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_SEC_EDGAR_CACHE_DIR = Path(__file__).resolve().parent / "cache" / "sec_edgar"


def companyfacts_cache_path(cache_dir: Path, cik: str) -> Path:
    return cache_dir / "companyfacts" / f"{cik}.json"


def ticker_mapping_cache_path(cache_dir: Path) -> Path:
    return cache_dir / "company_tickers.json"


def read_cached_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def write_cached_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        temporary_path = Path(handle.name)
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
    try:
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
