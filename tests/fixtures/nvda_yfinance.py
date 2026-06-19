from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

FIXED_NOW = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)

NVDA_INFO: dict[str, Any] = {
    "symbol": "NVDA",
    "shortName": "NVIDIA Corporation",
    "currentPrice": 1100.0,
    "regularMarketPrice": 1100.0,
    "trailingPE": 65.2,
    "priceToBook": 54.1,
    "priceToSalesTrailingTwelveMonths": 28.7,
    "enterpriseToEbitda": 48.6,
    "revenueGrowth": 0.69,
    "grossMargins": 0.759,
    "shortPercentOfFloat": 0.013,
    "operatingCashflow": 64682000000,
    "capitalExpenditures": 1123000000,
    "freeCashflow": 63559000000,
    "cik": "1045810",
}

NVDA_EARNINGS_HISTORY = pd.DataFrame(
    {
        "epsEstimate": [4.12, 4.43, 4.89, 5.05, 5.15, 5.43, 6.12, 6.75],
        "epsActual": [4.35, 4.75, 5.22, 5.61, 5.88, 6.15, 7.02, 7.64],
        "epsDifference": [0.23, 0.32, 0.33, 0.56, 0.73, 0.72, 0.90, 0.89],
        "surprisePercent": [5.58, 7.22, 6.75, 11.09, 14.17, 13.26, 14.71, 13.19],
    },
    index=pd.to_datetime(
        [
            "2024-02-21",
            "2024-05-22",
            "2024-08-28",
            "2024-11-20",
            "2025-02-26",
            "2025-05-28",
            "2026-02-26",
            "2026-05-28",
        ]
    ),
)

NVDA_UPGRADES_DOWNGRADES = pd.DataFrame(
    {
        "Firm": ["Alpha Research", "Beta Capital", "Gamma Advisors", "Legacy Desk"],
        "ToGrade": ["Buy", "Neutral", "Overweight", "Buy"],
        "FromGrade": ["Hold", "Buy", "Equal Weight", "Hold"],
        "Action": ["up", "down", "upgrade", "up"],
    },
    index=pd.to_datetime(
        [
            "2026-06-10T14:00:00Z",
            "2026-05-25T14:00:00Z",
            "2026-06-01T14:00:00Z",
            "2026-04-15T14:00:00Z",
        ]
    ),
)

rng = np.random.default_rng(42)
n = 400
dates = pd.bdate_range(end="2026-06-18", periods=n)
returns = rng.normal(0.0008, 0.022, n)
prices = 700.0 * np.exp(np.cumsum(returns))
prices[-1] = 1100.0
NVDA_PRICE_HISTORY = pd.DataFrame({"Close": prices}, index=dates)

NVDA_QUARTERLY_CASH_FLOW = pd.DataFrame(
    {
        pd.Timestamp("2025-10-31"): [15100000000, 2100000000],
        pd.Timestamp("2026-01-31"): [16600000000, 2200000000],
        pd.Timestamp("2026-04-30"): [18900000000, 2350000000],
    },
    index=["Operating Cash Flow", "Capital Expenditure"],
)

NVDA_OPTIONS_CALLS = pd.DataFrame(
    {
        "contractSymbol": ["NVDA240621C01100000", "NVDA240621C01150000", "NVDA240621C01050000"],
        "strike": [1100.0, 1150.0, 1050.0],
        "lastPrice": [45.2, 22.1, 78.3],
        "bid": [44.8, 21.9, 77.9],
        "ask": [45.6, 22.3, 78.7],
        "volume": [1250, 890, 2100],
        "openInterest": [8500, 4200, 12300],
        "impliedVolatility": [0.42, 0.45, 0.40],
    }
)

NVDA_OPTIONS_PUTS = pd.DataFrame(
    {
        "contractSymbol": ["NVDA240621P01100000", "NVDA240621P01050000", "NVDA240621P01150000"],
        "strike": [1100.0, 1050.0, 1150.0],
        "lastPrice": [38.5, 18.9, 65.1],
        "bid": [38.1, 18.7, 64.8],
        "ask": [38.9, 19.1, 65.4],
        "volume": [980, 1450, 620],
        "openInterest": [7200, 9800, 3100],
        "impliedVolatility": [0.43, 0.41, 0.46],
    }
)


@dataclass
class FakeTicker:
    info: dict[str, Any]
    earnings_history: pd.DataFrame
    upgrades_downgrades: pd.DataFrame
    quarterly_cash_flow: pd.DataFrame
    price_history: pd.DataFrame
    options: tuple[str, ...] = ("2026-06-21", "2026-07-19", "2026-08-16")
    _calls: pd.DataFrame = field(default_factory=lambda: NVDA_OPTIONS_CALLS.copy())
    _puts: pd.DataFrame = field(default_factory=lambda: NVDA_OPTIONS_PUTS.copy())

    def history(self, *args, **kwargs) -> pd.DataFrame:
        return self.price_history.copy()

    def option_chain(self, expiry: str) -> SimpleNamespace:
        return SimpleNamespace(calls=self._calls.copy(), puts=self._puts.copy())


def build_fake_yfinance_module(
    *,
    info: dict[str, Any] | None = None,
    earnings_history: pd.DataFrame | None = None,
    upgrades_downgrades: pd.DataFrame | None = None,
    quarterly_cash_flow: pd.DataFrame | None = None,
    price_history: pd.DataFrame | None = None,
    calls: pd.DataFrame | None = None,
    puts: pd.DataFrame | None = None,
) -> SimpleNamespace:
    def ticker_factory(symbol: str) -> FakeTicker:
        assert symbol == "NVDA"
        return FakeTicker(
            info=dict(NVDA_INFO if info is None else info),
            earnings_history=(NVDA_EARNINGS_HISTORY if earnings_history is None else earnings_history).copy(),
            upgrades_downgrades=(NVDA_UPGRADES_DOWNGRADES if upgrades_downgrades is None else upgrades_downgrades).copy(),
            quarterly_cash_flow=(NVDA_QUARTERLY_CASH_FLOW if quarterly_cash_flow is None else quarterly_cash_flow).copy(),
            price_history=(NVDA_PRICE_HISTORY if price_history is None else price_history).copy(),
            _calls=(NVDA_OPTIONS_CALLS if calls is None else calls).copy(),
            _puts=(NVDA_OPTIONS_PUTS if puts is None else puts).copy(),
        )

    return SimpleNamespace(Ticker=ticker_factory)
