from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from analyst_service.core import macro as macro_module


def _install_fake_yfinance(monkeypatch, ticker_map: dict[str, object]) -> None:
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=lambda symbol: ticker_map[symbol]))


class _FakeResponse:
    def __init__(self, *, text: str = "", json_data: dict | None = None) -> None:
        self.text = text
        self._json_data = json_data or {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._json_data


def test_fetch_macro_populates_next_fomc_and_market_fields(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(macro_module, "CACHE_PATH", tmp_path / "fomc-calendar.json")
    monkeypatch.setattr(macro_module, "_today", lambda: macro_module.date(2026, 6, 18))
    _install_fake_yfinance(
        monkeypatch,
        {
            "^IRX": SimpleNamespace(info={"currentPrice": 4.50}, fast_info=SimpleNamespace(last_price=None)),
            "^TNX": SimpleNamespace(info={}, fast_info=SimpleNamespace(last_price=42.1)),
            "^VIX": SimpleNamespace(info={}, fast_info=SimpleNamespace(last_price=18.4)),
            "ZQ=F": SimpleNamespace(info={}, fast_info=SimpleNamespace(last_price=95.875)),
        },
    )

    fomc_html = """
    <html>
      <body>
        <div>June 16-17, 2026</div>
        <div>July 28-29, 2026</div>
        <div>September 15-16, 2026</div>
        <div>January 26-27, 2027</div>
      </body>
    </html>
    """

    def fake_get(url: str, **kwargs):
        if url == macro_module.FED_FOMC_CALENDAR_URL:
            return _FakeResponse(text=fomc_html)
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(macro_module.requests, "get", fake_get)

    data = macro_module.fetch_macro()

    assert data.days_to_next_fomc == 41
    assert data.next_fomc_date == "2026-07-29"
    assert data.rate_cut_probability_pct is not None
    assert 0 <= data.rate_cut_probability_pct <= 100
    assert data.rate_cut_probability_source == "zq_futures_derived"
    assert data.treasury_10y == 4.21
    assert data.vix == 18.4
    assert data.freshness == "live"


def test_fetch_macro_uses_fred_when_irx_info_is_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(macro_module, "CACHE_PATH", tmp_path / "fomc-calendar.json")
    monkeypatch.setattr(macro_module, "_today", lambda: macro_module.date(2026, 6, 18))
    _install_fake_yfinance(
        monkeypatch,
        {
            "^IRX": SimpleNamespace(info={}, fast_info=SimpleNamespace(last_price=None)),
            "^TNX": SimpleNamespace(info={}, fast_info=SimpleNamespace(last_price=None)),
            "^VIX": SimpleNamespace(info={}, fast_info=SimpleNamespace(last_price=None)),
            "ZQ=F": SimpleNamespace(info={}, fast_info=SimpleNamespace(last_price=96.0)),
        },
    )

    fomc_html = "<html><body><div>July 28-29, 2026</div></body></html>"
    fred_json = {"observations": [{"value": "4.50"}]}

    def fake_get(url: str, **kwargs):
        if url == macro_module.FED_FOMC_CALENDAR_URL:
            return _FakeResponse(text=fomc_html)
        if url == macro_module.FRED_DFEDTARU_URL:
            return _FakeResponse(json_data=fred_json)
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(macro_module.requests, "get", fake_get)

    data = macro_module.fetch_macro()

    assert data.days_to_next_fomc == 41
    assert data.rate_cut_probability_pct == 100.0
    assert data.rate_cut_probability_source == "zq_futures_derived"


def test_fetch_macro_does_not_crash_when_all_sources_fail(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(macro_module, "CACHE_PATH", tmp_path / "fomc-calendar.json")
    monkeypatch.setattr(macro_module, "_today", lambda: macro_module.date(2027, 1, 1))
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=lambda symbol: (_ for _ in ()).throw(RuntimeError("boom"))))
    monkeypatch.setattr(
        macro_module.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    data = macro_module.fetch_macro()

    assert data.days_to_next_fomc is None
    assert data.next_fomc_date is None
    assert data.rate_cut_probability_pct is None
    assert data.rate_cut_probability_source == "missing"
    assert data.treasury_10y is None
    assert data.vix is None
    assert data.freshness == "missing"
