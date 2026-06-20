from __future__ import annotations

import httpx

from analyst_service.core import sentiment as sentiment_module


def test_score_headlines_returns_none_for_empty_list() -> None:
    assert sentiment_module.score_headlines([]) is None


def test_score_headlines_returns_none_below_minimum() -> None:
    assert sentiment_module.score_headlines(["NVDA beats earnings estimates"]) is None


def test_score_headlines_detects_bullish_bias() -> None:
    headlines = ["beat", "upgrade", "record"] * 4
    score = sentiment_module.score_headlines(headlines)

    assert score is not None
    assert score > 0


def test_score_headlines_detects_bearish_bias() -> None:
    headlines = ["miss", "downgrade", "weak"] * 4
    score = sentiment_module.score_headlines(headlines)

    assert score is not None
    assert score < 0


def test_score_headlines_returns_near_neutral_for_flat_headlines() -> None:
    score = sentiment_module.score_headlines(["flat trading continues"] * 5)

    assert score is not None
    assert abs(score) < 0.05


def test_fetch_tiingo_news_returns_empty_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)

    assert sentiment_module.fetch_tiingo_news("NVDA") == []


def test_fetch_yahoo_rss_headlines_parses_feed(monkeypatch) -> None:
    xml_payload = """
    <rss>
      <channel>
        <item><title>NVDA beats expectations</title></item>
        <item><title>Analysts upgrade NVDA</title></item>
      </channel>
    </rss>
    """

    class FakeResponse:
        text = xml_payload

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(sentiment_module.httpx, "get", lambda *args, **kwargs: FakeResponse())

    assert sentiment_module.fetch_yahoo_rss_headlines("NVDA") == [
        "NVDA beats expectations",
        "Analysts upgrade NVDA",
    ]


def test_fetch_yahoo_rss_headlines_returns_empty_on_failure(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(sentiment_module.httpx, "get", fail)

    assert sentiment_module.fetch_yahoo_rss_headlines("NVDA") == []
