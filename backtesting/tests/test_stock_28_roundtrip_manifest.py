from __future__ import annotations

import json
from pathlib import Path

from backtesting.stock_28_roundtrip_manifest import build_stock_28_r2_roundtrip_manifest


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_stock_28_roundtrip_manifest_verifies_downloaded_artifacts_and_summarizes_coverage(tmp_path: Path) -> None:
    source_dir = tmp_path / "artifacts"
    download_root = tmp_path / "downloads"
    key_prefix = "stock-automation/2026-07-18-stock-28-roundtrip"

    free_price_manifest = source_dir / "free-price-manifest.json"
    coverage_report = source_dir / "stock-28-coverage-bias-report.json"
    sec_cache_audit = source_dir / "stock-28-sec-cache-audit.json"

    _write_json(free_price_manifest, {"generated_at": "2026-07-18T00:00:00+00:00"})
    _write_json(
        coverage_report,
        {
            "generated_at": "2026-07-18T00:10:00+00:00",
            "coverage_split": {
                "price_universe_symbols": 3,
                "sec_mapped_universe_symbols": 2,
                "sec_cached_companyfacts_symbols": 1,
                "sec_uncached_mapped_symbols": 1,
                "sec_unmapped_universe_symbols": 1,
                "price_status_counts": {"completed": 3},
            },
            "filing_gap_analysis": {
                "cached_sec_symbol_count": 1,
                "latest_period": {
                    "period": "2024-Q1",
                    "period_type": "quarterly",
                    "symbol_periods": 1,
                    "complete_feature_input_symbols": 0,
                    "symbols_with_missing_features": 1,
                    "missing_feature_counts": {"eps": 1},
                },
            },
            "artifact_fingerprints": {"sec_companyfacts_content_sha256": "c" * 64},
            "report_fingerprint_sha256": "r" * 64,
            "certification_state": {
                "point_in_time_fundamentals": True,
                "price_point_in_time_certified": False,
                "corporate_actions_available_as_of": False,
                "universe_membership_point_in_time": False,
                "forecast_promotion_eligible": False,
            },
            "next_action": "Keep uncached symbols separate.",
        },
    )
    _write_json(sec_cache_audit, {"audited_at": "2026-07-18T00:05:00+00:00"})

    for path in (free_price_manifest, coverage_report, sec_cache_audit):
        target = download_root / key_prefix / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())

    manifest = build_stock_28_r2_roundtrip_manifest(
        key_prefix=key_prefix,
        download_root=download_root,
        free_price_manifest_path=free_price_manifest,
        coverage_report_path=coverage_report,
        sec_cache_audit_path=sec_cache_audit,
    )

    assert manifest["round_trip_verified"] is True
    assert manifest["requested_symbols"]["price_universe_symbols"] == 3
    assert manifest["completed_symbols"]["sec_cached_companyfacts_symbols"] == 1
    assert manifest["failed_symbols"]["sec_uncached_mapped_symbols"] == 1
    assert manifest["coverage"]["latest_period"]["period"] == "2024-Q1"
    assert manifest["certification_state"]["forecast_promotion_eligible"] is False
    assert len(manifest["artifacts"]) == 3
