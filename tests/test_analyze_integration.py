from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd
from fastapi.testclient import TestClient

from analyst_service.api.main import app
from analyst_service.core import analysis as analysis_module
from analyst_service.core import macro as macro_module
from analyst_service.core import sentiment as sentiment_module
from tests.fixtures.nvda_yfinance import FIXED_NOW, NVDA_PRICE_HISTORY, build_fake_yfinance_module


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


def _install_fake_yfinance(monkeypatch) -> None:
    base = build_fake_yfinance_module()
    macro_tickers = {
        "^IRX": SimpleNamespace(info={"currentPrice": 4.5}, fast_info=SimpleNamespace(last_price=None)),
        "^TNX": SimpleNamespace(info={}, fast_info=SimpleNamespace(last_price=42.1)),
        "^VIX": SimpleNamespace(info={}, fast_info=SimpleNamespace(last_price=18.4)),
        "ZQ=F": SimpleNamespace(info={}, fast_info=SimpleNamespace(last_price=95.875)),
    }

    def ticker_factory(symbol: str):
        if symbol == "NVDA":
            return base.Ticker(symbol)
        if symbol in macro_tickers:
            return macro_tickers[symbol]
        raise AssertionError(f"Unexpected ticker: {symbol}")

    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(Ticker=ticker_factory, download=lambda *args, **kwargs: _ohlcv_frame().copy()),
    )


def _mock_sentiment_sec_get(url: str, **kwargs):
    submissions_payload = {
        "filings": {
            "recent": {
                "form": ["13F-HR"],
                "accessionNumber": ["0001045810-26-000123"],
                "filingDate": ["2026-05-15"],
                "primaryDocument": ["primary_doc.xml"],
            }
        }
    }
    index_payload = {
        "directory": {
            "item": [
                {"name": "primary_doc.xml"},
                {"name": "infotable.xml"},
            ]
        }
    }
    holdings_xml = """
    <informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
      <infoTable>
        <nameOfIssuer>NVIDIA CORP</nameOfIssuer>
        <sshPrnamt>1000</sshPrnamt>
        <sshPrnamtType>SH</sshPrnamtType>
      </infoTable>
      <infoTable>
        <nameOfIssuer>ANOTHER CO</nameOfIssuer>
        <sshPrnamt>2500</sshPrnamt>
        <sshPrnamtType>SH</sshPrnamtType>
      </infoTable>
    </informationTable>
    """

    class FakeResponse:
        def __init__(self, *, json_data=None, text: str = "") -> None:
            self._json_data = json_data
            self.text = text

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._json_data

    if url.endswith("/submissions/CIK0001045810.json"):
        return FakeResponse(json_data=submissions_payload)
    if url.endswith("/000104581026000123/index.json"):
        return FakeResponse(json_data=index_payload)
    if url.endswith("/000104581026000123/infotable.xml"):
        return FakeResponse(text=holdings_xml)
    raise AssertionError(f"Unexpected SEC URL: {url}")


def _mock_macro_get(url: str, **kwargs):
    fomc_html = """
    <html>
      <body>
        <div>June 16-17, 2026</div>
        <div>July 28-29, 2026</div>
        <div>September 15-16, 2026</div>
      </body>
    </html>
    """

    class FakeResponse:
        def __init__(self, *, text: str = "") -> None:
            self.text = text

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {}

    if url == macro_module.FED_FOMC_CALENDAR_URL:
        return FakeResponse(text=fomc_html)
    raise AssertionError(f"Unexpected macro URL: {url}")


def _all_keys(payload):
    if isinstance(payload, dict):
        for key, value in payload.items():
            yield key
            yield from _all_keys(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _all_keys(item)


def test_analyze_returns_stage_f_blocks_and_signals(monkeypatch, tmp_path) -> None:
    _install_fake_yfinance(monkeypatch)
    monkeypatch.setattr(sentiment_module, "_sec_get", _mock_sentiment_sec_get)
    monkeypatch.setattr(macro_module.requests, "get", _mock_macro_get)
    monkeypatch.setattr(macro_module, "CACHE_PATH", tmp_path / "fomc-calendar.json")
    monkeypatch.setattr(macro_module, "_today", lambda: macro_module.date(2026, 6, 18))
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(analysis_module, "append_recommendation", lambda response: None)

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
    assert payload["fundamentals"] is not None
    assert payload["sentiment"] is not None
    assert payload["macro"] is not None
    assert payload["data_quality_score"] >= 70
    assert len(payload["signals"]) >= 12
    assert payload["recommendation"]["direction"] in ["BUY", "HOLD", "SELL"]
    assert 0.0 <= payload["recommendation"]["confidence"] <= 1.0
    assert not any(key.endswith("_rising") for key in _all_keys(payload))
