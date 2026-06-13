from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from shared.data_quality import FreshValue
from shared.enums import Freshness, Universe
from shared.time_utils import is_stale

from screener_service.core.settings import load_screener_config

CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "universes"
UNIVERSE_TTL_SECONDS = 7 * 24 * 60 * 60


def resolve_universe(universe: Universe, tickers: list[str] | None = None) -> FreshValue[list[str]]:
    if universe in {Universe.CUSTOM, Universe.WATCHLIST}:
        symbols = sorted({ticker.strip().upper() for ticker in (tickers or []) if ticker.strip()})
        freshness = Freshness.LIVE if symbols else Freshness.MISSING
        return FreshValue(symbols, freshness, datetime.now(timezone.utc) if symbols else None)

    cached = _read_cache(universe)
    if cached is not None:
        symbols, as_of = cached
        freshness = Freshness.STALE if is_stale(as_of, UNIVERSE_TTL_SECONDS) else Freshness.DELAYED
        if symbols and freshness != Freshness.STALE:
            return FreshValue(symbols, freshness, as_of)

    configured = load_screener_config()["universes"].get(universe.value, [])
    symbols = sorted({str(ticker).strip().upper() for ticker in configured if str(ticker).strip()})
    if not symbols:
        return FreshValue([], Freshness.MISSING, None)
    as_of = datetime.now(timezone.utc)
    _write_cache(universe, symbols, as_of)
    return FreshValue(symbols, Freshness.DELAYED, as_of)


def _read_cache(universe: Universe) -> tuple[list[str], datetime] | None:
    path = CACHE_DIR / f"{universe.value.lower()}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        symbols = [str(symbol).upper() for symbol in data["symbols"]]
        as_of = datetime.fromisoformat(data["as_of"])
        return symbols, as_of
    except Exception:
        return None


def _write_cache(universe: Universe, symbols: list[str], as_of: datetime) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{universe.value.lower()}.json"
    path.write_text(json.dumps({"as_of": as_of.isoformat(), "symbols": symbols}, indent=2), encoding="utf-8")
