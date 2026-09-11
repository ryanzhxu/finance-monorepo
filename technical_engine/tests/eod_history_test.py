"""Deterministic SQLite and scheduler contracts for offline EOD history."""
from __future__ import annotations

import csv
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("BACKGROUND_MARKET_REFRESH_ENABLED", "false")
os.environ.setdefault("EOD_HISTORY_ENABLED", "false")
sys.path.insert(0, str(ROOT))

# The lightweight bundled test venv intentionally has no Flask. EOD contracts
# exercise scheduler helpers only, so provide the tiny decorator surface needed
# to import server.py without creating a web application dependency.
try:
    import flask  # noqa: F401
except ModuleNotFoundError:
    class _FakeApp:
        def __init__(self, *args, **kwargs):
            self.json = types.SimpleNamespace(ensure_ascii=True)
        def route(self, *args, **kwargs):
            return lambda function: function
        def after_request(self, function):
            return function
        def run(self, *args, **kwargs):
            return None
    sys.modules["flask"] = types.SimpleNamespace(
        Flask=_FakeApp, jsonify=lambda value: value,
        request=types.SimpleNamespace(args={}, get_json=lambda **_: {}),
        send_from_directory=lambda *args, **kwargs: None,
    )

import server
from 历史记录 import 历史记录数据库 as history_db


def record(ticker="NVDA", horizon="short", **changes):
    base = {
        "market_date": "2026-08-18", "recorded_at_et": "2026-08-18T16:30:05-04:00",
        "ticker": ticker, "asset_type": "stock", "horizon": horizon, "data_status": "available",
        "action": "hold", "confidence": 58, "price_state": "NEUTRAL_ZONE", "current_price": 180.25,
        "opportunity_low": 165.0, "opportunity_high": 170.0, "reduce_low": 190.0, "reduce_high": 195.0,
        "invalidation": 158.0, "landscape_quality": 2.2, "direction": 33, "confirmation": 62,
        "risk": 35, "exhaustion": 4, "market_regime": "normal",
        "market_context": {"regime": "normal", "vix": {"current": 18}},
        "technical_features": {"horizon": horizon, "momentum": {"rsi": {"value": 58}}},
        "supporting_reasons": ["Trend is constructive."], "limiting_reasons": ["Price is neutral."],
        "primary_classification": "Semiconductors", "lifecycle": "EstablishedLeader",
        "company_traits": ["Semiconductor", "AIInfrastructure", "LargeCap"],
        "applied_profile_modifiers": {"effective": {"riskSensitivity": 1.0}},
        "leveraged": None, "etf_direction": None, "underlying": None, "etf_modifiers": None,
        "material_change": [],
    }
    base.update(changes)
    return base


class EodHistoryDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="eod-历史记录-")
        self.db = Path(self.temp.name) / "历史记录" / "历史记录.sqlite"
        self.previous = os.environ.get("DECISION_HISTORY_DB_PATH")
        os.environ["DECISION_HISTORY_DB_PATH"] = str(self.db)

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("DECISION_HISTORY_DB_PATH", None)
        else:
            os.environ["DECISION_HISTORY_DB_PATH"] = self.previous
        self.temp.cleanup()

    def rows(self):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute("SELECT * FROM decision_history ORDER BY ticker, horizon").fetchall()
        finally:
            conn.close()

    def test_schema_initializes_on_unicode_path_and_survives_reopen(self):
        self.assertEqual(history_db.initialize(), self.db)
        self.assertTrue(self.db.exists())
        self.assertTrue(history_db.initialize().exists())

    def test_one_ticker_three_horizons_writes_three_rows(self):
        rows = [record(horizon=horizon) for horizon in ("short", "mid", "long")]
        result = history_db.write_snapshot("2026-08-18", "start", "end", rows)
        self.assertEqual(result["row_count"], 3)
        self.assertEqual(result["ticker_count"], 1)
        self.assertEqual(len(self.rows()), 3)

    def test_same_date_ticker_horizon_upserts_without_duplicate(self):
        history_db.write_snapshot("2026-08-18", "start", "end", [record(confidence=45)])
        history_db.write_snapshot("2026-08-18", "start2", "end2", [record(confidence=71)])
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][7], 71.0)

    def test_multiple_ticker_transaction_and_eod_run_success(self):
        rows = [record("NVDA", horizon) for horizon in ("short", "mid", "long")] + [record("TQQQ", horizon, asset_type="ETF", primary_classification=None, lifecycle=None, company_traits=None, leveraged=True, etf_direction="long", underlying="Nasdaq-100", etf_modifiers={"riskSensitivity": 1.2}) for horizon in ("short", "mid", "long")]
        result = history_db.write_snapshot("2026-08-18", "start", "end", rows)
        self.assertEqual(result["ticker_count"], 2)
        self.assertEqual(len(self.rows()), 6)
        conn = sqlite3.connect(self.db)
        try:
            run = conn.execute("SELECT status, row_count, unavailable_count FROM eod_runs WHERE market_date='2026-08-18'").fetchone()
            self.assertEqual(run, ("success", 6, 0))
            etf = conn.execute("SELECT asset_type, leveraged, etf_direction, underlying, etf_modifiers_json FROM decision_history WHERE ticker='TQQQ' LIMIT 1").fetchone()
            self.assertEqual(etf[:4], ("ETF", 1, "long", "Nasdaq-100"))
            self.assertIn("riskSensitivity", etf[4])
        finally:
            conn.close()

    def test_unavailable_ticker_is_a_valid_explicit_row(self):
        result = history_db.write_snapshot("2026-08-18", "start", "end", [record("MU", data_status="unavailable", action=None, confidence=None, technical_features=None, current_price=None)])
        self.assertEqual(result["unavailable_count"], 1)
        self.assertEqual(self.rows()[0][5], "unavailable")

    def test_failed_transaction_rolls_back_incomplete_rows(self):
        good = record("GOOD", "short")
        bad = record("BAD", "not_a_horizon")
        with self.assertRaises(sqlite3.IntegrityError):
            history_db.write_snapshot("2026-08-18", "start", "end", [good, bad])
        self.assertEqual(self.rows(), [])
        self.assertFalse(history_db.successful_run_exists("2026-08-18"))

    def test_failed_retry_does_not_overwrite_existing_success(self):
        history_db.write_snapshot("2026-08-18", "start", "end", [record()])
        history_db.mark_run_terminal("2026-08-18", "later", "later", "failed", "test failure")
        self.assertTrue(history_db.successful_run_exists("2026-08-18"))

    def test_export_script_writes_csv(self):
        history_db.write_snapshot("2026-08-18", "start", "end", [record()])
        output = Path(self.temp.name) / "export.csv"
        run = subprocess.run([sys.executable, str(ROOT / "历史记录" / "导出历史记录.py"), "--db", str(self.db), "--format", "csv", "--output", str(output)], cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        with output.open(encoding="utf-8") as handle:
            exported = list(csv.DictReader(handle))
        self.assertEqual(len(exported), 1)
        self.assertEqual(exported[0]["ticker"], "NVDA")

    def test_local_fallback_is_unicode_safe_when_no_render_disk_or_env(self):
        os.environ.pop("DECISION_HISTORY_DB_PATH", None)
        with patch.object(history_db, "RENDER_PERSISTENT_DISK", Path(self.temp.name) / "missing"):
            self.assertEqual(history_db.resolve_db_path().name, "历史记录.sqlite")


class EodHistorySchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="eod-server-")
        self.db = Path(self.temp.name) / "历史记录.sqlite"
        self.previous = os.environ.get("DECISION_HISTORY_DB_PATH")
        os.environ["DECISION_HISTORY_DB_PATH"] = str(self.db)

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("DECISION_HISTORY_DB_PATH", None)
        else:
            os.environ["DECISION_HISTORY_DB_PATH"] = self.previous
        self.temp.cleanup()

    def test_timezone_and_dst_aware_430_schedule(self):
        self.assertEqual(server.EOD_HISTORY_TIMEZONE.key, "America/New_York")
        summer = server.next_eod_history_run(datetime(2026, 8, 18, 16, 29, tzinfo=ZoneInfo("America/New_York")))
        winter = server.next_eod_history_run(datetime(2026, 1, 20, 16, 29, tzinfo=ZoneInfo("America/New_York")))
        self.assertEqual(summer.strftime("%H:%M %z"), "16:30 -0400")
        self.assertEqual(winter.strftime("%H:%M %z"), "16:30 -0500")

    def test_weekend_is_skipped_without_refresh(self):
        saturday = datetime(2026, 8, 22, 16, 30, tzinfo=ZoneInfo("America/New_York"))
        with patch.object(server, "_eod_refresh_and_cache_snapshot") as refresh:
            result = server.run_eod_history_once(saturday, reason="test")
        self.assertEqual(result["status"], "skipped")
        refresh.assert_not_called()

    def test_no_current_trading_date_skips_without_node(self):
        previous_day_payload = {"success": True, "items": [{"ticker": "NVDA", "analysis": {"price": 1, "history": {"timestamps": ["2026-08-17"], "availability": "available"}}}]}
        now = datetime(2026, 8, 18, 16, 30, tzinfo=ZoneInfo("America/New_York"))
        with patch.object(server, "eod_history_watchlist_tickers", return_value=["NVDA"]), patch.object(server, "_eod_refresh_and_cache_snapshot", return_value=previous_day_payload), patch.object(server, "build_eod_decision_snapshot") as node:
            result = server.run_eod_history_once(now, reason="test")
        self.assertEqual(result["status"], "skipped")
        node.assert_not_called()

    def test_full_refresh_precedes_production_engine_snapshot_and_writes_rows(self):
        now = datetime(2026, 8, 18, 16, 30, tzinfo=ZoneInfo("America/New_York"))
        payload = {"success": True, "items": [{"ticker": "NVDA", "analysis": {"price": 180, "history": {"timestamps": ["2026-08-18"], "availability": "available"}}}]}
        snapshot = {"records": [record("NVDA", horizon) for horizon in ("short", "mid", "long")]}
        events = []
        def refreshed(_):
            events.append("refresh")
            return payload
        def generated(_, __):
            events.append("production_js_engine")
            return snapshot
        with patch.object(server, "eod_history_watchlist_tickers", return_value=["NVDA"]), patch.object(server, "_eod_refresh_and_cache_snapshot", side_effect=refreshed), patch.object(server, "write_eod_snapshot_input", return_value=(self.temp.name, "input", "output")), patch.object(server, "build_eod_decision_snapshot", side_effect=generated), patch.object(server.shutil, "rmtree"):
            result = server.run_eod_history_once(now, reason="test")
        self.assertEqual(result["status"], "success")
        self.assertEqual(events, ["refresh", "production_js_engine"])
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM decision_history").fetchone()[0], 3)
        finally:
            conn.close()

    def test_engine_failure_marks_run_failed_without_success_rows(self):
        now = datetime(2026, 8, 18, 16, 30, tzinfo=ZoneInfo("America/New_York"))
        payload = {"success": True, "items": [{"ticker": "NVDA", "analysis": {"price": 180, "history": {"timestamps": ["2026-08-18"], "availability": "available"}}}]}
        with patch.object(server, "eod_history_watchlist_tickers", return_value=["NVDA"]), patch.object(server, "_eod_refresh_and_cache_snapshot", return_value=payload), patch.object(server, "write_eod_snapshot_input", return_value=(self.temp.name, "input", "output")), patch.object(server, "build_eod_decision_snapshot", side_effect=RuntimeError("engine failure")), patch.object(server.shutil, "rmtree"):
            result = server.run_eod_history_once(now, reason="test")
        self.assertEqual(result["status"], "failed")
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM decision_history").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT status FROM eod_runs WHERE market_date='2026-08-18'").fetchone()[0], "failed")
        finally:
            conn.close()

    def test_catchup_requires_current_day_and_no_success(self):
        before = datetime(2026, 8, 18, 16, 29, tzinfo=ZoneInfo("America/New_York"))
        after = datetime(2026, 8, 18, 16, 31, tzinfo=ZoneInfo("America/New_York"))
        self.assertFalse(server.eod_history_should_catch_up(before))
        self.assertTrue(server.eod_history_should_catch_up(after))

    def test_server_does_not_use_history_export_on_normal_routes(self):
        source = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertNotIn("export_rows(", source)


if __name__ == "__main__":
    unittest.main()
