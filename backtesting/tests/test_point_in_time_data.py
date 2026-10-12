from datetime import date, datetime, timezone

from backtesting.point_in_time_data import PointInTimeDataManifest


def test_point_in_time_manifest_blocks_incomplete_price_evidence() -> None:
    manifest = PointInTimeDataManifest(
        provider="fixture",
        dataset_version="2026-07",
        retrieved_at=datetime.now(timezone.utc),
        coverage_start=date(2000, 1, 1),
        coverage_end=date(2024, 12, 31),
        file_checksums={"prices.parquet": "sha256:fixture"},
        price_available_as_of=True,
        corporate_actions_available_as_of=False,
        universe_membership_available_as_of=True,
        delisted_securities_included=False,
    )

    assert manifest.price_forecast_certified is False
    assert manifest.certification_gaps == ["corporate_actions_available_as_of", "delisted_securities_included"]


def test_point_in_time_manifest_certifies_complete_price_evidence() -> None:
    manifest = PointInTimeDataManifest(
        provider="fixture",
        dataset_version="2026-07",
        retrieved_at=datetime.now(timezone.utc),
        coverage_start=date(2000, 1, 1),
        coverage_end=date(2024, 12, 31),
        file_checksums={"prices.parquet": "sha256:fixture"},
        price_available_as_of=True,
        corporate_actions_available_as_of=True,
        universe_membership_available_as_of=True,
        delisted_securities_included=True,
    )

    assert manifest.price_forecast_certified is True
    assert manifest.certification_gaps == []
