from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
except ImportError:
    pass
else:
    load_dotenv(ROOT / ".env")

sys.path.insert(0, str(ROOT))

from analyst_service.core.cache import backend_name as cache_backend_name
from analyst_service.core.data_fetcher import fetch_fundamentals, fetch_sentiment


def _load_symbols() -> list[str]:
    return [symbol.strip().upper() for symbol in os.getenv("SYMBOLS", "").split(",") if symbol.strip()]


def _main() -> int:
    if not os.getenv("REDIS_URL"):
        print("[warn] REDIS_URL not set; cache backend may fall back to file storage.", file=sys.stderr)
    else:
        print(f"[info] cache backend={cache_backend_name()}")

    symbols = _load_symbols()
    if not symbols:
        print("[error] SYMBOLS is required (comma-separated tickers).", file=sys.stderr)
        return 1

    failures = 0

    for symbol in symbols:
        symbol_failed = False

        try:
            fundamentals = fetch_fundamentals(symbol).value
            print(
                f"[{symbol}] fundamentals cached "
                f"(eps_surprise={fundamentals.eps_surprise_pct}, pe={fundamentals.pe_ratio}, "
                f"pe_percentile={fundamentals.pe_percentile_5y}, upgrades={fundamentals.analyst_upgrades_30d}, "
                f"downgrades={fundamentals.analyst_downgrades_30d})"
            )
        except Exception as exc:
            symbol_failed = True
            print(f"[{symbol}] fundamentals error: {exc}", file=sys.stderr)

        try:
            sentiment = fetch_sentiment(symbol).value
            print(
                f"[{symbol}] sentiment cached "
                f"(put_call_ratio={sentiment.put_call_ratio}, short_interest_pct={sentiment.short_interest_pct}, "
                f"news_sentiment_score={sentiment.news_sentiment_score})"
            )
        except Exception as exc:
            symbol_failed = True
            print(f"[{symbol}] sentiment error: {exc}", file=sys.stderr)

        if symbol_failed:
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_main())
