from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SmokeCheck:
    name: str
    method: str
    path: str
    service: str
    payload: dict[str, Any] | None = None
    query: dict[str, Any] | None = None


CHECKS: tuple[SmokeCheck, ...] = (
    SmokeCheck("frontend_root", "GET", "/", "frontend"),
    SmokeCheck("analyst_health", "GET", "/health", "analyst"),
    SmokeCheck("analyst_search", "GET", "/search", "analyst", query={"q": "nvda", "limit": 3}),
    SmokeCheck(
        "analyst_entry",
        "POST",
        "/entry",
        "analyst",
        payload={"symbol": "NVDA", "asset_type": "STOCK", "horizon": "2-4W", "current_price": 208.65},
    ),
    SmokeCheck("screener_health", "GET", "/screen/health", "screener"),
    SmokeCheck("screener_regime", "GET", "/screen/regime", "screener"),
    SmokeCheck(
        "screener_demand_shock",
        "POST",
        "/screen/demand-shock",
        "screener",
        payload={
            "universe": "CUSTOM",
            "tickers": ["NVDA", "KO"],
            "limit": 2,
            "horizon": "2-4W",
            "include_analysis": False,
            "include_narrative": False,
            "lookback_days": 30,
        },
    ),
    SmokeCheck(
        "screener_custom",
        "POST",
        "/screen/custom",
        "screener",
        payload={
            "universe": "CUSTOM",
            "tickers": ["NVDA", "KO"],
            "limit": 2,
            "horizon": "2-4W",
            "include_analysis": False,
            "include_narrative": False,
            "lookback_days": 30,
        },
    ),
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deployed smoke checks against a Render environment.")
    parser.add_argument("--environment", required=True, help="Environment label to show in logs, e.g. dev or prod.")
    parser.add_argument("--frontend-url", required=True, help="Base frontend URL.")
    parser.add_argument("--analyst-url", required=True, help="Base analyst service URL.")
    parser.add_argument("--screener-url", required=True, help="Base screener service URL.")
    parser.add_argument("--retries", type=int, default=1, help="Number of full-suite attempts before failing.")
    parser.add_argument("--retry-delay", type=int, default=30, help="Seconds to wait between attempts.")
    parser.add_argument("--timeout", type=int, default=35, help="Per-request timeout in seconds.")
    return parser.parse_args()


def _base_urls(args: argparse.Namespace) -> dict[str, str]:
    return {
        "frontend": args.frontend_url.rstrip("/"),
        "analyst": args.analyst_url.rstrip("/"),
        "screener": args.screener_url.rstrip("/"),
    }


def _build_url(base_url: str, check: SmokeCheck) -> str:
    path = check.path if check.path.startswith("/") else f"/{check.path}"
    url = f"{base_url}{path}"
    if check.query:
        url = f"{url}?{urllib.parse.urlencode(check.query)}"
    return url


def _extract_summary(check_name: str, body: str, content_type: str) -> dict[str, Any] | None:
    if "application/json" not in content_type:
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None

    if check_name == "analyst_health":
        return {
            "status": payload.get("status"),
            "cache_backend": payload.get("cache_backend"),
            "provider_keys": sorted((payload.get("providers") or {}).keys()),
        }
    if check_name == "analyst_search":
        return {
            "count": len(payload) if isinstance(payload, list) else None,
            "first": payload[0] if isinstance(payload, list) and payload else None,
        }
    if check_name == "analyst_entry":
        return {
            "current_price": payload.get("current_price"),
            "entry_assessment": payload.get("entry_assessment"),
            "risk_reward_ratio": payload.get("risk_reward_ratio"),
        }
    if check_name == "screener_health":
        return {
            "status": payload.get("status"),
            "cache_backend": payload.get("cache_backend"),
            "providers": payload.get("providers"),
        }
    if check_name == "screener_regime":
        return {
            "market_regime": payload.get("market_regime"),
            "days_to_next_fomc": payload.get("days_to_next_fomc"),
        }
    if check_name == "screener_demand_shock":
        return {
            "screen_type": payload.get("screen_type"),
            "result_count": len(payload.get("results", [])) if isinstance(payload, dict) else None,
        }
    if check_name == "screener_custom":
        return {
            "screen_type": payload.get("screen_type"),
            "result_count": len(payload.get("results", [])) if isinstance(payload, dict) else None,
        }
    return None


def _run_check(
    environment: str,
    base_urls: dict[str, str],
    check: SmokeCheck,
    timeout: int,
    ssl_context: ssl.SSLContext,
) -> dict[str, Any]:
    url = _build_url(base_urls[check.service], check)
    headers = {"User-Agent": "finance-monorepo-smoke/1.0"}
    data = None
    if check.payload is not None:
        data = json.dumps(check.payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=check.method)

    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context) as response:
            body = response.read().decode("utf-8", errors="replace")
            content_type = response.headers.get("Content-Type", "")
            result: dict[str, Any] = {
                "environment": environment,
                "check": check.name,
                "ok": 200 <= response.status < 300,
                "status": response.status,
                "url": url,
            }
            summary = _extract_summary(check.name, body, content_type)
            if summary is not None:
                result["summary"] = summary
            else:
                result["body_preview"] = body[:200]
            return result
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "environment": environment,
            "check": check.name,
            "ok": False,
            "status": exc.code,
            "url": url,
            "body_preview": body[:300],
        }
    except Exception as exc:  # pragma: no cover - network-level failures vary
        return {
            "environment": environment,
            "check": check.name,
            "ok": False,
            "status": None,
            "url": url,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _write_step_summary(environment: str, attempt: int, retries: int, results: list[dict[str, Any]]) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    all_ok = all(result["ok"] for result in results)
    lines = [
        f"# {environment.title()} Smoke Test Summary",
        "",
        f"- Attempts used: {attempt}/{retries}",
        f"- Overall status: {'PASS' if all_ok else 'FAIL'}",
        "",
        "| Check | Status | HTTP | Notes |",
        "| --- | --- | --- | --- |",
    ]
    for result in results:
        if "summary" in result:
            notes = json.dumps(result["summary"], ensure_ascii=True)
        elif "error" in result:
            notes = result["error"]
        else:
            notes = result.get("body_preview", "")
        notes = notes.replace("\n", " ")[:180]
        lines.append(
            f"| `{result['check']}` | {'PASS' if result['ok'] else 'FAIL'} | {result['status'] if result['status'] is not None else '-'} | {notes} |"
        )

    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
        handle.write("\n")


def main() -> int:
    args = _parse_args()
    if args.retries < 1:
        raise SystemExit("--retries must be at least 1")
    if args.retry_delay < 0:
        raise SystemExit("--retry-delay must be zero or greater")

    ssl_context = ssl.create_default_context()
    base_urls = _base_urls(args)
    final_results: list[dict[str, Any]] = []
    final_attempt = 0

    for attempt in range(1, args.retries + 1):
        final_attempt = attempt
        print(f"Running {args.environment} smoke suite attempt {attempt}/{args.retries}...", flush=True)
        results = [_run_check(args.environment, base_urls, check, args.timeout, ssl_context) for check in CHECKS]
        final_results = results
        print(json.dumps(results, indent=2), flush=True)
        if all(result["ok"] for result in results):
            break
        if attempt < args.retries:
            print(f"Attempt {attempt} failed; retrying in {args.retry_delay}s.", flush=True)
            time.sleep(args.retry_delay)

    _write_step_summary(args.environment, final_attempt, args.retries, final_results)

    failures = [result for result in final_results if not result["ok"]]
    if failures:
        print(f"{args.environment} smoke suite failed with {len(failures)} failing checks.", file=sys.stderr)
        return 1

    print(f"{args.environment} smoke suite passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
