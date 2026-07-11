from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Iterable

import httpx
from pydantic import ValidationError

from shared.models import AnalyzeResponse

DEFAULT_ANALYST_BASE_URL = "https://finance-api.rxlab.workers.dev"
DEFAULT_BATCH_SIZE = 20
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_VERIFY_SAMPLE_SIZE = 5
DEFAULT_SUCCESS_THRESHOLD = 0.90

# Curated default warm set. Keep this configurable via WARMUP_SYMBOLS_FILE for
# repo-side overrides or later universe expansion.
DEFAULT_SP500_WARMUP_SYMBOLS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "GOOG",
    "META",
    "AVGO",
    "BRK-B",
    "TSLA",
    "JPM",
    "LLY",
    "V",
    "XOM",
    "MA",
    "UNH",
    "COST",
    "ORCL",
    "PG",
    "HD",
    "JNJ",
    "WMT",
    "BAC",
    "ABBV",
    "CRM",
    "NFLX",
    "AMD",
    "KO",
    "PEP",
    "MRK",
    "TMO",
    "CVX",
    "CSCO",
    "ACN",
    "MCD",
    "LIN",
    "IBM",
    "DIS",
    "WFC",
    "QCOM",
    "ABT",
    "GE",
    "TXN",
    "PM",
    "CAT",
    "NKE",
    "INTU",
    "NOW",
    "AMGN",
    "SBUX",
    "BKNG",
    "HON",
    "ISRG",
    "RTX",
    "LOW",
    "BLK",
    "DHR",
    "ADI",
    "ELV",
    "PYPL",
    "PFE",
    "T",
    "SCHW",
    "SPGI",
    "PLD",
    "GILD",
    "MDT",
    "MO",
    "USB",
    "LRCX",
    "MU",
    "MMM",
    "CI",
    "FIS",
    "ZTS",
    "C",
    "AMAT",
    "QSR",
    "FI",
    "AON",
    "DE",
    "TJX",
    "SO",
    "DUK",
    "APD",
    "ICE",
    "NSC",
    "GD",
    "ITW",
    "PNC",
    "CL",
    "MMC",
    "EOG",
    "ADP",
    "CME",
    "SHW",
    "BMY",
    "F",
    "LULU",
    "PANW",
    "SNPS",
    "KDP",
    "KHC",
    "REGN",
]

DEFAULT_SECTOR_ETFS = [
    "SPY",
    "QQQ",
    "DIA",
    "IWM",
    "XLB",
    "XLC",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLU",
    "XLV",
    "XLY",
    "XLRE",
    "SMH",
    "XBI",
    "KRE",
    "TAN",
    "ITB",
    "XOP",
]

DEFAULT_WATCHLIST = [
    "NVDA",
    "AAPL",
    "MSFT",
    "AMZN",
    "META",
    "GOOGL",
    "JPM",
    "TSLA",
    "COST",
    "ORCL",
]

REPO_SP500_UNIVERSE_PATH = Path(__file__).resolve().parents[1] / "screener_service" / "cache" / "universes" / "sp500.json"


@dataclass(frozen=True)
class BatchResult:
    requested_symbols: list[str]
    parsed_responses: list[AnalyzeResponse]
    parse_failures: list[dict[str, Any]]
    elapsed_seconds: float


@dataclass(frozen=True)
class WarmupSummary:
    total_symbols: int
    cached_symbols: int
    failed_symbols: int
    cache_hit_rate: float
    avg_data_quality_score: float | None
    total_batches: int
    elapsed_seconds: float
    verify_sample_size: int
    verify_avg_data_quality_score: float | None
    health_status: dict[str, Any] | None


def _emit(event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    sys.stdout.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
    sys.stdout.flush()


def _normalize_symbol(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    symbol = value.strip().upper()
    return symbol or None


def _dedupe_preserve_order(symbols: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(symbols))


def _load_json_symbols(path: Path) -> list[str]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text())
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, dict):
        raw_items = []
        for key in ("symbols", "sp500", "sector_etfs", "watchlist"):
            value = payload.get(key)
            if isinstance(value, list):
                raw_items.extend(value)
    else:
        raw_items = []
    normalized = [_normalize_symbol(item) for item in raw_items]
    return [symbol for symbol in normalized if symbol]


def load_symbols(symbols_file: str | None = None) -> list[str]:
    symbols = []
    file_path = symbols_file or os.getenv("WARMUP_SYMBOLS_FILE")
    if file_path:
        try:
            symbols.extend(_load_json_symbols(Path(file_path)))
        except Exception as exc:
            _emit("symbols_file_error", path=file_path, error=str(exc))
    try:
        symbols.extend(_load_json_symbols(REPO_SP500_UNIVERSE_PATH))
    except Exception as exc:
        _emit("repo_sp500_universe_error", path=str(REPO_SP500_UNIVERSE_PATH), error=str(exc))
    symbols.extend(DEFAULT_SP500_WARMUP_SYMBOLS)
    symbols.extend(DEFAULT_SECTOR_ETFS)
    symbols.extend(DEFAULT_WATCHLIST)
    return _dedupe_preserve_order(symbol for symbol in symbols if symbol)


def iter_batches(symbols: list[str], batch_size: int) -> Iterable[list[str]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    for index in range(0, len(symbols), batch_size):
        yield symbols[index : index + batch_size]


def _analyze_payload(symbols: list[str]) -> dict[str, Any]:
    return {"symbols": symbols, "include_narrative": False}


def _request_batch(
    client: httpx.Client,
    base_url: str,
    symbols: list[str],
) -> BatchResult:
    start = time.perf_counter()
    response = client.post(f"{base_url.rstrip('/')}/batch", json=_analyze_payload(symbols))
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError(f"unexpected batch response type: {type(payload).__name__}")

    parsed_responses: list[AnalyzeResponse] = []
    parse_failures: list[dict[str, Any]] = []
    for index, symbol in enumerate(symbols):
        if index >= len(payload):
            parse_failures.append({"symbol": symbol, "error": "missing response item"})
            continue
        item = payload[index]
        try:
            parsed_responses.append(AnalyzeResponse.model_validate(item))
        except ValidationError as exc:
            parse_failures.append({"symbol": symbol, "error": "response validation failed", "details": str(exc)})

    for extra_index in range(len(symbols), len(payload)):
        parse_failures.append({"symbol": None, "error": f"unexpected extra response item at index {extra_index}"})

    elapsed_seconds = time.perf_counter() - start
    return BatchResult(
        requested_symbols=list(symbols),
        parsed_responses=parsed_responses,
        parse_failures=parse_failures,
        elapsed_seconds=elapsed_seconds,
    )


def _request_health(client: httpx.Client, base_url: str) -> dict[str, Any] | None:
    try:
        response = client.get(f"{base_url.rstrip('/')}/health")
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else None
    except Exception as exc:
        _emit("health_check_failed", error=str(exc))
        return None


def _request_verify_sample(
    client: httpx.Client,
    base_url: str,
    symbols: list[str],
) -> list[AnalyzeResponse]:
    verified: list[AnalyzeResponse] = []
    for symbol in symbols:
        response = client.post(
            f"{base_url.rstrip('/')}/analyze",
            json={"symbol": symbol, "include_narrative": False, "include_entry": True},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"unexpected analyze response type for {symbol}: {type(payload).__name__}")
        verified.append(AnalyzeResponse.model_validate(payload))
    return verified


def run_warmup(
    *,
    base_url: str,
    symbols: list[str],
    batch_size: int,
    verify_sample_size: int = DEFAULT_VERIFY_SAMPLE_SIZE,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    emit: Callable[..., None] = _emit,
) -> WarmupSummary:
    client_timeout = httpx.Timeout(timeout_seconds, connect=10.0)
    total_cached = 0
    total_failed = 0
    quality_scores: list[float] = []
    batch_count = 0
    start = time.perf_counter()

    with httpx.Client(timeout=client_timeout) as client:
        health_status = _request_health(client, base_url)
        if health_status is not None:
            emit("health_status", **health_status)

        for batch_index, batch in enumerate(iter_batches(symbols, batch_size), start=1):
            batch_count += 1
            batch_start = time.perf_counter()
            try:
                batch_result = _request_batch(client, base_url, batch)
            except Exception as exc:
                total_failed += len(batch)
                emit(
                    "batch_failure",
                    batch_index=batch_index,
                    batch_size=len(batch),
                    symbols=batch,
                    error=str(exc),
                    elapsed_seconds=round(time.perf_counter() - batch_start, 3),
                )
                continue

            successes = len(batch_result.parsed_responses)
            failures = len(batch_result.parse_failures)
            total_cached += successes
            total_failed += len(batch) - successes
            quality_scores.extend(float(item.data_quality_score) for item in batch_result.parsed_responses)

            emit(
                "batch_summary",
                batch_index=batch_index,
                batch_size=len(batch),
                success_count=successes,
                failure_count=failures,
                avg_data_quality_score=(
                    round(mean(item.data_quality_score for item in batch_result.parsed_responses), 2)
                    if batch_result.parsed_responses
                    else None
                ),
                elapsed_seconds=round(batch_result.elapsed_seconds, 3),
                symbols=batch,
                parse_failures=batch_result.parse_failures,
            )

        verify_sample: list[AnalyzeResponse] = []
        if verify_sample_size > 0 and symbols:
            sample = symbols[: min(verify_sample_size, len(symbols))]
            try:
                verify_sample = _request_verify_sample(client, base_url, sample)
                emit(
                    "verification_sample",
                    sample_size=len(sample),
                    symbols=sample,
                    avg_data_quality_score=(
                        round(mean(item.data_quality_score for item in verify_sample), 2) if verify_sample else None
                    ),
                )
            except Exception as exc:
                emit("verification_failed", sample_symbols=sample, error=str(exc))

    elapsed_seconds = time.perf_counter() - start
    total_symbols = len(symbols)
    cache_hit_rate = (total_cached / total_symbols) if total_symbols else 0.0
    summary = WarmupSummary(
        total_symbols=total_symbols,
        cached_symbols=total_cached,
        failed_symbols=total_failed,
        cache_hit_rate=round(cache_hit_rate, 4),
        avg_data_quality_score=(round(mean(quality_scores), 2) if quality_scores else None),
        total_batches=batch_count,
        elapsed_seconds=round(elapsed_seconds, 3),
        verify_sample_size=len(verify_sample),
        verify_avg_data_quality_score=(
            round(mean(item.data_quality_score for item in verify_sample), 2) if verify_sample else None
        ),
        health_status=health_status,
    )
    emit("warmup_summary", **summary.__dict__)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Warm the analyst service cache by batching analysis requests.")
    parser.add_argument("--base-url", default=os.getenv("ANALYST_BASE_URL", DEFAULT_ANALYST_BASE_URL))
    parser.add_argument("--symbols-file", default=os.getenv("WARMUP_SYMBOLS_FILE"))
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("WARMUP_BATCH_SIZE", str(DEFAULT_BATCH_SIZE))))
    parser.add_argument(
        "--verify-sample-size",
        type=int,
        default=int(os.getenv("WARMUP_VERIFY_SAMPLE_SIZE", str(DEFAULT_VERIFY_SAMPLE_SIZE))),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(os.getenv("WARMUP_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))),
    )
    parser.add_argument(
        "--success-threshold",
        type=float,
        default=float(os.getenv("WARMUP_SUCCESS_THRESHOLD", str(DEFAULT_SUCCESS_THRESHOLD))),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    symbols = load_symbols(args.symbols_file)
    if not symbols:
        _emit("warmup_error", error="no warmup symbols available")
        return 1

    summary = run_warmup(
        base_url=args.base_url,
        symbols=symbols,
        batch_size=args.batch_size,
        verify_sample_size=args.verify_sample_size,
        timeout_seconds=args.timeout_seconds,
    )
    success_ratio = summary.cached_symbols / summary.total_symbols if summary.total_symbols else 0.0
    if success_ratio < args.success_threshold:
        _emit(
            "warmup_failed",
            success_ratio=round(success_ratio, 4),
            threshold=args.success_threshold,
            total_symbols=summary.total_symbols,
            cached_symbols=summary.cached_symbols,
            failed_symbols=summary.failed_symbols,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
