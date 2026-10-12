import json
from datetime import date
from types import SimpleNamespace

import httpx

from backtesting.sec_edgar import (
    SEC_COMPANY_TICKERS_URL,
    build_sec_fundamental_observations,
    fetch_sec_json,
    resolve_sec_ciks,
)
from backtesting.sec_edgar_cache import write_cached_json
from tools import download_sec_edgar_fundamentals
from tools.download_sec_edgar_fundamentals import _normalized_cik, _requested_symbols


def _companyfacts_payload(cik: int) -> dict[str, object]:
    return {
        "cik": cik,
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [{"form": "10-Q", "filed": "2024-05-03", "end": "2024-03-30", "val": 90, "accn": "a"}]
                    }
                }
            }
        },
    }


def test_sec_fundamentals_use_next_business_day_after_filing() -> None:
    observations = build_sec_fundamental_observations(
        {
            "cik": 320193,
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {"form": "10-Q", "filed": "2024-05-03", "end": "2024-03-30", "val": 90, "accn": "a"},
                                {"form": "8-K", "filed": "2024-05-03", "end": "2024-03-30", "val": 91, "accn": "b"},
                            ]
                        }
                    }
                }
            },
        },
        symbol="aapl",
    )

    assert len(observations) == 1
    assert observations[0].cik == "0000320193"
    assert observations[0].symbol == "AAPL"
    assert observations[0].available_on == date(2024, 5, 6)


def test_cik_resolution_uses_official_ticker_mapping() -> None:
    resolved = resolve_sec_ciks(
        ["aapl", "missing"],
        get_json=lambda url: {
            "0": {"ticker": "AAPL", "cik_str": 320193},
            "1": {"ticker": "MSFT", "cik_str": 789019},
        }
        if url == SEC_COMPANY_TICKERS_URL
        else {},
    )

    assert resolved == {"AAPL": "0000320193"}


def test_sec_fetch_requires_a_contact_user_agent_and_sends_it(monkeypatch) -> None:
    request = httpx.Request("GET", "https://example.test")
    seen: dict[str, object] = {}

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        seen["url"] = url
        seen["headers"] = kwargs["headers"]
        return httpx.Response(200, request=request, json={"ok": True})

    monkeypatch.setattr("backtesting.sec_edgar.httpx.get", fake_get)

    assert fetch_sec_json("https://example.test", user_agent="finance-research contact=owner@example.com") == {"ok": True}
    assert seen["headers"] == {"User-Agent": "finance-research contact=owner@example.com", "Accept": "application/json"}


def test_manual_cik_is_normalized_for_sec_endpoint() -> None:
    assert _normalized_cik("320193") == "0000320193"


def test_symbols_file_accepts_newline_or_comma_separated_values(tmp_path) -> None:
    symbols_file = tmp_path / "symbols.txt"
    symbols_file.write_text("msft, aapl\nNVDA\n", encoding="utf-8")

    assert _requested_symbols(SimpleNamespace(symbols=None, symbols_file=symbols_file)) == ["AAPL", "MSFT", "NVDA"]


def test_sec_downloader_stops_nonzero_on_systemic_failure_with_partial_manifest(monkeypatch, tmp_path) -> None:
    args = SimpleNamespace(
        user_agent="finance-research contact=owner@example.com",
        minimum_request_interval=0.1,
        symbols=None,
        symbols_file=None,
        ciks=None,
        run_id="sec-run-1",
        resume=False,
        cache_dir=tmp_path / "cache",
        refresh=False,
        output=tmp_path / "observations.jsonl",
        provenance_output=tmp_path / "provenance.json",
        manifest_output=tmp_path / "manifest.json",
    )
    payload = _companyfacts_payload(320193)
    monkeypatch.setattr(download_sec_edgar_fundamentals, "parse_args", lambda: args)
    monkeypatch.setattr(download_sec_edgar_fundamentals, "_throttled_get_json", lambda *_: lambda _: {})
    monkeypatch.setattr(download_sec_edgar_fundamentals, "_resolve_ciks", lambda *_: {"AAPL": "0000320193", "MSFT": "0000789019"})
    monkeypatch.setattr(download_sec_edgar_fundamentals, "_sha256", lambda _: "test-sha")

    def companyfacts_payload(_args, cik, _get_json):
        if cik == "0000789019":
            raise httpx.ReadTimeout("timed out")
        path = download_sec_edgar_fundamentals.companyfacts_cache_path(_args.cache_dir, cik)
        write_cached_json(path, payload)
        return payload, path.relative_to(_args.cache_dir).as_posix()

    monkeypatch.setattr(download_sec_edgar_fundamentals, "_companyfacts_payload", companyfacts_payload)

    assert download_sec_edgar_fundamentals.main() == 1
    manifest = json.loads(args.manifest_output.read_text(encoding="utf-8"))
    assert manifest["status"] == "systemic_failure"
    assert manifest["failure_class"] == "transport"
    assert manifest["failed_symbols"] == {"MSFT": "ReadTimeout: timed out"}
    assert manifest["pending_symbols"] == ["MSFT"]
    assert manifest["completed"]["AAPL"]["observation_count"] == 1
    assert manifest["systemic_failure"]["symbol"] == "MSFT"
    assert "--resume" in manifest["next_action"]
    assert manifest["cache_counts"]["completed_symbols"] == 1
    assert args.output.exists() is False
    assert args.provenance_output.exists() is False


def test_sec_downloader_counts_missing_companyfacts_separately(monkeypatch, tmp_path) -> None:
    args = SimpleNamespace(
        user_agent="finance-research contact=owner@example.com",
        minimum_request_interval=0.1,
        symbols=None,
        symbols_file=None,
        ciks=None,
        run_id="sec-run-1",
        resume=False,
        cache_dir=tmp_path / "cache",
        refresh=False,
        output=tmp_path / "observations.jsonl",
        provenance_output=tmp_path / "provenance.json",
        manifest_output=tmp_path / "manifest.json",
    )
    request = httpx.Request("GET", "https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json")
    payload = _companyfacts_payload(320193)
    monkeypatch.setattr(download_sec_edgar_fundamentals, "parse_args", lambda: args)
    monkeypatch.setattr(download_sec_edgar_fundamentals, "_throttled_get_json", lambda *_: lambda _: {})
    monkeypatch.setattr(download_sec_edgar_fundamentals, "_resolve_ciks", lambda *_: {"AAPL": "0000320193", "MSFT": "0000789019"})
    monkeypatch.setattr(download_sec_edgar_fundamentals, "_sha256", lambda _: "test-sha")

    def companyfacts_payload(_args, cik, _get_json):
        if cik == "0000789019":
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)
        path = download_sec_edgar_fundamentals.companyfacts_cache_path(_args.cache_dir, cik)
        write_cached_json(path, payload)
        return payload, path.relative_to(_args.cache_dir).as_posix()

    monkeypatch.setattr(download_sec_edgar_fundamentals, "_companyfacts_payload", companyfacts_payload)

    assert download_sec_edgar_fundamentals.main() == 0
    manifest = json.loads(args.manifest_output.read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["failed_symbols"] == {}
    assert manifest["missing_companyfacts"] == {"MSFT": "HTTPStatusError: not found"}
    assert manifest["pending_symbols"] == []
    assert manifest["completed"]["AAPL"]["observation_count"] == 1
    assert args.output.read_text(encoding="utf-8")


def test_sec_downloader_classifies_systemic_failures_distinctly() -> None:
    request = httpx.Request("GET", "https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json")
    auth_error = httpx.HTTPStatusError("forbidden", request=request, response=httpx.Response(403, request=request))
    rate_limit_error = httpx.HTTPStatusError("too many requests", request=request, response=httpx.Response(429, request=request))
    dns_error = httpx.ConnectError("nodename nor servname provided, or not known", request=request)

    auth = download_sec_edgar_fundamentals._classify_failure(auth_error)
    rate_limit = download_sec_edgar_fundamentals._classify_failure(rate_limit_error)
    dns = download_sec_edgar_fundamentals._classify_failure(dns_error)

    assert auth["status"] == "failed"
    assert auth["failure_class"] == "auth"
    assert "SEC_EDGAR_USER_AGENT" in str(auth["next_action"])

    assert rate_limit["status"] == "failed"
    assert rate_limit["failure_class"] == "rate_limit"
    assert "recovery check" in str(rate_limit["next_action"])

    assert dns["status"] == "failed"
    assert dns["failure_class"] == "dns"
    assert "DNS/network reachability" in str(dns["next_action"])


def test_sec_downloader_resume_skips_completed_symbols(monkeypatch, tmp_path) -> None:
    args = SimpleNamespace(
        user_agent="finance-research contact=owner@example.com",
        minimum_request_interval=0.1,
        symbols=None,
        symbols_file=None,
        ciks=None,
        run_id="sec-run-1",
        resume=True,
        cache_dir=tmp_path / "cache",
        refresh=False,
        output=tmp_path / "observations.jsonl",
        provenance_output=tmp_path / "provenance.json",
        manifest_output=tmp_path / "manifest.json",
    )
    aapl_payload = _companyfacts_payload(320193)
    msft_payload = _companyfacts_payload(789019)
    write_cached_json(download_sec_edgar_fundamentals.companyfacts_cache_path(args.cache_dir, "0000320193"), aapl_payload)
    args.manifest_output.write_text(
        json.dumps(
            {
                "schema_version": "sec_edgar_download_manifest_v3",
                "run_id": "sec-run-1",
                "generated_at": "2026-07-17T00:00:00+00:00",
                "source": "sec_edgar_companyfacts",
                "requested_symbols": ["AAPL", "MSFT"],
                "ciks": {"AAPL": "0000320193", "MSFT": "0000789019"},
                "records": {
                    "AAPL": {
                        "status": "completed",
                        "cik": "0000320193",
                        "cache_file": "companyfacts/0000320193.json",
                        "observation_count": 1,
                        "completed_at": "2026-07-17T00:00:00+00:00",
                    },
                    "MSFT": {
                        "status": "failed",
                        "cik": "0000789019",
                        "error": "ReadTimeout: timed out",
                        "failed_at": "2026-07-17T00:00:01+00:00",
                    },
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(download_sec_edgar_fundamentals, "parse_args", lambda: args)
    monkeypatch.setattr(download_sec_edgar_fundamentals, "_throttled_get_json", lambda *_: lambda _: {})
    monkeypatch.setattr(
        download_sec_edgar_fundamentals,
        "_resolve_ciks",
        lambda *_: (_ for _ in ()).throw(AssertionError("resume must not resolve symbols again")),
    )
    monkeypatch.setattr(download_sec_edgar_fundamentals, "_sha256", lambda _: "test-sha")
    requested_ciks: list[str] = []

    def companyfacts_payload(_args, cik, _get_json):
        requested_ciks.append(cik)
        path = download_sec_edgar_fundamentals.companyfacts_cache_path(_args.cache_dir, cik)
        write_cached_json(path, msft_payload)
        return msft_payload, path.relative_to(_args.cache_dir).as_posix()

    monkeypatch.setattr(download_sec_edgar_fundamentals, "_companyfacts_payload", companyfacts_payload)

    assert download_sec_edgar_fundamentals.main() == 0
    assert requested_ciks == ["0000789019"]
    manifest = json.loads(args.manifest_output.read_text(encoding="utf-8"))
    assert manifest["failed_symbols"] == {}
    assert manifest["pending_symbols"] == []
    assert set(manifest["completed"]) == {"AAPL", "MSFT"}


def test_sec_downloader_resume_clears_stale_systemic_failure_fields_on_completion(monkeypatch, tmp_path) -> None:
    args = SimpleNamespace(
        user_agent="finance-research contact=owner@example.com",
        minimum_request_interval=0.1,
        symbols=None,
        symbols_file=None,
        ciks=None,
        run_id="sec-run-resume-cleanup",
        resume=True,
        cache_dir=tmp_path / "cache",
        refresh=False,
        output=tmp_path / "observations.jsonl",
        provenance_output=tmp_path / "provenance.json",
        manifest_output=tmp_path / "manifest.json",
    )
    aapl_payload = _companyfacts_payload(320193)
    msft_payload = _companyfacts_payload(789019)
    write_cached_json(download_sec_edgar_fundamentals.companyfacts_cache_path(args.cache_dir, "0000320193"), aapl_payload)
    args.manifest_output.write_text(
        json.dumps(
            {
                "schema_version": "sec_edgar_download_manifest_v3",
                "run_id": "sec-run-resume-cleanup",
                "generated_at": "2026-07-17T00:00:00+00:00",
                "source": "sec_edgar_companyfacts",
                "requested_symbols": ["AAPL", "MSFT"],
                "ciks": {"AAPL": "0000320193", "MSFT": "0000789019"},
                "records": {
                    "AAPL": {
                        "status": "completed",
                        "cik": "0000320193",
                        "cache_file": "companyfacts/0000320193.json",
                        "observation_count": 1,
                        "completed_at": "2026-07-17T00:00:00+00:00",
                    },
                    "MSFT": {
                        "status": "failed",
                        "cik": "0000789019",
                        "error": "ConnectError: nodename nor servname provided, or not known",
                        "failure_class": "dns",
                        "failed_at": "2026-07-17T00:00:01+00:00",
                    },
                },
                "status": "systemic_failure",
                "failure_class": "dns",
                "systemic_failure": {
                    "symbol": "MSFT",
                    "cik": "0000789019",
                    "failure_class": "dns",
                    "error": "ConnectError: nodename nor servname provided, or not known",
                    "failed_at": "2026-07-17T00:00:01+00:00",
                    "next_action": "Stop the batch, verify DNS/network reachability to sec.gov, then rerun with --resume after a recovery check.",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(download_sec_edgar_fundamentals, "parse_args", lambda: args)
    monkeypatch.setattr(download_sec_edgar_fundamentals, "_throttled_get_json", lambda *_: lambda _: {})
    monkeypatch.setattr(
        download_sec_edgar_fundamentals,
        "_resolve_ciks",
        lambda *_: (_ for _ in ()).throw(AssertionError("resume must not resolve symbols again")),
    )
    monkeypatch.setattr(download_sec_edgar_fundamentals, "_sha256", lambda _: "test-sha")

    def companyfacts_payload(_args, cik, _get_json):
        path = download_sec_edgar_fundamentals.companyfacts_cache_path(_args.cache_dir, cik)
        write_cached_json(path, msft_payload)
        return msft_payload, path.relative_to(_args.cache_dir).as_posix()

    monkeypatch.setattr(download_sec_edgar_fundamentals, "_companyfacts_payload", companyfacts_payload)

    assert download_sec_edgar_fundamentals.main() == 0

    manifest = json.loads(args.manifest_output.read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["failure_class"] is None
    assert manifest["systemic_failure"] is None
    assert manifest["failed_symbols"] == {}
    assert manifest["pending_symbols"] == []
    assert set(manifest["completed"]) == {"AAPL", "MSFT"}


def test_sec_downloader_completed_resume_rebuilds_outputs_from_cache_only(monkeypatch, tmp_path) -> None:
    args = SimpleNamespace(
        user_agent="finance-research contact=owner@example.com",
        minimum_request_interval=0.1,
        symbols=None,
        symbols_file=None,
        ciks=None,
        run_id="sec-run-cache-only",
        resume=True,
        cache_dir=tmp_path / "cache",
        refresh=False,
        output=tmp_path / "observations.jsonl",
        provenance_output=tmp_path / "provenance.json",
        manifest_output=tmp_path / "manifest.json",
    )
    payload = _companyfacts_payload(320193)
    cache_file = download_sec_edgar_fundamentals.companyfacts_cache_path(args.cache_dir, "0000320193")
    write_cached_json(cache_file, payload)
    args.manifest_output.write_text(
        json.dumps(
            {
                "schema_version": "sec_edgar_download_manifest_v3",
                "run_id": "sec-run-cache-only",
                "generated_at": "2026-07-17T00:00:00+00:00",
                "source": "sec_edgar_companyfacts",
                "requested_symbols": ["AAPL"],
                "ciks": {"AAPL": "0000320193"},
                "ticker_mapping_cache_file": None,
                "records": {
                    "AAPL": {
                        "status": "completed",
                        "cik": "0000320193",
                        "cache_file": "companyfacts/0000320193.json",
                        "observation_count": 1,
                        "completed_at": "2026-07-17T00:00:00+00:00",
                    }
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(download_sec_edgar_fundamentals, "parse_args", lambda: args)
    monkeypatch.setattr(download_sec_edgar_fundamentals, "_throttled_get_json", lambda *_: lambda _: {})
    monkeypatch.setattr(
        download_sec_edgar_fundamentals,
        "_resolve_ciks",
        lambda *_: (_ for _ in ()).throw(AssertionError("cache-only resume must not resolve symbols again")),
    )
    monkeypatch.setattr(
        download_sec_edgar_fundamentals,
        "_companyfacts_payload",
        lambda *_: (_ for _ in ()).throw(AssertionError("cache-only resume must not fetch companyfacts again")),
    )
    monkeypatch.setattr(download_sec_edgar_fundamentals, "_sha256", lambda _: "test-sha")

    assert download_sec_edgar_fundamentals.main() == 0

    manifest = json.loads(args.manifest_output.read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["pending_symbols"] == []
    assert manifest["failed_symbols"] == {}
    assert manifest["cache_counts"]["completed_symbols"] == 1
    assert args.output.read_text(encoding="utf-8")
    provenance = json.loads(args.provenance_output.read_text(encoding="utf-8"))
    assert provenance["source"] == "SEC EDGAR companyfacts"
