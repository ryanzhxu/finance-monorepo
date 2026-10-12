from datetime import date

from backtesting.forecast import ForecastObservation
from backtesting.sec_edgar import SecFundamentalObservation, _next_business_day
from backtesting.sec_fundamental_features import (
    COMBINED_FEATURE_SCHEMA,
    attach_sec_fundamental_features,
    build_sec_fundamental_feature_snapshots,
)


def _fact(
    tag: str,
    value: float,
    *,
    filed: date,
    period_start: date | None,
    report_date: date,
    accession: str,
) -> SecFundamentalObservation:
    return SecFundamentalObservation(
        cik="0000320193",
        symbol="AAPL",
        tag=tag,
        unit="USD/shares" if tag == "EarningsPerShareDiluted" else "USD",
        value=value,
        form="10-Q",
        period_start=period_start,
        report_date=report_date,
        filed_on=filed,
        available_on=_next_business_day(filed),
        accession_number=accession,
    )


def _quarterly_facts() -> list[SecFundamentalObservation]:
    prior_filed = date(2023, 5, 3)
    current_filed = date(2024, 5, 3)
    values = []
    for tag, prior, current in (
        ("Revenues", 100, 120),
        ("NetIncomeLoss", 20, 30),
        ("OperatingIncomeLoss", 25, 36),
        ("EarningsPerShareDiluted", 1, 1.5),
    ):
        values.extend(
            [
                _fact(tag, prior, filed=prior_filed, period_start=date(2023, 1, 1), report_date=date(2023, 3, 31), accession="prior"),
                _fact(tag, current, filed=current_filed, period_start=date(2024, 1, 1), report_date=date(2024, 3, 31), accession="current"),
            ]
        )
    values.extend(
        [
            _fact("Liabilities", 200, filed=current_filed, period_start=None, report_date=date(2024, 3, 31), accession="current"),
            _fact("StockholdersEquity", 100, filed=current_filed, period_start=None, report_date=date(2024, 3, 31), accession="current"),
        ]
    )
    return values


def test_sec_fundamental_features_exclude_future_filing_and_trace_sources() -> None:
    facts = _quarterly_facts()
    snapshots = build_sec_fundamental_feature_snapshots("AAPL", [date(2024, 5, 3), date(2024, 5, 6)], facts)

    assert len(snapshots) == 2
    before, after = snapshots
    assert "sec_revenue_yoy" not in before.feature_values
    assert after.feature_values["sec_revenue_yoy"] == 0.2
    assert after.feature_values["sec_operating_margin"] == 0.3
    assert after.feature_values["sec_liabilities_to_equity"] == 2
    assert after.feature_sources["sec_revenue_yoy"].accessions == ["current", "prior"]
    assert after.feature_sources["sec_revenue_yoy"].available_on == date(2024, 5, 6)


def test_join_requires_all_sec_features_and_uses_separate_schema() -> None:
    facts = _quarterly_facts()
    snapshots = build_sec_fundamental_feature_snapshots("AAPL", [date(2024, 5, 6)], facts)
    observation = ForecastObservation(
        as_of=date(2024, 5, 6),
        symbol="AAPL",
        signal_score=70,
        forward_return_3m=0.2,
        max_drawdown_3m=-0.1,
        label_version="next_open_low_v2",
        feature_schema_version="continuous_regime_v1",
        feature_values={"price_feature": 1},
        market_regime="risk_on",
    )

    joined, skipped = attach_sec_fundamental_features([observation], snapshots)

    assert not skipped
    assert joined[0].feature_schema_version == COMBINED_FEATURE_SCHEMA
    assert joined[0].feature_values["sec_eps_yoy"] == 0.5


def test_future_sec_filing_cannot_change_existing_as_of_snapshot() -> None:
    facts = _quarterly_facts()
    as_of = date(2024, 5, 6)
    before = build_sec_fundamental_feature_snapshots("AAPL", [as_of], facts)
    future = _fact(
        "Revenues",
        999,
        filed=date(2025, 5, 2),
        period_start=date(2025, 1, 1),
        report_date=date(2025, 3, 31),
        accession="future",
    )
    after = build_sec_fundamental_feature_snapshots("AAPL", [as_of], [*facts, future])

    assert before[0].feature_values == after[0].feature_values
    assert before[0].feature_sources == after[0].feature_sources
