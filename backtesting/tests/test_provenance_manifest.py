from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backtesting.provenance_manifest import (
    CertificationState,
    ProvenanceVerificationError,
    build_cache_only_report,
    verify_cached_files,
    verify_report,
)


def test_cache_only_report_is_reproducible_and_surfaces_coverage(tmp_path) -> None:
    (tmp_path / "AAPL.csv").write_text("date,close\n2026-01-01,100\n", encoding="utf-8")
    (tmp_path / "SPY.csv").write_text("date,close\n2026-01-01,500\n", encoding="utf-8")
    generated_at = datetime(2026, 8, 4, tzinfo=timezone.utc)
    kwargs = {
        "dataset_id": "fixture-dataset",
        "source": "fixture-cache",
        "adjustment_mode": "adjusted_close",
        "requested_symbols": ("AAPL", "MSFT"),
        "benchmark_symbols": ("SPY", "QQQ"),
        "certification": CertificationState(),
        "retrieved_at": generated_at,
    }

    first = build_cache_only_report(tmp_path, **kwargs)
    second = build_cache_only_report(tmp_path, **kwargs)

    assert first == second
    assert first.cache_only is True
    assert first.redownload_performed is False
    assert first.manifest.completed_symbols == ("AAPL",)
    assert first.missing_symbols == ("MSFT",)
    assert first.benchmark_coverage == {"QQQ": False, "SPY": True}
    assert any("Point-in-time certification is false" in item for item in first.manifest.limitations)
    verify_report(first)


def test_manifest_verification_detects_cache_mutation(tmp_path) -> None:
    cache_file = tmp_path / "AAPL.csv"
    cache_file.write_text("close\n100\n", encoding="utf-8")
    report = build_cache_only_report(
        tmp_path,
        dataset_id="fixture-dataset",
        source="fixture-cache",
        adjustment_mode="unadjusted",
        requested_symbols=("AAPL",),
        benchmark_symbols=(),
        certification=CertificationState(point_in_time_certified=True),
        retrieved_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )

    verify_cached_files(tmp_path, report.manifest)
    cache_file.write_text("close\n101\n", encoding="utf-8")

    with pytest.raises(ProvenanceVerificationError, match="changed"):
        verify_cached_files(tmp_path, report.manifest)


def test_certified_state_is_explicit_and_fingerprint_is_immutable(tmp_path) -> None:
    (tmp_path / "SPY.csv").write_text("close\n500\n", encoding="utf-8")
    report = build_cache_only_report(
        tmp_path,
        dataset_id="certified-fixture",
        source="fixture-cache",
        adjustment_mode="split_adjusted",
        requested_symbols=("SPY",),
        benchmark_symbols=("SPY",),
        certification=CertificationState(
            point_in_time_certified=True,
            universe_membership_point_in_time=True,
            historical_corporate_actions_complete=True,
        ),
        retrieved_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )

    assert report.manifest.certification.point_in_time_certified is True
    assert report.manifest.limitations == ()
    verify_report(report)


def test_custom_cache_path_cannot_escape_cache_directory(tmp_path) -> None:
    with pytest.raises(ValueError, match="inside cache_dir"):
        build_cache_only_report(
            tmp_path,
            dataset_id="unsafe-fixture",
            source="fixture-cache",
            adjustment_mode="unadjusted",
            requested_symbols=("AAPL",),
            benchmark_symbols=(),
            certification=CertificationState(),
            file_names={"AAPL": "../outside.csv"},
        )
