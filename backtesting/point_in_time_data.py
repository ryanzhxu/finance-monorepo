from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PointInTimeDataManifest(BaseModel):
    """Evidence required before a historical vendor feed can unlock numeric forecasts."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["point_in_time_data_manifest_v1"] = "point_in_time_data_manifest_v1"
    provider: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    retrieved_at: datetime
    coverage_start: date
    coverage_end: date
    file_checksums: dict[str, str] = Field(min_length=1)
    price_available_as_of: bool
    corporate_actions_available_as_of: bool
    universe_membership_available_as_of: bool
    delisted_securities_included: bool
    fundamentals_available_as_of: bool = False
    estimates_available_as_of: bool = False

    @model_validator(mode="after")
    def validate_coverage(self) -> PointInTimeDataManifest:
        if self.coverage_start > self.coverage_end:
            raise ValueError("coverage_start must not be after coverage_end")
        if any(not name or not digest for name, digest in self.file_checksums.items()):
            raise ValueError("file_checksums must contain non-empty names and digests")
        return self

    @property
    def price_forecast_certified(self) -> bool:
        return all(
            (
                self.price_available_as_of,
                self.corporate_actions_available_as_of,
                self.universe_membership_available_as_of,
                self.delisted_securities_included,
            )
        )

    @property
    def certification_gaps(self) -> list[str]:
        required = {
            "price_available_as_of": self.price_available_as_of,
            "corporate_actions_available_as_of": self.corporate_actions_available_as_of,
            "universe_membership_available_as_of": self.universe_membership_available_as_of,
            "delisted_securities_included": self.delisted_securities_included,
        }
        return [name for name, available in required.items() if not available]
