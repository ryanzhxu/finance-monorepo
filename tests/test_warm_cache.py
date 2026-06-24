from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import warm_cache


def test_load_symbols_dedupes_and_merges_file(tmp_path: Path) -> None:
    symbols_file = tmp_path / "symbols.json"
    symbols_file.write_text(json.dumps(["msft", "AAPL", "", "nvda", "AAPL"]))

    symbols = warm_cache.load_symbols(str(symbols_file))

    assert symbols[:3] == ["MSFT", "AAPL", "NVDA"]
    assert "SPY" in symbols
    assert "XLK" in symbols
    assert symbols.count("AAPL") == 1


def test_iter_batches_chunks_symbols() -> None:
    batches = list(warm_cache.iter_batches(["A", "B", "C", "D", "E"], 2))

    assert batches == [["A", "B"], ["C", "D"], ["E"]]


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str | None, dict | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url: str, json: dict | None = None):
        self.requests.append(("POST", url, json))
        if url.endswith("/analyze"):
            symbol = json["symbol"]
            return _FakeResponse(
                {
                    "symbol": symbol,
                    "generated_at": "2026-06-23T05:00:00Z",
                    "data_freshness": {"price": "live"},
                    "data_quality_score": 96,
                    "confidence": 0.5,
                    "technicals": {
                        "rsi_14": 50,
                        "rsi_weekly": 50,
                        "macd": {},
                        "ma_20": 100,
                        "ma_50": 100,
                        "ma_200": 100,
                        "support_levels": [95, 90],
                        "resistance_levels": [105, 110],
                        "atr_14": 1,
                    },
                    "fundamentals": {},
                    "sentiment": {},
                    "macro": {"market_regime": "neutral"},
                    "signals": [],
                    "entry": None,
                    "recommendation": {
                        "direction": "HOLD",
                        "confidence": 0.5,
                        "signal_vote": {"HOLD": 1},
                        "weighted_score": 0.0,
                        "horizon": "2-4W",
                        "review_action": "hold_monitor",
                        "risk_flags": [],
                    },
                    "narrative": None,
                }
            )
        symbols = json["symbols"]
        return _FakeResponse(
            [
                {
                    "symbol": symbol,
                    "generated_at": "2026-06-23T05:00:00Z",
                    "data_freshness": {"price": "live"},
                    "data_quality_score": 96,
                    "confidence": 0.5,
                    "technicals": {
                        "rsi_14": 50,
                        "rsi_weekly": 50,
                        "macd": {},
                        "ma_20": 100,
                        "ma_50": 100,
                        "ma_200": 100,
                        "support_levels": [95, 90],
                        "resistance_levels": [105, 110],
                        "atr_14": 1,
                    },
                    "fundamentals": {},
                    "sentiment": {},
                    "macro": {"market_regime": "neutral"},
                    "signals": [],
                    "entry": None,
                    "recommendation": {
                        "direction": "HOLD",
                        "confidence": 0.5,
                        "signal_vote": {"HOLD": 1},
                        "weighted_score": 0.0,
                        "horizon": "2-4W",
                        "review_action": "hold_monitor",
                        "risk_flags": [],
                    },
                    "narrative": None,
                }
                for symbol in symbols
            ]
        )

    def get(self, url: str):
        self.requests.append(("GET", url, None))
        return _FakeResponse(
            {
                "status": "ok",
                "service": "analyst_service",
                "config_valid": True,
                "providers": {"redis": "connected"},
                "llm_available": False,
                "cache_backend": "redis",
            }
        )


def test_run_warmup_emits_summary(monkeypatch) -> None:
    fake_client = _FakeClient()
    monkeypatch.setattr(warm_cache.httpx, "Client", lambda *args, **kwargs: fake_client)

    emitted: list[tuple[str, dict]] = []
    summary = warm_cache.run_warmup(
        base_url="https://example.com",
        symbols=["AAPL", "MSFT", "NVDA"],
        batch_size=2,
        verify_sample_size=2,
        emit=lambda event, **fields: emitted.append((event, fields)),
    )

    assert summary.total_symbols == 3
    assert summary.cached_symbols == 3
    assert summary.cache_hit_rate == 1.0
    assert summary.avg_data_quality_score == 96
    assert summary.verify_sample_size == 2
    assert summary.verify_avg_data_quality_score == 96
    assert summary.health_status["cache_backend"] == "redis"
    assert any(event == "batch_summary" for event, _ in emitted)
    assert any(event == "verification_sample" for event, _ in emitted)
    assert any(event == "warmup_summary" for event, _ in emitted)


def test_main_fails_below_threshold(monkeypatch) -> None:
    monkeypatch.setattr(warm_cache, "load_symbols", lambda symbols_file=None: ["AAPL", "MSFT"])
    monkeypatch.setattr(
        warm_cache,
        "run_warmup",
        lambda **kwargs: warm_cache.WarmupSummary(
            total_symbols=2,
            cached_symbols=1,
            failed_symbols=1,
            cache_hit_rate=0.5,
            avg_data_quality_score=80.0,
            total_batches=1,
            elapsed_seconds=0.1,
            verify_sample_size=0,
            verify_avg_data_quality_score=None,
            health_status=None,
        ),
    )

    assert warm_cache.main(["--success-threshold", "0.9"]) == 1
