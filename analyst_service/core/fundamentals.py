from __future__ import annotations

from shared.models import Fundamentals


def normalize_fundamentals(fundamentals: Fundamentals | None) -> Fundamentals:
    return fundamentals or Fundamentals()
