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


def test_fetch_marketaux_headlines_returns_empty_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("MARKETAUX_API_KEY", raising=False)

    assert sentiment_module.fetch_marketaux_headlines("NVDA") == []


def test_fetch_marketaux_headlines_parses_response(monkeypatch) -> None:
    json_payload = {
        "data": [
            {
                "title": "NVDA beats expectations",
                "description": "Revenue growth stayed strong.",
            },
            {
                "title": "Analysts upgrade NVDA",
                "description": "Demand trends remain healthy.",
            },
            {
                "title": "",
                "description": "Should be ignored without a title.",
            },
        ]
    }

    class FakeResponse:
        def json(self):
            return json_payload

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(sentiment_module.httpx, "get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setenv("MARKETAUX_API_KEY", "test-key")

    assert sentiment_module.fetch_marketaux_headlines("NVDA") == [
        "NVDA beats expectations Revenue growth stayed strong.",
        "Analysts upgrade NVDA Demand trends remain healthy.",
    ]


def test_fetch_marketaux_headlines_returns_empty_on_failure(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(sentiment_module.httpx, "get", fail)
    monkeypatch.setenv("MARKETAUX_API_KEY", "test-key")

    assert sentiment_module.fetch_marketaux_headlines("NVDA") == []
