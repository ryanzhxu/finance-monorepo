from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from shared.models import AnalyzeResponse


logger = logging.getLogger(__name__)

DEFAULT_STORE_PATH = Path(__file__).resolve().parents[1] / "cache" / "analysis.sqlite3"


@dataclass(frozen=True)
class PersistedAnalysis:
    id: int
    symbol: str
    generated_at: datetime
    horizon: str
    direction: str
    confidence: float
    weighted_score: float
    data_quality_score: int
    entry_assessment: str | None
    current_price: float | None
    payload: dict[str, object]


def analysis_store_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    configured = os.getenv("ANALYSIS_STORE_PATH", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_STORE_PATH


class AnalysisStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = analysis_store_path(path)

    def save(self, response: AnalyzeResponse) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            self._create_schema(connection)
            entry = response.entry
            connection.execute(
                """
                INSERT INTO analysis_records (
                    symbol, generated_at, horizon, direction, confidence, weighted_score,
                    data_quality_score, entry_assessment, current_price, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    response.symbol,
                    response.generated_at.isoformat(),
                    response.recommendation.horizon.value,
                    response.recommendation.direction.value,
                    response.recommendation.confidence,
                    response.recommendation.weighted_score,
                    response.data_quality_score,
                    entry.entry_assessment.value if entry is not None else None,
                    entry.current_price if entry is not None else None,
                    json.dumps(response.model_dump(mode="json"), sort_keys=True),
                ),
            )

    def list(
        self,
        *,
        symbol: str | None = None,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[PersistedAnalysis]:
        """Stored analyses, oldest first.

        Filtering happens in SQL, which the existing (symbol, generated_at)
        index already serves. `limit` keeps the MOST RECENT rows - a timeline
        truncated to its oldest entries would be useless - but the returned
        list is still oldest-first, so callers can reverse it themselves.
        """
        if not self.path.exists():
            return []
        clauses: list[str] = []
        params: list[object] = []
        if symbol:
            clauses.append("UPPER(symbol) = ?")
            params.append(symbol.strip().upper())
        if since is not None:
            clauses.append("generated_at >= ?")
            params.append(since.isoformat())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        # Take the newest `limit` rows, then restore ascending order.
        order = "DESC" if limit is not None else "ASC"
        tail = f"LIMIT {int(limit)}" if limit is not None else ""
        with self._connection() as connection:
            self._create_schema(connection)
            rows = connection.execute(
                f"""
                SELECT id, symbol, generated_at, horizon, direction, confidence, weighted_score,
                       data_quality_score, entry_assessment, current_price, payload_json
                FROM analysis_records
                {where}
                ORDER BY generated_at {order}, id {order}
                {tail}
                """,
                params,
            ).fetchall()
        if limit is not None:
            rows = list(reversed(rows))
        return [
            PersistedAnalysis(
                id=int(row["id"]),
                symbol=str(row["symbol"]),
                generated_at=datetime.fromisoformat(str(row["generated_at"])),
                horizon=str(row["horizon"]),
                direction=str(row["direction"]),
                confidence=float(row["confidence"]),
                weighted_score=float(row["weighted_score"]),
                data_quality_score=int(row["data_quality_score"]),
                entry_assessment=str(row["entry_assessment"]) if row["entry_assessment"] is not None else None,
                current_price=float(row["current_price"]) if row["current_price"] is not None else None,
                payload=json.loads(str(row["payload_json"])),
            )
            for row in rows
        ]

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=1.0)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_records (
                id INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                horizon TEXT NOT NULL,
                direction TEXT NOT NULL,
                confidence REAL NOT NULL,
                weighted_score REAL NOT NULL,
                data_quality_score INTEGER NOT NULL,
                entry_assessment TEXT,
                current_price REAL,
                payload_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_analysis_records_symbol_generated_at
            ON analysis_records(symbol, generated_at)
            """
        )


def persist_analysis(response: AnalyzeResponse, path: Path | None = None) -> bool:
    try:
        AnalysisStore(path).save(response)
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        logger.warning("Could not persist analysis for %s: %s", response.symbol, exc)
        return False
    return True


def load_persisted_analyses(
    path: Path | None = None,
    *,
    symbol: str | None = None,
    since: datetime | None = None,
    limit: int | None = None,
) -> list[PersistedAnalysis]:
    return AnalysisStore(path).list(symbol=symbol, since=since, limit=limit)
