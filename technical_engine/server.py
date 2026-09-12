#!/usr/bin/env python3
import json
import math
import os
import queue
import re
import gc
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from email.utils import parsedate_to_datetime
from html import unescape
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from flask import Flask, jsonify, request, send_from_directory
try:
    from flask_cors import CORS
except Exception:
    CORS = None


class LazyModule:
    def __init__(self, module_name):
        self.module_name = module_name
        self.module = None

    def _load(self):
        if self.module is None:
            import importlib
            self.module = importlib.import_module(self.module_name)
        return self.module

    def __getattr__(self, item):
        return getattr(self._load(), item)


pd = LazyModule("pandas")
yf = LazyModule("yfinance")


ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from 历史记录 import 历史记录数据库 as eod_history_db

ENV_FILE = os.path.join(ROOT, ".env")
if os.path.exists(ENV_FILE):
    try:
        with open(ENV_FILE, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        pass
PORT = int(os.environ.get("PORT", "4173"))
HOST = os.environ.get("HOST", "127.0.0.1")
CACHE_SECONDS = 60 * 60
QUOTE_FETCH_TIMEOUT_SECONDS = 12
MARKET_CACHE_TTL_SECONDS = int(os.environ.get("MARKET_CACHE_TTL_SECONDS", str(60 * 60)))
MARKET_DATA_MAX_TICKERS = int(os.environ.get("MARKET_DATA_MAX_TICKERS", "60"))
MARKET_DATA_MAX_WORKERS = int(os.environ.get("MARKET_DATA_MAX_WORKERS", "2"))
MARKET_DATA_MAX_LIVE_TICKERS = int(os.environ.get("MARKET_DATA_MAX_LIVE_TICKERS", "2"))
MARKET_DATA_ROUTE_TIMEOUT_SECONDS = int(os.environ.get("MARKET_DATA_ROUTE_TIMEOUT_SECONDS", "18"))
MARKET_DATA_PER_TICKER_TIMEOUT_SECONDS = int(os.environ.get("MARKET_DATA_PER_TICKER_TIMEOUT_SECONDS", "8"))
# Keep the live refresh inside the route's per-ticker budget. More history can
# be requested with an environment override, but `max` is too slow/unreliable
# for a dashboard quote request and can make every row appear unavailable.
TECHNICAL_DAILY_HISTORY_PERIOD = os.environ.get("TECHNICAL_DAILY_HISTORY_PERIOD", "2y")
TECHNICAL_INTRADAY_HISTORY_PERIOD = os.environ.get("TECHNICAL_INTRADAY_HISTORY_PERIOD", "120d")
TECHNICAL_FOUR_HOUR_HISTORY_PERIOD = os.environ.get("TECHNICAL_FOUR_HOUR_HISTORY_PERIOD", TECHNICAL_INTRADAY_HISTORY_PERIOD)
# Native 4H and 1H requests run concurrently. This is the shared deadline for
# the pair, not a reason to synthesize or substitute a missing timeframe.
TECHNICAL_INTRADAY_FETCH_TIMEOUT_SECONDS = float(os.environ.get("TECHNICAL_INTRADAY_FETCH_TIMEOUT_SECONDS", "4.5"))
TECHNICAL_FOUR_HOUR_BAR_METHOD = "provider_native_v1"
TECHNICAL_FOUR_HOUR_TIMEZONE = "America/New_York"
OPTIONS_FETCH_TIMEOUT_SECONDS = float(os.environ.get("OPTIONS_FETCH_TIMEOUT_SECONDS", "6"))
# Increment when an options field changes methodology so cached synthetic data
# cannot be presented as a current options snapshot.
OPTIONS_SNAPSHOT_VERSION = 2
BACKGROUND_MARKET_REFRESH_ENABLED = os.environ.get("BACKGROUND_MARKET_REFRESH_ENABLED", "true").strip().lower() not in {"0", "false", "no", "n"}
BACKGROUND_MARKET_REFRESH_STARTUP_DELAY_SECONDS = int(os.environ.get("BACKGROUND_MARKET_REFRESH_STARTUP_DELAY_SECONDS", "15"))
BACKGROUND_MARKET_REFRESH_AFTER_HOUR_SECONDS = int(os.environ.get("BACKGROUND_MARKET_REFRESH_AFTER_HOUR_SECONDS", "5"))
BACKGROUND_MARKET_REFRESH_ON_START = os.environ.get("BACKGROUND_MARKET_REFRESH_ON_START", "true").strip().lower() not in {"0", "false", "no", "n"}
EOD_HISTORY_ENABLED = os.environ.get("EOD_HISTORY_ENABLED", "true").strip().lower() not in {"0", "false", "no", "n"}
EOD_HISTORY_STARTUP_DELAY_SECONDS = int(os.environ.get("EOD_HISTORY_STARTUP_DELAY_SECONDS", "30"))
EOD_HISTORY_NODE_TIMEOUT_SECONDS = int(os.environ.get("EOD_HISTORY_NODE_TIMEOUT_SECONDS", "120"))
EOD_HISTORY_NODE_MAX_OLD_SPACE_MB = int(os.environ.get("EOD_HISTORY_NODE_MAX_OLD_SPACE_MB", "192"))
EOD_HISTORY_TIMEZONE = ZoneInfo("America/New_York")
EOD_HISTORY_HOUR = 16
EOD_HISTORY_MINUTE = 30
EOD_HISTORY_NODE_RUNNER = os.path.join(ROOT, "历史记录", "生成决策快照.js")
DECISION_V1_NODE_RUNNER = os.path.join(ROOT, "decision-v1", "emit-decision-v1.js")
DECISION_V1_NODE_TIMEOUT_SECONDS = int(os.environ.get("DECISION_V1_NODE_TIMEOUT_SECONDS", "45"))
CACHE = {}
SEARCH_CACHE_SECONDS = 10 * 60
SYMBOL_SEARCH_CACHE = {}
NEWS_CACHE_SECONDS = 60 * 60
COMPANY_NEWS_CACHE = {}
COMPANY_NEWS_CACHE_LOCK = threading.Lock()
MARKET_CONTEXT_CACHE = {"value": None, "expiresAt": 0}
FEAR_GREED_CACHE = {"value": None, "expiresAt": 0}
WATCHLIST_DB_PATH = os.environ.get("WATCHLIST_DB_PATH", "data/watchlist.db")
MARKET_CACHE_DIR = os.environ.get("MARKET_CACHE_DIR", os.path.join("data", "cache"))
MARKET_EVENTS_FILE = os.environ.get("MARKET_EVENTS_FILE", os.path.join(ROOT, "market_events.json"))
WATCHLIST_LOCK = threading.Lock()
QUOTE_FETCH_LOCK = threading.Lock()
BACKGROUND_REFRESH_LOCK = threading.Lock()
FULL_REFRESH_RUN_LOCK = threading.Lock()
EOD_HISTORY_RUN_LOCK = threading.Lock()
BACKGROUND_REFRESH_THREAD_STARTED = False
EOD_HISTORY_THREAD_STARTED = False
BACKGROUND_REFRESH_STATE = {
    "enabled": BACKGROUND_MARKET_REFRESH_ENABLED,
    "running": False,
    "last_started_at": None,
    "last_completed_at": None,
    "last_success_count": 0,
    "last_failed_count": 0,
    "last_error": None,
    "last_batches": [],
    "next_run_at": None,
}
EOD_HISTORY_STATE = {
    "enabled": EOD_HISTORY_ENABLED,
    "running": False,
    "last_started_at": None,
    "last_completed_at": None,
    "last_status": None,
    "last_error": None,
    "next_run_at": None,
}
WATCHLIST_SCHEMA_VERSION = 1
WATCHLIST_MIGRATION_TICKERS = ["QQQ"]
DEFAULT_SHARED_WATCHLIST = [
    "NVDA", "TSLA", "AMD", "BABA", "GOOGL", "AMZN", "AAPL", "CRCL", "FFAI", "HIMS",
    "MPT", "META", "MSFT", "NFLX", "PLTR", "NOW", "SOFI", "TEM", "XE", "ZETA",
    "QQQ",
]
US_SYMBOL_CATALOG = [
    {"ticker": "QQQ", "name": "Invesco QQQ Trust", "aliases": ["Nasdaq 100 ETF", "Nasdaq-100", "纳指100", "QQQ ETF"], "exchange": "NASDAQ"},
    {"ticker": "SPMO", "name": "Invesco S&P 500 Momentum ETF", "aliases": ["S&P 500 Momentum ETF", "Momentum ETF"], "exchange": "NYSE"},
    {"ticker": "TQQQ", "name": "ProShares UltraPro QQQ", "aliases": ["Nasdaq 100 3x Bull ETF", "3x QQQ", "Leveraged QQQ"], "exchange": "NASDAQ"},
    {"ticker": "SQQQ", "name": "ProShares UltraPro Short QQQ", "aliases": ["Nasdaq 100 3x Bear ETF", "Inverse QQQ", "Short QQQ"], "exchange": "NASDAQ"},
    {"ticker": "SOXL", "name": "Direxion Daily Semiconductor Bull 3X Shares", "aliases": ["Semiconductor Bull 3X ETF", "3x Semiconductor Bull"], "exchange": "NYSE"},
    {"ticker": "SOXS", "name": "Direxion Daily Semiconductor Bear 3X Shares", "aliases": ["Semiconductor Bear 3X ETF", "3x Semiconductor Bear"], "exchange": "NYSE"},
    {"ticker": "NVDA", "name": "NVIDIA", "aliases": ["NVIDIA Corp", "英伟达"], "exchange": "NASDAQ"},
    {"ticker": "TSLA", "name": "Tesla", "aliases": ["Tesla Inc", "特斯拉"], "exchange": "NASDAQ"},
    {"ticker": "AMD", "name": "AMD", "aliases": ["Advanced Micro Devices", "超威半导体"], "exchange": "NASDAQ"},
    {"ticker": "BABA", "name": "Alibaba", "aliases": ["Alibaba Group Holding Limited", "阿里巴巴"], "exchange": "NYSE"},
    {"ticker": "GOOGL", "name": "Google", "aliases": ["Alphabet", "谷歌"], "exchange": "NASDAQ"},
    {"ticker": "AMZN", "name": "Amazon", "aliases": ["Amazon.com", "亚马逊"], "exchange": "NASDAQ"},
    {"ticker": "AAPL", "name": "Apple", "aliases": ["Apple Inc", "苹果"], "exchange": "NASDAQ"},
    {"ticker": "CRCL", "name": "Circle", "aliases": ["Circle Internet Group"], "exchange": "NYSE"},
    {"ticker": "FFAI", "name": "Faraday Future AI", "aliases": ["Faraday Future", "法拉第未来"], "exchange": "NASDAQ"},
    {"ticker": "HIMS", "name": "Hims & Hers", "aliases": ["Hims and Hers", "Hims Hers"], "exchange": "NYSE"},
    {"ticker": "MPT", "name": "Medical Properties Trust", "aliases": ["医疗地产信托"], "exchange": "NYSE"},
    {"ticker": "META", "name": "Meta", "aliases": ["Meta Platforms", "Facebook"], "exchange": "NASDAQ"},
    {"ticker": "MSFT", "name": "Microsoft", "aliases": ["微软"], "exchange": "NASDAQ"},
    {"ticker": "NFLX", "name": "Netflix", "aliases": ["奈飞"], "exchange": "NASDAQ"},
    {"ticker": "PLTR", "name": "Palantir", "aliases": ["Palantir Technologies"], "exchange": "NASDAQ"},
    {"ticker": "NOW", "name": "ServiceNow", "aliases": ["Service Now"], "exchange": "NYSE"},
    {"ticker": "SOFI", "name": "SoFi", "aliases": ["SoFi Technologies"], "exchange": "NASDAQ"},
    {"ticker": "TEM", "name": "Tempus AI", "aliases": ["Tempus"], "exchange": "NASDAQ"},
    {"ticker": "XE", "name": "XE", "aliases": ["Energy Fuels"], "exchange": "NYSE"},
    {"ticker": "ZETA", "name": "Zeta Global", "aliases": ["Zeta"], "exchange": "NYSE"},
]
POSITIVE_NEWS_KEYWORDS = [
    "beat", "beats", "surge", "growth", "upgrade", "raises", "raised", "expands", "partnership",
    "approval", "rebound", "record", "strong demand", "buyback", "bullish", "rally", "wins",
    "launch", "profit jump", "guidance raised", "breakthrough", "ai demand", "cloud growth",
    "增长", "上调", "合作", "突破", "回升", "利好", "创新高", "反弹", "订单增长",
]

NEGATIVE_NEWS_KEYWORDS = [
    "miss", "misses", "downgrade", "cut", "cuts", "lawsuit", "probe", "investigation",
    "antitrust", "regulation", "tariff", "war", "conflict", "delay", "recall", "warning",
    "slump", "fall", "drop", "weak demand", "bearish", "fraud", "default", "bankruptcy",
    "监管", "诉讼", "调查", "下调", "关税", "战争", "冲突", "延迟", "召回", "下滑", "利空",
]

MACRO_EVENT_PATTERNS = [
    ("fed", re.compile(r"\bfed\b|fomc|rate cut|rate hike|interest rate|powell", re.I)),
    ("inflation", re.compile(r"\bcpi\b|\bppi\b|inflation|jobs report|payroll", re.I)),
    ("tariff", re.compile(r"tariff|trade war|export restriction|sanction", re.I)),
    ("war", re.compile(r"war|missile|middle east|iran|israel|geopolitical|conflict", re.I)),
    ("regulation", re.compile(r"regulation|antitrust|lawsuit|probe|investigation", re.I)),
    ("energy", re.compile(r"oil|energy|crude|opec|gas price|lng", re.I)),
]


def normalize_ticker_input(value):
    invisible = "\u200b\u200c\u200d\ufeff"
    cleaned = "".join(ch for ch in (value or "") if ch not in invisible)
    return "".join(ch for ch in cleaned.strip().upper() if ch.isalnum() or ch in ".-")


def infer_market_type(ticker, market_type=None):
    return "US"


def normalize_watchlist_item(value):
    if isinstance(value, dict):
        ticker = normalize_ticker_input(value.get("ticker"))
        market_type = infer_market_type(ticker, value.get("market_type"))
        created_at = value.get("created_at") or value.get("createdAt")
    else:
        ticker = normalize_ticker_input(str(value))
        market_type = infer_market_type(ticker)
        created_at = None
    if not ticker:
        return None
    return {
        "id": None,
        "ticker": ticker,
        "market_type": market_type,
        "created_at": created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def normalize_search_query(value):
    return " ".join(str(value or "").strip().split())


def normalize_watchlist(values):
    seen = set()
    normalized = []
    for value in values or []:
        item = normalize_watchlist_item(value)
        ticker = item["ticker"] if item else ""
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        normalized.append(ticker)
    return normalized


def normalize_watchlist_items(values):
    seen = set()
    items = []
    for value in values or []:
        item = normalize_watchlist_item(value)
        if not item:
            continue
        key = (item["ticker"], item["market_type"])
        if key in seen:
            continue
        seen.add(key)
        item["id"] = len(items) + 1
        items.append(item)
    return items


def watchlist_items_to_tickers(items):
    return [item["ticker"] for item in items or [] if item.get("ticker")]


def sqlite_timestamp_to_iso(value):
    if not value:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = str(value)
    if "T" in text:
        return text if text.endswith("Z") else f"{text}Z"
    return f"{text.replace(' ', 'T')}Z"


def get_watchlist_conn():
    init_watchlist_db()
    conn = sqlite3.connect(WATCHLIST_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def get_watchlist_connection():
    db_dir = os.path.dirname(WATCHLIST_DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(WATCHLIST_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_watchlist_db():
    db_exists = os.path.exists(WATCHLIST_DB_PATH)
    with WATCHLIST_LOCK:
        with get_watchlist_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS watchlist (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  ticker TEXT NOT NULL,
                  market_type TEXT NOT NULL,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  UNIQUE(ticker, market_type)
                )
                """
            )
            if not db_exists:
                for item in normalize_watchlist_items(DEFAULT_SHARED_WATCHLIST):
                    conn.execute(
                        "INSERT OR IGNORE INTO watchlist (ticker, market_type) VALUES (?, ?)",
                        (item["ticker"], item["market_type"]),
                    )
            current_version = conn.execute("PRAGMA user_version").fetchone()[0]
            if current_version < WATCHLIST_SCHEMA_VERSION:
                for item in normalize_watchlist_items(WATCHLIST_MIGRATION_TICKERS):
                    conn.execute(
                        "INSERT OR IGNORE INTO watchlist (ticker, market_type) VALUES (?, ?)",
                        (item["ticker"], item["market_type"]),
                    )
                conn.execute(f"PRAGMA user_version = {WATCHLIST_SCHEMA_VERSION}")
            conn.commit()


def row_to_watchlist_item(row):
    return {
        "id": row["id"],
        "ticker": row["ticker"],
        "market_type": row["market_type"],
        "created_at": sqlite_timestamp_to_iso(row["created_at"]),
    }


def watchlist_rows_to_items(rows):
    return [row_to_watchlist_item(row) for row in rows]


def load_shared_watchlist():
    return watchlist_items_to_tickers(load_shared_watchlist_items())


def load_shared_watchlist_items():
    init_watchlist_db()
    with WATCHLIST_LOCK:
        with get_watchlist_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, ticker, market_type, created_at
                FROM watchlist
                ORDER BY datetime(created_at) ASC, id ASC
                """
            ).fetchall()
            return watchlist_rows_to_items(rows)


def add_shared_ticker(ticker, market_type=None):
    ticker = normalize_ticker_input(ticker)
    normalized_market_type = infer_market_type(ticker, market_type)
    if ticker:
        init_watchlist_db()
        with WATCHLIST_LOCK:
            with get_watchlist_connection() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO watchlist (ticker, market_type) VALUES (?, ?)",
                    (ticker, normalized_market_type),
                )
                conn.commit()
    return load_shared_watchlist_items()


def remove_shared_ticker(ticker, market_type=None):
    ticker = normalize_ticker_input(ticker)
    if ticker:
        init_watchlist_db()
        normalized_market_type = infer_market_type(ticker, market_type) if market_type else None
        with WATCHLIST_LOCK:
            with get_watchlist_connection() as conn:
                if normalized_market_type:
                    conn.execute(
                        "DELETE FROM watchlist WHERE ticker = ? AND market_type = ?",
                        (ticker, normalized_market_type),
                    )
                else:
                    conn.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker,))
                conn.commit()
    return load_shared_watchlist_items()


def resolve_market_symbol(ticker):
    normalized = (ticker or "").strip().upper()
    return normalized


def search_us_candidates(query, limit=8):
    normalized = normalize_search_query(query)
    if not normalized:
        return []

    cache_key = normalized.upper()
    now = time.time()
    cached = SYMBOL_SEARCH_CACHE.get(cache_key)
    if cached and cached["expiresAt"] > now:
        return cached["value"]

    candidates = []
    seen = set()
    query_upper = normalized.upper()

    local_ranked = []
    for item in US_SYMBOL_CATALOG:
        ticker = item["ticker"]
        alias_blob = " ".join([item["name"], *item.get("aliases", [])]).upper()
        score = None
        if ticker == query_upper:
            score = 0
        elif ticker.startswith(query_upper):
            score = 1
        elif query_upper in alias_blob:
            score = 2
        if score is None:
            continue
        local_ranked.append((score, len(item["name"]), item))

    local_ranked.sort(key=lambda pair: (pair[0], pair[1], pair[2]["ticker"]))
    for _, _, item in local_ranked[:limit]:
        symbol = item["ticker"]
        seen.add(symbol)
        candidates.append(format_symbol_candidate({
            "ticker": symbol,
            "name": item["name"],
            "market": "us",
            "exchange": item["exchange"],
        }))

    try:
        search = yf.Search(normalized, max_results=max(limit * 2, 10), news_count=0)
        quotes = getattr(search, "quotes", []) or []
        for quote in quotes:
            symbol = normalize_ticker_input(quote.get("symbol"))
            if not symbol or symbol in seen:
                continue
            quote_type = str(quote.get("quoteType", "")).upper()
            exchange = str(quote.get("exchange", "") or quote.get("exchangeDisp", "") or "").upper()
            if quote_type not in {"EQUITY", "ETF"}:
                continue
            if exchange not in {"NMS", "NYQ", "ASE", "NASDAQ", "NYSE", "AMEX", "PCX", "BATS"}:
                continue
            seen.add(symbol)
            candidates.append(format_symbol_candidate({
                "ticker": symbol,
                "name": quote.get("shortname") or quote.get("longname") or symbol,
                "market": "us",
                "exchange": exchange,
            }))
            if len(candidates) >= limit:
                break
    except Exception:
        pass

    if not candidates:
        symbol = normalize_ticker_input(normalized)
        if symbol:
            try:
                quote = get_cached_quote(symbol)
                candidates = [format_symbol_candidate({
                    "ticker": symbol,
                    "name": quote.get("shortName") or quote.get("longName") or symbol,
                    "market": "us",
                    "exchange": quote.get("exchangeName") or "US",
                })]
            except Exception:
                candidates = []

    SYMBOL_SEARCH_CACHE[cache_key] = {
        "value": candidates,
        "expiresAt": now + SEARCH_CACHE_SECONDS,
    }
    return candidates


def format_symbol_candidate(item):
    ticker = normalize_ticker_input(item.get("ticker"))
    market = "us"
    exchange = str(item.get("exchange") or "").upper()
    symbol_display = ticker
    return {
        "ticker": ticker,
        "symbolDisplay": symbol_display,
        "name": str(item.get("name") or ticker),
        "market": market,
        "marketLabel": "US",
        "exchange": exchange or "US",
    }


def search_symbol_candidates(query, limit=10):
    normalized = normalize_search_query(query)
    if not normalized:
        return []

    return search_us_candidates(normalized, limit=limit)[:limit]


def iso_from_epoch(value):
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def dt_from_epoch(value):
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def iso_from_local_close(value, hour, minute, offset_hours):
    if value is None:
        return None
    try:
        if isinstance(value, pd.Timestamp):
            dt_value = value.to_pydatetime()
        elif isinstance(value, datetime):
            dt_value = value
        else:
            dt_value = datetime.combine(value, datetime.min.time())
        local_tz = timezone(timedelta(hours=offset_hours))
        dt_local = dt_value.replace(hour=hour, minute=minute, second=0, microsecond=0, tzinfo=local_tz)
        return dt_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def normalize_numeric(value):
    """Return a finite number while preserving a real numeric zero.

    Provider feeds use a mixture of None, empty strings, textual placeholders,
    NaN, and infinity for unavailable fields.  None of these may become zero
    merely because Python or JavaScript considers them falsy.
    """
    try:
        if value is None:
            return None
        if isinstance(value, str) and value.strip().lower() in {"", "n/a", "na", "none", "null", "nan", "inf", "infinity", "-inf", "-infinity"}:
            return None
        if pd.isna(value):
            return None
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _safe_float(value):
    """Compatibility alias for the canonical missing-aware numeric parser."""
    return normalize_numeric(value)


def _safe_int(value):
    try:
        if value is None or pd.isna(value):
            return None
        return int(float(value))
    except Exception:
        return None


def _safe_text(value):
    if value is None:
        return ""
    return str(value).strip()


def build_source_info(status, missing_source=None, suggested_source=None, source_name=None):
    return {
        "status": status,
        "missing_source": missing_source or "—",
        "suggested_source": suggested_source or "—",
        "source_name": source_name or status,
    }


def http_get_text(url, timeout=8):
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
            "Accept": "application/rss+xml, application/xml, text/xml, text/html;q=0.9, */*;q=0.8",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="ignore")


def http_get_json(url, timeout=8):
    text = http_get_text(url, timeout=timeout)
    return json.loads(text)


def http_get_json_with_accept(url, timeout=8, accept="application/json, text/plain;q=0.9, */*;q=0.8"):
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
            "Accept": accept,
            "Referer": "https://www.cnn.com/",
            "Origin": "https://www.cnn.com",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset, errors="ignore"))


def http_get_json_browser(url, timeout=8, referer="https://finance.yahoo.com/"):
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
            "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
            "Referer": referer,
        },
    )
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset, errors="ignore"))


def _unwrap_yahoo_value(value):
    if isinstance(value, dict):
        for key in ("raw", "fmt", "longFmt"):
            if key in value and value.get(key) is not None:
                return value.get(key)
    return value


def _yahoo_nested_value(payload, *keys):
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return _unwrap_yahoo_value(current)


def fetch_yahoo_chart_points(symbol, range_value="3mo", interval="1d", limit=60, value_scale=1.0):
    rows = fetch_yahoo_chart_rows(symbol, range_value=range_value, interval=interval, limit=limit)
    return [
        {"date": row["date"], "value": row["close"] * value_scale}
        for row in rows
        if row.get("close") is not None
    ][-limit:]


def fetch_yahoo_chart_rows(symbol, range_value="3mo", interval="1d", limit=252):
    encoded_symbol = quote_plus(symbol)
    urls = [
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_symbol}?range={quote_plus(range_value)}&interval={quote_plus(interval)}",
        f"https://query2.finance.yahoo.com/v8/finance/chart/{encoded_symbol}?range={quote_plus(range_value)}&interval={quote_plus(interval)}",
    ]
    for url in urls:
        try:
            payload = http_get_json_browser(url, timeout=8)
            result = (((payload or {}).get("chart") or {}).get("result") or [None])[0] or {}
            timestamps = result.get("timestamp") or []
            quote = (((result.get("indicators") or {}).get("quote") or [None])[0]) or {}
            rows = []
            for index, ts in enumerate(timestamps):
                stamp = dt_from_epoch(ts)
                if stamp is None:
                    continue
                close = _safe_float((quote.get("close") or [None])[index] if index < len(quote.get("close") or []) else None)
                if close is None:
                    continue
                rows.append({
                    "date": stamp.date().isoformat(),
                    "datetime": stamp,
                    "open": _safe_float((quote.get("open") or [None])[index] if index < len(quote.get("open") or []) else None),
                    "high": _safe_float((quote.get("high") or [None])[index] if index < len(quote.get("high") or []) else None),
                    "low": _safe_float((quote.get("low") or [None])[index] if index < len(quote.get("low") or []) else None),
                    "close": close,
                    "volume": _safe_int((quote.get("volume") or [None])[index] if index < len(quote.get("volume") or []) else None),
                })
            if rows:
                return rows[-limit:]
        except Exception:
            continue
    return []


def fetch_yahoo_chart_frame(symbol, range_value="1y", interval="1d", limit=260):
    rows = fetch_yahoo_chart_rows(symbol, range_value=range_value, interval=interval, limit=limit)
    if not rows:
        return pd.DataFrame()
    try:
        # Technical OHLCV must stay sourced from real provider fields. A close
        # cannot stand in for missing OHLC, and missing volume cannot become
        # zero, because either substitution would manufacture indicator input.
        clean_rows = [
            row for row in rows
            if all(row.get(field) is not None for field in ("open", "high", "low", "close", "volume"))
        ]
        if not clean_rows:
            return pd.DataFrame()
        frame = pd.DataFrame({
            "Open": [row["open"] for row in clean_rows],
            "High": [row["high"] for row in clean_rows],
            "Low": [row["low"] for row in clean_rows],
            "Close": [row["close"] for row in clean_rows],
            "Volume": [row["volume"] for row in clean_rows],
        }, index=pd.DatetimeIndex([row["datetime"] for row in clean_rows]))
        return frame
    except Exception:
        return pd.DataFrame()


def fetch_yahoo_quote_snapshot(symbol):
    urls = [
        f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={quote_plus(symbol)}",
        f"https://query2.finance.yahoo.com/v7/finance/quote?symbols={quote_plus(symbol)}",
    ]
    for url in urls:
        try:
            payload = http_get_json_browser(url, timeout=8)
            result = (((payload or {}).get("quoteResponse") or {}).get("result") or [None])[0] or {}
            if result:
                return {key: _unwrap_yahoo_value(value) for key, value in result.items()}
        except Exception:
            continue
    return {}


def stooq_symbol_candidates(symbol):
    normalized = _safe_text(symbol).lower().replace("-", ".")
    candidates = []
    if normalized in {"^vix", "vix"}:
        candidates.extend(["^vix", "vix"])
    if normalized in {"^tnx", "tnx"}:
        candidates.extend(["10yus.b", "us10y", "10yus", "^tnx", "tnx"])
    if normalized.startswith("^"):
        candidates.extend([normalized, normalized[1:]])
    elif "." not in normalized:
        candidates.append(f"{normalized}.us")
    candidates.append(normalized)
    if normalized in {"spy", "qqq"}:
        candidates.append(f"{normalized}.us")
    seen = []
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.append(candidate)
    return seen


def fetch_stooq_history_rows(symbol, limit=260):
    for candidate in stooq_symbol_candidates(symbol):
        try:
            url = f"https://stooq.com/q/d/l/?s={quote_plus(candidate)}&i=d"
            csv_text = http_get_text(url, timeout=8)
            rows = []
            for raw_line in csv_text.splitlines()[1:]:
                parts = [part.strip() for part in raw_line.split(",")]
                if len(parts) < 6 or parts[0].lower() == "no data":
                    continue
                try:
                    stamp = datetime.strptime(parts[0], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                close = _safe_float(parts[4])
                if close is None:
                    continue
                rows.append({
                    "date": stamp.date().isoformat(),
                    "datetime": stamp,
                    "open": _safe_float(parts[1]),
                    "high": _safe_float(parts[2]),
                    "low": _safe_float(parts[3]),
                    "close": close,
                    "volume": _safe_int(parts[5]),
                    "source_symbol": candidate,
                })
            if rows:
                return rows[-limit:]
        except Exception:
            continue
    return []


def fetch_stooq_chart_frame(symbol, limit=260):
    rows = fetch_stooq_history_rows(symbol, limit=limit)
    if not rows:
        return pd.DataFrame()
    try:
        clean_rows = [
            row for row in rows
            if all(row.get(field) is not None for field in ("open", "high", "low", "close", "volume"))
        ]
        if not clean_rows:
            return pd.DataFrame()
        return pd.DataFrame({
            "Open": [row["open"] for row in clean_rows],
            "High": [row["high"] for row in clean_rows],
            "Low": [row["low"] for row in clean_rows],
            "Close": [row["close"] for row in clean_rows],
            "Volume": [row["volume"] for row in clean_rows],
        }, index=pd.DatetimeIndex([row["datetime"] for row in clean_rows]))
    except Exception:
        return pd.DataFrame()


def fetch_yahoo_quote_summary_snapshot(symbol):
    modules = ",".join([
        "price",
        "summaryProfile",
        "calendarEvents",
    ])
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        try:
            url = f"https://{host}/v10/finance/quoteSummary/{quote_plus(symbol)}?modules={modules}"
            payload = http_get_json_browser(url, timeout=8)
            result = ((((payload or {}).get("quoteSummary") or {}).get("result")) or [None])[0] or {}
            price = result.get("price") or {}
            summary_profile = result.get("summaryProfile") or {}
            calendar_events = result.get("calendarEvents") or {}
            flattened = {}
            for source in [price, summary_profile, calendar_events]:
                for key, value in source.items():
                    flattened[key] = _unwrap_yahoo_value(value)
            if flattened:
                return flattened
        except Exception:
            continue
    return {}


def merge_yahoo_fallback_info(symbol, info):
    merged = dict(info or {})
    quote_snapshot = fetch_yahoo_quote_snapshot(symbol)
    quote_summary = fetch_yahoo_quote_summary_snapshot(symbol)
    for source in [quote_snapshot, quote_summary]:
        for key, value in (source or {}).items():
            if merged.get(key) is None and value is not None:
                merged[key] = value
    return merged, quote_snapshot, quote_summary



def _earnings_countdown(earnings_datetime):
    if earnings_datetime is None:
        return {
            "earnings_datetime": None,
            "session": "unknown",
            "calendar_days_remaining": None,
            "trading_days_remaining": None,
            "full_trading_sessions_remaining": None,
            "status": "unavailable",
            "calculation_method": "unavailable",
        }
    try:
        ny_tz = ZoneInfo("America/New_York")
        event_local = earnings_datetime.astimezone(ny_tz)
        now_local = datetime.now(timezone.utc).astimezone(ny_tz)
        event_date = event_local.date()
        today = now_local.date()
        calendar_days = (event_date - today).days
        session = "before_market" if event_local.hour < 9 or (event_local.hour == 9 and event_local.minute < 30) else "after_market" if event_local.hour >= 16 else "during_market"
        if calendar_days < 0:
            status = "reported_or_past"
            trading_days = 0
            full_sessions = 0
        else:
            business_days = 0
            cursor = today
            while cursor <= event_date:
                if cursor.weekday() < 5:
                    business_days += 1
                cursor += timedelta(days=1)
            trading_days = business_days
            # A whole session must finish before the scheduled release; today and
            # the event date do not count as future complete sessions.
            full_sessions = sum(
                1 for offset in range(1, max(calendar_days, 0))
                if (today + timedelta(days=offset)).weekday() < 5
            )
            status = "upcoming"
        return {
            "earnings_datetime": event_local.isoformat(),
            "session": session,
            "calendar_days_remaining": calendar_days,
            "trading_days_remaining": trading_days,
            "full_trading_sessions_remaining": full_sessions,
            "status": status,
            "calculation_method": "weekday_estimate_excluding_us_market_holidays",
        }
    except Exception:
        return {
            "earnings_datetime": None,
            "session": "unknown",
            "calendar_days_remaining": None,
            "trading_days_remaining": None,
            "full_trading_sessions_remaining": None,
            "status": "unavailable",
            "calculation_method": "unavailable",
        }



def fetch_fred_series_points(series_id, limit=120):
    try:
        csv_text = http_get_text(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}", timeout=8)
        rows = []
        for raw_line in csv_text.splitlines()[1:]:
            if not raw_line or "," not in raw_line:
                continue
            date_text, value_text = raw_line.split(",", 1)
            value_text = value_text.strip()
            if not value_text or value_text == ".":
                continue
            value = _safe_float(value_text)
            if value is None:
                continue
            rows.append({"date": date_text.strip(), "value": value})
        return rows[-limit:]
    except Exception:
        return []


def parse_fear_greed_datetime(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        timestamp = value / 1000 if value > 10_000_000_000 else value
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def extract_fear_greed_records(node, records=None):
    if records is None:
        records = []
    if isinstance(node, dict):
        numeric_value = None
        for key in ("score", "value"):
            candidate = _safe_float(node.get(key))
            if candidate is not None and 0 <= candidate <= 100:
                numeric_value = candidate
                break
        if numeric_value is not None:
            label = (
                _safe_text(node.get("rating"))
                or _safe_text(node.get("label"))
                or _safe_text(node.get("classification"))
                or _safe_text(node.get("status"))
                or _safe_text(node.get("name"))
            )
            stamp = None
            for key in ("timestamp", "time", "x", "date", "updated_at"):
                stamp = parse_fear_greed_datetime(node.get(key))
                if stamp is not None:
                    break
            records.append({
                "value": numeric_value,
                "label": label,
                "timestamp": stamp,
            })
        for value in node.values():
            extract_fear_greed_records(value, records)
    elif isinstance(node, list):
        for item in node:
            extract_fear_greed_records(item, records)
    return records


def parse_fear_greed_payload(payload):
    records = extract_fear_greed_records(payload, [])
    if not records:
        return None
    deduped = []
    seen = set()
    for record in records:
        dedupe_key = (
            record["value"],
            record["label"],
            record["timestamp"].isoformat() if record["timestamp"] else None,
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(record)
    if not deduped:
        return None
    deduped.sort(key=lambda item: item["timestamp"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    latest = deduped[0]
    previous = deduped[1] if len(deduped) > 1 else None
    trend = None
    if previous is not None:
        delta = latest["value"] - previous["value"]
        if delta >= 3:
            trend = "rising"
        elif delta <= -3:
            trend = "falling"
        else:
            trend = "neutral"
    return {
        "value": latest["value"],
        "label": latest["label"] or fear_greed_label(latest["value"]),
        "trend": trend,
    }


def fetch_fear_greed_value():
    candidate_urls = [
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
        "https://production.dataviz.cnn.io/index/fearandgreed/current",
    ]
    for url in candidate_urls:
        try:
            payload = http_get_json_with_accept(url, timeout=6)
        except Exception:
            continue
        parsed = parse_fear_greed_payload(payload)
        if parsed is not None and parsed.get("value") is not None:
            return parsed
    return None


def fetch_fear_greed_snapshot():
    now = time.time()
    cached = FEAR_GREED_CACHE.get("value")
    if cached and FEAR_GREED_CACHE.get("expiresAt", 0) > now:
        return cached

    live_snapshot = fetch_fear_greed_value()
    if live_snapshot is not None and live_snapshot.get("value") is not None:
        snapshot = {
            "value": live_snapshot.get("value"),
            "label": live_snapshot.get("label") or fear_greed_label(live_snapshot.get("value")),
            "trend": live_snapshot.get("trend"),
            "source_name": "CNN Fear & Greed",
            "source_status": "Live",
            "source_reason": None,
        }
        FEAR_GREED_CACHE["value"] = snapshot
        FEAR_GREED_CACHE["expiresAt"] = now + (30 * 60)
        return snapshot

    if cached:
        stale_snapshot = dict(cached)
        stale_snapshot["source_status"] = "Stale"
        stale_snapshot["source_reason"] = "Using the last successful CNN Fear & Greed snapshot because the live feed is unavailable."
        return stale_snapshot

    return {
        "value": None,
        "label": None,
        "trend": None,
        "source_name": "CNN Fear & Greed",
        "source_status": "Data unavailable",
        "source_reason": "CNN Fear & Greed feed is unavailable.",
    }


def summarize_fomc_rate_path(series_points):
    if not series_points:
        return None
    latest = series_points[-1]
    latest_value = latest.get("value")
    if latest_value is None:
        return None
    baseline = None
    for point in reversed(series_points[:-1]):
        if point.get("value") is None:
            continue
        if abs(point["value"] - latest_value) >= 0.05:
            baseline = point
            break
    if baseline is None:
        return {
            "current_rate": latest_value,
            "last_change": 0.0,
            "direction": "unchanged",
            "summary": f"Fed funds rate is {latest_value:.2f}% and has not changed recently.",
            "last_change_date": latest.get("date"),
        }
    delta = round(latest_value - baseline["value"], 2)
    direction = "hike" if delta > 0 else "cut"
    summary = (
        f"Fed funds rate is {latest_value:.2f}%. Latest FOMC path points to a {direction} of {abs(delta):.2f}% versus {baseline['date']}."
    )
    return {
        "current_rate": latest_value,
        "last_change": delta,
        "direction": direction,
        "summary": summary,
        "last_change_date": baseline.get("date"),
    }


def parse_google_news_rss(query, market="us", limit=6):
    if not query:
        return []
    hl, gl, ceid = "en-US", "US", "US:en"
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl={hl}&gl={gl}&ceid={quote_plus(ceid)}"
    xml_text = http_get_text(url, timeout=8)
    root = ET.fromstring(xml_text)
    articles = []
    seen = set()
    for item in root.findall(".//item"):
        raw_title = unescape(_safe_text(item.findtext("title")))
        if not raw_title:
            continue
        source = None
        headline = raw_title
        if " - " in raw_title:
            headline, source = raw_title.rsplit(" - ", 1)
        headline = headline.strip()
        dedupe_key = headline.lower()
        if not headline or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        published_at = _safe_text(item.findtext("pubDate"))
        try:
            if published_at:
                published_at = parsedate_to_datetime(published_at).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pass
        articles.append({
            "headline": headline,
            "source": source,
            "link": _safe_text(item.findtext("link")),
            "published_at": published_at,
        })
        if len(articles) >= limit:
            break
    return articles


def normalize_yfinance_news_items(raw_items, limit=6):
    if not raw_items:
        return []
    articles = []
    seen = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        content = raw.get("content") if isinstance(raw.get("content"), dict) else {}
        candidate = content or raw
        headline = unescape(_safe_text(candidate.get("title") or raw.get("title")))
        if not headline:
            continue
        dedupe_key = headline.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        link = (
            _safe_text(candidate.get("canonicalUrl", {}).get("url") if isinstance(candidate.get("canonicalUrl"), dict) else None)
            or _safe_text(candidate.get("clickThroughUrl", {}).get("url") if isinstance(candidate.get("clickThroughUrl"), dict) else None)
            or _safe_text(candidate.get("link"))
            or _safe_text(raw.get("link"))
        )
        source = (
            _safe_text(candidate.get("provider", {}).get("displayName") if isinstance(candidate.get("provider"), dict) else None)
            or _safe_text(raw.get("publisher"))
            or _safe_text(raw.get("provider"))
        )
        published_at = (
            candidate.get("pubDate")
            or raw.get("providerPublishTime")
            or raw.get("published")
            or raw.get("published_at")
        )
        if isinstance(published_at, (int, float)):
            timestamp = published_at / 1000 if published_at > 10_000_000_000 else published_at
            try:
                published_at = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                published_at = None
        elif published_at:
            published_at = _safe_text(published_at)

        articles.append({
            "headline": headline,
            "source": source,
            "link": link,
            "published_at": published_at,
        })
        if len(articles) >= limit:
            break
    return articles


def merge_news_articles(primary, fallback, limit=6):
    merged = []
    seen = set()
    for bucket in [primary or [], fallback or []]:
        for article in bucket:
            headline = _safe_text(article.get("headline"))
            if not headline:
                continue
            dedupe_key = headline.lower()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            merged.append(article)
            if len(merged) >= limit:
                return merged
    return merged


def fetch_yfinance_company_news(symbol, limit=6):
    try:
        ticker = yf.Ticker(symbol)
        raw_items = []
        if hasattr(ticker, "get_news"):
            try:
                raw_items = ticker.get_news(count=limit)
            except TypeError:
                raw_items = ticker.get_news()
            except Exception:
                raw_items = []
        if not raw_items:
            raw_items = getattr(ticker, "news", []) or []
        return normalize_yfinance_news_items(raw_items, limit=limit)
    except Exception:
        return []


def fetch_yfinance_market_news(symbols=None, limit=6):
    merged = []
    seen = set()
    for symbol in (symbols or ["SPY", "QQQ", "^GSPC"]):
        for article in fetch_yfinance_company_news(symbol, limit=limit):
            headline = _safe_text(article.get("headline"))
            if not headline:
                continue
            dedupe_key = headline.lower()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            merged.append(article)
            if len(merged) >= limit:
                return merged
    return merged


def score_news_articles(articles, fallback_summary, market="company"):
    if not articles:
        return {
            "score": 50,
            "sentiment": None,
            "summary": fallback_summary,
            "key_points": [],
            "bullish_news": [],
            "bearish_news": [],
            "key_catalysts": [],
            "risk_events": [],
        }

    running = 0
    bullish = []
    bearish = []
    key_points = []
    for article in articles:
        headline = _safe_text(article.get("headline"))
        if not headline:
            continue
        lowered = headline.lower()
        positive_hits = sum(1 for keyword in POSITIVE_NEWS_KEYWORDS if keyword.lower() in lowered)
        negative_hits = sum(1 for keyword in NEGATIVE_NEWS_KEYWORDS if keyword.lower() in lowered)
        delta = max(-3, min(3, positive_hits - negative_hits))
        if market == "macro" and any(word in lowered for word in ["tariff", "war", "conflict", "inflation", "hawkish", "antitrust", "probe"]):
            delta -= 1
        running += delta
        label = headline if not article.get("source") else f"{headline} · {article.get('source')}"
        key_points.append(label)
        if delta > 0:
            bullish.append(label)
        elif delta < 0:
            bearish.append(label)

    score = max(25, min(78, int(round(50 + running * 6))))
    sentiment = "neutral"
    if score >= 58:
        sentiment = "bullish"
    elif score <= 42:
        sentiment = "bearish"

    if market == "macro":
        if sentiment == "bullish":
            summary = "Broad macro-news flow is leaning supportive."
        elif sentiment == "bearish":
            summary = "Broad macro-news flow is leaning risk-off."
        else:
            summary = "Macro-news flow is mixed and currently balanced."
    else:
        if sentiment == "bullish":
            summary = "Recent company headlines are leaning constructive."
        elif sentiment == "bearish":
            summary = "Recent company headlines are leaning cautious."
        else:
            summary = "Recent company headlines are mixed."

    return {
        "score": score,
        "sentiment": sentiment,
        "summary": summary,
        "key_points": key_points[:4],
        "bullish_news": bullish[:3],
        "bearish_news": bearish[:3],
        "key_catalysts": bullish[:3],
        "risk_events": bearish[:3],
    }


def classify_macro_events(articles):
    events = []
    for article in articles[:5]:
        headline = _safe_text(article.get("headline"))
        lowered = headline.lower()
        event_type = "other"
        for candidate, pattern in MACRO_EVENT_PATTERNS:
            if pattern.search(lowered):
                event_type = candidate
                break
        impact = "mixed"
        severity = "low"
        if any(word in lowered for word in ["tariff", "war", "conflict", "inflation", "hawkish", "probe", "sanction"]):
            impact = "negative"
            severity = "high" if any(word in lowered for word in ["war", "missile", "sanction", "tariff"]) else "medium"
        elif any(word in lowered for word in ["rate cut", "cooling inflation", "stimulus", "rebound"]):
            impact = "positive"
            severity = "medium"
        events.append({
            "event_type": event_type,
            "headline": headline,
            "summary": headline,
            "affected_sectors": [],
            "affected_tickers": [],
            "impact": impact,
            "severity": severity,
            "source": article.get("source"),
            "link": article.get("link"),
            "published_at": article.get("published_at"),
        })
    return events


def fetch_company_news_payload(ticker, quote):
    symbol = quote.get("symbol") or ticker
    company_name = quote.get("longName") or quote.get("shortName") or ticker
    query = f"{symbol} {company_name} stock"
    try:
        google_articles = parse_google_news_rss(query, market="us", limit=6)
        yf_articles = fetch_yfinance_company_news(symbol, limit=6)
        articles = merge_news_articles(google_articles, yf_articles, limit=6)
        scored = score_news_articles(
            articles,
            "Recent company-news feed is unavailable, so this module stays neutral.",
            market="company",
        )
        return {
            "sentiment": scored["sentiment"],
            "score": scored["score"],
            "summary": scored["summary"],
            "key_points": scored["key_points"],
            "latest_news": articles[:5],
            "bullish_news": scored["bullish_news"],
            "bearish_news": scored["bearish_news"],
            "key_catalysts": scored["key_catalysts"],
            "risk_events": scored["risk_events"],
            "source_info": build_source_info(
                "Live",
                source_name="Google News RSS / Yahoo Finance",
                suggested_source="Google News RSS / Yahoo Finance / FMP / Polygon",
            ),
        }
    except Exception as exc:
        return {
            "sentiment": None,
            "score": 50,
            "summary": f"Company-news feed unavailable: {exc}",
            "key_points": [],
            "latest_news": [],
            "bullish_news": [],
            "bearish_news": [],
            "key_catalysts": [],
            "risk_events": [],
            "source_info": build_source_info(
                "Data unavailable",
                missing_source="Google News RSS / Yahoo Finance",
                suggested_source="Google News RSS / Yahoo Finance / FMP / Polygon",
                source_name="Company News Feed",
            ),
        }


def fetch_single_symbol_last_close(symbol):
    try:
        history = yf.Ticker(symbol).history(period="5d", interval="1d", auto_adjust=False)
        if history is None or history.empty:
            ticker = yf.Ticker(symbol)
            fast_info = getattr(ticker, "fast_info", {}) or {}
            return _safe_float(
                fast_info.get("lastPrice")
                or fast_info.get("regularMarketPrice")
                or fast_info.get("previousClose")
            )
        closes = history["Close"].dropna()
        if closes.empty:
            ticker = yf.Ticker(symbol)
            fast_info = getattr(ticker, "fast_info", {}) or {}
            return _safe_float(
                fast_info.get("lastPrice")
                or fast_info.get("regularMarketPrice")
                or fast_info.get("previousClose")
            )
        return _safe_float(closes.iloc[-1])
    except Exception:
        return None


def fetch_symbol_history_points(symbol, period="3mo", interval="1d", limit=60, value_scale=1.0):
    try:
        history = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False)
        if history is None or history.empty:
            raise ValueError("empty yfinance history")
        rows = []
        closes = history.get("Close")
        if closes is None:
            raise ValueError("missing close series")
        for index, raw_value in closes.dropna().items():
            value = _safe_float(raw_value)
            if value is None:
                continue
            if hasattr(index, "to_pydatetime"):
                stamp = index.to_pydatetime()
            elif isinstance(index, datetime):
                stamp = index
            else:
                try:
                    stamp = pd.Timestamp(index).to_pydatetime()
                except Exception:
                    stamp = None
            if stamp is None:
                continue
            rows.append({
                "date": stamp.date().isoformat(),
                "value": value * value_scale,
            })
        if rows:
            return rows[-limit:]
    except Exception:
        pass
    yahoo_points = fetch_yahoo_chart_points(symbol, range_value=period, interval=interval, limit=limit, value_scale=value_scale)
    if yahoo_points:
        return yahoo_points
    stooq_rows = fetch_stooq_history_rows(symbol, limit=limit)
    return [
        {"date": row["date"], "value": row["close"] * value_scale}
        for row in stooq_rows
        if row.get("close") is not None
    ][-limit:]


def scale_series_points(series_points, scale):
    if not series_points:
        return []
    return [
        {
            "date": point.get("date"),
            "value": (_safe_float(point.get("value")) * scale) if _safe_float(point.get("value")) is not None else None,
        }
        for point in series_points
        if _safe_float(point.get("value")) is not None
    ]


def fetch_treasury_history_points(limit=40):
    yahoo_points = fetch_symbol_history_points("^TNX", period="3mo", interval="1d", limit=limit, value_scale=1.0)
    latest = latest_series_value(yahoo_points)
    if latest is not None and latest > 20:
        return scale_series_points(yahoo_points, 0.1)
    if yahoo_points:
        return yahoo_points
    return fetch_fred_series_points("DGS10", limit=limit)


def latest_series_value(series_points):
    if not series_points:
        return None
    latest = series_points[-1]
    return _safe_float(latest.get("value"))


def series_change(series_points, sessions_back=5):
    if not series_points or len(series_points) < 2:
        return None
    latest_value = latest_series_value(series_points)
    if latest_value is None:
        return None
    anchor_index = max(0, len(series_points) - 1 - max(1, int(sessions_back)))
    anchor_value = None
    for point in reversed(series_points[:anchor_index + 1]):
        anchor_value = _safe_float(point.get("value"))
        if anchor_value is not None:
            break
    if anchor_value is None:
        return None
    return round(latest_value - anchor_value, 2)


def classify_change_trend(change_5d, change_20d, short_threshold, long_threshold):
    if change_5d is None and change_20d is None:
        return "neutral"
    short_value = change_5d or 0.0
    long_value = change_20d or 0.0
    if short_value >= short_threshold or long_value >= long_threshold:
        return "rising"
    if short_value <= -short_threshold or long_value <= -long_threshold:
        return "falling"
    return "neutral"


def fear_greed_label(value):
    if value is None:
        return None
    if value <= 25:
        return "Extreme Fear"
    if value <= 45:
        return "Fear"
    if value <= 55:
        return "Neutral"
    if value <= 75:
        return "Greed"
    return "Extreme Greed"


def load_market_events():
    try:
        if not os.path.exists(MARKET_EVENTS_FILE):
            return []
        with open(MARKET_EVENTS_FILE, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        events = payload.get("events", []) if isinstance(payload, dict) else []
        return [event for event in events if isinstance(event, dict)]
    except Exception:
        return []


def parse_iso_date(date_text):
    try:
        return datetime.strptime(str(date_text).strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def find_active_market_event(events, as_of_date=None, lookback_days=3):
    if not events:
        return {
            "active": False,
            "type": None,
            "title": None,
            "impact": None,
            "severity": None,
            "summary": "No recent Fed or macro event is active in the configured window.",
            "date": None,
            "source": "market_events.json",
        }
    today = as_of_date or datetime.now(timezone.utc).date()
    window_start = today - timedelta(days=lookback_days)
    ranked = []
    severity_rank = {"high": 3, "medium": 2, "low": 1}
    for event in events:
        event_date = parse_iso_date(event.get("date"))
        if event_date is None or event_date < window_start or event_date > today:
            continue
        ranked.append((event_date, severity_rank.get(str(event.get("severity", "")).lower(), 0), event))
    if not ranked:
        return {
            "active": False,
            "type": None,
            "title": None,
            "impact": None,
            "severity": None,
            "summary": "No recent Fed or macro event is active in the configured window.",
            "date": None,
            "source": "market_events.json",
        }
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    chosen = ranked[0][2]
    return {
        "active": True,
        "type": _safe_text(chosen.get("type")),
        "title": _safe_text(chosen.get("title")),
        "impact": _safe_text(chosen.get("impact")),
        "severity": _safe_text(chosen.get("severity")) or "medium",
        "summary": _safe_text(chosen.get("summary")) or _safe_text(chosen.get("title")) or "Recent configured macro event is active.",
        "date": parse_iso_date(chosen.get("date")).isoformat(),
        "source": "market_events.json",
    }


def build_index_trend(symbol, label):
    points = fetch_symbol_history_points(symbol, period="1y", interval="1d", limit=180)
    if not points:
        return {
            "symbol": symbol,
            "label": label,
            "value": None,
            "change_5d_pct": None,
            "change_20d_pct": None,
            "change_60d_pct": None,
            "change_120d_pct": None,
            "trend": "neutral",
            "impact": "Data unavailable",
        }
    current_value = latest_series_value(points)
    def pct_change_for_lookback(lookback):
        if current_value is None or len(points) <= lookback:
            return None
        base_value = _safe_float(points[max(0, len(points) - lookback - 1)].get("value"))
        if base_value in (None, 0):
            return None
        return round(((current_value - base_value) / base_value) * 100, 2)
    change_5d_pct = pct_change_for_lookback(5)
    change_20d_pct = pct_change_for_lookback(20)
    change_60d_pct = pct_change_for_lookback(60)
    change_120d_pct = pct_change_for_lookback(120)
    trend = "neutral"
    if (change_5d_pct or 0) >= 1.5 and (change_20d_pct or 0) >= 0:
        trend = "rising"
    elif (change_5d_pct or 0) <= -1.5 and (change_20d_pct or 0) <= 0:
        trend = "falling"
    impact = "Neutral"
    if trend == "rising":
        impact = "Supportive equity trend"
    elif trend == "falling":
        impact = "Broad market trend is soft"
    return {
        "symbol": symbol,
        "label": label,
        "value": current_value,
        "change_5d_pct": change_5d_pct,
        "change_20d_pct": change_20d_pct,
        "change_60d_pct": change_60d_pct,
        "change_120d_pct": change_120d_pct,
        "trend": trend,
        "impact": impact,
    }


SECTOR_ETF_BENCHMARKS = {
    "XLK": "Technology",
    "SMH": "Semiconductors",
    "IGV": "Software",
    "XLY": "Consumer Discretionary",
    "XLF": "Financials",
    "XLV": "Healthcare",
    "VNQ": "Real Estate",
}


def fetch_market_context_core_sources():
    tasks = {
        "vix_points": lambda: (
            fetch_symbol_history_points("^VIX", period="3mo", interval="1d", limit=40)
            or fetch_fred_series_points("VIXCLS", limit=40)
        ),
        "treasury_points": lambda: fetch_treasury_history_points(limit=40),
        "fear_greed_snapshot": fetch_fear_greed_snapshot,
        "spy_trend": lambda: build_index_trend("SPY", "SPY"),
        "qqq_trend": lambda: build_index_trend("QQQ", "QQQ"),
    }
    for symbol in SECTOR_ETF_BENCHMARKS:
        tasks[f"sector_{symbol.lower()}"] = lambda symbol=symbol: build_index_trend(symbol, symbol)
    defaults = {
        "vix_points": [],
        "treasury_points": [],
        "fear_greed_snapshot": {
            "value": None,
            "label": None,
            "trend": None,
            "source_name": "CNN Fear & Greed",
            "source_status": "Data unavailable",
            "source_reason": "CNN Fear & Greed feed is unavailable.",
        },
        "spy_trend": build_unavailable_market_trend("SPY"),
        "qqq_trend": build_unavailable_market_trend("QQQ"),
    }
    for symbol in SECTOR_ETF_BENCHMARKS:
        defaults[f"sector_{symbol.lower()}"] = build_unavailable_market_trend(symbol)
    results = dict(defaults)
    executor = ThreadPoolExecutor(max_workers=len(tasks))
    futures = {executor.submit(task): name for name, task in tasks.items()}
    try:
        for future in as_completed(futures, timeout=7):
            name = futures[future]
            try:
                value = future.result(timeout=1)
                if value:
                    results[name] = value
            except Exception:
                continue
    except FuturesTimeoutError:
        pass
    finally:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
    return results


def build_unavailable_market_trend(symbol):
    return {
        "symbol": symbol,
        "label": symbol,
        "value": None,
        "change_5d_pct": None,
        "change_20d_pct": None,
        "change_60d_pct": None,
        "change_120d_pct": None,
        "trend": "neutral",
        "impact": "Data unavailable",
    }


def fetch_market_context_payload():
    core_sources = fetch_market_context_core_sources()
    vix_points = core_sources["vix_points"]
    vix = latest_series_value(vix_points)
    vix_5d_change = series_change(vix_points, 5)
    vix_20d_change = series_change(vix_points, 20)
    vix_trend = classify_change_trend(vix_5d_change, vix_20d_change, 1.0, 2.5)
    treasury_points = core_sources["treasury_points"]
    treasury_yield = latest_series_value(treasury_points)
    yield_5d_change = series_change(treasury_points, 5)
    yield_20d_change = series_change(treasury_points, 20)
    yield_5d_change_bps = round(yield_5d_change * 100, 1) if yield_5d_change is not None else None
    yield_20d_change_bps = round(yield_20d_change * 100, 1) if yield_20d_change is not None else None
    yield_trend = classify_change_trend(yield_5d_change_bps, yield_20d_change_bps, 10.0, 25.0)
    fed_funds_value = None
    fomc_rate_path = None
    fear_greed_snapshot = core_sources["fear_greed_snapshot"]
    fear_greed = fear_greed_snapshot.get("value")
    fear_greed_label_value = fear_greed_snapshot.get("label") or fear_greed_label(fear_greed)
    active_event = find_active_market_event(load_market_events(), datetime.now(timezone.utc).date(), lookback_days=3)
    spy_trend = core_sources["spy_trend"]
    qqq_trend = core_sources["qqq_trend"]
    sector_trends = {
        symbol: core_sources.get(f"sector_{symbol.lower()}") or build_unavailable_market_trend(symbol)
        for symbol in SECTOR_ETF_BENCHMARKS
    }
    # News and Fed event scraping are intentionally excluded from the fast
    # market-context refresh. The stable core is VIX, 10Y, sentiment and indices.
    macro_articles = []
    filtered_events = classify_macro_events(macro_articles)
    macro_articles = [article for article, event in zip(macro_articles, filtered_events) if event.get("event_type") != "other"] or macro_articles
    macro_news = score_news_articles(
        macro_articles,
        "Broad macro-news feed is currently unavailable, so macro stays neutral.",
        market="macro",
    )
    broad_events = [event for event in classify_macro_events(macro_articles) if event.get("event_type") != "other"][:5]
    fed_type = active_event.get("type")
    rising_indices = [item for item in [spy_trend, qqq_trend] if item.get("trend") == "rising"]
    falling_indices = [item for item in [spy_trend, qqq_trend] if item.get("trend") == "falling"]

    regime = "neutral"
    if active_event.get("active") and fed_type in {"fed_rate_hike", "fed_hawkish"}:
        regime = "risk_off"
    elif (vix is not None and vix >= 30) or len(falling_indices) == 2:
        regime = "risk_off"
    elif vix is not None and vix < 20 and len(rising_indices) == 2:
        regime = "risk_on"

    vix_impact = "Neutral volatility backdrop."
    if vix is None:
        vix_impact = "Data unavailable"
    elif vix > 30:
        vix_impact = "High volatility is a clear short-term risk-off signal."
    elif vix >= 20:
        vix_impact = "Elevated volatility keeps short-term risk appetite in check."
    elif vix < 15:
        vix_impact = "Low volatility is supportive for risk appetite."

    yield_impact = "Neutral yield backdrop."
    if treasury_yield is None:
        yield_impact = "Data unavailable"
    elif yield_trend == "rising":
        yield_impact = "Rising 10Y yield is usually negative for high multiple, REIT, and rate-sensitive stocks."
    elif yield_trend == "falling":
        yield_impact = "Falling 10Y yield is generally supportive for duration-sensitive equities."

    fear_greed_impact = "Neutral sentiment read."
    if fear_greed_label_value == "Extreme Fear":
        fear_greed_impact = "Extreme fear raises short-term caution but can create medium-term opportunity."
    elif fear_greed_label_value == "Fear":
        fear_greed_impact = "Fear argues for more patient entries in the short term."
    elif fear_greed_label_value == "Greed":
        fear_greed_impact = "Greed raises short-term chasing risk."
    elif fear_greed_label_value == "Extreme Greed":
        fear_greed_impact = "Extreme greed raises chase risk and can favor covered-call style positioning."

    trend_summary = "Broad index trend is mixed."
    if len(rising_indices) == 2:
        trend_summary = "SPY and QQQ are both trending higher, which is supportive for risk appetite."
    elif len(falling_indices) == 2:
        trend_summary = "SPY and QQQ are both soft, which keeps the backdrop risk-off."

    market_summary = "Market environment is balanced."
    if regime == "risk_off":
        market_summary = "Market environment is leaning risk-off due to volatility, yields, or a hawkish macro event."
    elif regime == "risk_on":
        market_summary = "Market environment is leaning risk-on with supportive volatility, yield, and index trends."

    macro_summary_bits = []
    if vix is not None:
        macro_summary_bits.append(f"VIX {vix:.1f}")
    if fear_greed is not None:
        macro_summary_bits.append(f"Fear & Greed {fear_greed:.0f}/100 ({fear_greed_label_value})")
    if treasury_yield is not None:
        macro_summary_bits.append(f"10Y {treasury_yield:.2f}%")
    if fed_funds_value is not None:
        macro_summary_bits.append(f"Fed funds {fed_funds_value:.2f}%")
    macro_summary_bits.append(market_summary)
    if active_event.get("active") and active_event.get("summary"):
        macro_summary_bits.append(active_event["summary"])

    market_context = {
        "regime": regime,
        "vix": {
            "value": vix,
            "change_5d": vix_5d_change,
            "change_20d": vix_20d_change,
            "trend": vix_trend,
            "impact": vix_impact,
        },
        "fear_greed": {
            "value": fear_greed,
            "label": fear_greed_label_value,
            "trend": fear_greed_snapshot.get("trend"),
            "impact": fear_greed_impact,
        },
        "ten_year_yield": {
            "value": treasury_yield,
            "change_5d_bps": yield_5d_change_bps,
            "change_20d_bps": yield_20d_change_bps,
            "trend": yield_trend,
            "impact": yield_impact,
        },
        "fed_event": active_event,
        "equity_trend": {
            "spy": spy_trend,
            "qqq": qqq_trend,
            "summary": trend_summary,
            "impact": "supportive" if len(rising_indices) == 2 else "cautious" if len(falling_indices) == 2 else "neutral",
        },
        "sector_trends": sector_trends,
        "summary": market_summary,
        "source_info": {
            "vix": build_source_info("Live" if vix is not None else "Data unavailable", missing_source="Cboe / FRED / Yahoo Finance", suggested_source="FRED VIXCLS / Yahoo Finance ^VIX / Cboe", source_name="FRED VIXCLS"),
            "fear_greed": build_source_info(
                fear_greed_snapshot.get("source_status") or ("Live" if fear_greed is not None else "Data unavailable"),
                missing_source=fear_greed_snapshot.get("source_reason") or "CNN Fear & Greed",
                suggested_source="CNN Fear & Greed direct endpoint / CNN scraper / RapidAPI / custom in-house sentiment composite.",
                source_name=fear_greed_snapshot.get("source_name") or "Fear & Greed",
            ),
            "ten_year_yield": build_source_info("Live" if treasury_yield is not None else "Data unavailable", missing_source="FRED DGS10 / Yahoo Finance ^TNX", suggested_source="FRED DGS10 / Yahoo Finance ^TNX / Alpha Vantage", source_name="FRED DGS10"),
            "fed_event": build_source_info("Live", missing_source="Economic calendar / market_events.json", suggested_source="FMP Economic Calendar / Alpha Vantage / market_events.json", source_name="market_events.json"),
            "equity_trend": build_source_info("Live" if spy_trend.get("value") is not None or qqq_trend.get("value") is not None else "Data unavailable", missing_source="Yahoo Finance SPY / QQQ", suggested_source="Yahoo Finance SPY / QQQ", source_name="Yahoo Finance"),
            "sector_trends": build_source_info("Live" if any((trend or {}).get("value") is not None for trend in sector_trends.values()) else "Data unavailable", missing_source="Yahoo Finance sector ETFs", suggested_source="Yahoo Finance XLK / SMH / IGV / XLY / XLF / XLV", source_name="Yahoo Finance"),
        },
    }

    return {
        "macro": {
            "vix": vix,
            "fear_greed": fear_greed,
            "treasury_yield": treasury_yield,
            "fed_funds_rate": fed_funds_value,
            "fomc_rate_path": fomc_rate_path,
            "summary": " · ".join(macro_summary_bits) if macro_summary_bits else "Macro data is neutral due to missing live feeds.",
            "source_info": {
                "vix": build_source_info("Live" if vix is not None else "Data unavailable", missing_source="Cboe / FRED / Yahoo Finance", suggested_source="FRED VIXCLS / Yahoo Finance ^VIX / Cboe", source_name="FRED VIXCLS"),
                "fear_greed": build_source_info(
                    fear_greed_snapshot.get("source_status") or ("Live" if fear_greed is not None else "Data unavailable"),
                    missing_source=fear_greed_snapshot.get("source_reason") or "CNN Fear & Greed",
                    suggested_source="CNN Fear & Greed direct endpoint / CNN scraper / RapidAPI / custom in-house sentiment composite.",
                    source_name=fear_greed_snapshot.get("source_name") or "Fear & Greed",
                ),
                "treasury_yield": build_source_info("Live" if treasury_yield is not None else "Data unavailable", missing_source="FRED / Yahoo Finance ^TNX", suggested_source="FRED DGS10 / Yahoo Finance ^TNX / Alpha Vantage", source_name="FRED DGS10"),
                "fed_funds_rate": build_source_info("Live" if fed_funds_value is not None else "Data unavailable", missing_source="FRED DFF / FEDFUNDS", suggested_source="FRED DFF / FEDFUNDS", source_name="FRED"),
                "fomc_rate_path": build_source_info("Live" if fomc_rate_path is not None else "Data unavailable", missing_source="Federal Reserve / FRED", suggested_source="Federal Reserve FOMC / FRED DFF", source_name="FRED / Federal Reserve"),
                "market_events": build_source_info("Live", missing_source="Economic calendar / market_events.json", suggested_source="FMP Economic Calendar / Alpha Vantage / market_events.json", source_name="market_events.json"),
                "equity_trend": build_source_info("Live" if spy_trend.get("value") is not None or qqq_trend.get("value") is not None else "Data unavailable", missing_source="Yahoo Finance SPY / QQQ", suggested_source="Yahoo Finance SPY / QQQ", source_name="Yahoo Finance"),
            },
        },
        "market_context": market_context,
        "broad_macro_news": {
            "score": macro_news["score"],
            "sentiment": macro_news["sentiment"],
            "major_events": broad_events,
            "summary": macro_news["summary"],
            "source_info": build_source_info(
                "Live" if macro_articles else "Data unavailable",
                missing_source="Broad market news feed",
                suggested_source="Google News RSS / Reuters / FMP Market News / Alpha Vantage News",
                source_name="Google News RSS",
            ),
        },
    }


def _purge_expired_company_news_cache_unlocked(now):
    expired_keys = [
        key for key, entry in COMPANY_NEWS_CACHE.items()
        if not isinstance(entry, dict) or entry.get("expiresAt", 0) <= now
    ]
    for key in expired_keys:
        COMPANY_NEWS_CACHE.pop(key, None)
    return len(expired_keys)


def purge_expired_company_news_cache(now=None):
    """Drop expired news payloads without imposing a ticker-count limit."""
    current_time = time.time() if now is None else now
    with COMPANY_NEWS_CACHE_LOCK:
        return _purge_expired_company_news_cache_unlocked(current_time)


def get_cached_company_news(ticker, quote):
    # News is ticker-level content, not a price-level metric. One stable key
    # replaces the prior payload after its TTL instead of accumulating a key
    # for every quote timestamp.
    cache_key = normalize_ticker_input(ticker) or str(ticker or "").upper()
    now = time.time()
    with COMPANY_NEWS_CACHE_LOCK:
        _purge_expired_company_news_cache_unlocked(now)
        cached = COMPANY_NEWS_CACHE.get(cache_key)
        if cached and cached.get("expiresAt", 0) > now:
            return cached.get("value")

    value = fetch_company_news_payload(ticker, quote)
    stored_at = time.time()
    with COMPANY_NEWS_CACHE_LOCK:
        _purge_expired_company_news_cache_unlocked(stored_at)
        COMPANY_NEWS_CACHE[cache_key] = {
            "value": value,
            "expiresAt": stored_at + NEWS_CACHE_SECONDS,
        }
    return value


def get_cached_market_context():
    now = time.time()
    cached = MARKET_CONTEXT_CACHE.get("value")
    if cached and MARKET_CONTEXT_CACHE["expiresAt"] > now:
        cached_vix = ((cached.get("market_context") or {}).get("vix") or {}).get("value")
        cached_yield = ((cached.get("market_context") or {}).get("ten_year_yield") or {}).get("value")
        cached_fear_greed = ((cached.get("market_context") or {}).get("fear_greed") or {}).get("value")
        cache_age_budget = MARKET_CONTEXT_CACHE["expiresAt"] - now
        critical_missing = cached_vix is None or cached_yield is None or cached_fear_greed is None
        if not critical_missing or cache_age_budget > (NEWS_CACHE_SECONDS - 90):
            return cached
    value = fetch_market_context_payload()
    MARKET_CONTEXT_CACHE["value"] = value
    MARKET_CONTEXT_CACHE["expiresAt"] = now + NEWS_CACHE_SECONDS
    return value


def build_unavailable_options_payload(reason, market="us"):
    return {
        "snapshotVersion": OPTIONS_SNAPSHOT_VERSION,
        "available": False,
        "market": market,
        "reason": reason,
        "callWall": None,
        "putWall": None,
        "gammaFlip": None,
        "gammaFlipStatus": "unavailable_no_real_gex",
        "impliedVolatility": None,
        "historicVolatility": None,
        "ivPercentile": None,
        "ivRank": None,
        "netGammaExposure": None,
        "expiries": [],
        "nearestExpiry": None,
        "updatedAt": None,
        "expectedMove": {
            "atmStraddleMove": None,
            "atmStraddleMovePct": None,
            "sevenDayMove": None,
            "sevenDayMovePct": None,
            "thirtyDayMove": None,
            "thirtyDayMovePct": None,
            "source": None,
            "samples": [],
        },
        "skew": {
            "putCallIvSkew": None,
            "method": None,
            "source": None,
        },
        "termStructure": {
            "frontIv": None,
            "backIv": None,
            "slope": None,
            "regime": None,
            "points": [],
        },
        "coverage": "none",
        "wallMethod": None,
    }


def build_unavailable_quote(ticker, reason, stale_value=None):
    base = stale_value.copy() if isinstance(stale_value, dict) else {}
    metadata = base.get("metadata") if isinstance(base.get("metadata"), dict) else {}
    history = base.get("history") if isinstance(base.get("history"), dict) else {}
    return {
        "price": base.get("price"),
        "previousClose": base.get("previousClose"),
        "change": base.get("change"),
        "changePercent": base.get("changePercent"),
        "updatedAt": base.get("updatedAt"),
        "symbol": base.get("symbol") or resolve_market_symbol(ticker),
        "shortName": base.get("shortName"),
        "longName": base.get("longName"),
        "exchangeName": base.get("exchangeName"),
        "metadata": {
            "sector": metadata.get("sector"),
            "industry": metadata.get("industry"),
            "businessSummary": metadata.get("businessSummary"),
            "country": metadata.get("country"),
            "city": metadata.get("city"),
            "state": metadata.get("state"),
            "exchange": metadata.get("exchange"),
            "quoteType": metadata.get("quoteType"),
            "ipoDate": metadata.get("ipoDate"),
            "earningsDate": metadata.get("earningsDate"),
            "earningsTimestamp": metadata.get("earningsTimestamp"),
            "earningsTimestampStart": metadata.get("earningsTimestampStart"),
            "earningsTimestampEnd": metadata.get("earningsTimestampEnd"),
            "daysToEarnings": metadata.get("daysToEarnings"),
            "earningsCountdown": metadata.get("earningsCountdown"),
        },
        "history": {
            "timestamps": history.get("timestamps", []),
            "closes": history.get("closes", []),
            "highs": history.get("highs", []),
            "lows": history.get("lows", []),
            "volumes": history.get("volumes", []),
        },
        "error": reason,
        "stale": bool(stale_value),
        "marketStatus": "closed" if stale_value else "unavailable",
        "dataStaleness": "stale" if stale_value else "unavailable",
        "last_successful_update": base.get("last_successful_update") or base.get("updatedAt"),
    }


def _norm_pdf(value):
    return math.exp(-0.5 * value * value) / math.sqrt(2 * math.pi)


def _weighted_average(values):
    weighted_total = 0.0
    total_weight = 0.0
    for value, weight in values:
        if value is None or weight is None or weight <= 0 or not math.isfinite(value) or not math.isfinite(weight):
            continue
        weighted_total += value * weight
        total_weight += weight
    if total_weight <= 0:
        return None
    return weighted_total / total_weight


def _run_with_timeout(func, timeout_seconds, fallback=None):
    result_queue = queue.Queue(maxsize=1)

    def worker():
        try:
            result_queue.put(("ok", func()))
        except Exception as exc:
            result_queue.put(("error", exc))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    try:
        status, payload = result_queue.get(timeout=timeout_seconds)
    except queue.Empty:
        return fallback

    if status == "error":
        return fallback
    return payload


def _median(values):
    filtered = sorted(
        value for value in (values or [])
        if value is not None and math.isfinite(value)
    )
    if not filtered:
        return None
    midpoint = len(filtered) // 2
    if len(filtered) % 2 == 1:
        return filtered[midpoint]
    return (filtered[midpoint - 1] + filtered[midpoint]) / 2


def _standard_deviation(values):
    filtered = [
        value for value in (values or [])
        if value is not None and math.isfinite(value)
    ]
    if len(filtered) < 2:
        return None
    average = sum(filtered) / len(filtered)
    variance = sum((value - average) ** 2 for value in filtered) / (len(filtered) - 1)
    if variance < 0 or not math.isfinite(variance):
        return None
    return math.sqrt(variance)


def _weighted_median(values):
    filtered = sorted(
        (
            (value, weight)
            for value, weight in (values or [])
            if value is not None and weight is not None and weight > 0 and math.isfinite(value) and math.isfinite(weight)
        ),
        key=lambda item: item[0],
    )
    if not filtered:
        return None
    total_weight = sum(weight for _, weight in filtered)
    threshold = total_weight / 2
    running = 0.0
    for value, weight in filtered:
        running += weight
        if running >= threshold:
            return value
    return filtered[-1][0]


def _annualized_volatility(returns):
    if returns is None or len(returns) < 2:
        return None
    mean_return = sum(returns) / len(returns)
    variance = sum((value - mean_return) ** 2 for value in returns) / (len(returns) - 1)
    if variance < 0 or not math.isfinite(variance):
        return None
    return math.sqrt(variance) * math.sqrt(252) * 100


def _close_to_close_volatility(closes, window):
    if closes is None or len(closes) < window:
        return None
    window_closes = closes[-window:]
    returns = []
    for previous_close, current_close in zip(window_closes, window_closes[1:]):
        previous_close = _safe_float(previous_close)
        current_close = _safe_float(current_close)
        if previous_close is None or current_close is None or previous_close <= 0 or current_close <= 0:
            continue
        returns.append(math.log(current_close / previous_close))
    return _annualized_volatility(returns)


def _parkinson_volatility(highs, lows, window):
    if highs is None or lows is None or len(highs) < window or len(lows) < window:
        return None
    window_highs = highs[-window:]
    window_lows = lows[-window:]
    log_ranges = []
    for high_value, low_value in zip(window_highs, window_lows):
        high_value = _safe_float(high_value)
        low_value = _safe_float(low_value)
        if high_value is None or low_value is None or high_value <= 0 or low_value <= 0 or high_value < low_value:
            continue
        log_ranges.append(math.log(high_value / low_value) ** 2)
    if not log_ranges:
        return None
    variance = sum(log_ranges) / (4 * len(log_ranges) * math.log(2))
    if variance < 0 or not math.isfinite(variance):
        return None
    return math.sqrt(variance) * math.sqrt(252) * 100


def _estimate_historic_volatility(closes, highs, lows):
    hv20 = _close_to_close_volatility(closes, 20)
    if hv20 is not None and math.isfinite(hv20):
        return hv20
    components = [
        (_close_to_close_volatility(closes, 30), 0.65),
        (_parkinson_volatility(highs, lows, 20), 0.35),
    ]
    return _weighted_average(components)


def _rolling_historic_volatility_proxy(closes, highs, lows, min_history=40):
    if closes is None or highs is None or lows is None:
        return []
    series = []
    length = min(len(closes), len(highs), len(lows))
    for end_index in range(min_history, length + 1):
        value = _estimate_historic_volatility(
            closes[:end_index],
            highs[:end_index],
            lows[:end_index],
        )
        if value is not None and math.isfinite(value):
            series.append(value)
    return series


def _build_iv_history_proxy(rolling_hv_series):
    if not rolling_hv_series:
        return []
    long_run_hv = _median(rolling_hv_series)
    if long_run_hv is None or long_run_hv <= 0:
        return []
    hv_vol_of_vol = _standard_deviation(rolling_hv_series)
    normalized_vol_of_vol = (hv_vol_of_vol / long_run_hv) if hv_vol_of_vol is not None and long_run_hv > 0 else 0.0
    base_premium = max(1.04, min(1.28, 1.05 + (min(long_run_hv, 100) / 100 * 0.18) + (min(normalized_vol_of_vol, 1.0) * 0.08)))
    regime_reactivity = max(0.32, min(0.52, 0.34 + (min(normalized_vol_of_vol, 1.0) * 0.10) + (min(long_run_hv, 100) / 100 * 0.06)))
    anchor = long_run_hv * base_premium
    proxy_series = []
    for hv_value in rolling_hv_series:
        proxy_value = anchor + ((hv_value - long_run_hv) * regime_reactivity)
        proxy_series.append(max(proxy_value, long_run_hv * 0.55))
    return proxy_series


def _estimate_iv_regime_metrics(current_iv, closes, highs, lows):
    historic_volatility = _estimate_historic_volatility(closes, highs, lows)
    return {
        "historicVolatility": historic_volatility,
        # Historical implied-volatility observations are not available from the
        # current chain feed. Historical realized volatility is not an IV proxy.
        "ivPercentile": None,
        "ivRank": None,
    }


def _frame_atm_iv_candidates(frame, spot_price, max_distance=0.06, limit=2):
    if frame is None or frame.empty or spot_price is None or spot_price <= 0:
        return []
    candidates = []
    for _, row in frame.iterrows():
        strike = _safe_float(row.get("strike"))
        implied_volatility = _safe_float(row.get("impliedVolatility"))
        open_interest = max(_safe_int(row.get("openInterest")) or 0, 0)
        volume = max(_safe_int(row.get("volume")) or 0, 0)
        if (
            strike is None
            or implied_volatility is None
            or implied_volatility <= 0
            or implied_volatility > 8
        ):
            continue
        distance = abs(strike - spot_price) / max(spot_price, 1)
        if distance > max_distance:
            continue
        liquidity = open_interest + (volume * 0.35)
        candidates.append({
            "iv": implied_volatility * 100,
            "distance": distance,
            "liquidity": liquidity,
        })
    return sorted(
        candidates,
        key=lambda item: (item["distance"], -item["liquidity"]),
    )[:limit]


def _estimate_expiry_atm_iv(calls_frame, puts_frame, spot_price, dte):
    call_candidates = _frame_atm_iv_candidates(calls_frame, spot_price)
    put_candidates = _frame_atm_iv_candidates(puts_frame, spot_price)
    candidates = call_candidates + put_candidates
    if not candidates:
        return None

    raw_center = _median([candidate["iv"] for candidate in candidates])
    filtered_candidates = [
        candidate for candidate in candidates
        if raw_center
        and abs(candidate["iv"] - raw_center) / max(raw_center, 1) <= 0.22
    ] or candidates

    expiry_weight = 1 / (1 + (abs(dte - 30) / 12))
    weighted_candidates = [
        (
            candidate["iv"],
            expiry_weight
            * (1 / (1 + ((candidate["distance"] / 0.01) ** 2)))
            * (1 + min(1.0, math.log1p(candidate["liquidity"]) / 6.0)),
        )
        for candidate in filtered_candidates
    ]
    weighted_iv = _weighted_average(weighted_candidates)
    if weighted_iv is None:
        return None

    weighted_center = _weighted_median(weighted_candidates) or weighted_iv
    if abs(weighted_iv - weighted_center) / max(weighted_center, 1) > 0.08:
        weighted_iv = (weighted_iv * 0.4) + (weighted_center * 0.6)

    total_liquidity = sum(candidate["liquidity"] for candidate in filtered_candidates)
    observation_weight = expiry_weight * max(0.75, 0.8 + min(0.9, math.log1p(total_liquidity) / 8.0))
    return weighted_iv, observation_weight


def _option_mid_price(row):
    bid = _safe_float(row.get("bid"))
    ask = _safe_float(row.get("ask"))
    last_price = _safe_float(row.get("lastPrice"))
    if bid is not None and ask is not None and bid >= 0 and ask >= bid and ask > 0:
        return (bid + ask) / 2
    if last_price is not None and last_price > 0:
        return last_price
    return None


def _nearest_atm_straddle_pair(calls_frame, puts_frame, spot_price):
    """Return a tradable same-strike ATM call/put pair, never a synthetic pair."""
    if (
        calls_frame is None
        or puts_frame is None
        or calls_frame.empty
        or puts_frame.empty
        or spot_price is None
        or spot_price <= 0
    ):
        return None

    def collect_contracts(frame):
        contracts = {}
        for _, row in frame.iterrows():
            strike = _safe_float(row.get("strike"))
            mid = _option_mid_price(row)
            if strike is None or strike <= 0 or mid is None or mid <= 0:
                continue
            key = round(strike, 6)
            liquidity = (_safe_int(row.get("openInterest")) or 0) + ((_safe_int(row.get("volume")) or 0) * 0.35)
            candidate = {"row": row, "strike": strike, "mid": mid, "liquidity": liquidity}
            existing = contracts.get(key)
            if existing is None or candidate["liquidity"] > existing["liquidity"]:
                contracts[key] = candidate
        return contracts

    calls = collect_contracts(calls_frame)
    puts = collect_contracts(puts_frame)
    common_strikes = set(calls).intersection(puts)
    if not common_strikes:
        return None

    candidates = []
    for key in common_strikes:
        call_contract = calls[key]
        put_contract = puts[key]
        candidates.append({
            "strike": call_contract["strike"],
            "call": call_contract,
            "put": put_contract,
            "distance": abs(call_contract["strike"] - spot_price),
            "liquidity": call_contract["liquidity"] + put_contract["liquidity"],
        })
    return min(candidates, key=lambda item: (item["distance"], -item["liquidity"]))


def _estimate_expiry_expected_move(calls_frame, puts_frame, spot_price, dte, atm_iv=None):
    if spot_price is None or spot_price <= 0 or dte is None or dte < 0:
        return None
    straddle_pair = _nearest_atm_straddle_pair(calls_frame, puts_frame, spot_price)
    if straddle_pair is None:
        return None
    straddle_move = straddle_pair["call"]["mid"] + straddle_pair["put"]["mid"]
    straddle_move_pct = (straddle_move / spot_price) * 100

    return {
        "daysToExpiry": dte,
        "callStrike": straddle_pair["strike"],
        "putStrike": straddle_pair["strike"],
        "atmIv": round(atm_iv, 2) if atm_iv is not None else None,
        "straddleMove": round(straddle_move, 2),
        "straddleMovePct": round(straddle_move_pct, 2),
        "ivMove": None,
        "ivMovePct": None,
        "source": "atm-straddle",
        "pairMethod": "same-strike-atm-call-put-mid",
    }


def _option_iv_near_moneyness(frame, spot_price, target_moneyness, tolerance=0.035):
    if frame is None or frame.empty or spot_price is None or spot_price <= 0:
        return None
    candidates = []
    for _, row in frame.iterrows():
        strike = _safe_float(row.get("strike"))
        implied_volatility = _safe_float(row.get("impliedVolatility"))
        if strike is None or implied_volatility is None or implied_volatility <= 0 or implied_volatility > 8:
            continue
        moneyness = strike / spot_price
        distance = abs(moneyness - target_moneyness)
        if distance > tolerance:
            continue
        liquidity = (_safe_int(row.get("openInterest")) or 0) + ((_safe_int(row.get("volume")) or 0) * 0.35)
        candidates.append((implied_volatility * 100, 1 / (1 + distance * 100) * (1 + min(1, math.log1p(liquidity) / 7))))
    return _weighted_average(candidates) if candidates else None


def _estimate_expiry_skew(calls_frame, puts_frame, spot_price):
    put_iv = _option_iv_near_moneyness(puts_frame, spot_price, 0.95)
    call_iv = _option_iv_near_moneyness(calls_frame, spot_price, 1.05)
    if put_iv is None or call_iv is None:
        return None
    return {
        "putCallIvSkew": round(put_iv - call_iv, 2),
        "putIv": round(put_iv, 2),
        "callIv": round(call_iv, 2),
        "method": "5pct-otm-iv-difference",
        "source": "yfinance-options-chain",
    }


def _nearest_expected_move_sample(samples, target_dte):
    if not samples:
        return None
    return min(samples, key=lambda item: (abs((item.get("daysToExpiry") or 9999) - target_dte), item.get("daysToExpiry") or 9999))


def _build_options_expected_move_payload(samples):
    if not samples:
        return {
            "atmStraddleMove": None,
            "atmStraddleMovePct": None,
            "sevenDayMove": None,
            "sevenDayMovePct": None,
            "thirtyDayMove": None,
            "thirtyDayMovePct": None,
            "source": None,
            "samples": [],
        }
    front = min(samples, key=lambda item: item.get("daysToExpiry") or 9999)
    seven_day = _nearest_expected_move_sample(samples, 7)
    thirty_day = _nearest_expected_move_sample(samples, 30)

    def pick_move(sample):
        if not sample:
            return None, None
        return sample.get("straddleMove"), sample.get("straddleMovePct")

    atm_move, atm_move_pct = pick_move(front)
    seven_move, seven_move_pct = pick_move(seven_day)
    thirty_move, thirty_move_pct = pick_move(thirty_day)
    return {
        "atmStraddleMove": atm_move,
        "atmStraddleMovePct": atm_move_pct,
        "atmStraddleExpiry": front.get("expiry"),
        "atmStraddleDaysToExpiry": front.get("daysToExpiry"),
        "sevenDayMove": seven_move,
        "sevenDayMovePct": seven_move_pct,
        "sevenDayExpiry": seven_day.get("expiry") if seven_day else None,
        "sevenDayDaysToExpiry": seven_day.get("daysToExpiry") if seven_day else None,
        "thirtyDayMove": thirty_move,
        "thirtyDayMovePct": thirty_move_pct,
        "thirtyDayExpiry": thirty_day.get("expiry") if thirty_day else None,
        "thirtyDayDaysToExpiry": thirty_day.get("daysToExpiry") if thirty_day else None,
        "source": "per-expiry-atm-straddle",
        "samples": samples[:6],
    }


def _build_term_structure_payload(points):
    cleaned = sorted(
        [point for point in points if point.get("atmIv") is not None and point.get("daysToExpiry") is not None],
        key=lambda item: item["daysToExpiry"],
    )
    if len(cleaned) < 2:
        return {
            "frontIv": cleaned[0]["atmIv"] if cleaned else None,
            "backIv": None,
            "slope": None,
            "regime": None,
            "points": cleaned,
        }
    front = cleaned[0]
    back = cleaned[-1]
    slope = back["atmIv"] - front["atmIv"]
    if slope > 2:
        regime = "contango"
    elif slope < -2:
        regime = "backwardation"
    else:
        regime = "flat"
    return {
        "frontIv": round(front["atmIv"], 2),
        "backIv": round(back["atmIv"], 2),
        "slope": round(slope, 2),
        "regime": regime,
        "points": cleaned,
    }


def _estimate_implied_volatility(expiry_samples):
    if not expiry_samples:
        return None
    weighted_center = _weighted_median(expiry_samples)
    if weighted_center is None:
        return _weighted_average(expiry_samples)
    filtered = [
        (value, weight)
        for value, weight in expiry_samples
        if abs(value - weighted_center) / max(weighted_center, 1) <= 0.16
    ] or expiry_samples
    return _weighted_average(filtered)


def _black_scholes_gamma(spot_price, strike, implied_volatility, time_years, risk_free_rate=0.0):
    if (
        spot_price is None
        or strike is None
        or implied_volatility is None
        or spot_price <= 0
        or strike <= 0
        or implied_volatility <= 0
        or time_years <= 0
        or not math.isfinite(implied_volatility)
    ):
        return 0.0
    try:
        numerator = math.log(spot_price / strike) + (risk_free_rate + 0.5 * implied_volatility * implied_volatility) * time_years
        denominator = implied_volatility * math.sqrt(time_years)
        if denominator <= 0:
            return 0.0
        d1 = numerator / denominator
        return _norm_pdf(d1) / (spot_price * implied_volatility * math.sqrt(time_years))
    except Exception:
        return 0.0


def _estimate_option_gamma_exposure(spot_price, strike, implied_volatility, time_years, open_interest):
    gamma = _black_scholes_gamma(spot_price, strike, implied_volatility, time_years)
    if gamma <= 0 or open_interest <= 0:
        return 0.0
    # Approximate dealer gamma exposure for a 1% move.
    return gamma * open_interest * 100 * (spot_price ** 2) * 0.01


def _aggregate_option_metrics(frame, bucket, contracts, spot_price, time_years, side):
    if frame is None or frame.empty:
        return
    expiry_seen = set()
    for _, row in frame.iterrows():
        strike = _safe_float(row.get("strike"))
        open_interest = _safe_int(row.get("openInterest")) or 0
        volume = _safe_int(row.get("volume")) or 0
        implied_volatility = _safe_float(row.get("impliedVolatility"))
        if strike is None or open_interest <= 0:
            continue
        normalized_strike = round(strike, 2)
        gamma_exposure = _estimate_option_gamma_exposure(
            spot_price,
            normalized_strike,
            implied_volatility,
            time_years,
            open_interest,
        )
        item = bucket.setdefault(normalized_strike, {"openInterest": 0, "volume": 0, "gammaExposure": 0.0, "expiryCount": 0})
        item["openInterest"] += max(0, open_interest)
        item["volume"] += max(0, volume)
        item["gammaExposure"] += max(0.0, gamma_exposure)
        if normalized_strike not in expiry_seen:
            item["expiryCount"] += 1
            expiry_seen.add(normalized_strike)
        contracts.append({
            "strike": normalized_strike,
            "openInterest": max(0, open_interest),
            "volume": max(0, volume),
            "impliedVolatility": implied_volatility,
            "timeYears": time_years,
            "daysToExpiry": max(1, int(round(time_years * 365))),
            "side": side,
            "gammaExposure": gamma_exposure,
        })


def _is_round_wall_strike(strike, spot_price):
    if strike is None:
        return False
    scaled = abs(strike)
    if scaled >= 100:
        return abs(strike % 50) < 1e-6 or abs(strike % 100) < 1e-6
    if scaled >= 30:
        return abs(strike % 10) < 1e-6 or abs(strike % 5) < 1e-6
    return abs((strike * 2) - round(strike * 2)) < 1e-6


def _wall_round_strength(strike):
    if strike is None:
        return 0
    scaled = abs(strike)

    def hits(modulus):
        remainder = strike % modulus
        return abs(remainder) < 1e-6 or abs(remainder - modulus) < 1e-6

    if scaled >= 100:
        if hits(100):
            return 4
        if hits(50):
            return 3
        if hits(25):
            return 2
        if hits(10):
            return 1
        return 0
    if scaled >= 30:
        if hits(10):
            return 3
        if hits(5):
            return 2
        if hits(2.5):
            return 1
        return 0
    if abs(strike - round(strike)) < 1e-6:
        return 3
    if abs((strike * 2) - round(strike * 2)) < 1e-6:
        return 1
    return 0


def _call_wall_score(strike, payload, spot_price, metric_key, max_open_interest, max_expiry_count):
    gamma_value = max(payload.get(metric_key) or 0, 0)
    if gamma_value <= 0:
        return 0.0
    open_interest = max(payload.get("openInterest", 0), 0)
    expiry_count = max(payload.get("expiryCount", 0), 0)
    volume = max(payload.get("volume", 0), 0)
    open_interest_ratio = math.sqrt(open_interest / max(max_open_interest, 1))
    expiry_ratio = expiry_count / max(max_expiry_count, 1)
    volume_factor = math.log1p(volume) / 12.0
    distance_ratio = abs(strike - spot_price) / max(spot_price, 1)
    distance_multiplier = max(0.83, 1.0 - max(distance_ratio - 0.18, 0.0) * 0.3)
    if spot_price > 0 and strike >= spot_price * 1.08 and strike <= spot_price * 1.35:
        distance_multiplier *= 1.02
    if spot_price > 0 and strike >= spot_price and strike <= spot_price * 1.03 and open_interest_ratio < 0.75:
        distance_multiplier *= 0.94
    round_bonus = 0.08 if _is_round_wall_strike(strike, spot_price) else 0.0
    structure_multiplier = 1 + (0.42 * open_interest_ratio) + (0.12 * expiry_ratio) + (0.02 * volume_factor) + round_bonus
    return gamma_value * structure_multiplier * distance_multiplier


def _put_wall_score(strike, payload, spot_price, metric_key, max_open_interest, max_expiry_count):
    gamma_value = max(payload.get(metric_key) or 0, 0)
    if gamma_value <= 0:
        return 0.0
    open_interest = max(payload.get("openInterest", 0), 0)
    expiry_count = max(payload.get("expiryCount", 0), 0)
    volume = max(payload.get("volume", 0), 0)
    open_interest_ratio = math.sqrt(open_interest / max(max_open_interest, 1))
    expiry_ratio = expiry_count / max(max_expiry_count, 1)
    volume_factor = math.log1p(volume) / 12.0
    relative_strike = strike / max(spot_price, 1)
    above_penalty = max(relative_strike - 1.05, 0.0)
    below_penalty = max((1 - relative_strike) - 0.25, 0.0)
    distance_multiplier = max(0.82, 1.0 - (above_penalty * 0.65) - (below_penalty * 0.15))
    round_bonus = 0.08 if _is_round_wall_strike(strike, spot_price) else 0.0
    structure_multiplier = 1 + (0.40 * open_interest_ratio) + (0.12 * expiry_ratio) + (0.02 * volume_factor) + round_bonus
    return gamma_value * structure_multiplier * distance_multiplier


def _pick_wall(bucket, spot_price, side="call", metric_key="gammaExposure"):
    if not bucket:
        return None
    if side == "put":
        strike_floor = max(0.01, spot_price * 0.8)
        strike_ceiling = spot_price * 1.15
    else:
        strike_floor = max(0.01, spot_price * 0.85)
        strike_ceiling = spot_price * 1.8
    eligible = {
        strike: payload
        for strike, payload in bucket.items()
        if strike_floor <= strike <= strike_ceiling
    } or bucket
    max_open_interest = max((max(payload.get("openInterest", 0), 0) for payload in eligible.values()), default=1)
    max_expiry_count = max((max(payload.get("expiryCount", 0), 0) for payload in eligible.values()), default=1)
    if side == "put":
        ranked = sorted(
            (
                (
                    _put_wall_score(strike, payload, spot_price, metric_key, max_open_interest, max_expiry_count),
                    strike,
                    payload,
                )
                for strike, payload in eligible.items()
            ),
            key=lambda item: (
                -item[0],
                -(item[2].get(metric_key) or 0),
                -item[2].get("openInterest", 0),
                -item[2].get("expiryCount", 0),
                abs(item[1] - spot_price),
                item[1],
            ),
        )
        top_score = ranked[0][0]
        shortlist = [
            item for item in ranked
            if top_score > 0 and ((top_score - item[0]) / top_score) <= 0.015
        ] or ranked[:1]
        shortlist = sorted(
            shortlist,
            key=lambda item: (
                -_wall_round_strength(item[1]),
                -item[2].get("expiryCount", 0),
                abs(item[1] - spot_price),
                -item[2].get("openInterest", 0),
                -item[0],
                item[1],
            ),
        )
        _, strike, payload = shortlist[0]
    else:
        _, strike, payload = sorted(
            (
                (
                    _call_wall_score(strike, payload, spot_price, metric_key, max_open_interest, max_expiry_count),
                    strike,
                    payload,
                )
                for strike, payload in eligible.items()
            ),
            key=lambda item: (
                -item[0],
                -(item[2].get(metric_key) or 0),
                -item[2].get("openInterest", 0),
                -item[2].get("expiryCount", 0),
                abs(item[1] - spot_price),
                item[1],
            ),
        )[0]
    return {
        "strike": strike,
        "openInterest": payload["openInterest"],
        "volume": payload["volume"],
        "expiryCount": payload.get("expiryCount", 0),
        "method": "aggregated-open-interest",
        "gammaExposure": None,
    }


def _total_signed_gamma_exposure(contracts, scenario_price):
    total = 0.0
    for contract in contracts:
        strike = contract.get("strike")
        implied_volatility = contract.get("impliedVolatility")
        time_years = contract.get("timeYears")
        open_interest = contract.get("openInterest", 0)
        side = contract.get("side")
        sign = 1 if side == "call" else -1
        total += sign * _estimate_option_gamma_exposure(
            scenario_price,
            strike,
            implied_volatility,
            time_years,
            open_interest,
        )
    return total


def _estimate_gamma_flip_profile(contracts, spot_price, nearby_strike_count=41):
    if not contracts:
        return None
    strikes = sorted({contract["strike"] for contract in contracts if contract.get("strike") is not None})
    if not strikes:
        return None

    if nearby_strike_count and len(strikes) > nearby_strike_count:
        nearby = set(sorted(strikes, key=lambda strike: (abs(strike - spot_price), strike))[:nearby_strike_count])
        contracts = [contract for contract in contracts if contract.get("strike") in nearby]
        strikes = sorted(nearby)
        if not contracts:
            return None

    min_strike = min(strikes)
    max_strike = max(strikes)
    low = max(0.01, min(spot_price * 0.65, min_strike * 0.95))
    high = max(spot_price * 1.45, max_strike * 1.02)
    step = max(0.25, round(spot_price * 0.0035, 2))

    profile = []
    current = low
    while current <= high + 1e-9:
        profile.append((round(current, 4), _total_signed_gamma_exposure(contracts, current)))
        current += step

    spot_net_gamma = _total_signed_gamma_exposure(contracts, spot_price)
    crossing_candidates = []
    for index in range(len(profile) - 1):
        strike, net_value = profile[index]
        next_strike, next_net = profile[index + 1]
        if net_value == 0:
            crossing_candidates.append((strike, 0.0))
            continue
        if (net_value < 0 < next_net) or (net_value > 0 > next_net):
            span = abs(net_value) + abs(next_net)
            ratio = abs(net_value) / span if span else 0.5
            flip_strike = round(strike + (next_strike - strike) * ratio, 2)
            crossing_candidates.append((flip_strike, min(abs(net_value), abs(next_net))))

    crossing = None
    if crossing_candidates:
        preferred = crossing_candidates
        if spot_net_gamma < 0:
            above_spot = [item for item in crossing_candidates if item[0] >= spot_price]
            if above_spot:
                preferred = above_spot
        elif spot_net_gamma > 0:
            below_spot = [item for item in crossing_candidates if item[0] <= spot_price]
            if below_spot:
                preferred = below_spot
        crossing = sorted(preferred, key=lambda item: (abs(item[0] - spot_price), item[1]))[0]

    min_balance_strike, min_balance_value = sorted(
        profile,
        key=lambda item: (abs(item[1]), abs(item[0] - spot_price)),
    )[0]

    return {
        "hasCrossing": crossing is not None,
        "crossingStrike": crossing[0] if crossing else None,
        "crossingBalance": round(abs(crossing[1]), 2) if crossing else None,
        "spotNetGamma": round(spot_net_gamma, 2),
        "minBalanceStrike": round(min_balance_strike, 2),
        "minBalance": round(abs(min_balance_value), 2),
        "method": "estimated-gex-zero-cross-nearby-strikes" if crossing else "estimated-gex-min-balance-nearby-strikes",
        "nearbyStrikeCount": nearby_strike_count,
    }


def _median_strike(values):
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return round((ordered[middle - 1] + ordered[middle]) / 2, 2)


def _contract_days_to_expiry(contract):
    days_to_expiry = contract.get("daysToExpiry")
    if days_to_expiry is not None:
        return max(0, int(days_to_expiry))
    time_years = contract.get("timeYears")
    if time_years is None:
        return 0
    return max(0, int(round(time_years * 365)))


def _term_bucket_gamma_flip_profile(contracts, spot_price, min_days, max_days):
    filtered_contracts = [
        contract
        for contract in contracts
        if min_days <= _contract_days_to_expiry(contract) <= max_days
    ]
    if not filtered_contracts:
        return None
    return _estimate_gamma_flip_profile(filtered_contracts, spot_price, nearby_strike_count=None)


def _weighted_bucket_crossing(profiles):
    weighted_points = []
    for profile in profiles:
        strike = profile.get("crossingStrike") if profile else None
        if strike is None:
            continue
        balance = max(profile.get("crossingBalance") or 0, 1.0)
        spot_net_gamma = abs(profile.get("spotNetGamma") or 0)
        weight = spot_net_gamma / max(math.log10(balance + 10), 1.0)
        if weight <= 0:
            continue
        weighted_points.append((strike, weight))
    if not weighted_points:
        return None
    total_weight = sum(weight for _, weight in weighted_points)
    if total_weight <= 0:
        return None
    return sum(strike * weight for strike, weight in weighted_points) / total_weight


def _profile_gamma_sign(profile):
    if not profile:
        return None
    spot_net_gamma = profile.get("spotNetGamma")
    if spot_net_gamma is None or spot_net_gamma == 0:
        return 0
    return 1 if spot_net_gamma > 0 else -1


def _refine_gamma_flip_with_term_structure(base_flip, contracts, spot_price):
    if not base_flip or base_flip.get("strike") is None or not contracts:
        return base_flip

    bucket_profiles = {
        "0-7": _term_bucket_gamma_flip_profile(contracts, spot_price, 0, 7),
        "8-21": _term_bucket_gamma_flip_profile(contracts, spot_price, 8, 21),
        "22-45": _term_bucket_gamma_flip_profile(contracts, spot_price, 22, 45),
        "46-90": _term_bucket_gamma_flip_profile(contracts, spot_price, 46, 90),
        "91-180": _term_bucket_gamma_flip_profile(contracts, spot_price, 91, 180),
    }
    short_term_average = _weighted_bucket_crossing([
        bucket_profiles["0-7"],
        bucket_profiles["8-21"],
    ])
    medium_term_average = _weighted_bucket_crossing([
        bucket_profiles["8-21"],
        bucket_profiles["22-45"],
        bucket_profiles["46-90"],
    ])

    adjusted_strike = float(base_flip["strike"])
    method = base_flip.get("method") or "estimated-gex"

    if (
        spot_price < 25
        and short_term_average is not None
        and adjusted_strike < spot_price
        and short_term_average > adjusted_strike
    ):
        adjusted_strike = short_term_average
        method = "estimated-gex-low-price-short-term"

    sign_0_7 = _profile_gamma_sign(bucket_profiles["0-7"])
    sign_8_21 = _profile_gamma_sign(bucket_profiles["8-21"])
    sign_22_45 = _profile_gamma_sign(bucket_profiles["22-45"])
    if (
        base_flip.get("method") == "estimated-gex-adaptive-expanded-window"
        and short_term_average is not None
        and sign_0_7 is not None
        and sign_8_21 is not None
        and sign_22_45 is not None
        and sign_0_7 != sign_8_21
        and sign_0_7 == sign_22_45
    ):
        adjusted_strike = short_term_average
        method = "estimated-gex-adaptive-short-term"

    if (
        base_flip.get("method") == "estimated-gex-adaptive-expanded-window"
        and medium_term_average is not None
    ):
        medium_term_strikes = [
            profile["crossingStrike"]
            for profile in (
                bucket_profiles["8-21"],
                bucket_profiles["22-45"],
                bucket_profiles["46-90"],
            )
            if profile and profile.get("crossingStrike") is not None
        ]
        if len(medium_term_strikes) >= 2:
            medium_term_spread = max(medium_term_strikes) - min(medium_term_strikes)
            if adjusted_strike < medium_term_average and medium_term_spread <= spot_price * 0.22:
                if medium_term_spread <= spot_price * 0.10:
                    adjusted_strike = medium_term_average
                else:
                    adjusted_strike = (adjusted_strike * 0.55) + (medium_term_average * 0.45)
                method = "estimated-gex-adaptive-term-structure"

    if (
        base_flip.get("method") == "estimated-gex-zero-cross-nearby-strikes"
        and short_term_average is not None
        and abs(short_term_average - adjusted_strike) / max(spot_price, 1) <= 0.015
        and abs(short_term_average - spot_price) <= abs(adjusted_strike - spot_price) + (spot_price * 0.002)
    ):
        adjusted_strike = (adjusted_strike + short_term_average) / 2
        method = "estimated-gex-nearby-short-term-smooth"

    if abs(adjusted_strike - base_flip["strike"]) < 0.005:
        return base_flip

    return {
        "strike": round(adjusted_strike, 2),
        "balance": base_flip.get("balance"),
        "method": method,
    }


def _estimate_gamma_flip(contracts, spot_price, nearby_strike_count=41, put_wall=None, call_wall=None):
    profile = _estimate_gamma_flip_profile(contracts, spot_price, nearby_strike_count=nearby_strike_count)
    if not profile:
        return None

    if profile.get("hasCrossing"):
        strike = profile.get("crossingStrike")
        spot_net_gamma = profile.get("spotNetGamma", 0) or 0
        if (
            strike is not None
            and put_wall
            and put_wall.get("strike") is not None
            and put_wall["strike"] < spot_price
            and spot_net_gamma > 0
            and strike < put_wall["strike"] * 0.93
        ):
            strike = round((put_wall["strike"] * 0.7) + (strike * 0.3), 2)
            return _refine_gamma_flip_with_term_structure({
                "strike": strike,
                "balance": profile.get("crossingBalance"),
                "method": "estimated-gex-zero-cross-put-support-blend",
            }, contracts, spot_price)
        return _refine_gamma_flip_with_term_structure({
            "strike": strike,
            "balance": profile.get("crossingBalance"),
            "method": profile.get("method"),
        }, contracts, spot_price)

    expanded_candidates = []
    for count in [61, 81, 101, None]:
        if count == nearby_strike_count:
            continue
        next_profile = _estimate_gamma_flip_profile(contracts, spot_price, nearby_strike_count=count)
        if next_profile and next_profile.get("hasCrossing") and next_profile.get("crossingStrike") is not None:
            expanded_candidates.append(next_profile)

    if expanded_candidates:
        spot_net_gamma = profile.get("spotNetGamma", 0) or 0
        if spot_net_gamma >= 0:
            below_spot = [item for item in expanded_candidates if item["crossingStrike"] <= spot_price]
            candidate = max(below_spot, key=lambda item: item["crossingStrike"]) if below_spot else expanded_candidates[0]
            candidate_strike = candidate["crossingStrike"]
            if (
                put_wall
                and put_wall.get("strike") is not None
                and put_wall["strike"] < spot_price
                and candidate_strike < put_wall["strike"] * 0.93
            ):
                candidate_strike = round((put_wall["strike"] + candidate_strike) / 2, 2)
            return _refine_gamma_flip_with_term_structure({
                "strike": candidate_strike,
                "balance": candidate.get("crossingBalance"),
                "method": "estimated-gex-adaptive-putwall-blend",
            }, contracts, spot_price)

        viable_candidates = [
            item for item in expanded_candidates
            if item["crossingStrike"] >= spot_price
        ] or expanded_candidates
        if (
            put_wall
            and call_wall
            and put_wall.get("strike") is not None
            and call_wall.get("strike") is not None
            and abs(call_wall["strike"] - put_wall["strike"]) / max(spot_price, 1) <= 0.04
            and spot_price <= min(call_wall["strike"], put_wall["strike"]) * 0.94
        ):
            anchor = (call_wall["strike"] + put_wall["strike"]) / 2
            candidate_strike = min(
                viable_candidates,
                key=lambda item: (
                    abs(item["crossingStrike"] - anchor),
                    item.get("crossingBalance") or 0,
                    item.get("nearbyStrikeCount") or 10_000,
                ),
            )["crossingStrike"]
        else:
            candidate_spread = max(item["crossingStrike"] for item in viable_candidates) - min(item["crossingStrike"] for item in viable_candidates)
            if candidate_spread >= 12:
                candidate_strike = _median_strike([item["crossingStrike"] for item in viable_candidates]) or viable_candidates[0]["crossingStrike"]
            else:
                candidate_strike = max(
                    viable_candidates,
                    key=lambda item: (
                        item["crossingStrike"],
                        -(item.get("crossingBalance") or 0),
                    ),
                )["crossingStrike"]
        return _refine_gamma_flip_with_term_structure({
            "strike": candidate_strike,
            "balance": min(item.get("crossingBalance") or 0 for item in viable_candidates),
            "method": "estimated-gex-adaptive-expanded-window",
        }, contracts, spot_price)

    return _refine_gamma_flip_with_term_structure({
        "strike": profile.get("minBalanceStrike"),
        "balance": profile.get("minBalance"),
        "method": profile.get("method"),
    }, contracts, spot_price)


def fetch_us_options_market(instrument, ticker, spot_price, updated_at, history_frame=None):
    try:
        expiries = list(instrument.options or [])
    except Exception:
        return build_unavailable_options_payload("Unable to load options expiries", market="us")

    if not expiries:
        return build_unavailable_options_payload("No listed options expiries", market="us")

    today = datetime.now(timezone.utc).date()
    ranked_expiries = []
    for expiry in expiries:
        try:
            expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
            dte = (expiry_date - today).days
            ranked_expiries.append((expiry, dte))
        except Exception:
            continue

    if not ranked_expiries:
        return build_unavailable_options_payload("No valid options expiries", market="us")

    valid_expiries = [item for item in ranked_expiries if 0 <= item[1] <= 270] or ranked_expiries[:12]
    selected = []
    seen_expiries = set()
    # Use a compact but representative term set. The longer anchor prevents
    # structural OI walls from being dominated by only the nearest weeklies.
    target_dtes = [7, 30, 60, 90, 180]
    for target_dte in target_dtes:
        candidates = [item for item in valid_expiries if item[1] >= 0]
        if not candidates:
            continue
        expiry, dte = min(candidates, key=lambda item: (abs(item[1] - target_dte), item[1]))
        if expiry in seen_expiries:
            continue
        seen_expiries.add(expiry)
        selected.append((expiry, dte))
        if len(selected) >= len(target_dtes):
            break
    wall_expiries = selected or valid_expiries[:4]
    call_bucket = {}
    put_bucket = {}
    used_expiries = []
    iv_expiry_samples = []
    expected_move_samples = []
    term_structure_points = []
    skew_samples = []
    total_calls_count = 0
    total_puts_count = 0
    for expiry, dte in wall_expiries:
        try:
            chain = instrument.option_chain(expiry)
        except Exception:
            continue
        time_years = max(dte / 365.0, 1 / 365.0)
        calls_frame = getattr(chain, "calls", None)
        puts_frame = getattr(chain, "puts", None)
        total_calls_count += len(calls_frame.index) if calls_frame is not None else 0
        total_puts_count += len(puts_frame.index) if puts_frame is not None else 0
        _aggregate_option_metrics(calls_frame, call_bucket, [], spot_price, time_years, "call")
        _aggregate_option_metrics(puts_frame, put_bucket, [], spot_price, time_years, "put")
        expiry_iv_value = None
        if 3 <= dte <= 75:
            expiry_iv = _estimate_expiry_atm_iv(calls_frame, puts_frame, spot_price, dte)
            if expiry_iv is not None:
                iv_expiry_samples.append(expiry_iv)
                expiry_iv_value = expiry_iv[0]
        elif dte >= 0:
            expiry_iv = _estimate_expiry_atm_iv(calls_frame, puts_frame, spot_price, dte)
            expiry_iv_value = expiry_iv[0] if expiry_iv is not None else None
        if 0 <= dte <= 180:
            expected_move = _estimate_expiry_expected_move(calls_frame, puts_frame, spot_price, dte, expiry_iv_value)
            if expected_move:
                expected_move["expiry"] = expiry
                expected_move_samples.append(expected_move)
            if expiry_iv_value is not None:
                term_structure_points.append({
                    "expiry": expiry,
                    "daysToExpiry": dte,
                    "atmIv": round(expiry_iv_value, 2),
                })
            skew_sample = _estimate_expiry_skew(calls_frame, puts_frame, spot_price)
            if skew_sample:
                skew_sample["expiry"] = expiry
                skew_sample["daysToExpiry"] = dte
                skew_samples.append(skew_sample)
        used_expiries.append({"expiry": expiry, "daysToExpiry": dte})

    if not call_bucket and not put_bucket:
        return build_unavailable_options_payload("No options chain data returned", market="us")

    # OI identifies concentration, but not dealer positioning. It is valid for
    # an OI wall; it cannot produce a verified Gamma Flip or net dealer GEX.
    call_wall = _pick_wall(call_bucket, spot_price, side="call", metric_key="openInterest")
    put_wall = _pick_wall(put_bucket, spot_price, side="put", metric_key="openInterest")
    total_call_oi = sum(item["openInterest"] for item in call_bucket.values())
    total_put_oi = sum(item["openInterest"] for item in put_bucket.values())
    implied_volatility = _estimate_implied_volatility(iv_expiry_samples)
    history_closes = history_frame["Close"].tolist() if history_frame is not None and "Close" in history_frame else []
    history_highs = history_frame["High"].tolist() if history_frame is not None and "High" in history_frame else []
    history_lows = history_frame["Low"].tolist() if history_frame is not None and "Low" in history_frame else []
    iv_regime = _estimate_iv_regime_metrics(implied_volatility, history_closes, history_highs, history_lows)
    skew_summary = skew_samples[0] if skew_samples else {
        "putCallIvSkew": None,
        "method": None,
        "source": None,
    }

    return {
        "snapshotVersion": OPTIONS_SNAPSHOT_VERSION,
        "available": True,
        "market": "us",
        "reason": None,
        "callWall": call_wall,
        "putWall": put_wall,
        "gammaFlip": None,
        "gammaFlipStatus": "unavailable_no_real_gex",
        "expiries": used_expiries,
        "nearestExpiry": used_expiries[0]["expiry"] if used_expiries else None,
        "updatedAt": updated_at,
        "totalCallOpenInterest": total_call_oi,
        "totalPutOpenInterest": total_put_oi,
        "totalCallGammaExposure": None,
        "totalPutGammaExposure": None,
        "netGammaExposure": None,
        "impliedVolatility": round(implied_volatility, 2) if implied_volatility is not None else None,
        "historicVolatility": round(iv_regime["historicVolatility"], 2) if iv_regime.get("historicVolatility") is not None else None,
        "ivPercentile": round(iv_regime["ivPercentile"], 2) if iv_regime.get("ivPercentile") is not None else None,
        "ivRank": round(iv_regime["ivRank"], 2) if iv_regime.get("ivRank") is not None else None,
        "expectedMove": _build_options_expected_move_payload(expected_move_samples),
        "skew": skew_summary,
        "termStructure": _build_term_structure_payload(term_structure_points),
        "coverage": "aggregated-open-interest-atm-straddle-expected-move",
        "wallMethod": "aggregated-open-interest",
        "gammaFlipStrikeCount": None,
        "selectedExpiration": used_expiries[0]["expiry"] if used_expiries else None,
        "callsCount": total_calls_count,
        "putsCount": total_puts_count,
    }


def _normalize_download_history_frame(frame):
    if frame is None or frame.empty:
        return pd.DataFrame()
    if isinstance(frame.columns, pd.MultiIndex):
        normalized = pd.DataFrame(index=frame.index)
        for field in ["Open", "High", "Low", "Close", "Volume"]:
            match = next((column for column in frame.columns if field in column), None)
            if match is not None:
                normalized[field] = frame[match]
        frame = normalized
    return frame


def load_yfinance_history_frame(instrument, symbol, period="1y", interval="1d"):
    try:
        history = instrument.history(period=period, interval=interval, auto_adjust=False)
        if history is not None and not history.empty:
            return history
    except Exception:
        pass

    try:
        downloaded = yf.download(
            symbol,
            period=period,
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        downloaded = _normalize_download_history_frame(downloaded)
        if downloaded is not None and not downloaded.empty:
            return downloaded
    except Exception:
        pass

    fallback_limit = 1300 if period in {"2y", "5y"} and interval == "1d" else 260
    yahoo_frame = fetch_yahoo_chart_frame(symbol, range_value=period, interval=interval, limit=fallback_limit)
    if yahoo_frame is not None and not yahoo_frame.empty:
        return yahoo_frame

    stooq_frame = fetch_stooq_chart_frame(symbol)
    if stooq_frame is not None and not stooq_frame.empty:
        return stooq_frame

    return pd.DataFrame()


def load_yfinance_intraday_history_frame(instrument, symbol, period="60d", interval="1h"):
    """Return only genuine intraday data; never fall back to daily Stooq bars."""
    try:
        history = instrument.history(period=period, interval=interval, auto_adjust=False)
        if history is not None and not history.empty:
            return history
    except Exception:
        pass

    try:
        downloaded = yf.download(
            symbol,
            period=period,
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        downloaded = _normalize_download_history_frame(downloaded)
        if downloaded is not None and not downloaded.empty:
            return downloaded
    except Exception:
        pass

    try:
        # Preserve the provider's real 1H history for its own technical
        # warm-up. Yahoo permits up to 730 days of 1H history; 6,000 rows
        # safely covers that maximum without manufacturing any missing bars.
        yahoo_frame = fetch_yahoo_chart_frame(symbol, range_value=period, interval=interval, limit=6000)
        if yahoo_frame is not None and not yahoo_frame.empty:
            return yahoo_frame
    except Exception:
        pass

    return pd.DataFrame()


def load_yfinance_native_four_hour_history_frame(instrument, period=TECHNICAL_FOUR_HOUR_HISTORY_PERIOD):
    """Fetch only the provider-native 4H regular-session series.

    This deliberately has no yfinance-download, Yahoo-chart, daily, or 1H
    reconstruction fallback. If the primary provider does not return verified
    4H data, the technical layer must receive an unavailable 4H interval.
    """
    metadata = {}
    try:
        frame = instrument.history(
            period=period,
            interval="4h",
            auto_adjust=False,
            prepost=False,
        )
        metadata = dict(instrument.history_metadata or {})
    except Exception:
        return pd.DataFrame(), metadata, "source_unavailable"

    if frame is None or frame.empty:
        return pd.DataFrame(), metadata, "source_unavailable"
    if metadata.get("dataGranularity") != "4h":
        return pd.DataFrame(), metadata, "invalid_source_data"
    if metadata.get("exchangeTimezoneName") != TECHNICAL_FOUR_HOUR_TIMEZONE:
        return pd.DataFrame(), metadata, "invalid_source_data"
    return frame, metadata, None


def validate_native_four_hour_history_frame(frame):
    """Keep only structurally valid provider-native US regular-session 4H bars.

    Normal sessions have 09:30 and 13:30 provider bars. A 09:30-only session
    is retained because Yahoo uses it for legitimate US early-close days. A
    13:30-only day, duplicate segments, malformed timestamps, and invalid
    OHLCV are excluded rather than repaired or filled.
    """
    empty = pd.DataFrame() if frame is None else frame.iloc[0:0].copy()
    result = {
        "frame": empty,
        "source_rows": 0 if frame is None else int(len(frame)),
        "excluded_invalid_rows": 0 if frame is None else int(len(frame)),
        "normal_session_days": 0,
        "single_session_days": 0,
        "invalid_session_days": 0,
        "invalid_session_examples": [],
        "unavailable_reason": "source_unavailable" if frame is None or frame.empty else "invalid_source_data",
    }
    if frame is None or frame.empty or not isinstance(frame.index, pd.DatetimeIndex):
        return result
    if frame.index.tz is None or str(frame.index.tz) != TECHNICAL_FOUR_HOUR_TIMEZONE:
        return result

    required = ("Open", "High", "Low", "Close", "Volume")
    if any(column not in frame.columns for column in required):
        return result

    day_rows = {}
    invalid_days = set()
    for stamp, row in frame.iterrows():
        try:
            local_stamp = stamp.tz_convert(TECHNICAL_FOUR_HOUR_TIMEZONE)
            local_time = local_stamp.strftime("%H:%M")
            day = local_stamp.date().isoformat()
            open_value = _safe_float(row["Open"])
            high_value = _safe_float(row["High"])
            low_value = _safe_float(row["Low"])
            close_value = _safe_float(row["Close"])
            volume_value = _safe_float(row["Volume"])
        except Exception:
            continue
        valid_ohlcv = (
            None not in (open_value, high_value, low_value, close_value, volume_value)
            and high_value >= max(open_value, close_value)
            and low_value <= min(open_value, close_value)
            and volume_value >= 0
        )
        if not valid_ohlcv or local_time not in {"09:30", "13:30"}:
            invalid_days.add(day)
            continue
        day_rows.setdefault(day, []).append((local_time, stamp))

    valid_indices = []
    for day, entries in sorted(day_rows.items()):
        times = [time_value for time_value, _stamp in entries]
        if day in invalid_days or len(set(times)) != len(times):
            result["invalid_session_days"] += 1
            if len(result["invalid_session_examples"]) < 5:
                result["invalid_session_examples"].append({"date": day, "times": times, "reason": "invalid_or_duplicate_session_bar"})
            continue
        if times == ["09:30", "13:30"]:
            result["normal_session_days"] += 1
            valid_indices.extend(stamp for _time, stamp in entries)
            continue
        if times == ["09:30"]:
            # Native provider single-bar session: retain as a legitimate early
            # close/session shape rather than creating an imaginary 13:30 bar.
            result["single_session_days"] += 1
            valid_indices.append(entries[0][1])
            continue
        result["invalid_session_days"] += 1
        if len(result["invalid_session_examples"]) < 5:
            result["invalid_session_examples"].append({"date": day, "times": times, "reason": "missing_opening_session_bar"})

    if valid_indices:
        result["frame"] = frame.loc[valid_indices].sort_index().copy()
        result["excluded_invalid_rows"] = int(len(frame) - len(result["frame"]))
        result["unavailable_reason"] = None
    return result


def native_four_hour_history_payload(frame, metadata=None, failure_reason=None):
    """Create a compact, provenance-bearing payload from validated 4H bars."""
    validation = validate_native_four_hour_history_frame(frame)
    payload = _history_payload(validation["frame"], timestamp_format="%Y-%m-%dT%H:%M:%S%z")
    unavailable_reason = None if validation["frame"].shape[0] else (failure_reason or validation["unavailable_reason"])
    payload.update({
        "interval": "4h",
        "lookback": TECHNICAL_FOUR_HOUR_HISTORY_PERIOD,
        "source": "yfinance",
        "bar_method": TECHNICAL_FOUR_HOUR_BAR_METHOD,
        "regular_hours_only": True,
        "timezone": TECHNICAL_FOUR_HOUR_TIMEZONE,
        "provider_data_granularity": (metadata or {}).get("dataGranularity"),
        "provider_exchange_timezone": (metadata or {}).get("exchangeTimezoneName"),
        "session_validation": {
            "normal_session_days": validation["normal_session_days"],
            "single_session_days": validation["single_session_days"],
            "invalid_session_days": validation["invalid_session_days"],
            "invalid_session_examples": validation["invalid_session_examples"],
        },
        "source_rows": validation["source_rows"],
        "available_bars": int(len(validation["frame"])),
        "excluded_invalid_rows": validation["excluded_invalid_rows"],
        "availability": "available" if len(validation["frame"]) else "unavailable",
        "available": bool(len(validation["frame"])),
        "unavailable_reason": unavailable_reason,
        "last_bar_timestamp": payload["timestamps"][-1] if payload["timestamps"] else None,
        "reason": None if len(validation["frame"]) else "Native provider 4H history was unavailable or failed session validation.",
    })
    return payload


def load_technical_intraday_history_frames(symbol):
    """Fetch 1H and provider-native 4H concurrently within one shared budget."""
    executor = ThreadPoolExecutor(max_workers=2)
    hourly_history = None
    native_four_hour = (pd.DataFrame(), {}, "source_unavailable")
    try:
        hourly_future = executor.submit(
            load_yfinance_intraday_history_frame,
            yf.Ticker(symbol),
            symbol,
            TECHNICAL_INTRADAY_HISTORY_PERIOD,
            "1h",
        )
        four_hour_future = executor.submit(
            load_yfinance_native_four_hour_history_frame,
            yf.Ticker(symbol),
            TECHNICAL_FOUR_HOUR_HISTORY_PERIOD,
        )
        deadline = time.monotonic() + TECHNICAL_INTRADAY_FETCH_TIMEOUT_SECONDS
        try:
            hourly_history = hourly_future.result(timeout=max(0, deadline - time.monotonic()))
        except Exception:
            hourly_history = None
        try:
            native_four_hour = four_hour_future.result(timeout=max(0, deadline - time.monotonic()))
        except Exception:
            native_four_hour = (pd.DataFrame(), {}, "source_unavailable")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return hourly_history, native_four_hour


def _history_payload(frame, timestamp_format="%Y-%m-%d"):
    if frame is None or frame.empty:
        return {
            "timestamps": [], "opens": [], "closes": [], "highs": [], "lows": [], "volumes": [],
            "availability": "unavailable", "available": False, "unavailable_reason": "source_unavailable",
            "source_rows": 0, "available_bars": 0, "excluded_invalid_rows": 0,
        }
    clean = frame.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
    if clean.empty:
        return {
            "timestamps": [], "opens": [], "closes": [], "highs": [], "lows": [], "volumes": [],
            "availability": "unavailable", "available": False, "unavailable_reason": "invalid_source_data",
            "source_rows": int(len(frame)), "available_bars": 0, "excluded_invalid_rows": int(len(frame)),
        }
    return {
        "timestamps": [entry.to_pydatetime().strftime(timestamp_format) for entry in clean.index],
        "opens": [_safe_float(value) for value in clean["Open"].tolist()],
        "closes": [_safe_float(value) for value in clean["Close"].tolist()],
        "highs": [_safe_float(value) for value in clean["High"].tolist()],
        "lows": [_safe_float(value) for value in clean["Low"].tolist()],
        "volumes": [_safe_int(value) for value in clean["Volume"].tolist()],
        "availability": "available", "available": True, "unavailable_reason": None,
        "source_rows": int(len(frame)), "available_bars": int(len(clean)), "excluded_invalid_rows": int(len(frame) - len(clean)),
    }


def fetch_us_quote_with_yfinance(ticker, include_options=False):
    symbol = resolve_market_symbol(ticker)
    instrument = yf.Ticker(symbol)
    quote_fetch_started = time.monotonic()
    history = load_yfinance_history_frame(instrument, symbol, period=TECHNICAL_DAILY_HISTORY_PERIOD, interval="1d")
    if history is None or history.empty:
        raise ValueError(f"No yfinance history for {ticker}")
    history = history.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
    if history.empty:
        raise ValueError(f"No clean yfinance history for {ticker}")

    # Technical intervals start before slower quote-profile enrichment. 1H and
    # provider-native 4H are fetched concurrently; a missing native 4H source
    # remains unavailable and is never reconstructed from 1H or daily bars.
    intraday_allowed = (time.monotonic() - quote_fetch_started) <= 4.5
    hourly_history = None
    native_four_hour_frame, native_four_hour_metadata, native_four_hour_failure = (pd.DataFrame(), {}, "source_unavailable")
    if intraday_allowed:
        hourly_history, (native_four_hour_frame, native_four_hour_metadata, native_four_hour_failure) = load_technical_intraday_history_frames(symbol)

    try:
        info = instrument.info or {}
    except Exception:
        info = {}
    try:
        fast_info = dict(instrument.fast_info or {})
    except Exception:
        fast_info = {}

    fallback_fields = ["shortName", "longName", "sector", "industry", "longBusinessSummary", "quoteType", "earningsTimestamp", "earningsTimestampStart", "earningsTimestampEnd"]
    quote_snapshot = {}
    quote_summary = {}
    quote_summary_attempted = False
    if any(info.get(field) is None for field in fallback_fields):
        quote_summary_attempted = True
        info, quote_snapshot, quote_summary = merge_yahoo_fallback_info(symbol, info)

    hourly_payload = _history_payload(hourly_history, timestamp_format="%Y-%m-%dT%H:%M:%S%z")
    hourly_payload.update({
        "interval": "1h",
        "lookback": TECHNICAL_INTRADAY_HISTORY_PERIOD,
        "source": "yfinance_or_yahoo_chart_intraday",
        "last_bar_timestamp": hourly_payload["timestamps"][-1] if hourly_payload["timestamps"] else None,
        "reason": None if hourly_payload["availability"] == "available" else ("Intraday history was skipped to protect quote refresh." if not intraday_allowed else "Intraday history was not available within the quote-refresh time budget."),
    })
    four_hour_payload = native_four_hour_history_payload(
        native_four_hour_frame,
        metadata=native_four_hour_metadata,
        failure_reason=native_four_hour_failure if intraday_allowed else "source_unavailable",
    )
    daily_payload = _history_payload(history)
    daily_payload.update({
        "interval": "1d",
        "lookback": TECHNICAL_DAILY_HISTORY_PERIOD,
        "source": "yfinance_or_yahoo_chart_daily",
        "last_bar_timestamp": daily_payload["timestamps"][-1] if daily_payload["timestamps"] else None,
    })

    latest_row = history.iloc[-1]
    previous_row = history.iloc[-2] if len(history) > 1 else latest_row
    price = _safe_float(latest_row["Close"])
    previous_close = _safe_float(info.get("regularMarketPreviousClose")) or _safe_float(info.get("previousClose")) or _safe_float(fast_info.get("previous_close")) or _safe_float(previous_row["Close"])
    change = price - previous_close if price is not None and previous_close is not None else None
    change_percent = (change / previous_close) * 100 if change is not None and previous_close else None
    regular_market_time = dt_from_epoch(info.get("regularMarketTime"))
    updated_at = regular_market_time.strftime("%Y-%m-%dT%H:%M:%SZ") if regular_market_time else iso_from_local_close(history.index[-1], 16, 0, -4)
    earnings_timestamp = info.get("earningsTimestamp") or info.get("earningsTimestampStart") or info.get("earningsTimestampEnd")
    earnings_dt = dt_from_epoch(earnings_timestamp)
    earnings_date = iso_from_epoch(earnings_timestamp)
    days_to_earnings = (earnings_dt.date() - datetime.now(timezone.utc).date()).days if earnings_dt is not None else None

    return {
        "price": price,
        "previousClose": previous_close,
        "change": change,
        "changePercent": change_percent,
        "updatedAt": updated_at,
        "marketStatus": "open",
        "dataStaleness": "fresh",
        "last_successful_update": updated_at,
        "symbol": symbol,
        "shortName": info.get("shortName") or info.get("displayName"),
        "longName": info.get("longName") or info.get("shortName") or info.get("displayName"),
        "exchangeName": info.get("exchange") or info.get("fullExchangeName"),
        "metadata": {
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "businessSummary": info.get("longBusinessSummary") or info.get("shortBusinessSummary"),
            "country": info.get("country"),
            "city": info.get("city"),
            "state": info.get("state"),
            "exchange": info.get("exchange") or info.get("fullExchangeName"),
            "quoteType": info.get("quoteType"),
            "floatShares": _safe_int(info.get("floatShares")),
            "sharesOutstanding": _safe_int(info.get("sharesOutstanding")) or _safe_int(fast_info.get("shares")),
            "ipoDate": iso_from_epoch(info.get("firstTradeDateEpochUtc")),
            "earningsDate": earnings_date,
            "earningsTimestamp": _safe_int(earnings_timestamp),
            "earningsTimestampStart": _safe_int(info.get("earningsTimestampStart")),
            "earningsTimestampEnd": _safe_int(info.get("earningsTimestampEnd")),
            "daysToEarnings": days_to_earnings,
            "earningsCountdown": _earnings_countdown(earnings_dt),
        },
        "earnings": {
            "earningsDate": earnings_date,
            "daysToEarnings": days_to_earnings,
            "earningsCountdown": _earnings_countdown(earnings_dt),
            "earningsTimestampStart": iso_from_epoch(info.get("earningsTimestampStart")),
            "earningsTimestampEnd": iso_from_epoch(info.get("earningsTimestampEnd")),
            "source": "yfinance-info-yahoo-quote-summary",
        },
        "debug": {
            "yfinance_import_success": True,
            "yahoo_quote_summary_attempt": quote_summary_attempted,
            "yahoo_quote_snapshot_attempt": bool(quote_snapshot),
            "raw_keys_sample": sorted(list(info.keys()))[:20],
            "quote_summary_keys_sample": sorted(list(quote_summary.keys()))[:20] if quote_summary else [],
            "quote_snapshot_keys_sample": sorted(list(quote_snapshot.keys()))[:20] if quote_snapshot else [],
        },
        "history": {
            **daily_payload,
            "intervals": {"1h": hourly_payload, "4h": four_hour_payload},
        },
    }

def fetch_quote(ticker, include_options=False):
    return fetch_us_quote_with_yfinance(ticker, include_options=include_options)


def fetch_quote_with_timeout(ticker, timeout_seconds=QUOTE_FETCH_TIMEOUT_SECONDS, include_options=False):
    result_queue = queue.Queue(maxsize=1)

    def worker():
        try:
            result_queue.put(("ok", fetch_quote(ticker, include_options=include_options)))
        except Exception as exc:
            result_queue.put(("error", exc))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    try:
        status, payload = result_queue.get(timeout=timeout_seconds)
    except queue.Empty:
        raise TimeoutError(f"Quote fetch timed out for {ticker} after {timeout_seconds}s")

    if status == "error":
        raise payload
    return payload


def get_cached_quote(ticker):
    with QUOTE_FETCH_LOCK:
        entry = CACHE.get(ticker)
        now = time.time()
        if entry and entry["expiresAt"] > now:
            return entry["value"]
        stale_value = entry["value"] if entry else None

        try:
            value = fetch_quote_with_timeout(ticker)
            CACHE[ticker] = {
                "value": value,
                "expiresAt": now + CACHE_SECONDS,
            }
            return value
        except Exception as exc:
            try:
                value = fetch_quote_with_timeout(
                    ticker,
                    timeout_seconds=max(4, QUOTE_FETCH_TIMEOUT_SECONDS // 2),
                    include_options=False,
                )
                value["quoteWarning"] = str(exc)
                CACHE[ticker] = {
                    "value": value,
                    "expiresAt": now + CACHE_SECONDS,
                }
                return value
            except Exception:
                pass
            if stale_value:
                fallback = stale_value.copy()
                fallback["error"] = str(exc)
                fallback["stale"] = True
                return fallback
            return build_unavailable_quote(ticker, str(exc))


def ensure_market_cache_dir():
    if MARKET_CACHE_DIR:
        os.makedirs(MARKET_CACHE_DIR, exist_ok=True)


def market_cache_module_dir(module_name):
    ensure_market_cache_dir()
    path = os.path.join(MARKET_CACHE_DIR, module_name)
    os.makedirs(path, exist_ok=True)
    return path


def market_cache_path(ticker, module_name="quotes"):
    safe_ticker = re.sub(r"[^A-Z0-9._-]", "_", normalize_ticker_input(ticker))
    return os.path.join(market_cache_module_dir(module_name), f"{safe_ticker}.json")


def market_cache_key_path(cache_key, module_name):
    safe_key = re.sub(r"[^A-Z0-9._-]", "_", _safe_text(cache_key) or "snapshot").upper()
    return os.path.join(market_cache_module_dir(module_name), f"{safe_key}.json")


def read_json_cache_file(path):
    try:
        if not path or not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        traceback.print_exc()
        return None


def write_json_cache_file(path, payload):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        return True
    except Exception:
        traceback.print_exc()
        return False


def read_module_cache(module_name, cache_key, legacy_path=None):
    payload = read_json_cache_file(market_cache_key_path(cache_key, module_name))
    if payload is not None:
        return payload
    if legacy_path:
        return read_json_cache_file(legacy_path)
    return None


def write_module_cache(module_name, cache_key, payload):
    return write_json_cache_file(market_cache_key_path(cache_key, module_name), payload)


def count_cache_files(module_name):
    try:
        directory = market_cache_module_dir(module_name)
        return len([name for name in os.listdir(directory) if name.endswith(".json")])
    except Exception:
        return 0


def parse_iso_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None



def read_market_cache(ticker):
    try:
        legacy_path = os.path.join(MARKET_CACHE_DIR, f"{re.sub(r'[^A-Z0-9._-]', '_', normalize_ticker_input(ticker))}.json")
        cached = read_module_cache("quotes", ticker, legacy_path=legacy_path)
        if cached is None:
            return None
        updated_at = cached.get("updated_at") or cached.get("updatedAt")
        updated_dt = parse_iso_datetime(updated_at)
        cached["cache_age_seconds"] = (
            max(0, (datetime.now(timezone.utc) - updated_dt).total_seconds())
            if updated_dt else None
        )
        return cached
    except Exception:
        traceback.print_exc()
        return None


def is_market_cache_fresh(cached):
    if not cached:
        return False
    age_seconds = cached.get("cache_age_seconds")
    if age_seconds is None or age_seconds > MARKET_CACHE_TTL_SECONDS:
        return False
    quote = cached.get("quote") if isinstance(cached, dict) else None
    if not isinstance(quote, dict):
        quote = cached if isinstance(cached, dict) else {}
    hourly = ((quote.get("history") or {}).get("intervals") or {}).get("1h") or {}
    four_hour = ((quote.get("history") or {}).get("intervals") or {}).get("4h") or {}
    # A cache written before the configured real intraday history request is
    # not technically fresh: it cannot support the current 4H indicator
    # warm-up. It is refreshed through the normal cache lifecycle, not filled
    # with synthetic bars.
    if hourly.get("lookback") != TECHNICAL_INTRADAY_HISTORY_PERIOD:
        return False
    # Retire caches whose 4H features would have been derived from the former
    # morning-only 1H aggregation. A current quote must prove native-provider
    # provenance before its technical history is considered fresh.
    if four_hour.get("lookback") != TECHNICAL_FOUR_HOUR_HISTORY_PERIOD:
        return False
    if four_hour.get("source") != "yfinance":
        return False
    if four_hour.get("bar_method") != TECHNICAL_FOUR_HOUR_BAR_METHOD:
        return False
    if four_hour.get("timezone") != TECHNICAL_FOUR_HOUR_TIMEZONE:
        return False
    if four_hour.get("regular_hours_only") is not True:
        return False
    return True


def normalize_cached_market_quote(ticker, cached, stale=False):
    quote = cached.get("quote") if isinstance(cached, dict) else None
    if not isinstance(quote, dict):
        quote = cached if isinstance(cached, dict) else {}
    normalized = quote.copy()
    normalized["ticker"] = normalize_ticker_input(ticker)
    normalized["market_type"] = infer_market_type(normalized["ticker"])
    normalized["quote_status"] = "stale" if stale else normalized.get("quote_status") or "available"
    normalized["quote_source"] = normalized.get("quote_source") or "cache"
    normalized["stale"] = bool(stale)
    normalized["dataStaleness"] = "stale" if stale else normalized.get("dataStaleness") or "fresh"
    normalized["marketStatus"] = normalized.get("marketStatus") or ("closed" if stale else "open")
    normalized["cache_age_seconds"] = cached.get("cache_age_seconds") if isinstance(cached, dict) else None
    normalized["cache_updated_at"] = cached.get("updated_at") if isinstance(cached, dict) else None
    normalized["last_quote_time"] = normalized.get("updatedAt") or normalized.get("last_successful_update")
    # Preserve cached price history while preventing retired fundamentals from
    # leaking back through quote entries written by earlier app versions.
    for key in (
        "trailingPE", "forwardPE", "marketCap", "enterpriseValue",
        "enterpriseToEbitda", "pegRatio", "priceToSalesTrailing12Months",
        "dividendYield", "trailingEps", "forwardEps",
    ):
        normalized.pop(key, None)
    metadata = normalized.get("metadata")
    if isinstance(metadata, dict):
        for key in (
            "fundamentals", "companyAnalysis", "financialData", "financialFacts",
            "financialStatement", "financialDataStatus", "normalizedFundamentals",
            "earningsMetrics", "earningsQuality", "capitalAllocation", "cashFlow",
            "balanceSheet", "valuation", "growth",
        ):
            metadata.pop(key, None)
    normalized.pop("optionsMarket", None)
    return normalized



def extract_options_fields_from_quote(quote):
    options_market = quote.get("optionsMarket") if isinstance(quote, dict) else {}
    if not isinstance(options_market, dict):
        options_market = {}
    expected_move = options_market.get("expectedMove") if isinstance(options_market.get("expectedMove"), dict) else {}
    skew = options_market.get("skew") if isinstance(options_market.get("skew"), dict) else {}
    term_structure = options_market.get("termStructure") if isinstance(options_market.get("termStructure"), dict) else {}
    return {
        "snapshot_version": options_market.get("snapshotVersion"),
        "status": "available" if options_market.get("available") else "unavailable",
        "reason": options_market.get("reason"),
        "call_wall": options_market.get("callWall"),
        "put_wall": options_market.get("putWall"),
        "gamma_flip": options_market.get("gammaFlip"),
        "atm_straddle_move_pct": expected_move.get("atmStraddleMovePct"),
        "seven_day_expected_move_pct": expected_move.get("sevenDayMovePct"),
        "thirty_day_expected_move_pct": expected_move.get("thirtyDayMovePct"),
        "iv_percentile": options_market.get("ivPercentile"),
        "iv_rank": options_market.get("ivRank"),
        "skew": skew.get("putCallIvSkew"),
        "term_structure_slope": term_structure.get("slope"),
        "term_structure_regime": term_structure.get("regime"),
        "expiries_count": len(options_market.get("expiries") or []),
        "coverage": options_market.get("coverage"),
        "wall_method": options_market.get("wallMethod"),
        "gamma_flip_status": options_market.get("gammaFlipStatus"),
    }



def options_cache_valid(payload):
    if not isinstance(payload, dict):
        return False
    options = payload.get("options") or {}
    if options.get("snapshot_version") != OPTIONS_SNAPSHOT_VERSION:
        return False
    return any(options.get(key) is not None for key in ("put_wall", "call_wall", "gamma_flip")) or bool(options.get("expiries_count"))


def market_context_payload_status(payload):
    market_context = (payload or {}).get("market_context") or {}
    equity_trend = market_context.get("equity_trend") or {}
    available_keys = 0
    if (market_context.get("vix") or {}).get("value") is not None:
        available_keys += 1
    if (market_context.get("ten_year_yield") or {}).get("value") is not None:
        available_keys += 1
    if (equity_trend.get("spy") or {}).get("value") is not None:
        available_keys += 1
    if (equity_trend.get("qqq") or {}).get("value") is not None:
        available_keys += 1
    if (market_context.get("fear_greed") or {}).get("value") is not None:
        available_keys += 1
    if available_keys >= 4:
        return "available"
    if available_keys >= 1:
        return "partial"
    return "unavailable"


def market_context_payload_valid(payload):
    return market_context_payload_status(payload) in {"available", "partial"}


def market_context_has_index_lookbacks(payload):
    market_context = (payload or {}).get("market_context") or {}
    equity_trend = market_context.get("equity_trend") or {}
    spy = equity_trend.get("spy") or {}
    qqq = equity_trend.get("qqq") or {}
    required_fields = ("change_60d_pct", "change_120d_pct")
    return all(spy.get(field) is not None for field in required_fields) and all(qqq.get(field) is not None for field in required_fields)


def flatten_market_context_payload(payload, meta=None):
    market_context = (payload or {}).get("market_context") or {}
    equity_trend = market_context.get("equity_trend") or {}
    return {
        "status": (meta or {}).get("status") or market_context_payload_status(payload),
        "updated_at": (meta or {}).get("cache_updated_at"),
        "vix": market_context.get("vix") or {},
        "ten_year_yield": market_context.get("ten_year_yield") or {},
        "spy_trend": equity_trend.get("spy") or {},
        "qqq_trend": equity_trend.get("qqq") or {},
        "fear_greed": market_context.get("fear_greed") or {},
        "regime": market_context.get("regime"),
        "summary": market_context.get("summary"),
        "cache_used": (meta or {}).get("cache_used"),
        "source_attempts": (meta or {}).get("source_attempts") or [],
    }


def cache_updated_at_and_age(payload):
    if not isinstance(payload, dict):
        return None, None
    updated_at = payload.get("updated_at") or payload.get("updatedAt")
    updated_dt = parse_iso_datetime(updated_at)
    age_seconds = (
        max(0, (datetime.now(timezone.utc) - updated_dt).total_seconds())
        if updated_dt else None
    )
    return updated_at, age_seconds


def fields_available_from_mapping(mapping):
    if not isinstance(mapping, dict):
        return []
    return [key for key, value in mapping.items() if value is not None]


def merge_quote_with_cached_modules(ticker, quote, cached):
    if not isinstance(quote, dict) or not cached:
        return quote
    cached_quote = normalize_cached_market_quote(ticker, cached, stale=False)
    merged = dict(quote)

    for field in ("shortName", "longName", "exchangeName"):
        if merged.get(field) is None and cached_quote.get(field) is not None:
            merged[field] = cached_quote.get(field)

    merged_metadata = dict(cached_quote.get("metadata") or {})
    merged_metadata.update({key: value for key, value in (merged.get("metadata") or {}).items() if value is not None})
    if merged_metadata:
        merged["metadata"] = merged_metadata

    if (not merged.get("history")) and cached_quote.get("history"):
        merged["history"] = cached_quote.get("history")

    return merged


def write_market_cache(ticker, quote):
    try:
        updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        normalized = normalize_ticker_input(ticker)
        quote_payload = {
            "ticker": normalized,
            "market_type": infer_market_type(ticker),
            "quote": quote,
            "updated_at": updated_at,
        }
        write_json_cache_file(market_cache_path(normalized, "quotes"), quote_payload)
        return updated_at
    except Exception:
        traceback.print_exc()
        return None


def unavailable_company_news(reason="Company-news feed skipped for fast market-data response"):
    return {
        "sentiment": None,
        "score": 50,
        "summary": reason,
        "key_points": [],
        "latest_news": [],
        "bullish_news": [],
        "bearish_news": [],
        "key_catalysts": [],
        "risk_events": [],
        "source_info": build_source_info(
            "Data unavailable",
            missing_source="Google News RSS / Yahoo Finance",
            suggested_source="Google News RSS / Yahoo Finance / FMP / Polygon",
            source_name="Company News Feed",
        ),
    }


def build_unavailable_market_context(reason="Market context skipped for fast market-data response"):
    source_info = {
        "vix": build_source_info("Data unavailable", "Cboe / FRED / Yahoo Finance", "FRED VIXCLS / Yahoo Finance ^VIX / Cboe", "Macro Feed"),
        "fear_greed": build_source_info("Data unavailable", "CNN Fear & Greed", "CNN Fear & Greed direct endpoint / CNN scraper / RapidAPI / custom in-house sentiment composite.", "Fear & Greed Feed"),
        "ten_year_yield": build_source_info("Data unavailable", "FRED DGS10 / Yahoo Finance ^TNX", "FRED DGS10 / Yahoo Finance ^TNX / Alpha Vantage", "Macro Feed"),
        "fed_event": build_source_info("Data unavailable", "Economic calendar / market_events.json", "FMP Economic Calendar / Alpha Vantage / market_events.json", "market_events.json"),
        "equity_trend": build_source_info("Data unavailable", "Yahoo Finance SPY / QQQ", "Yahoo Finance SPY / QQQ", "Yahoo Finance"),
    }
    return {
        "macro": {
            "vix": None,
            "fear_greed": None,
            "treasury_yield": None,
            "score": 50,
            "summary": reason,
            "source_info": source_info,
        },
        "market_context": {
            "regime": "neutral",
            "vix": {"value": None, "change_5d": None, "change_20d": None, "trend": "neutral", "impact": "Data unavailable"},
            "fear_greed": {"value": None, "label": None, "trend": None, "impact": "Data unavailable"},
            "ten_year_yield": {"value": None, "change_5d_bps": None, "change_20d_bps": None, "trend": "neutral", "impact": "Data unavailable"},
            "equity_trend": {
                "spy": {"symbol": "SPY", "label": "SPY", "value": None, "change_5d_pct": None, "change_20d_pct": None, "change_60d_pct": None, "change_120d_pct": None, "trend": "neutral", "impact": "Data unavailable"},
                "qqq": {"symbol": "QQQ", "label": "QQQ", "value": None, "change_5d_pct": None, "change_20d_pct": None, "change_60d_pct": None, "change_120d_pct": None, "trend": "neutral", "impact": "Data unavailable"},
                "summary": reason,
                "impact": "neutral",
            },
            "sector_trends": {},
            "summary": reason,
            "source_info": source_info,
        },
        "broad_macro_news": {
            "score": 50,
            "sentiment": None,
            "major_events": [],
            "summary": reason,
            "source_info": build_source_info("Data unavailable", "Broad market news feed", "Google News RSS / Reuters / FMP Market News", "Broad Market News Feed"),
        },
    }


def read_market_context_cache():
    cached = read_module_cache("market_context", "snapshot")
    if not isinstance(cached, dict):
        return None
    updated_at = cached.get("updated_at") or cached.get("updatedAt")
    updated_dt = parse_iso_datetime(updated_at)
    cached["cache_age_seconds"] = (
        max(0, (datetime.now(timezone.utc) - updated_dt).total_seconds())
        if updated_dt else None
    )
    return cached


def write_market_context_cache(payload):
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    wrapped = {
        "updated_at": updated_at,
        "payload": payload,
    }
    write_module_cache("market_context", "snapshot", wrapped)
    return updated_at


def get_market_context_cached_snapshot(force=False, allow_live=True):
    attempts = []
    now = time.time()
    cached_memory = MARKET_CONTEXT_CACHE.get("value")
    if (
        cached_memory
        and not force
        and MARKET_CONTEXT_CACHE.get("expiresAt", 0) > now
        and (market_context_payload_valid(cached_memory) or not allow_live)
        and (market_context_has_index_lookbacks(cached_memory) or not allow_live)
    ):
        attempts.append({"source": "memory_cache", "success": True, "fresh": True})
        return cached_memory, {
            "cache_used": True,
            "cache_layer": "memory",
            "source_attempts": attempts,
            "status": market_context_payload_status(cached_memory),
            "missing_fields": [],
            "cache_updated_at": None,
        }

    cached_disk = read_market_context_cache()
    cached_disk_payload = cached_disk.get("payload") if isinstance(cached_disk, dict) else None
    cache_is_fresh = (
        cached_disk is not None
        and cached_disk.get("cache_age_seconds") is not None
        and cached_disk.get("cache_age_seconds") <= MARKET_CACHE_TTL_SECONDS
    )
    if cached_disk:
        attempts.append({
            "source": "disk_cache",
            "success": True,
            "fresh": cache_is_fresh,
            "age_minutes": round((cached_disk.get("cache_age_seconds") or 0) / 60, 2) if cached_disk.get("cache_age_seconds") is not None else None,
        })
        disk_has_required_index_lookbacks = market_context_has_index_lookbacks(cached_disk_payload)
        if (
            cached_disk_payload
            and not force
            and cache_is_fresh
            and (market_context_payload_valid(cached_disk_payload) or not allow_live)
            and (disk_has_required_index_lookbacks or not allow_live)
        ):
            MARKET_CONTEXT_CACHE["value"] = cached_disk_payload
            MARKET_CONTEXT_CACHE["expiresAt"] = now + NEWS_CACHE_SECONDS
            return cached_disk_payload, {
                "cache_used": True,
                "cache_layer": "disk",
                "source_attempts": attempts,
                "status": market_context_payload_status(cached_disk_payload),
                "missing_fields": [],
                "cache_updated_at": cached_disk.get("updated_at"),
            }

    if allow_live:
        live_payload = _run_with_timeout(fetch_market_context_payload, 8, fallback=None)
        if live_payload and market_context_payload_valid(live_payload):
            MARKET_CONTEXT_CACHE["value"] = live_payload
            MARKET_CONTEXT_CACHE["expiresAt"] = now + NEWS_CACHE_SECONDS
            cache_updated_at = write_market_context_cache(live_payload)
            attempts.append({"source": "live_market_context", "success": True, "fresh": True})
            return live_payload, {
                "cache_used": False,
                "cache_layer": None,
                "source_attempts": attempts,
                "status": market_context_payload_status(live_payload),
                "missing_fields": [],
                "cache_updated_at": cache_updated_at,
            }
        attempts.append({"source": "live_market_context", "success": False, "error": "Live market-context fetch failed, timed out, or returned no usable VIX/10Y/SPY/QQQ/Fear-Greed fields"})

    if cached_disk_payload:
        return cached_disk_payload, {
            "cache_used": True,
            "cache_layer": "disk",
            "source_attempts": attempts,
            "status": "stale" if market_context_payload_valid(cached_disk_payload) else "unavailable",
            "missing_fields": [],
            "cache_updated_at": cached_disk.get("updated_at"),
        }

    if cached_memory:
        return cached_memory, {
            "cache_used": True,
            "cache_layer": "memory",
            "source_attempts": attempts,
            "status": "stale" if market_context_payload_valid(cached_memory) else "unavailable",
            "missing_fields": [],
            "cache_updated_at": None,
        }

    unavailable = build_unavailable_market_context()
    missing_fields = ["vix", "fear_greed", "ten_year_yield", "spy_trend", "qqq_trend"]
    return unavailable, {
        "cache_used": False,
        "cache_layer": None,
        "source_attempts": attempts,
        "status": "unavailable",
        "missing_fields": missing_fields,
        "cache_updated_at": None,
    }


def get_lightweight_market_context(force=False, allow_live=True):
    payload, _meta = get_market_context_cached_snapshot(force=force, allow_live=allow_live)
    return payload


def build_unavailable_or_cached_quote(ticker, error_message, cached=None):
    if cached:
        quote = normalize_cached_market_quote(ticker, cached, stale=True)
        quote["error"] = error_message
        quote["quoteWarning"] = error_message
        return quote, {"ticker": normalize_ticker_input(ticker), "error": error_message, "used_cache": True}
    quote = build_unavailable_quote(ticker, error_message)
    quote["ticker"] = normalize_ticker_input(ticker)
    quote["market_type"] = infer_market_type(ticker)
    quote["quote_status"] = "unavailable"
    quote["quote_source"] = None
    quote["last_quote_time"] = None
    quote["companyNews"] = unavailable_company_news()
    return quote, {"ticker": normalize_ticker_input(ticker), "error": error_message, "used_cache": False}


def fetch_market_quote_for_ticker(ticker, force=False):
    ticker = normalize_ticker_input(ticker)
    attempts = []
    cached = read_market_cache(ticker)
    if cached:
        attempts.append({
            "source": "cache",
            "success": True,
            "price": ((cached.get("quote") or {}).get("price") if isinstance(cached.get("quote"), dict) else cached.get("price")),
            "age_minutes": round((cached.get("cache_age_seconds") or 0) / 60, 2) if cached.get("cache_age_seconds") is not None else None,
            "fresh": is_market_cache_fresh(cached),
        })
        if not force and is_market_cache_fresh(cached):
            quote = normalize_cached_market_quote(ticker, cached, stale=False)
            quote["companyNews"] = quote.get("companyNews") or unavailable_company_news()
            return quote, None, True, attempts

    source_name = "yfinance"
    try:
        quote = fetch_quote_with_timeout(
            ticker,
            timeout_seconds=MARKET_DATA_PER_TICKER_TIMEOUT_SECONDS,
            include_options=False,
        )
        if quote.get("price") is None:
            raise ValueError("Live quote returned no price")
        quote = merge_quote_with_cached_modules(ticker, quote, cached)
        quote["ticker"] = ticker
        quote["market_type"] = infer_market_type(ticker)
        quote["quote_status"] = "available"
        quote["quote_source"] = source_name
        quote["stale"] = False
        quote["dataStaleness"] = quote.get("dataStaleness") or "fresh"
        quote["last_quote_time"] = quote.get("updatedAt") or quote.get("last_successful_update")
        quote["companyNews"] = quote.get("companyNews") or unavailable_company_news()
        CACHE[ticker] = {"value": quote, "expiresAt": time.time() + CACHE_SECONDS}
        quote["cache_updated_at"] = write_market_cache(ticker, quote)
        attempts.append({"source": source_name, "success": True, "price": quote.get("price"), "error": None})
        return quote, None, False, attempts
    except Exception as exc:
        error_message = str(exc)
        attempts.append({"source": source_name, "success": False, "price": None, "error": error_message})
        try:
            quote = fetch_quote_with_timeout(
                ticker,
                timeout_seconds=max(1, min(5, MARKET_DATA_PER_TICKER_TIMEOUT_SECONDS)),
                include_options=False,
            )
            if quote.get("price") is None:
                raise ValueError("Live quote returned no price")
            quote = merge_quote_with_cached_modules(ticker, quote, cached)
            quote["ticker"] = ticker
            quote["market_type"] = infer_market_type(ticker)
            quote["quote_status"] = "available"
            quote["quote_source"] = f"{source_name}:quote_only"
            quote["stale"] = False
            quote["dataStaleness"] = quote.get("dataStaleness") or "fresh"
            quote["last_quote_time"] = quote.get("updatedAt") or quote.get("last_successful_update")
            quote["companyNews"] = quote.get("companyNews") or unavailable_company_news()
            quote["quoteWarning"] = error_message
            CACHE[ticker] = {"value": quote, "expiresAt": time.time() + CACHE_SECONDS}
            quote["cache_updated_at"] = write_market_cache(ticker, quote)
            attempts.append({"source": f"{source_name}:quote_only", "success": True, "price": quote.get("price"), "error": None})
            return quote, None, False, attempts
        except Exception as fallback_exc:
            error_message = f"{error_message}; quote-only fallback failed: {fallback_exc}"
            attempts.append({"source": f"{source_name}:quote_only", "success": False, "price": None, "error": str(fallback_exc)})
        quote, failure = build_unavailable_or_cached_quote(ticker, error_message, cached=cached)
        quote["companyNews"] = quote.get("companyNews") or unavailable_company_news()
        return quote, failure, bool(cached), attempts


def quote_to_market_item(ticker, quote):
    last_quote_time = None
    if isinstance(quote, dict):
        last_quote_time = quote.get("last_quote_time") or quote.get("updatedAt")
    return {
        "ticker": normalize_ticker_input(ticker),
        "market_type": infer_market_type(ticker),
        "price": quote.get("price") if isinstance(quote, dict) else None,
        "quote_status": quote.get("quote_status") if isinstance(quote, dict) else "unavailable",
        "quote_source": quote.get("quote_source") if isinstance(quote, dict) else None,
        "last_quote_time": last_quote_time,
        "analysis": quote if isinstance(quote, dict) else {},
        "error": quote.get("error") if isinstance(quote, dict) else "Quote unavailable",
    }


def build_market_data_payload(tickers, force=False, auto_refresh=False, cache_only=True, refresh_market_context=True):
    normalized_tickers = []
    seen = set()
    for raw_ticker in tickers:
        ticker = normalize_ticker_input(raw_ticker)
        if ticker and ticker not in seen:
            normalized_tickers.append(ticker)
            seen.add(ticker)
    requested_count = len(normalized_tickers)
    requested_tickers = list(normalized_tickers)
    if len(normalized_tickers) > MARKET_DATA_MAX_TICKERS:
        normalized_tickers = normalized_tickers[:MARKET_DATA_MAX_TICKERS]
    processed_tickers = list(normalized_tickers)
    missing_from_request = [ticker for ticker in requested_tickers if ticker not in processed_tickers]

    quotes = {}
    failed = []
    used_cache_count = 0
    stale_cache_count = 0
    us_live_tickers = []
    live_attempted_tickers = []
    live_success_tickers = []
    live_failed_tickers = []
    cache_only_tickers = []
    deferred_live_tickers = []
    source_attempts_by_ticker = {}
    live_refresh_started = False
    live_refresh_completed = False
    cache_age_samples = []

    for ticker in normalized_tickers:
        cached = read_market_cache(ticker)
        if cached:
            if cached.get("cache_age_seconds") is not None:
                cache_age_samples.append(cached.get("cache_age_seconds"))
            if is_market_cache_fresh(cached) and not force:
                quote = normalize_cached_market_quote(ticker, cached, stale=False)
                quote["companyNews"] = quote.get("companyNews") or unavailable_company_news()
                quotes[ticker] = quote
                used_cache_count += 1
                cache_only_tickers.append(ticker)
                continue
            if cache_only and not force and not auto_refresh:
                quote = normalize_cached_market_quote(ticker, cached, stale=True)
                quote["companyNews"] = quote.get("companyNews") or unavailable_company_news()
                quotes[ticker] = quote
                used_cache_count += 1
                stale_cache_count += 1
                cache_only_tickers.append(ticker)
                continue
        if cache_only and not force and not auto_refresh:
            quote, failure = build_unavailable_or_cached_quote(
                ticker,
                "No cached quote available yet",
                cached=cached,
            )
            quotes[ticker] = quote
            if cached:
                used_cache_count += 1
                stale_cache_count += 1
            cache_only_tickers.append(ticker)
            if failure:
                failed.append(failure)
            continue
        # A forced refresh must always attempt the provider. The old branch
        # treated hourly force refreshes as cache-only whenever an entry was
        # fresh, which meant newly added or changed watchlist data could stay
        # stale until that cache expired.
        if auto_refresh and not force and cached and is_market_cache_fresh(cached):
            quote = normalize_cached_market_quote(ticker, cached, stale=False)
            quote["companyNews"] = quote.get("companyNews") or unavailable_company_news()
            quotes[ticker] = quote
            used_cache_count += 1
            cache_only_tickers.append(ticker)
            continue
        us_live_tickers.append(ticker)

    live_candidates = us_live_tickers
    if (force or auto_refresh) and len(live_candidates) > MARKET_DATA_MAX_LIVE_TICKERS:
        allowed_live = set(live_candidates[:MARKET_DATA_MAX_LIVE_TICKERS])
        deferred_live_tickers = [ticker for ticker in live_candidates if ticker not in allowed_live]
        us_live_tickers = [ticker for ticker in us_live_tickers if ticker in allowed_live]
        for ticker in deferred_live_tickers:
            cached = read_market_cache(ticker)
            quote, failure = build_unavailable_or_cached_quote(
                ticker,
                f"Live refresh deferred: request exceeded per-request live limit ({MARKET_DATA_MAX_LIVE_TICKERS})",
                cached=cached,
            )
            quote["companyNews"] = quote.get("companyNews") or unavailable_company_news()
            quotes[ticker] = quote
            source_attempts_by_ticker[ticker] = [{
                "source": "live_refresh_limit",
                "success": False,
                "deferred": True,
                "error": f"Per-request live refresh limit is {MARKET_DATA_MAX_LIVE_TICKERS}",
            }]
            cache_only_tickers.append(ticker)
            if cached:
                used_cache_count += 1
                stale_cache_count += 1 if quote.get("stale") or quote.get("quote_status") == "stale" else 0
            if failure:
                failed.append(failure)

    executor = None
    futures = {}
    completed = set()
    if us_live_tickers:
        live_refresh_started = True
        live_attempted_tickers.extend(us_live_tickers)
        executor = ThreadPoolExecutor(max_workers=max(1, MARKET_DATA_MAX_WORKERS))
        futures = {
            executor.submit(fetch_market_quote_for_ticker, ticker, force): ticker
            for ticker in us_live_tickers
        }
        try:
            for future in as_completed(futures, timeout=MARKET_DATA_ROUTE_TIMEOUT_SECONDS):
                ticker = futures[future]
                completed.add(ticker)
                try:
                    quote, failure, used_cache, attempts = future.result(timeout=1)
                except Exception as exc:
                    traceback.print_exc()
                    cached = read_market_cache(ticker)
                    quote, failure = build_unavailable_or_cached_quote(ticker, str(exc), cached=cached)
                    used_cache = bool(cached)
                    attempts = [{"source": "worker", "success": False, "error": str(exc)}]
                quotes[ticker] = quote
                source_attempts_by_ticker[ticker] = attempts
                if quote.get("price") is not None and not used_cache:
                    live_success_tickers.append(ticker)
                elif failure:
                    live_failed_tickers.append(ticker)
                if used_cache:
                    used_cache_count += 1
                    stale_cache_count += 1 if quote.get("stale") or quote.get("quote_status") == "stale" else 0
                if failure:
                    failed.append(failure)
        except FuturesTimeoutError:
            pass
        finally:
            for future, ticker in futures.items():
                if ticker in completed:
                    continue
                future.cancel()
                cached = read_market_cache(ticker)
                quote, failure = build_unavailable_or_cached_quote(
                    ticker,
                    f"Market-data route timed out before {ticker} completed",
                    cached=cached,
                )
                quotes[ticker] = quote
                source_attempts_by_ticker[ticker] = [{"source": "route_timeout", "success": False, "error": f"Market-data route timed out before {ticker} completed"}]
                live_failed_tickers.append(ticker)
                if cached:
                    used_cache_count += 1
                    stale_cache_count += 1 if quote.get("stale") or quote.get("quote_status") == "stale" else 0
                if failure:
                    failed.append(failure)
            if executor:
                executor.shutdown(wait=False, cancel_futures=True)
        live_refresh_completed = True

    for ticker in normalized_tickers:
        if ticker not in quotes:
            quote, failure = build_unavailable_or_cached_quote(ticker, "Quote unavailable")
            quotes[ticker] = quote
            failed.append(failure)
            live_failed_tickers.append(ticker)

    request_started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Fetch real market data for display. The frontend deliberately does not
    # convert this payload into a market-environment or macro score.
    market_context, market_context_meta = get_market_context_cached_snapshot(
        force=False,
        # A complete watchlist refresh runs in small quote batches. Fetch the
        # shared market context once for that transaction, rather than once per
        # batch; later batches and the final cache snapshot reuse it.
        allow_live=bool((force or auto_refresh) and refresh_market_context),
    )
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    request_completed_at = fetched_at
    quote_times = [
        quote.get("updatedAt")
        for quote in quotes.values()
        if isinstance(quote, dict) and quote.get("updatedAt")
    ]
    updated_at = max(quote_times) if quote_times else fetched_at
    refresh_reference_candidates = []
    for quote in quotes.values():
        if isinstance(quote, dict) and quote.get("cache_updated_at") and quote.get("price") is not None:
            refresh_reference_candidates.append(quote.get("cache_updated_at"))
    if market_context_meta.get("cache_updated_at") and market_context_payload_valid(market_context):
        refresh_reference_candidates.append(market_context_meta.get("cache_updated_at"))
    if not refresh_reference_candidates:
        if any(
            isinstance(quote, dict)
            and quote.get("price") is not None
            and not quote.get("stale")
            and quote.get("quote_source") not in {None, "cache"}
            for quote in quotes.values()
        ) or (not market_context_meta.get("cache_used") and market_context_payload_valid(market_context)):
            refresh_reference_candidates.append(fetched_at)
    last_dashboard_refresh = max(refresh_reference_candidates) if refresh_reference_candidates else None
    live_refresh_successful = bool(live_success_tickers) or (
        not market_context_meta.get("cache_used") and market_context_payload_valid(market_context)
    )
    last_successful_live_refresh_at = fetched_at if live_refresh_successful else None
    last_successful_cache_update_at = last_dashboard_refresh
    last_any_successful_ticker_refresh_at = max([
        quote.get("cache_updated_at") or quote.get("updatedAt")
        for quote in quotes.values()
        if isinstance(quote, dict) and quote.get("price") is not None and (quote.get("cache_updated_at") or quote.get("updatedAt"))
    ] or [None])
    stale_quote_count = sum(
        1 for quote in quotes.values()
        if isinstance(quote, dict) and (
            quote.get("stale")
            or quote.get("dataStaleness") == "stale"
            or quote.get("quote_status") == "stale"
        )
    )
    unavailable_count = sum(
        1 for quote in quotes.values()
        if isinstance(quote, dict) and quote.get("quote_status") == "unavailable"
    )
    hard_failed = [
        failure for failure in failed
        if isinstance(failure, dict) and not failure.get("used_cache")
    ]
    cache_fallback_failures = [
        failure for failure in failed
        if isinstance(failure, dict) and failure.get("used_cache")
    ]
    cache_fallback_tickers = sorted({
        normalize_ticker_input(failure.get("ticker") or failure.get("symbol"))
        for failure in cache_fallback_failures
        if failure.get("ticker") or failure.get("symbol")
    })
    hard_failed_tickers = sorted({
        normalize_ticker_input(failure.get("ticker") or failure.get("symbol"))
        for failure in hard_failed
        if failure.get("ticker") or failure.get("symbol")
    })
    items = [quote_to_market_item(ticker, quotes[ticker]) for ticker in normalized_tickers]
    success_count = sum(
        1 for quote in quotes.values()
        if isinstance(quote, dict) and quote.get("price") is not None
    )
    cache_age_minutes = round((max(cache_age_samples) / 60), 2) if cache_age_samples else None
    last_refresh_dt = parse_iso_datetime(last_dashboard_refresh) if last_dashboard_refresh else None
    next_refresh_dt = (last_refresh_dt + timedelta(minutes=60)) if last_refresh_dt else None
    for ticker, quote in quotes.items():
        if isinstance(quote, dict):
            quote["data_quality"] = {
                "quote_status": quote.get("quote_status") or ("stale" if quote.get("stale") else "available"),
                "quote_source": quote.get("quote_source"),
                "market_context_status": market_context_meta.get("status"),
                "cache_used": bool(quote.get("quote_source") == "cache" or quote.get("stale")),
                "stale_fields": ["price"] if quote.get("stale") else [],
                "unavailable_fields": ["price"] if quote.get("price") is None else [],
                "warnings": [quote.get("error")] if quote.get("error") else [],
            }
            quote["source_attempts"] = source_attempts_by_ticker.get(ticker, [])

    warning = None
    if requested_count > len(normalized_tickers):
        warning = f"Ticker list truncated to {MARKET_DATA_MAX_TICKERS} symbols"

    return {
        "success": success_count > 0,
        "source": "cache-first-yfinance",
        "quotes": quotes,
        "items": items,
        "data": quotes,
        "failed": failed,
        "warning": warning,
        "marketContext": market_context,
        "market_context": flatten_market_context_payload(market_context, market_context_meta),
        "fetchedAt": fetched_at,
        "updatedAt": updated_at,
        "requested_tickers": requested_tickers,
        "processed_tickers": processed_tickers,
        "missing_from_request": missing_from_request,
        "refresh_status": {
            "refresh_interval_minutes": 60,
            "request_started_at": request_started_at,
            "request_completed_at": request_completed_at,
            "last_successful_live_refresh_at": last_successful_live_refresh_at,
            "last_successful_cache_update_at": last_successful_cache_update_at,
            "last_any_successful_ticker_refresh_at": last_any_successful_ticker_refresh_at,
            "last_dashboard_refresh": last_dashboard_refresh,
            "next_dashboard_refresh": next_refresh_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if next_refresh_dt else None,
            "next_auto_refresh_at": next_refresh_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if next_refresh_dt else None,
            "cache_age_minutes": cache_age_minutes,
            "is_cache_only": bool(cache_only and not force and not auto_refresh),
            "is_force_refresh": bool(force),
            "is_auto_refresh": bool(auto_refresh),
            "live_refresh_started": live_refresh_started,
            "live_refresh_completed": live_refresh_completed if live_refresh_started else False,
            "force_requested_tickers": requested_tickers if force else [],
            "live_limit_per_request": MARKET_DATA_MAX_LIVE_TICKERS,
            "live_attempted_tickers": sorted(set(live_attempted_tickers)),
            "live_success_tickers": sorted(set(live_success_tickers)),
            "live_failed_tickers": sorted(set(live_failed_tickers)),
            "deferred_live_tickers": sorted(set(deferred_live_tickers)),
            "cache_only_tickers": sorted(set(cache_only_tickers)),
            "requested_tickers": requested_tickers,
            "processed_tickers": processed_tickers,
            "missing_from_request": missing_from_request,
            "total_tickers": len(normalized_tickers),
            "success_count": success_count,
            "failed_count": len(hard_failed),
            "live_failure_count": len(failed),
            "cache_fallback_count": len(cache_fallback_failures),
            "cache_fallback_tickers": cache_fallback_tickers,
            "hard_failed_tickers": hard_failed_tickers,
            "unavailable_count": unavailable_count,
            "has_stale_quotes": stale_quote_count > 0 or unavailable_count > 0,
            "stale_quote_count": stale_quote_count,
            "unavailable_quote_count": unavailable_count,
            "used_cache_count": used_cache_count,
            "stale_cache_count": stale_cache_count,
            "is_partial": success_count > 0 and success_count < len(normalized_tickers),
            "is_loading_live_data": success_count > 0 and success_count < len(normalized_tickers) and len(failed) == 0,
            "force_refresh": bool(force),
        },
    }


def next_top_of_hour_utc(now=None):
    current = now or datetime.now(timezone.utc)
    next_run = current.replace(minute=0, second=0, microsecond=0)
    if next_run <= current:
        next_run += timedelta(hours=1)
    return next_run + timedelta(seconds=max(0, BACKGROUND_MARKET_REFRESH_AFTER_HOUR_SECONDS))


def chunk_tickers_for_live_refresh(tickers):
    batch_size = max(1, MARKET_DATA_MAX_LIVE_TICKERS)
    return [tickers[index:index + batch_size] for index in range(0, len(tickers), batch_size)]


def _refresh_market_cache_for_tickers(tickers, reason="scheduled_hourly"):
    """Force-refresh every requested ticker in provider-safe batches.

    This is deliberately the one server-side live-refresh primitive used by
    hourly work, EOD capture, and browser-triggered full refreshes. A batch is
    only a provider/resource boundary; it is never a reason to omit later
    watchlist tickers from the completed dashboard snapshot.
    """
    tickers = normalize_watchlist(tickers)[:MARKET_DATA_MAX_TICKERS]
    batches = chunk_tickers_for_live_refresh(tickers)
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    batch_summaries = []
    total_success = 0
    total_failed = 0
    total_cache_fallback = 0

    with BACKGROUND_REFRESH_LOCK:
        BACKGROUND_REFRESH_STATE.update({
            "running": True,
            "last_started_at": started_at,
            "last_completed_at": None,
            "last_error": None,
            "last_batches": [],
        })

    try:
        for batch_index, batch in enumerate(batches, start=1):
            payload = build_market_data_payload(
                batch,
                force=True,
                auto_refresh=True,
                cache_only=False,
                refresh_market_context=(batch_index == 1),
            )
            status = payload.get("refresh_status") or {}
            success_count = int(status.get("success_count") or 0)
            failed_count = int(status.get("failed_count") or 0)
            cache_fallback_count = int(status.get("cache_fallback_count") or 0)
            total_success += success_count
            total_failed += failed_count
            total_cache_fallback += cache_fallback_count
            batch_summaries.append({
                "batch": batch_index,
                "tickers": batch,
                "success_count": success_count,
                "failed_count": failed_count,
                "cache_fallback_count": cache_fallback_count,
                "last_dashboard_refresh": status.get("last_dashboard_refresh"),
            })
    except Exception as exc:
        traceback.print_exc()
        with BACKGROUND_REFRESH_LOCK:
            BACKGROUND_REFRESH_STATE.update({
                "running": False,
                "last_completed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "last_success_count": total_success,
                "last_failed_count": total_failed,
                "last_cache_fallback_count": total_cache_fallback,
                "last_error": str(exc),
                "last_batches": batch_summaries,
            })
        return {
            "completed": False,
            "reason": reason,
            "requested_tickers": tickers,
            "batch_count": len(batches),
            "success_count": total_success,
            "failed_count": total_failed,
            "cache_fallback_count": total_cache_fallback,
            "batches": batch_summaries,
            "error": str(exc),
        }

    completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with BACKGROUND_REFRESH_LOCK:
        BACKGROUND_REFRESH_STATE.update({
            "running": False,
            "last_completed_at": completed_at,
            "last_success_count": total_success,
            "last_failed_count": total_failed,
            "last_cache_fallback_count": total_cache_fallback,
            "last_error": None,
            "last_batches": batch_summaries,
            "last_reason": reason,
        })
    return {
        "completed": True,
        "reason": reason,
        "requested_tickers": tickers,
        "batch_count": len(batches),
        "success_count": total_success,
        "failed_count": total_failed,
        "cache_fallback_count": total_cache_fallback,
        "batches": batch_summaries,
        "completed_at": completed_at,
    }


def _refresh_market_cache_for_watchlist(reason="scheduled_hourly"):
    tickers = load_shared_watchlist()
    if not tickers:
        tickers = watchlist_items_to_tickers(normalize_watchlist_items(DEFAULT_SHARED_WATCHLIST))
    return _refresh_market_cache_for_tickers(tickers, reason=reason)


def refresh_market_cache_for_watchlist(reason="scheduled_hourly"):
    """Run one complete live watchlist refresh without overlapping EOD writes.

    The same lock is shared by hourly refresh and the EOD recorder so an EOD
    snapshot cannot accidentally mix cache generations from two provider runs.
    """
    with FULL_REFRESH_RUN_LOCK:
        summary = _refresh_market_cache_for_watchlist(reason=reason)
        return bool(summary.get("completed"))


def watchlist_market_cache_needs_refresh():
    tickers = load_shared_watchlist()
    if not tickers:
        tickers = watchlist_items_to_tickers(normalize_watchlist_items(DEFAULT_SHARED_WATCHLIST))
    tickers = normalize_watchlist(tickers)[:MARKET_DATA_MAX_TICKERS]
    if not tickers:
        return False
    for ticker in tickers:
        cached = read_market_cache(ticker)
        if not is_market_cache_fresh(cached):
            return True
    return False


def background_market_refresh_loop():
    if BACKGROUND_MARKET_REFRESH_STARTUP_DELAY_SECONDS > 0:
        time.sleep(BACKGROUND_MARKET_REFRESH_STARTUP_DELAY_SECONDS)
    if BACKGROUND_MARKET_REFRESH_ON_START and watchlist_market_cache_needs_refresh():
        refresh_market_cache_for_watchlist(reason="startup_cache_warm")
    while True:
        next_run = next_top_of_hour_utc()
        with BACKGROUND_REFRESH_LOCK:
            BACKGROUND_REFRESH_STATE["next_run_at"] = next_run.strftime("%Y-%m-%dT%H:%M:%SZ")
        delay = max(1, (next_run - datetime.now(timezone.utc)).total_seconds())
        time.sleep(delay)
        refresh_market_cache_for_watchlist(reason="scheduled_hourly")


def start_background_market_refresh_scheduler():
    global BACKGROUND_REFRESH_THREAD_STARTED
    if not BACKGROUND_MARKET_REFRESH_ENABLED:
        return False
    with BACKGROUND_REFRESH_LOCK:
        if BACKGROUND_REFRESH_THREAD_STARTED:
            return False
        BACKGROUND_REFRESH_THREAD_STARTED = True
        BACKGROUND_REFRESH_STATE["next_run_at"] = next_top_of_hour_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    thread = threading.Thread(
        target=background_market_refresh_loop,
        name="market-cache-hourly-refresh",
        daemon=True,
    )
    thread.start()
    return True


def eod_history_now_et(now=None):
    """Normalize an injected or live time into America/New_York."""
    current = now or datetime.now(EOD_HISTORY_TIMEZONE)
    if current.tzinfo is None:
        return current.replace(tzinfo=EOD_HISTORY_TIMEZONE)
    return current.astimezone(EOD_HISTORY_TIMEZONE)


def eod_history_timestamp(now):
    return eod_history_now_et(now).isoformat(timespec="seconds")


def eod_history_watchlist_tickers():
    tickers = load_shared_watchlist()
    if not tickers:
        tickers = watchlist_items_to_tickers(normalize_watchlist_items(DEFAULT_SHARED_WATCHLIST))
    return normalize_watchlist(tickers)[:MARKET_DATA_MAX_TICKERS]


def eod_history_daily_dates(payload):
    """Return each valid daily-bar date represented in an EOD cache snapshot."""
    dates = set()
    for item in (payload or {}).get("items") or []:
        quote = item.get("analysis") if isinstance(item, dict) else None
        if not isinstance(quote, dict):
            continue
        history = quote.get("history") or {}
        timestamps = history.get("timestamps") or []
        if history.get("availability") == "unavailable" or not timestamps:
            continue
        latest = str(timestamps[-1])[:10]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", latest):
            dates.add(latest)
    return dates


def eod_history_valid_trading_session(payload, market_date):
    """Do not turn a holiday/weekend cache into a fake current-date record."""
    return market_date in eod_history_daily_dates(payload)


def eod_history_node_executable():
    """Find the existing JS runtime; production can override its exact path."""
    configured = os.environ.get("EOD_DECISION_NODE_PATH") or os.environ.get("NODE_EXECUTABLE")
    if configured:
        return configured
    return shutil.which("node")


def write_eod_snapshot_input(payload, market_date, recorded_at_et):
    """Serialize the fetched snapshot once, then release it before Node runs."""
    temp_directory = tempfile.mkdtemp(prefix="eod-history-")
    input_path = os.path.join(temp_directory, "snapshot.json")
    output_path = os.path.join(temp_directory, "decision-snapshot.json")
    with open(input_path, "w", encoding="utf-8") as handle:
        json.dump({"marketDate": market_date, "recordedAtEt": recorded_at_et, "payload": payload}, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return temp_directory, input_path, output_path


def build_eod_decision_snapshot(input_path, output_path):
    """Run the exact JS Decision Engine in a bounded one-shot child process."""
    node = eod_history_node_executable()
    if not node:
        raise RuntimeError("Node.js is required for EOD history because the production Decision Engine is JavaScript. Set EOD_DECISION_NODE_PATH on Render if node is not on PATH.")
    if not os.path.isfile(EOD_HISTORY_NODE_RUNNER):
        raise RuntimeError(f"EOD Decision snapshot runner is missing: {EOD_HISTORY_NODE_RUNNER}")
    node_memory_flag = [f"--max-old-space-size={max(64, EOD_HISTORY_NODE_MAX_OLD_SPACE_MB)}"] if EOD_HISTORY_NODE_MAX_OLD_SPACE_MB > 0 else []
    completed = subprocess.run(
        [node, *node_memory_flag, EOD_HISTORY_NODE_RUNNER, input_path, output_path],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=EOD_HISTORY_NODE_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown Node error").strip()
        raise RuntimeError(f"Production JS Decision Engine EOD snapshot failed: {detail[:1200]}")
    with open(output_path, "r", encoding="utf-8") as handle:
        snapshot = json.load(handle)
    if not isinstance(snapshot.get("records"), list):
        raise RuntimeError("EOD Decision snapshot did not return a record list")
    return snapshot


def _eod_refresh_and_cache_snapshot(tickers):
    """Keep live refresh and the cache read in one server-side transaction lock."""
    with FULL_REFRESH_RUN_LOCK:
        summary = _refresh_market_cache_for_watchlist(reason="eod_history")
        if not summary.get("completed"):
            return None
        # The preceding chunked force refresh updated every watchlist ticker.
        # Reading the cache-only payload here prevents a second provider fetch.
        return build_market_data_payload(tickers, force=False, auto_refresh=False, cache_only=True)


def run_eod_history_once(now=None, reason="scheduled_eod"):
    """Full-refresh, calculate, and atomically persist one EOD snapshot.

    This function intentionally has no browser/UI dependency.  It is called by
    the Render server's own scheduler and by the explicit local dev entrypoint.
    """
    current = eod_history_now_et(now)
    market_date = current.date().isoformat()
    started_at_et = eod_history_timestamp(current)
    with EOD_HISTORY_RUN_LOCK:
        with BACKGROUND_REFRESH_LOCK:
            EOD_HISTORY_STATE.update({
                "running": True, "last_started_at": started_at_et, "last_completed_at": None,
                "last_status": "running", "last_error": None,
            })
        print(f"[EOD HISTORY] started {current.strftime('%Y-%m-%d %H:%M ET')} ({reason})")
        eod_history_db.mark_run_started(market_date, started_at_et)
        temp_directory = None
        try:
            if current.weekday() >= 5:
                completed_at_et = eod_history_timestamp(datetime.now(EOD_HISTORY_TIMEZONE))
                eod_history_db.mark_run_terminal(market_date, started_at_et, completed_at_et, "skipped", "no valid trading session: weekend")
                print("[EOD HISTORY] skipped: no valid trading session.")
                return {"status": "skipped", "market_date": market_date, "reason": "weekend"}
            tickers = eod_history_watchlist_tickers()
            if not tickers:
                raise RuntimeError("EOD history has no watchlist tickers to record")
            payload = _eod_refresh_and_cache_snapshot(tickers)
            if not payload or not payload.get("success"):
                raise RuntimeError("full live refresh did not produce a valid market snapshot")
            if not eod_history_valid_trading_session(payload, market_date):
                completed_at_et = eod_history_timestamp(datetime.now(EOD_HISTORY_TIMEZONE))
                eod_history_db.mark_run_terminal(market_date, started_at_et, completed_at_et, "skipped", "no valid trading session")
                print("[EOD HISTORY] skipped: no valid trading session.")
                return {"status": "skipped", "market_date": market_date, "reason": "no_valid_trading_session"}
            print("[EOD HISTORY] full refresh complete")
            temp_directory, input_path, output_path = write_eod_snapshot_input(payload, market_date, started_at_et)
            # The cache payload contains OHLCV only for this temporary handoff;
            # it is released before the child JS process creates compact rows.
            del payload
            gc.collect()
            snapshot = build_eod_decision_snapshot(input_path, output_path)
            records = snapshot.get("records") or []
            expected_rows = len(tickers) * 3
            if len(records) != expected_rows:
                raise RuntimeError(f"EOD Decision snapshot returned {len(records)} rows; expected {expected_rows}")
            completed_at_et = eod_history_timestamp(datetime.now(EOD_HISTORY_TIMEZONE))
            result = eod_history_db.write_snapshot(market_date, started_at_et, completed_at_et, records)
            print(f"[EOD HISTORY] {result['ticker_count']} tickers / {result['row_count']} horizon rows")
            print(f"[EOD HISTORY] {result['unavailable_count']} unavailable")
            print("[EOD HISTORY] database commit success")
            print(f"[EOD HISTORY] db size {result['database_size_mb']:.3f} MB")
            print("[EOD HISTORY] completed")
            with BACKGROUND_REFRESH_LOCK:
                EOD_HISTORY_STATE.update({
                    "running": False, "last_completed_at": completed_at_et, "last_status": "success", "last_error": None,
                })
            return {"status": "success", "market_date": market_date, "database_path": str(eod_history_db.resolve_db_path()), **result}
        except Exception as exc:
            completed_at_et = eod_history_timestamp(datetime.now(EOD_HISTORY_TIMEZONE))
            eod_history_db.mark_run_terminal(market_date, started_at_et, completed_at_et, "failed", str(exc)[:1200])
            print(f"[EOD HISTORY] FAILED: {exc}")
            with BACKGROUND_REFRESH_LOCK:
                EOD_HISTORY_STATE.update({
                    "running": False, "last_completed_at": completed_at_et, "last_status": "failed", "last_error": str(exc),
                })
            return {"status": "failed", "market_date": market_date, "error": str(exc)}
        finally:
            if temp_directory:
                shutil.rmtree(temp_directory, ignore_errors=True)


def next_eod_history_run(now=None):
    current = eod_history_now_et(now)
    candidate = current.replace(hour=EOD_HISTORY_HOUR, minute=EOD_HISTORY_MINUTE, second=0, microsecond=0)
    if candidate <= current:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def eod_history_should_catch_up(now=None):
    current = eod_history_now_et(now)
    if current.weekday() >= 5 or (current.hour, current.minute) < (EOD_HISTORY_HOUR, EOD_HISTORY_MINUTE):
        return False
    return not eod_history_db.successful_run_exists(current.date().isoformat())


def eod_history_scheduler_loop():
    if EOD_HISTORY_STARTUP_DELAY_SECONDS > 0:
        time.sleep(EOD_HISTORY_STARTUP_DELAY_SECONDS)
    # Safe catch-up only starts a current-day full refresh. Trading-date
    # validation inside run_eod_history_once prevents a future date from being
    # written with yesterday's bars.
    if eod_history_should_catch_up():
        run_eod_history_once(reason="startup_eod_catchup")
    while True:
        next_run = next_eod_history_run()
        with BACKGROUND_REFRESH_LOCK:
            EOD_HISTORY_STATE["next_run_at"] = next_run.isoformat(timespec="seconds")
        delay = max(1, (next_run - datetime.now(EOD_HISTORY_TIMEZONE)).total_seconds())
        time.sleep(delay)
        run_eod_history_once(reason="scheduled_eod")


def start_eod_history_scheduler():
    global EOD_HISTORY_THREAD_STARTED
    if not EOD_HISTORY_ENABLED:
        return False
    with BACKGROUND_REFRESH_LOCK:
        if EOD_HISTORY_THREAD_STARTED:
            return False
        EOD_HISTORY_THREAD_STARTED = True
        EOD_HISTORY_STATE["next_run_at"] = next_eod_history_run().isoformat(timespec="seconds")
    thread = threading.Thread(target=eod_history_scheduler_loop, name="eod-decision-history", daemon=True)
    thread.start()
    return True


def get_quote_for_debug_modules(ticker, force=False):
    normalized = normalize_ticker_input(ticker)
    cached = read_market_cache(normalized)
    if cached and not force and is_market_cache_fresh(cached):
        quote = normalize_cached_market_quote(normalized, cached, stale=False)
        return quote, True, None
    try:
        quote = fetch_quote_with_timeout(
            normalized,
            timeout_seconds=MARKET_DATA_PER_TICKER_TIMEOUT_SECONDS,
        )
        quote["ticker"] = normalized
        quote["market_type"] = infer_market_type(normalized)
        quote["quote_status"] = "available"
        quote["quote_source"] = "yfinance"
        write_market_cache(normalized, quote)
        return quote, False, None
    except Exception as exc:
        if cached:
            quote = normalize_cached_market_quote(normalized, cached, stale=True)
            quote["error"] = str(exc)
            return quote, True, str(exc)
        return build_unavailable_quote(normalized, str(exc)), False, str(exc)


def watchlist_response_payload(items):
    return {
        "success": True,
        "items": items,
        "watchlist": watchlist_items_to_tickers(items),
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/market-data":
            self.handle_market_data(parsed)
            return
        if parsed.path == "/api/symbol-search":
            self.handle_symbol_search(parsed)
            return
        if parsed.path == "/api/watchlist":
            self.handle_watchlist_get()
            return

        if parsed.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/watchlist":
            self.handle_watchlist_add()
            return
        self.send_error(404, "Not found")

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/watchlist" or parsed.path.startswith("/api/watchlist/"):
            self.handle_watchlist_delete(parsed)
            return
        self.send_error(404, "Not found")

    def handle_market_data(self, parsed):
        params = parse_qs(parsed.query)
        tickers = [
            ticker.strip().upper()
            for ticker in params.get("tickers", [""])[0].split(",")
            if ticker.strip()
        ]

        quotes = {}
        for ticker in tickers:
            try:
                quotes[ticker] = get_cached_quote(ticker)
            except Exception as exc:
                quotes[ticker] = {
                    "price": None,
                    "previousClose": None,
                    "change": None,
                    "changePercent": None,
                    "updatedAt": None,
                    "symbol": resolve_market_symbol(ticker),
                    "shortName": None,
                    "longName": None,
                    "exchangeName": None,
                    "metadata": {
                        "sector": None,
                        "industry": None,
                        "businessSummary": None,
                        "ipoDate": None,
                    },
                    "history": {"timestamps": [], "closes": [], "highs": [], "lows": [], "volumes": []},
                    "error": str(exc),
                }

        for ticker, quote in quotes.items():
            try:
                quote["companyNews"] = get_cached_company_news(ticker, quote)
            except Exception as exc:
                quote["companyNews"] = {
                    "sentiment": None,
                    "score": 50,
                    "summary": f"Company-news feed unavailable: {exc}",
                    "key_points": [],
                    "latest_news": [],
                    "bullish_news": [],
                    "bearish_news": [],
                    "key_catalysts": [],
                    "risk_events": [],
                    "source_info": build_source_info(
                        "Data unavailable",
                        missing_source="Google News RSS / Yahoo Finance",
                        suggested_source="Google News RSS / Yahoo Finance / FMP / Polygon",
                        source_name="Company News Feed",
                    ),
                }

        try:
            market_context = get_cached_market_context()
        except Exception as exc:
            market_context = {
                "macro": {
                    "vix": None,
                    "fear_greed": None,
                    "treasury_yield": None,
                    "fed_funds_rate": None,
                    "fomc_rate_path": None,
                    "score": 50,
                    "summary": f"Macro feed unavailable: {exc}",
                    "source_info": {
                        "vix": build_source_info("Data unavailable", "Cboe / FRED / Yahoo Finance", "Cboe / FRED VIXCLS / Yahoo Finance", "Macro Feed"),
                        "fear_greed": build_source_info("Data unavailable", "CNN Fear & Greed", "CNN Fear & Greed direct endpoint / CNN scraper / RapidAPI / custom in-house sentiment composite.", "Fear & Greed Feed"),
                        "treasury_yield": build_source_info("Data unavailable", "FRED / Yahoo Finance ^TNX", "FRED / Yahoo Finance ^TNX / Alpha Vantage", "Macro Feed"),
                        "fed_funds_rate": build_source_info("Data unavailable", "FRED DFF / FEDFUNDS", "FRED DFF / FEDFUNDS", "FRED"),
                        "fomc_rate_path": build_source_info("Data unavailable", "Federal Reserve / FRED", "Federal Reserve FOMC / FRED DFF", "Federal Reserve / FRED"),
                        "market_events": build_source_info("Live", "Economic calendar / market_events.json", "FMP Economic Calendar / Alpha Vantage / market_events.json", "market_events.json"),
                        "equity_trend": build_source_info("Data unavailable", "Yahoo Finance SPY / QQQ", "Yahoo Finance SPY / QQQ", "Yahoo Finance"),
                    },
                },
                "market_context": {
                    "regime": "neutral",
                    "vix": {"value": None, "change_5d": None, "change_20d": None, "trend": "neutral", "impact": "Data unavailable"},
                    "fear_greed": {"value": None, "label": None, "trend": None, "impact": "Data unavailable"},
                    "ten_year_yield": {"value": None, "change_5d_bps": None, "change_20d_bps": None, "trend": "neutral", "impact": "Data unavailable"},
                    "fed_event": {
                        "active": False,
                        "type": None,
                        "title": None,
                        "impact": None,
                        "severity": None,
                        "summary": f"Fed / rate event feed unavailable: {exc}",
                        "date": None,
                        "source": "market_events.json",
                    },
                    "equity_trend": {
                        "spy": {"symbol": "SPY", "label": "SPY", "value": None, "change_5d_pct": None, "change_20d_pct": None, "change_60d_pct": None, "change_120d_pct": None, "trend": "neutral", "impact": "Data unavailable"},
                        "qqq": {"symbol": "QQQ", "label": "QQQ", "value": None, "change_5d_pct": None, "change_20d_pct": None, "change_60d_pct": None, "change_120d_pct": None, "trend": "neutral", "impact": "Data unavailable"},
                        "summary": f"Equity trend feed unavailable: {exc}",
                        "impact": "neutral",
                    },
                    "summary": f"Market context feed unavailable: {exc}",
                    "source_info": {
                        "vix": build_source_info("Data unavailable", "Cboe / FRED / Yahoo Finance", "FRED VIXCLS / Yahoo Finance ^VIX / Cboe", "Macro Feed"),
                        "fear_greed": build_source_info("Data unavailable", "CNN Fear & Greed", "CNN Fear & Greed direct endpoint / CNN scraper / RapidAPI / custom in-house sentiment composite.", "Fear & Greed Feed"),
                        "ten_year_yield": build_source_info("Data unavailable", "FRED DGS10 / Yahoo Finance ^TNX", "FRED DGS10 / Yahoo Finance ^TNX / Alpha Vantage", "Macro Feed"),
                        "fed_event": build_source_info("Live", "Economic calendar / market_events.json", "FMP Economic Calendar / Alpha Vantage / market_events.json", "market_events.json"),
                        "equity_trend": build_source_info("Data unavailable", "Yahoo Finance SPY / QQQ", "Yahoo Finance SPY / QQQ", "Yahoo Finance"),
                    },
                },
                "broad_macro_news": {
                    "score": 50,
                    "sentiment": None,
                    "major_events": [],
                    "summary": f"Broad macro-news feed unavailable: {exc}",
                    "source_info": build_source_info("Data unavailable", "Broad market news feed", "Google News RSS / Reuters / FMP Market News", "Broad Market News Feed"),
                },
            }

        payload = {
            "source": "yfinance",
            "quotes": quotes,
            "marketContext": market_context,
        }
        payload["fetchedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        quote_times = [
            quote.get("updatedAt")
            for quote in quotes.values()
            if isinstance(quote, dict) and quote.get("updatedAt")
        ]
        payload["updatedAt"] = max(quote_times) if quote_times else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        stale_quote_count = sum(
            1 for quote in quotes.values()
            if isinstance(quote, dict) and (quote.get("stale") or quote.get("dataStaleness") == "stale")
        )
        next_refresh_dt = datetime.fromisoformat(payload["fetchedAt"].replace("Z", "+00:00")) + timedelta(minutes=60)
        payload["refresh_status"] = {
            "refresh_interval_minutes": 60,
            "last_dashboard_refresh": payload["fetchedAt"],
            "next_dashboard_refresh": next_refresh_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "has_stale_quotes": stale_quote_count > 0,
            "stale_quote_count": stale_quote_count,
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def handle_symbol_search(self, parsed):
        params = parse_qs(parsed.query)
        query = normalize_search_query(params.get("q", [""])[0])
        limit_raw = params.get("limit", ["10"])[0]
        try:
            limit = max(1, min(int(limit_raw), 20))
        except ValueError:
            limit = 10

        if not query:
            self.respond_json(200, {"query": "", "candidates": []})
            return

        candidates = search_symbol_candidates(query, limit=limit)
        self.respond_json(200, {
            "query": query,
            "candidates": candidates,
            "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    def respond_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_watchlist_get(self):
        items = load_shared_watchlist_items()
        self.respond_json(200, watchlist_response_payload(items))

    def handle_watchlist_add(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self.respond_json(400, {"error": "Invalid JSON"})
            return

        ticker = normalize_ticker_input(payload.get("ticker"))
        market_type = infer_market_type(ticker, payload.get("market_type"))
        if not ticker:
            self.respond_json(400, {"error": "Ticker is required"})
            return

        items = add_shared_ticker(ticker, market_type)
        self.respond_json(200, watchlist_response_payload(items))

    def handle_watchlist_delete(self, parsed):
        params = parse_qs(parsed.query)
        path_prefix = "/api/watchlist/"
        path_ticker = unquote(parsed.path[len(path_prefix):]) if parsed.path.startswith(path_prefix) else ""
        ticker = normalize_ticker_input(path_ticker or params.get("ticker", [""])[0])
        market_type = params.get("market_type", [None])[0]
        if not ticker:
            self.respond_json(400, {"error": "Ticker is required"})
            return

        items = remove_shared_ticker(ticker, market_type)
        self.respond_json(200, watchlist_response_payload(items))


app = Flask(__name__, static_folder=ROOT, static_url_path="")
app.json.ensure_ascii = False
if CORS:
    CORS(app)


@app.after_request
def add_no_store_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/api/market-data")
def api_market_data():
    try:
        tickers = [
            normalize_ticker_input(ticker)
            for ticker in request.args.get("tickers", "").split(",")
            if normalize_ticker_input(ticker)
        ]
        force = str(request.args.get("force", "")).strip().lower() in {"1", "true", "yes", "y"}
        auto_refresh = str(request.args.get("auto_refresh", "")).strip().lower() in {"1", "true", "yes", "y"}
        full_refresh = str(request.args.get("full_refresh", "")).strip().lower() in {"1", "true", "yes", "y"}
        cache_only_param = str(request.args.get("cache_only", "")).strip().lower()
        cache_only = cache_only_param not in {"0", "false", "no", "n"}
        if full_refresh:
            force = True
        if force:
            cache_only = False
        if auto_refresh:
            cache_only = False
        if full_refresh:
            # Do not return after the first provider-safe pair. Complete all
            # requested batches under the shared refresh lock, then read the
            # exact resulting cache snapshot without triggering a second live
            # request. This makes a newly added ticker participate in the same
            # full refresh as every existing card.
            with FULL_REFRESH_RUN_LOCK:
                full_summary = _refresh_market_cache_for_tickers(tickers, reason="api_full_refresh")
                payload = build_market_data_payload(
                    tickers,
                    force=False,
                    auto_refresh=False,
                    cache_only=True,
                    refresh_market_context=False,
                )
            status = payload.setdefault("refresh_status", {})
            status.update({
                "is_full_watchlist_refresh": True,
                "full_refresh_completed": bool(full_summary.get("completed")),
                "full_refresh_batch_count": int(full_summary.get("batch_count") or 0),
                "full_refresh_requested_tickers": full_summary.get("requested_tickers") or [],
                "full_refresh_success_count": int(full_summary.get("success_count") or 0),
                "full_refresh_failed_count": int(full_summary.get("failed_count") or 0),
                "full_refresh_cache_fallback_count": int(full_summary.get("cache_fallback_count") or 0),
                "full_refresh_error": full_summary.get("error"),
            })
        else:
            payload = build_market_data_payload(
                tickers,
                force=force,
                auto_refresh=auto_refresh,
                cache_only=cache_only,
            )
        status_code = 200 if payload.get("success") or payload.get("items") else 503
        return jsonify(payload), status_code
    except Exception as exc:
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(exc),
            "items": [],
            "data": {},
            "quotes": {},
            "failed": [],
            "refresh_status": {
                "refresh_interval_minutes": 60,
                "total_tickers": 0,
                "success_count": 0,
                "failed_count": 0,
                "used_cache_count": 0,
                "unavailable_count": 0,
                "is_partial": False,
                "is_loading_live_data": False,
                "has_stale_quotes": False,
                "stale_quote_count": 0,
            },
        }), 500


@app.route("/api/debug/quote/<path:ticker>")
def api_debug_quote(ticker):
    normalized = normalize_ticker_input(ticker)
    if not normalized:
        return jsonify({"success": False, "error": "Ticker is required"}), 400
    try:
        cached = read_market_cache(normalized)
        quote, failure, _used_cache, attempts = fetch_market_quote_for_ticker(normalized, force=True)
        return jsonify({
            "success": quote.get("price") is not None,
            "ticker": normalized,
            "market_type": infer_market_type(normalized),
            "resolved_symbol": resolve_market_symbol(normalized),
            "quote_source_attempts": attempts,
            "cache_path": market_cache_path(normalized, "quotes"),
            "cache_exists": bool(cached),
            "cache_age_seconds": cached.get("cache_age_seconds") if isinstance(cached, dict) else None,
            "final_price": quote.get("price"),
            "quote_status": quote.get("quote_status"),
            "quote_source": quote.get("quote_source"),
            "error": failure.get("error") if failure else quote.get("error"),
        })
    except Exception as exc:
        traceback.print_exc()
        return jsonify({
            "success": False,
            "ticker": normalized,
            "market_type": infer_market_type(normalized),
            "quote_source_attempts": [],
            "final_price": None,
            "quote_status": "unavailable",
            "error": str(exc),
        }), 500

@app.route("/api/debug/bulk-status")
def api_debug_bulk_status():
    try:
        tickers = [
            normalize_ticker_input(ticker)
            for ticker in request.args.get("tickers", "").split(",")
            if normalize_ticker_input(ticker)
        ][:MARKET_DATA_MAX_TICKERS]
        items = []
        for ticker in tickers:
            quote_cache = read_market_cache(ticker)
            quote_payload = (quote_cache.get("quote") if isinstance(quote_cache, dict) else None) or {}
            quote_updated_at, quote_age = cache_updated_at_and_age(quote_cache)

            items.append({
                "ticker": ticker,
                "market_type": infer_market_type(ticker),
                "quote": {
                    "cache_exists": bool(quote_cache),
                    "cache_valid": bool(quote_cache and quote_payload.get("price") is not None and is_market_cache_fresh(quote_cache)),
                    "price": quote_payload.get("price"),
                    "status": quote_payload.get("quote_status") or ("available" if quote_payload.get("price") is not None else "unavailable"),
                    "source": quote_payload.get("quote_source"),
                    "updated_at": quote_updated_at,
                    "age_minutes": round(quote_age / 60, 2) if quote_age is not None else None,
                    "last_successful_refresh": quote_payload.get("last_successful_update") or quote_payload.get("updatedAt") or quote_updated_at,
                },
            })

        market_cached = read_market_context_cache()
        market_payload = (market_cached or {}).get("payload")
        flat_market = flatten_market_context_payload(market_payload, {
            "status": market_context_payload_status(market_payload),
            "cache_used": bool(market_cached),
            "cache_updated_at": (market_cached or {}).get("updated_at"),
        })
        market_fields_available = [
            field for field, value in {
                "vix": (flat_market.get("vix") or {}).get("value"),
                "ten_year_yield": (flat_market.get("ten_year_yield") or {}).get("value"),
                "spy_trend": (flat_market.get("spy_trend") or {}).get("value"),
                "qqq_trend": (flat_market.get("qqq_trend") or {}).get("value"),
                "fear_greed": (flat_market.get("fear_greed") or {}).get("value"),
            }.items()
            if value is not None
        ]
        return jsonify({
            "success": True,
            "tickers": tickers,
            "items": items,
            "market_context": {
                "cache_exists": bool(market_cached),
                "cache_valid": market_context_payload_valid(market_payload),
                "status": market_context_payload_status(market_payload),
                "fields_available": market_fields_available,
                "updated_at": (market_cached or {}).get("updated_at"),
            },
        })
    except Exception as exc:
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(exc),
            "tickers": [],
            "items": [],
            "market_context": {},
        }), 500

@app.route("/api/debug/market-context")
def api_debug_market_context():
    try:
        cached = read_market_context_cache()
        payload, meta = get_market_context_cached_snapshot(force=False, allow_live=True)
        market_context = (payload or {}).get("market_context") or {}
        equity_trend = market_context.get("equity_trend") or {}
        missing_fields = []
        if (market_context.get("vix") or {}).get("value") is None:
            missing_fields.append("vix")
        if (market_context.get("fear_greed") or {}).get("value") is None:
            missing_fields.append("fear_greed")
        if (market_context.get("ten_year_yield") or {}).get("value") is None:
            missing_fields.append("ten_year_yield")
        if (equity_trend.get("spy") or {}).get("value") is None:
            missing_fields.append("spy_trend")
        if (equity_trend.get("qqq") or {}).get("value") is None:
            missing_fields.append("qqq_trend")
        field_cache_attempt = {
            "source": "market_context_cache",
            "success": bool(cached),
            "valid": bool(cached and market_context_payload_valid((cached or {}).get("payload"))),
            "updated_at": cached.get("updated_at") if isinstance(cached, dict) else None,
        }
        context_has_any_field = market_context_payload_valid(payload)
        return jsonify({
            "success": context_has_any_field,
            "vix": market_context.get("vix"),
            "fear_greed": market_context.get("fear_greed"),
            "ten_year_yield": market_context.get("ten_year_yield"),
            "spy_trend": equity_trend.get("spy"),
            "qqq_trend": equity_trend.get("qqq"),
            "source_attempts": meta.get("source_attempts"),
            "vix_attempts": [field_cache_attempt, {"source": "yfinance_^VIX_or_fred", "success": (market_context.get("vix") or {}).get("value") is not None}],
            "ten_year_attempts": [field_cache_attempt, {"source": "yfinance_^TNX_or_fred", "success": (market_context.get("ten_year_yield") or {}).get("value") is not None}],
            "spy_attempts": [field_cache_attempt, {"source": "yfinance_or_yahoo_chart_SPY", "success": (equity_trend.get("spy") or {}).get("value") is not None}],
            "qqq_attempts": [field_cache_attempt, {"source": "yfinance_or_yahoo_chart_QQQ", "success": (equity_trend.get("qqq") or {}).get("value") is not None}],
            "fear_greed_attempts": [field_cache_attempt, {"source": "fear_greed_live_or_cache", "success": (market_context.get("fear_greed") or {}).get("value") is not None}],
            "cache_used": meta.get("cache_used"),
            "cache_layer": meta.get("cache_layer"),
            "cache_exists": bool(cached),
            "cache_valid": bool(cached and market_context_payload_valid((cached or {}).get("payload"))),
            "final_status": market_context_payload_status(payload),
            "missing_fields": missing_fields,
            "error": None if meta.get("status") != "unavailable" else "Market context unavailable",
        })
    except Exception as exc:
        traceback.print_exc()
        return jsonify({
            "success": False,
            "vix": None,
            "fear_greed": None,
            "ten_year_yield": None,
            "spy_trend": None,
            "qqq_trend": None,
            "source_attempts": [],
            "cache_used": False,
            "missing_fields": [],
            "error": str(exc),
        }), 500


@app.route("/api/symbol-search")
def api_symbol_search():
    query = normalize_search_query(request.args.get("q", ""))
    try:
        limit = max(1, min(int(request.args.get("limit", "10")), 20))
    except ValueError:
        limit = 10
    if not query:
        return jsonify({"query": "", "candidates": []})
    return jsonify({
        "query": query,
        "candidates": search_symbol_candidates(query, limit=limit),
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })


def build_decision_v1_payload(tickers):
    """Serialize cached quotes through the production Decision Engine.

    Deliberately reads the CACHE and never forces a live refresh: this serves
    on-demand HTTP requests, so a per-request full refresh would be both slow
    and a way to burn provider quota from outside. The same one-shot Node
    child-process pattern as the EOD recorder is reused, because the Decision
    Engine is JavaScript and must not be reimplemented in Python.
    """
    node = eod_history_node_executable()
    if not node:
        raise RuntimeError("Node.js is required because the production Decision Engine is JavaScript. Set EOD_DECISION_NODE_PATH if node is not on PATH.")
    if not os.path.isfile(DECISION_V1_NODE_RUNNER):
        raise RuntimeError(f"decision.v1 runner is missing: {DECISION_V1_NODE_RUNNER}")

    market = get_lightweight_market_context(force=False, allow_live=False) or {}
    items = []
    missing = []
    for ticker in tickers:
        quote = get_cached_quote(ticker)
        if quote:
            items.append({"ticker": ticker, "analysis": quote})
        else:
            missing.append(ticker)

    temp_directory = tempfile.mkdtemp(prefix="decision-v1-")
    try:
        input_path = os.path.join(temp_directory, "input.json")
        output_path = os.path.join(temp_directory, "decision-v1.json")
        with open(input_path, "w", encoding="utf-8") as handle:
            json.dump({"marketContext": market, "items": items}, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        completed = subprocess.run(
            [node, DECISION_V1_NODE_RUNNER, input_path, output_path],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            timeout=DECISION_V1_NODE_TIMEOUT_SECONDS, check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown Node error").strip()
            raise RuntimeError(f"decision.v1 serialization failed: {detail[:1200]}")
        with open(output_path, "r", encoding="utf-8") as handle:
            result = json.load(handle)
    finally:
        shutil.rmtree(temp_directory, ignore_errors=True)

    result["missing"] = missing
    return result


@app.route("/api/decision/<path:ticker>")
def api_decision_v1(ticker):
    """One ticker's decision.v1 payload: short, mid and long, independently.

    Returns 404 only when the ticker has no cached quote at all. A ticker the
    engine could not decide on comes back 200 with its reason in `errors`, so a
    consumer can tell "we have no data" from "the engine declined".
    """
    symbol = str(ticker or "").strip().upper()
    if not symbol:
        return jsonify({"success": False, "error": "ticker is required"}), 400
    try:
        result = build_decision_v1_payload([symbol])
    except Exception as error:
        return jsonify({"success": False, "error": str(error)[:600]}), 503

    decision = (result.get("decisions") or {}).get(symbol)
    if decision is None:
        reason = (result.get("errors") or {}).get(symbol)
        if symbol in (result.get("missing") or []):
            return jsonify({"success": False, "error": f"no cached quote for {symbol}"}), 404
        return jsonify({"success": False, "error": reason or f"no decision for {symbol}"}), 200
    return jsonify(decision)


@app.route("/api/decisions")
def api_decision_v1_batch():
    """Several tickers at once: /api/decisions?tickers=NVDA,META,MSFT"""
    raw = request.args.get("tickers") or ""
    symbols = [part.strip().upper() for part in raw.split(",") if part.strip()]
    if not symbols:
        return jsonify({"success": False, "error": "tickers is required"}), 400
    if len(symbols) > 25:
        return jsonify({"success": False, "error": "at most 25 tickers per request"}), 400
    try:
        return jsonify(build_decision_v1_payload(symbols))
    except Exception as error:
        return jsonify({"success": False, "error": str(error)[:600]}), 503


@app.route("/api/health")
def api_health():
    db_dir = os.path.dirname(WATCHLIST_DB_PATH)
    market_context_cache_exists = read_module_cache("market_context", "snapshot") is not None
    with BACKGROUND_REFRESH_LOCK:
        background_refresh = dict(BACKGROUND_REFRESH_STATE)
    return jsonify({
        "success": True,
        "status": "ok",
        "watchlist_db_path": WATCHLIST_DB_PATH,
        "watchlist_db_exists": os.path.exists(WATCHLIST_DB_PATH),
        "watchlist_db_dir": db_dir,
        "watchlist_db_dir_exists": os.path.isdir(db_dir) if db_dir else True,
        "market_cache_dir": MARKET_CACHE_DIR,
        "market_cache_dir_exists": os.path.isdir(MARKET_CACHE_DIR) if MARKET_CACHE_DIR else False,
        "quotes_cache_count": count_cache_files("quotes"),
        "options_cache_count": count_cache_files("options"),
        "market_context_cache_exists": market_context_cache_exists,
        "background_market_refresh": background_refresh,
        "cwd": os.getcwd(),
        "python_version": sys.version,
        "render_service": bool(os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_ID") or os.environ.get("RENDER_EXTERNAL_URL")),
    })


@app.route("/api/watchlist", methods=["GET"])
def api_watchlist_get():
    try:
        with get_watchlist_conn() as conn:
            rows = conn.execute(
                """
                SELECT id, ticker, market_type, created_at
                FROM watchlist
                ORDER BY datetime(created_at) ASC, id ASC
                """
            ).fetchall()
        items = watchlist_rows_to_items(rows)
        return jsonify(watchlist_response_payload(items))
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(exc), "items": [], "watchlist": []}), 500


@app.route("/api/watchlist", methods=["POST"])
def api_watchlist_post():
    try:
        payload = request.get_json(silent=True) or {}
        ticker = normalize_ticker_input(payload.get("ticker"))
        if not ticker:
            return jsonify({"success": False, "error": "Ticker is required", "items": [], "watchlist": []}), 400
        market_type = infer_market_type(ticker, payload.get("market_type"))
        with get_watchlist_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO watchlist (ticker, market_type) VALUES (?, ?)",
                (ticker, market_type),
            )
            conn.commit()
            rows = conn.execute(
                """
                SELECT id, ticker, market_type, created_at
                FROM watchlist
                ORDER BY datetime(created_at) ASC, id ASC
                """
            ).fetchall()
        return jsonify(watchlist_response_payload(watchlist_rows_to_items(rows)))
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(exc), "items": [], "watchlist": []}), 500


@app.route("/api/watchlist", methods=["DELETE"])
@app.route("/api/watchlist/<path:ticker>", methods=["DELETE"])
def api_watchlist_delete(ticker=None):
    try:
        normalized = normalize_ticker_input(ticker or request.args.get("ticker", ""))
        if not normalized:
            return jsonify({"success": False, "error": "Ticker is required", "items": [], "watchlist": []}), 400
        market_type = request.args.get("market_type")
        with get_watchlist_conn() as conn:
            if market_type:
                conn.execute(
                    "DELETE FROM watchlist WHERE ticker = ? AND market_type = ?",
                    (normalized, infer_market_type(normalized, market_type)),
                )
            else:
                conn.execute("DELETE FROM watchlist WHERE ticker = ?", (normalized,))
            conn.commit()
            rows = conn.execute(
                """
                SELECT id, ticker, market_type, created_at
                FROM watchlist
                ORDER BY datetime(created_at) ASC, id ASC
                """
            ).fetchall()
        return jsonify(watchlist_response_payload(watchlist_rows_to_items(rows)))
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(exc), "items": [], "watchlist": []}), 500


@app.route("/")
def serve_index():
    return send_from_directory(ROOT, "index.html")


@app.route("/<path:filename>")
def serve_static_file(filename):
    if filename.startswith("api/"):
        return jsonify({"success": False, "error": "Not found"}), 404
    return send_from_directory(ROOT, filename)


start_background_market_refresh_scheduler()
start_eod_history_scheduler()


def main():
    os.chdir(ROOT)
    display_host = "localhost" if HOST == "127.0.0.1" else HOST
    print(f"Serving dashboard on http://{display_host}:{PORT}")
    print(f"API endpoint: http://{display_host}:{PORT}/api/market-data?tickers=AAPL,MSFT,QQQ,SPMO")
    app.run(host=HOST, port=PORT, debug=False)


if __name__ == "__main__":
    main()
