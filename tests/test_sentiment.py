from __future__ import annotations

import sys
from types import SimpleNamespace

import httpx

from analyst_service.core import sentiment as sentiment_module
from tests.fixtures.nvda_yfinance import FIXED_NOW, NVDA_INFO, NVDA_PRICE_HISTORY, build_fake_yfinance_module


def _install_fake_yfinance(monkeypatch, **kwargs) -> None:
    monkeypatch.setitem(sys.modules, "yfinance", build_fake_yfinance_module(**kwargs))
    monkeypatch.setattr(sentiment_module, "_now_utc", lambda: FIXED_NOW)
    monkeypatch.setattr(sentiment_module, "fetch_finance_query_quote", lambda symbol: {})


def _mock_sec_get_factory():
    submissions_payload = {
        "filings": {
            "recent": {
                "form": ["10-K", "13F-HR", "8-K"],
                "accessionNumber": ["0001045810-26-000010", "0001045810-26-000123", "0001045810-26-000011"],
                "filingDate": ["2026-05-20", "2026-05-15", "2026-05-10"],
                "primaryDocument": ["nvda-10k.htm", "primary_doc.xml", "nvda-8k.htm"],
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
      <infoTable>
        <nameOfIssuer>BOND FUND</nameOfIssuer>
        <sshPrnamt>120</sshPrnamt>
        <sshPrnamtType>PRN</sshPrnamtType>
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

    def fake_sec_get(url: str, **kwargs):
        if url.endswith("/submissions/CIK0001045810.json"):
            return FakeResponse(json_data=submissions_payload)
        if url.endswith("/000104581026000123/index.json"):
            return FakeResponse(json_data=index_payload)
        if url.endswith("/000104581026000123/infotable.xml"):
            return FakeResponse(text=holdings_xml)
        raise AssertionError(f"Unexpected SEC URL: {url}")

    return fake_sec_get


def _mock_marketaux_headlines(symbol: str) -> list[str]:
    assert symbol == "NVDA"
    return [
        "NVDA beats earnings estimates as growth stays strong",
        "Analysts upgrade NVDA after record quarter",
        "NVDA rally continues on bullish momentum",
        "Opportunity remains as demand surges",
    ]


def _mock_empty_news(symbol: str) -> list[str]:
    _ = symbol
    return []


def test_fetch_sentiment_populates_options_hv_and_13f(monkeypatch) -> None:
    _install_fake_yfinance(monkeypatch)
    monkeypatch.setattr(sentiment_module, "_sec_get", _mock_sec_get_factory())
    monkeypatch.setattr(sentiment_module, "fetch_marketaux_headlines", _mock_marketaux_headlines)
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)

    data = sentiment_module.fetch_sentiment("NVDA", price_history=NVDA_PRICE_HISTORY)

    assert data.put_call_ratio is not None
    assert data.put_call_ratio > 0
    assert data.iv_rank_approx is not None
    assert 0 <= data.iv_rank_approx <= 100
    assert data.short_interest_pct == 1.3
    assert data.institutional_net_shares_last_13f == 3500
    assert data.institutional_13f_as_of == "2026-05-15"
    assert data.institutional_13f_freshness == "delayed_45d"
    assert data.news_sentiment_score is not None
    assert data.news_sentiment_score > 0
    assert data.news_headline_count == 4
    assert data.news_sentiment_source == "marketaux"
    assert data.reddit_mention_spike_24h_pct is None
    assert data.reddit_positive_pct is None


def test_fetch_sentiment_handles_missing_reddit_credentials(monkeypatch) -> None:
    _install_fake_yfinance(monkeypatch)
    monkeypatch.setattr(sentiment_module, "_sec_get", _mock_sec_get_factory())
    monkeypatch.setattr(sentiment_module, "fetch_marketaux_headlines", _mock_marketaux_headlines)
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)

    data = sentiment_module.fetch_sentiment("NVDA", price_history=NVDA_PRICE_HISTORY)

    assert data.reddit_mention_spike_24h_pct is None
    assert data.reddit_positive_pct is None
    assert data.institutional_13f_freshness == "delayed_45d"
    assert data.news_sentiment_source == "marketaux"
    assert data.news_sentiment_score is not None


def test_fetch_sentiment_does_not_raise_when_one_source_fails(monkeypatch) -> None:
    class BrokenTicker:
        def __init__(self) -> None:
            self.info = dict(NVDA_INFO)
            self.options = ("2026-06-21",)

        def option_chain(self, expiry: str):
            raise RuntimeError("options unavailable")

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=lambda symbol: BrokenTicker()))
    monkeypatch.setattr(sentiment_module, "_sec_get", lambda *args, **kwargs: (_ for _ in ()).throw(httpx.HTTPError("boom")))
    monkeypatch.setattr(sentiment_module, "fetch_marketaux_headlines", _mock_empty_news)
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)

    data = sentiment_module.fetch_sentiment("NVDA", price_history=NVDA_PRICE_HISTORY)

    assert data.put_call_ratio is None
    assert data.iv_rank_approx is not None
    assert data.short_interest_pct == 1.3
    assert data.institutional_net_shares_last_13f is None
    assert data.news_sentiment_score is None
    assert data.news_headline_count is None
    assert data.news_sentiment_source is None
    assert data.reddit_mention_spike_24h_pct is None
    assert data.reddit_positive_pct is None


def test_fetch_sentiment_uses_alpha_vantage_put_call_ratio_when_options_are_unavailable(monkeypatch) -> None:
    class BrokenTicker:
        def __init__(self) -> None:
            self.info = dict(NVDA_INFO)
            self.options = ("2026-06-21",)

        def option_chain(self, expiry: str):
            raise RuntimeError("options unavailable")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"put_call_ratio_full_chain": "0.54"}

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=lambda symbol: BrokenTicker()))
    monkeypatch.setattr(sentiment_module.httpx, "get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(sentiment_module, "_sec_get", lambda *args, **kwargs: (_ for _ in ()).throw(httpx.HTTPError("boom")))
    monkeypatch.setattr(sentiment_module, "fetch_marketaux_headlines", _mock_empty_news)
    monkeypatch.setenv("ALPHA_VANTAGE_KEY", "test-key")
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)

    data = sentiment_module.fetch_sentiment("NVDA", price_history=NVDA_PRICE_HISTORY)

    assert data.put_call_ratio == 0.54


def test_fetch_sentiment_uses_finance_query_short_interest_when_yfinance_metadata_is_missing(monkeypatch) -> None:
    class BrokenTicker:
        def __init__(self) -> None:
            self.info = {}
            self.options = ()

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=lambda symbol: BrokenTicker()))
    monkeypatch.setattr(sentiment_module, "fetch_finance_query_quote", lambda symbol: {"shortPercentOfFloat": 0.012200001})
    monkeypatch.setattr(sentiment_module, "_sec_get", lambda *args, **kwargs: (_ for _ in ()).throw(httpx.HTTPError("boom")))
    monkeypatch.setattr(sentiment_module, "fetch_marketaux_headlines", _mock_empty_news)
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)

    data = sentiment_module.fetch_sentiment("NVDA", price_history=NVDA_PRICE_HISTORY)

    assert data.short_interest_pct == 1.22
