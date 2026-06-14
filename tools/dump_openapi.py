from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OPENAPI_DIR = ROOT / "openapi"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analyst_service.api.main import app as analyst_app
from screener_service.api.main import app as screener_app


def dump_spec(filename: str, app) -> None:
    OPENAPI_DIR.mkdir(parents=True, exist_ok=True)
    payload = app.openapi()
    target = OPENAPI_DIR / filename
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    dump_spec("analyst.json", analyst_app)
    dump_spec("screener.json", screener_app)


if __name__ == "__main__":
    main()
