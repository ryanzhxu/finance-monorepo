from __future__ import annotations

from shared.models import Sentiment


def normalize_sentiment(sentiment: Sentiment | None) -> Sentiment:
    return sentiment or Sentiment()
