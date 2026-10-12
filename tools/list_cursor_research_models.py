from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from analyst_service.core.research_provider import list_cursor_models


def main() -> None:
    load_dotenv()
    print(json.dumps(asyncio.run(list_cursor_models()), indent=2))


if __name__ == "__main__":
    main()
