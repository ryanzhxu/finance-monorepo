from __future__ import annotations

import sys
from types import SimpleNamespace

import httpx
import pandas as pd
from fastapi.testclient import TestClient

from analyst_service.api.main import app
from analyst_service.api.routers import analysis as analysis_router
from analyst_service.core import analysis as analysis_module
from analyst_service.core import data_fetcher as data_fetcher_module
from analyst_service.core import macro as macro_module
from analyst_service.core import sentiment as sentiment_module
from analyst_service.core import fundamentals as fundamentals_module
from tests.fixtures.nvda_yfinance import FIXED_NOW, NVDA_PRICE_HISTORY


class SparseMetadataTicker:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.fast_info = SimpleNamespace(last_price=float(NVDA_PRICE_HISTORY["Close"].iloc[-1]))

    @property
    def info(self) -> dict[str, object]:
        # Simulate a provider response that still serves prices, but not metadata.
        return {}

    @property
    def earnings_history(self) -> pd.DataFrame:
        return pd.DataFrame()

    @property
    def upgrades_downgrades(self) -> pd.DataFrame:
        raise RuntimeError("non-local Yahoo metadata unavailable")

    @property
    def quarterly_cash_flow(self) -> pd.DataFrame:
        return pd.DataFrame()

    def history(self, *args, **kwargs) -> pd.DataFrame:
        return NVDA_PRICE_HISTORY.copy()


def _ohlcv_frame() -> pd.DataFrame:
    close = NVDA_PRICE_HISTORY["Close"].astype(float)
    open_ = close.shift(1).fillna(close.iloc[0] * 0.995)
    high = pd.concat([open_, close], axis=1).max(axis=1) * 1.01
    low = pd.concat([open_, close], axis=1).min(axis=1) * 0.99
    volume = pd.Series(1_250_000, index=close.index)
    return pd.DataFrame(
        {
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
        },
        index=close.index,
    )


def _install_sparse_yfinance(monkeypatch) -> None:
    macro_tickers = {
        "^IRX": SimpleNamespace(info={"currentPrice": 4.5}, fast_info=SimpleNamespace(last_price=None)),
        "^TNX": SimpleNamespace(info={}, fast_info=SimpleNamespace(last_price=42.1)),
        "^VIX": SimpleNamespace(info={}, fast_info=SimpleNamespace(last_price=18.4)),
        "ZQ=F": SimpleNamespace(info={}, fast_info=SimpleNamespace(last_price=95.875)),
    }

    def ticker_factory(symbol: str):
        if symbol in {"NVDA", "AAPL"}:
            return SparseMetadataTicker(symbol)
        if symbol in macro_tickers:
            return macro_tickers[symbol]
        raise AssertionError(f"Unexpected ticker: {symbol}")

    fake_module = SimpleNamespace(
        Ticker=ticker_factory,
        download=lambda *args, **kwargs: _ohlcv_frame().copy(),
    )
    monkeypatch.setitem(sys.modules, "yfinance", fake_module)
    monkeypatch.setattr(analysis_router, "yf", fake_module)
    monkeypatch.setattr(fundamentals_module, "_utc_now", lambda: FIXED_NOW)
    monkeypatch.setattr(fundamentals_module, "fetch_finance_query_quote", lambda symbol: {})
    monkeypatch.setattr(
        fundamentals_module,
        "fetch_finance_query_chart",
        lambda symbol, interval="1d", range_="5y": pd.DataFrame(),
    )
    monkeypatch.setattr(fundamentals_module, "stockdata_api_key", lambda: None)
    monkeypatch.setattr(sentiment_module, "fetch_finance_query_quote", lambda symbol: {})


def test_nonlocal_yfinance_shape_reports_degraded_feature_health_when_metadata_is_sparse(monkeypatch) -> None:
    _install_sparse_yfinance(monkeypatch)
    monkeypatch.delenv("ALPHA_VANTAGE_KEY", raising=False)
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)

    async def fake_check_sec_edgar() -> str:
        return "unreachable"

    async def fake_check_yahoo_search() -> str:
        return "ok"

    monkeypatch.setattr(analysis_router, "_check_sec_edgar", fake_check_sec_edgar)
    monkeypatch.setattr(analysis_router, "_check_yahoo_search", fake_check_yahoo_search)
    monkeypatch.setattr(analysis_router, "_check_finance_query_quote", lambda: fake_check_yahoo_search())
    monkeypatch.setattr(analysis_router, "_check_finance_query_chart", lambda: fake_check_yahoo_search())
    monkeypatch.setattr(analysis_router, "_check_finance_query_search", lambda: fake_check_yahoo_search())
    class FakeResponse:
        def __init__(self, payload) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    def fake_httpx_get(url: str, *args, **kwargs):
        if url == fundamentals_module.YAHOO_SEARCH_URL:
            return FakeResponse(
                {
                    "quotes": [
                        {
                            "symbol": "NVDA",
                            "quoteType": "EQUITY",
                            "longname": "NVIDIA Corporation",
                        }
                    ]
                }
            )
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(fundamentals_module.httpx, "get", fake_httpx_get)
    monkeypatch.setattr(
        fundamentals_module,
        "fetch_finance_query_quote",
        lambda symbol: {
            "longName": "NVIDIA Corporation",
            "priceToBook": 26.107807,
            "priceToSalesTrailing12Months": 20.131376,
            "enterpriseToEbitda": 30.561,
            "revenueGrowth": 0.852,
            "grossMargins": 0.74144995,
            "upgradeDowngradeHistory": {
                "history": [
                    {"epochGradeDate": 1780418448, "action": "up"},
                    {"epochGradeDate": 1780335598, "action": "down"},
                ]
            },
            "earningsHistory": {
                "history": [
                    {"quarter": 1769817600, "epsActual": 1.62, "surprisePercent": 0.0532},
                    {"quarter": 1777507200, "epsActual": 1.87, "surprisePercent": 0.0554},
                ]
            },
        },
    )
    monkeypatch.setattr(
        fundamentals_module,
        "fetch_finance_query_chart",
        lambda symbol, interval="1d", range_="5y": pd.DataFrame(
            {
                "open": [180.0, 190.0],
                "high": [181.0, 191.0],
                "low": [179.0, 189.0],
                "close": [180.0, 190.0],
                "volume": [1_000_000.0, 1_100_000.0],
            },
            index=pd.to_datetime(["2026-01-31", "2026-04-30"]),
        ),
    )

    client = TestClient(app)
    health = client.get("/health")

    assert health.status_code == 200
    providers = health.json()["providers"]
    assert providers["yfinance"] == "degraded"
    assert providers["yfinance.download_ohlcv"] == "ok"
    assert providers["yfinance.info"] == "empty"
    assert providers["yfinance.upgrades_downgrades"] == "unavailable"
    assert providers["yahoo.search"] == "ok"
    assert providers["finance_query"] == "ok"

    data = fundamentals_module.fetch_fundamentals("NVDA")

    assert data.company_name == "NVIDIA Corporation"
    assert data.analyst_upgrades_30d == 1
    assert data.analyst_downgrades_30d == 1
    assert data.pe_ratio is None
    assert data.revenue_growth_yoy_pct == 85.2
    assert data.gross_margin_pct == 74.14
    assert data.freshness == "quarterly"


def test_analyze_returns_sparse_but_valid_payload_for_nonlocal_yfinance_shape(monkeypatch, tmp_path) -> None:
    _install_sparse_yfinance(monkeypatch)
    monkeypatch.delenv("ALPHA_VANTAGE_KEY", raising=False)
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.delenv("MARKETAUX_API_KEY", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(analysis_module, "append_recommendation", lambda response: None)
    monkeypatch.setattr(data_fetcher_module, "_load_cached_payload", lambda key: None)
    monkeypatch.setattr(data_fetcher_module, "_store_cached_payload", lambda key, payload, ttl: None)
    class FakeResponse:
        def __init__(self, payload) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    def fake_httpx_get(url: str, *args, **kwargs):
        if url == fundamentals_module.YAHOO_SEARCH_URL:
            return FakeResponse(
                {
                    "quotes": [
                        {
                            "symbol": "NVDA",
                            "quoteType": "EQUITY",
                            "longname": "NVIDIA Corporation",
                        }
                    ]
                }
            )
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(fundamentals_module.httpx, "get", fake_httpx_get)
    monkeypatch.setattr(
        fundamentals_module,
        "fetch_finance_query_quote",
        lambda symbol: {
            "longName": "NVIDIA Corporation",
            "priceToBook": 26.107807,
            "priceToSalesTrailing12Months": 20.131376,
            "enterpriseToEbitda": 30.561,
            "revenueGrowth": 0.852,
            "grossMargins": 0.74144995,
            "shortPercentOfFloat": 0.012200001,
            "upgradeDowngradeHistory": {
                "history": [
                    {"epochGradeDate": 1780418448, "action": "up"},
                    {"epochGradeDate": 1780335598, "action": "down"},
                ]
            },
            "earningsHistory": {
                "history": [
                    {"quarter": 1769817600, "epsActual": 1.62, "surprisePercent": 0.0532},
                    {"quarter": 1777507200, "epsActual": 1.87, "surprisePercent": 0.0554},
                ]
            },
        },
    )
    monkeypatch.setattr(
        fundamentals_module,
        "fetch_finance_query_chart",
        lambda symbol, interval="1d", range_="5y": pd.DataFrame(
            {
                "open": [180.0, 190.0],
                "high": [181.0, 191.0],
                "low": [179.0, 189.0],
                "close": [180.0, 190.0],
                "volume": [1_000_000.0, 1_100_000.0],
            },
            index=pd.to_datetime(["2026-01-31", "2026-04-30"]),
        ),
    )
    monkeypatch.setattr(sentiment_module, "fetch_finance_query_quote", lambda symbol: {"shortPercentOfFloat": 0.012200001})
    monkeypatch.setattr(
        sentiment_module,
        "_sec_get",
        lambda *args, **kwargs: (_ for _ in ()).throw(httpx.HTTPError("boom")),
    )

    fomc_html = """
    <html>
      <body>
        <div>June 16-17, 2026</div>
        <div>July 28-29, 2026</div>
        <div>September 15-16, 2026</div>
      </body>
    </html>
    """

    class FakeMacroResponse:
        def __init__(self, *, text: str = "") -> None:
            self.text = text

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {}

    def fake_macro_get(url: str, **kwargs):
        if url == macro_module.FED_FOMC_CALENDAR_URL:
            return FakeMacroResponse(text=fomc_html)
        raise AssertionError(f"Unexpected macro URL: {url}")

    monkeypatch.setattr(macro_module.requests, "get", fake_macro_get)
    monkeypatch.setattr(macro_module, "CACHE_PATH", tmp_path / "fomc-calendar.json")
    monkeypatch.setattr(macro_module, "_today", lambda: macro_module.date(2026, 6, 18))

    client = TestClient(app)
    response = client.post(
        "/analyze",
        json={
            "symbol": "NVDA",
            "asset_type": "STOCK",
            "horizon": "2-4W",
            "include_narrative": False,
            "include_entry": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "NVDA"
    assert payload["company_name"] == "NVIDIA Corporation"
    assert payload["fundamentals"]["company_name"] == "NVIDIA Corporation"
    assert payload["fundamentals"]["analyst_upgrades_30d"] == 1
    assert payload["fundamentals"]["analyst_downgrades_30d"] == 1
    assert payload["fundamentals"]["pe_ratio"] is None
    assert payload["fundamentals"]["pb_ratio"] == 26.11
    assert payload["fundamentals"]["revenue_growth_yoy_pct"] == 85.2
    assert payload["fundamentals"]["gross_margin_pct"] == 74.14
    assert payload["sentiment"]["short_interest_pct"] == 1.22
    assert payload["data_quality_score"] >= 70
    assert payload["recommendation"]["direction"] in ["BUY", "HOLD", "SELL"]
    assert payload["entry"] is not None
    assert payload["data_freshness"]["price"] is not None


def test_sparse_fundamentals_use_short_cache_ttl(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(data_fetcher_module, "_load_cached_payload", lambda key: None)
    monkeypatch.setattr(
        data_fetcher_module,
        "fetch_raw_fundamentals",
        lambda symbol: fundamentals_module.FundamentalsData(),
    )

    def fake_store(key: str, payload: dict[str, object], ttl: int) -> None:
        captured["ttl"] = ttl
        captured["payload"] = payload

    monkeypatch.setattr(data_fetcher_module, "_store_cached_payload", fake_store)

    result = data_fetcher_module.fetch_fundamentals("NVDA")

    assert result.freshness.value == "missing"
    assert captured["ttl"] == 300


def test_nonlocal_yfinance_shape_uses_alpha_vantage_for_covered_fields(monkeypatch) -> None:
    _install_sparse_yfinance(monkeypatch)
    monkeypatch.setenv("ALPHA_VANTAGE_KEY", "test-key")
    monkeypatch.setattr(data_fetcher_module, "_load_cached_payload", lambda key: None)
    monkeypatch.setattr(data_fetcher_module, "_store_cached_payload", lambda key, payload, ttl: None)

    class FakeResponse:
        def __init__(self, payload) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    def fake_httpx_get(url: str, *args, **kwargs):
        if url == fundamentals_module.YAHOO_SEARCH_URL:
            return FakeResponse(
                {
                    "quotes": [
                        {
                            "symbol": "NVDA",
                            "quoteType": "EQUITY",
                            "longname": "NVIDIA Corporation",
                        }
                    ]
                }
            )
        params = kwargs.get("params", {})
        if url == fundamentals_module.ALPHA_VANTAGE_BASE_URL and params.get("function") == "OVERVIEW":
            return FakeResponse(
                {
                    "Name": "NVIDIA Corporation",
                    "TrailingPE": "32.26",
                    "PriceToBookRatio": "49.7",
                    "QuarterlyRevenueGrowthYOY": "0.852",
                    "GrossProfitTTM": "105000000000",
                    "RevenueTTM": "132911392405.06",
                }
            )
        if url == fundamentals_module.ALPHA_VANTAGE_BASE_URL and params.get("function") == "EARNINGS":
            return FakeResponse(
                {
                    "quarterlyEarnings": [
                        {
                            "reportedDate": "2026-05-28",
                            "surprisePercentage": "13.19",
                        }
                    ]
                }
            )
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(fundamentals_module.httpx, "get", fake_httpx_get)

    data = fundamentals_module.fetch_fundamentals("NVDA")

    assert data.company_name == "NVIDIA Corporation"
    assert data.eps_surprise_pct == 13.19
    assert data.pe_ratio == 32.26
    assert data.pb_ratio == 49.7
    assert data.revenue_growth_yoy_pct == 85.2
    assert data.gross_margin_pct == 79.0
    assert data.freshness == "quarterly"

    cached = data_fetcher_module.fetch_fundamentals("NVDA")

    assert cached.value.pe_ratio == 32.26
    assert cached.value.pb_ratio == 49.7
    assert cached.value.revenue_growth_yoy_pct == 85.2
    assert cached.value.gross_margin_pct == 79.0
