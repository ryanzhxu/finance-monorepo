from __future__ import annotations

import sys
from copy import deepcopy

import httpx
import pandas as pd

from analyst_service.core import fundamentals as fundamentals_module
from tests.fixtures.nvda_yfinance import (
    FIXED_NOW,
    NVDA_INFO,
    build_fake_yfinance_module,
)


def _install_fake_yfinance(monkeypatch, **kwargs) -> None:
    monkeypatch.setitem(sys.modules, "yfinance", build_fake_yfinance_module(**kwargs))
    monkeypatch.setattr(fundamentals_module, "_utc_now", lambda: FIXED_NOW)


def _sec_companyfacts_payload() -> dict:
    def usd_records(values: list[tuple[str, str, str, float]]) -> list[dict]:
        return [
            {"start": start, "end": end, "filed": filed, "val": value, "fy": 2026, "fp": fp}
            for start, end, filed, value, fp in values
        ]

    return {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": usd_records(
                            [
                                ("2025-02-01", "2025-05-03", "2025-05-20", 26044000000, "Q1"),
                                ("2025-05-04", "2025-08-02", "2025-08-20", 30040000000, "Q2"),
                                ("2025-08-03", "2025-11-01", "2025-11-20", 35110000000, "Q3"),
                                ("2025-11-02", "2026-01-31", "2026-02-20", 39331000000, "Q4"),
                                ("2026-02-01", "2026-05-03", "2026-05-20", 44120000000, "Q1"),
                            ]
                        )
                    }
                },
                "GrossProfit": {
                    "units": {
                        "USD": usd_records(
                            [
                                ("2025-02-01", "2025-05-03", "2025-05-20", 19400000000, "Q1"),
                                ("2025-05-04", "2025-08-02", "2025-08-20", 22350000000, "Q2"),
                                ("2025-08-03", "2025-11-01", "2025-11-20", 26580000000, "Q3"),
                                ("2025-11-02", "2026-01-31", "2026-02-20", 30070000000, "Q4"),
                                ("2026-02-01", "2026-05-03", "2026-05-20", 33950000000, "Q1"),
                            ]
                        )
                    }
                },
                "NetCashProvidedByUsedInOperatingActivities": {
                    "units": {
                        "USD": usd_records(
                            [
                                ("2025-08-03", "2025-11-01", "2025-11-20", 15100000000, "Q3"),
                                ("2025-11-02", "2026-01-31", "2026-02-20", 16600000000, "Q4"),
                                ("2026-02-01", "2026-05-03", "2026-05-20", 18900000000, "Q1"),
                            ]
                        )
                    }
                },
                "PaymentsToAcquirePropertyPlantAndEquipment": {
                    "units": {
                        "USD": usd_records(
                            [
                                ("2025-08-03", "2025-11-01", "2025-11-20", 2100000000, "Q3"),
                                ("2025-11-02", "2026-01-31", "2026-02-20", 2200000000, "Q4"),
                                ("2026-02-01", "2026-05-03", "2026-05-20", 2350000000, "Q1"),
                            ]
                        )
                    }
                },
                "EarningsPerShareDiluted": {
                    "units": {
                        "USD/shares": usd_records(
                            [
                                ("2025-05-04", "2025-08-02", "2025-08-20", 6.15, "Q2"),
                                ("2025-08-03", "2025-11-01", "2025-11-20", 7.02, "Q3"),
                                ("2025-11-02", "2026-01-31", "2026-02-20", 7.28, "Q4"),
                                ("2026-02-01", "2026-05-03", "2026-05-20", 7.64, "Q1"),
                            ]
                        )
                    }
                },
            }
        }
    }


def test_fetch_fundamentals_populates_fields_from_yfinance(monkeypatch) -> None:
    _install_fake_yfinance(monkeypatch)
    monkeypatch.setattr(
        fundamentals_module.httpx,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("SEC fallback should not be called")),
    )

    data = fundamentals_module.fetch_fundamentals("NVDA")

    assert data.eps_surprise_pct == 13.19
    assert data.pe_ratio == 65.2
    assert data.pb_ratio == 54.1
    assert data.ps_ratio == 28.7
    assert data.ev_ebitda == 48.6
    assert data.pe_percentile_5y is not None
    assert 0 <= data.pe_percentile_5y <= 100
    assert data.revenue_growth_yoy_pct == 69.0
    assert data.fcf_trend == "improving"
    assert data.gross_margin_pct == 75.9
    assert data.analyst_upgrades_30d == 2
    assert data.analyst_downgrades_30d == 1
    assert data.freshness == "quarterly"
    assert data.as_of == "2026-05-28"


def test_fetch_fundamentals_uses_sec_fallback_for_missing_financial_fields(monkeypatch) -> None:
    info = deepcopy(NVDA_INFO)
    info.pop("trailingPE")
    info.pop("revenueGrowth")
    info.pop("grossMargins")
    _install_fake_yfinance(
        monkeypatch,
        info=info,
        earnings_history=pd.DataFrame(),
        quarterly_cash_flow=pd.DataFrame(),
    )

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return _sec_companyfacts_payload()

    monkeypatch.setattr(fundamentals_module.httpx, "get", lambda *args, **kwargs: FakeResponse())

    data = fundamentals_module.fetch_fundamentals("NVDA")

    assert data.pe_ratio is not None
    assert data.revenue_growth_yoy_pct is not None
    assert data.gross_margin_pct is not None
    assert data.fcf_trend == "improving"
    assert data.as_of == "2026-05-03"
    assert data.freshness == "quarterly"


def test_fetch_fundamentals_returns_none_fields_when_sources_fail(monkeypatch) -> None:
    _install_fake_yfinance(
        monkeypatch,
        info={},
        earnings_history=pd.DataFrame(),
        upgrades_downgrades=pd.DataFrame(),
        quarterly_cash_flow=pd.DataFrame(),
        price_history=pd.DataFrame(),
    )
    monkeypatch.setattr(
        fundamentals_module.httpx,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(httpx.HTTPError("boom")),
    )

    data = fundamentals_module.fetch_fundamentals("NVDA")

    assert data.eps_surprise_pct is None
    assert data.pe_ratio is None
    assert data.pb_ratio is None
    assert data.ps_ratio is None
    assert data.ev_ebitda is None
    assert data.pe_percentile_5y is None
    assert data.revenue_growth_yoy_pct is None
    assert data.fcf_trend is None
    assert data.gross_margin_pct is None
    assert data.analyst_upgrades_30d == 0
    assert data.analyst_downgrades_30d == 0
    assert data.freshness == "missing"
    assert data.as_of is None


def test_fetch_fundamentals_uses_alpha_vantage_after_sec_gap(monkeypatch) -> None:
    info = deepcopy(NVDA_INFO)
    info.pop("trailingPE")
    info.pop("priceToBook")
    info.pop("priceToSalesTrailingTwelveMonths")
    info.pop("enterpriseToEbitda")
    info.pop("revenueGrowth")
    info.pop("grossMargins")
    _install_fake_yfinance(
        monkeypatch,
        info=info,
        earnings_history=pd.DataFrame(),
        quarterly_cash_flow=pd.DataFrame(),
    )

    class FakeResponse:
        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    def fake_get(url: str, *args, **kwargs):
        if "alphavantage.co" in url:
            return FakeResponse(
                {
                    "TrailingPE": "58.4",
                    "PriceToBookRatio": "40.2",
                    "PriceToSalesRatioTTM": "20.1",
                    "EVToEBITDA": "31.3",
                    "RevenueGrowthYOY": "0.42",
                    "GrossProfitTTM": "75000000000",
                    "RevenueTTM": "100000000000",
                }
            )
        return FakeResponse({})

    monkeypatch.setattr(fundamentals_module.httpx, "get", fake_get)
    monkeypatch.setenv("ALPHA_VANTAGE_KEY", "test-key")

    data = fundamentals_module.fetch_fundamentals("NVDA")

    assert data.pe_ratio == 58.4
    assert data.pb_ratio == 40.2
    assert data.ps_ratio == 20.1
    assert data.ev_ebitda == 31.3
    assert data.revenue_growth_yoy_pct == 42.0
    assert data.gross_margin_pct == 75.0
