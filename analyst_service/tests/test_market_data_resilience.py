from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pandas as pd
from fastapi.testclient import TestClient

from analyst_service.api.main import app
from analyst_service.api.routers import analysis as analysis_router
from analyst_service.core import analysis as analysis_module
from analyst_service.core import data_fetcher
from shared.data_quality import FreshValue
from shared.enums import Direction, Freshness, MarketRegime
from shared.models import AnalyzeRequest, Fundamentals, Macro, Recommendation, Sentiment


def _price_frame(close: float = 100.0) -> pd.DataFrame:
    index = pd.bdate_range(end="2026-06-15", periods=260)
    return pd.DataFrame(
        {
            "open": [close] * len(index),
            "high": [close + 1.0] * len(index),
            "low": [close - 1.0] * len(index),
            "close": [close] * len(index),
            "volume": [1_000_000.0] * len(index),
        },
        index=index,
    )


def _empty_ohlcv() -> pd.DataFrame:
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def test_fetch_ohlcv_prefers_alpha_vantage(monkeypatch) -> None:
    monkeypatch.setattr(data_fetcher, "_alpha_vantage_key", lambda: "test-key")
    monkeypatch.setattr(data_fetcher, "_fetch_alpha_vantage_ohlcv", lambda symbol, key: _price_frame(101.5))

    def fail_yahoo(symbol: str) -> pd.DataFrame:
        raise AssertionError("yfinance fallback should not run when AV history is present")

    monkeypatch.setattr(data_fetcher, "_fetch_yfinance_ohlcv", fail_yahoo)

    result = data_fetcher.fetch_ohlcv("NVDA")

    assert not result.value.empty
    assert float(result.value["close"].iloc[-1]) == 101.5
    assert result.freshness in {Freshness.DELAYED, Freshness.LAST_CLOSE, Freshness.STALE}


def test_fetch_ohlcv_uses_alpha_vantage_quote_when_history_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(data_fetcher, "_alpha_vantage_key", lambda: "test-key")
    monkeypatch.setattr(data_fetcher, "_fetch_alpha_vantage_ohlcv", lambda symbol, key: _empty_ohlcv())
    monkeypatch.setattr(data_fetcher, "_fetch_yfinance_ohlcv", lambda symbol: _empty_ohlcv())
    monkeypatch.setattr(data_fetcher, "_fetch_alpha_vantage_quote", lambda symbol, key: 142.25)

    result = data_fetcher.fetch_ohlcv("NVDA")

    assert result.freshness == Freshness.ESTIMATED
    assert not result.value.empty
    assert float(result.value["close"].iloc[-1]) == 142.25


def test_analyze_symbol_returns_without_raising_when_price_history_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        analysis_module,
        "load_service_config",
        lambda: {
            "entry_rules": {"support_window": 20},
            "weights": {},
            "thresholds": {
                "vote": {"buy_above": 0.25, "sell_below": -0.25},
                "signals": {"fomc_force_hold_days": 2},
            },
        },
    )
    monkeypatch.setattr(
        analysis_module,
        "fetch_ohlcv",
        lambda symbol, current_price: FreshValue(_empty_ohlcv(), Freshness.MISSING, None),
    )
    monkeypatch.setattr(
        analysis_module,
        "fetch_analysis_context",
        lambda symbol, price_history: (
            FreshValue(Fundamentals(pe_ratio=32.26), Freshness.QUARTERLY, datetime(2026, 6, 1, tzinfo=timezone.utc)),
            FreshValue(Sentiment(), Freshness.MISSING, None),
            FreshValue(Macro(market_regime=MarketRegime.NEUTRAL), Freshness.MISSING, None),
        ),
    )
    monkeypatch.setattr(analysis_module, "generate_signals", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        analysis_module,
        "aggregate_recommendation",
        lambda signals, horizon, thresholds, data_quality_score, entry, freshness, macro=None, apply_overrides=True: Recommendation(
            direction=Direction.HOLD,
            confidence=0.0,
            signal_vote={Direction.HOLD: 0},
            weighted_score=0.0,
            horizon=horizon,
            review_action="hold_monitor",
        ),
    )
    monkeypatch.setattr(analysis_module, "append_recommendation", lambda response: None)

    response = asyncio.run(
        analysis_module.analyze_symbol(
            AnalyzeRequest(
                symbol="NVDA",
                asset_type="STOCK",
                horizon="2-4W",
                include_narrative=False,
                include_entry=True,
            )
        )
    )

    assert response.entry is None
    assert response.fundamentals.pe_ratio == 32.26
    assert response.data_freshness["price"] == Freshness.MISSING


def test_entry_confluence_route_returns_degraded_payload_without_market_price(monkeypatch) -> None:
    monkeypatch.setattr(
        analysis_router,
        "load_service_config",
        lambda: {
            "entry_rules": {"support_window": 20},
            "weights": {},
            "thresholds": {
                "vote": {"buy_above": 0.25, "sell_below": -0.25},
                "signals": {"fomc_force_hold_days": 2},
            },
        },
    )
    monkeypatch.setattr(
        analysis_router,
        "load_fibonacci_config",
        lambda: {"default_lookback_days": 90, "overlap_tolerance_atr": 0.5},
    )
    monkeypatch.setattr(
        analysis_router,
        "fetch_ohlcv",
        lambda symbol, current_price: FreshValue(_empty_ohlcv(), Freshness.MISSING, None),
    )
    monkeypatch.setattr(
        analysis_router,
        "fetch_analysis_context",
        lambda symbol, price_history: (
            FreshValue(Fundamentals(), Freshness.MISSING, None),
            FreshValue(Sentiment(), Freshness.MISSING, None),
            FreshValue(Macro(), Freshness.MISSING, None),
        ),
    )

    client = TestClient(app)
    response = client.post("/entry/confluence", json={"symbol": "NVDA"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_price"] is None
    assert payload["classical"] == {}
    assert payload["fibonacci"] is None
    assert payload["confluence"] is None


def test_health_route_reports_feature_level_yahoo_statuses(monkeypatch) -> None:
    async def fake_yfinance_statuses() -> dict[str, str]:
        return {
            "yfinance.download_ohlcv": "rate_limited",
            "yfinance.info": "ok",
            "yfinance.options_chain": "ok",
            "yfinance.upgrades_downgrades": "empty",
            "yahoo.search": "ok",
            "yfinance": "rate_limited",
        }

    async def fake_sec_status() -> str:
        return "reachable"

    monkeypatch.setattr(analysis_router, "_check_yfinance_feature_statuses", fake_yfinance_statuses)
    monkeypatch.setattr(analysis_router, "_check_sec_edgar", fake_sec_status)
    monkeypatch.setattr(analysis_router, "load_service_config", lambda: {})
    monkeypatch.setattr(analysis_router, "llm_available", lambda: False)
    monkeypatch.setattr(analysis_router, "cache_backend_name", lambda: "file")
    monkeypatch.setattr(analysis_router, "redis_status", lambda: "not_configured")
    monkeypatch.setenv("ALPHA_VANTAGE_KEY", "test-key")

    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["providers"]["alpha_vantage"] == "configured"
    assert payload["providers"]["yfinance"] == "rate_limited"
    assert payload["providers"]["yfinance.download_ohlcv"] == "rate_limited"
    assert payload["providers"]["yfinance.upgrades_downgrades"] == "empty"
    assert payload["providers"]["yahoo.search"] == "ok"
