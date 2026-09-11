"""Small, short-lived SQLite helpers for offline EOD Decision History.

The dashboard never imports this module on a request path.  It is used only by
the server-side EOD scheduler and the explicit export utility.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable


HISTORY_DIRECTORY = Path(__file__).resolve().parent
SCHEMA_PATH = HISTORY_DIRECTORY / "历史记录建表.sql"
RENDER_PERSISTENT_DISK = Path("/var/data")


def resolve_db_path(path: str | os.PathLike[str] | None = None) -> Path:
    """Prefer an explicit path, then Render's configured persistent disk."""
    configured = path or os.environ.get("DECISION_HISTORY_DB_PATH")
    if configured:
        return Path(configured).expanduser()
    if RENDER_PERSISTENT_DISK.is_dir() and os.access(RENDER_PERSISTENT_DISK, os.W_OK):
        return RENDER_PERSISTENT_DISK / "历史记录.sqlite"
    return HISTORY_DIRECTORY / "历史记录.sqlite"


def _connect(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    db_path = resolve_db_path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # One Render worker performs brief, single-writer transactions. WAL keeps
    # this history write isolated from normal dashboard runtime work.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def initialize(path: str | os.PathLike[str] | None = None) -> Path:
    db_path = resolve_db_path(path)
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = _connect(db_path)
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()
    return db_path


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _database_storage_bytes(db_path: Path) -> int:
    # WAL sidecars are part of the persistent SQLite footprint until a later
    # checkpoint, so include them in the operator-facing size log.
    return sum(candidate.stat().st_size for candidate in (
        db_path,
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
    ) if candidate.exists())


DECISION_COLUMNS = (
    "market_date", "recorded_at_et", "ticker", "asset_type", "horizon", "data_status",
    "action", "confidence", "price_state", "current_price", "opportunity_low", "opportunity_high",
    "reduce_low", "reduce_high", "invalidation", "landscape_quality", "direction", "confirmation",
    "risk", "exhaustion", "market_regime", "market_context_json", "technical_features_json",
    "supporting_reasons_json", "limiting_reasons_json", "primary_classification", "lifecycle",
    "company_traits_json", "applied_profile_modifiers_json", "leveraged", "etf_direction", "underlying",
    "etf_modifiers_json", "material_change_json",
)


def _row_values(record: dict[str, Any]) -> tuple[Any, ...]:
    numeric = {
        "confidence", "current_price", "opportunity_low", "opportunity_high", "reduce_low", "reduce_high",
        "invalidation", "landscape_quality", "direction", "confirmation", "risk", "exhaustion",
    }
    json_fields = {
        "market_context_json": "market_context",
        "technical_features_json": "technical_features",
        "supporting_reasons_json": "supporting_reasons",
        "limiting_reasons_json": "limiting_reasons",
        "company_traits_json": "company_traits",
        "applied_profile_modifiers_json": "applied_profile_modifiers",
        "etf_modifiers_json": "etf_modifiers",
        "material_change_json": "material_change",
    }
    values: list[Any] = []
    for column in DECISION_COLUMNS:
        if column in numeric:
            values.append(_number(record.get(column)))
        elif column in json_fields:
            values.append(_json(record.get(json_fields[column])))
        elif column == "leveraged":
            value = record.get(column)
            values.append(None if value is None else int(bool(value)))
        else:
            values.append(record.get(column))
    return tuple(values)


_ASSIGNMENTS = ", ".join(f"{column}=excluded.{column}" for column in DECISION_COLUMNS if column not in {"market_date", "ticker", "horizon"})
_PLACEHOLDERS = ", ".join("?" for _ in DECISION_COLUMNS)
_UPSERT_SQL = (
    f"INSERT INTO decision_history ({', '.join(DECISION_COLUMNS)}) VALUES ({_PLACEHOLDERS}) "
    f"ON CONFLICT(market_date, ticker, horizon) DO UPDATE SET {_ASSIGNMENTS}"
)


def mark_run_started(market_date: str, started_at_et: str, path: str | os.PathLike[str] | None = None) -> None:
    initialize(path)
    conn = _connect(path)
    try:
        conn.execute(
            """
            INSERT INTO eod_runs (market_date, started_at_et, status)
            VALUES (?, ?, 'running')
            ON CONFLICT(market_date) DO UPDATE SET
              started_at_et=excluded.started_at_et,
              status=CASE WHEN eod_runs.status='success' THEN 'success' ELSE 'running' END,
              completed_at_et=CASE WHEN eod_runs.status='success' THEN eod_runs.completed_at_et ELSE NULL END,
              error_summary=CASE WHEN eod_runs.status='success' THEN eod_runs.error_summary ELSE NULL END
            """,
            (market_date, started_at_et),
        )
        conn.commit()
    finally:
        conn.close()


def mark_run_terminal(
    market_date: str,
    started_at_et: str,
    completed_at_et: str,
    status: str,
    error_summary: str | None = None,
    path: str | os.PathLike[str] | None = None,
) -> None:
    if status not in {"skipped", "failed"}:
        raise ValueError("terminal status must be skipped or failed")
    initialize(path)
    conn = _connect(path)
    try:
        existing = conn.execute("SELECT status FROM eod_runs WHERE market_date=?", (market_date,)).fetchone()
        # A retry after a successful same-day write may fail, but it must never
        # erase the successful audit record or mark the date as failed.
        if existing and existing["status"] == "success":
            return
        conn.execute(
            """
            INSERT INTO eod_runs (market_date, started_at_et, completed_at_et, status, error_summary)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(market_date) DO UPDATE SET
              started_at_et=excluded.started_at_et,
              completed_at_et=excluded.completed_at_et,
              status=excluded.status,
              error_summary=excluded.error_summary
            """,
            (market_date, started_at_et, completed_at_et, status, error_summary),
        )
        conn.commit()
    finally:
        conn.close()


def write_snapshot(
    market_date: str,
    started_at_et: str,
    completed_at_et: str,
    records: Iterable[dict[str, Any]],
    path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Atomically UPSERT every ticker/horizon row and mark this run successful."""
    initialize(path)
    db_path = resolve_db_path(path)
    prepared = list(records)
    rows = [_row_values(record) for record in prepared]
    tickers = {record.get("ticker") for record in prepared if record.get("ticker")}
    unavailable_count = sum(1 for record in prepared if record.get("data_status") == "unavailable")
    conn = _connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany(_UPSERT_SQL, rows)
        conn.execute(
            """
            INSERT INTO eod_runs (
              market_date, started_at_et, completed_at_et, status,
              ticker_count, row_count, unavailable_count, error_summary
            ) VALUES (?, ?, ?, 'success', ?, ?, ?, NULL)
            ON CONFLICT(market_date) DO UPDATE SET
              started_at_et=excluded.started_at_et,
              completed_at_et=excluded.completed_at_et,
              status='success', ticker_count=excluded.ticker_count,
              row_count=excluded.row_count, unavailable_count=excluded.unavailable_count,
              error_summary=NULL
            """,
            (market_date, started_at_et, completed_at_et, len(tickers), len(rows), unavailable_count),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    size_mb = round(_database_storage_bytes(db_path) / (1024 * 1024), 3)
    try:
        conn = _connect(db_path)
        try:
            conn.execute("UPDATE eod_runs SET database_size_mb=? WHERE market_date=?", (size_mb, market_date))
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        # The decision rows and success status have already committed. A
        # nonessential size-log update must not misreport that atomic success.
        pass
    return {"ticker_count": len(tickers), "row_count": len(rows), "unavailable_count": unavailable_count, "database_size_mb": size_mb}


def successful_run_exists(market_date: str, path: str | os.PathLike[str] | None = None) -> bool:
    db_path = resolve_db_path(path)
    if not db_path.exists():
        return False
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT 1 FROM eod_runs WHERE market_date=? AND status='success'", (market_date,)).fetchone()
        return row is not None
    finally:
        conn.close()


def database_size_mb(path: str | os.PathLike[str] | None = None) -> float:
    db_path = resolve_db_path(path)
    return round(_database_storage_bytes(db_path) / (1024 * 1024), 3)


def export_rows(
    path: str | os.PathLike[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    """Offline/export-only read path. Never use in normal Dashboard runtime."""
    db_path = resolve_db_path(path)
    if not db_path.exists():
        return []
    clauses: list[str] = []
    values: list[str] = []
    if date_from:
        clauses.append("market_date >= ?")
        values.append(date_from)
    if date_to:
        clauses.append("market_date <= ?")
        values.append(date_to)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM decision_history" + where + " ORDER BY market_date, ticker, horizon",
            values,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
