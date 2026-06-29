from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import unquote, urlparse

try:
    import psycopg
except ImportError:  # pragma: no cover - exercised only in Postgres-backed environments
    psycopg = None


COOKIE_NAME = "shared_space_session"
DEFAULT_SESSION_MAX_AGE = 30 * 24 * 60 * 60


class SharedSpaceUnavailableError(RuntimeError):
    pass


class SharedSpaceNotFoundError(RuntimeError):
    pass


@dataclass(frozen=True)
class SharedSpaceSettings:
    slug: str
    display_name: str
    passcode: str
    session_secret: str
    database_url: str
    session_max_age: int = DEFAULT_SESSION_MAX_AGE

    @classmethod
    def from_env(cls) -> SharedSpaceSettings | None:
        slug = os.getenv("SHARED_WATCHLIST_SLUG", "").strip().lower()
        display_name = os.getenv("SHARED_WATCHLIST_DISPLAY_NAME", "").strip()
        passcode = os.getenv("SHARED_WATCHLIST_PASSCODE", "").strip()
        session_secret = os.getenv("SHARED_WATCHLIST_SESSION_SECRET", "").strip()
        database_url = os.getenv("DATABASE_URL", "").strip()
        if not all((slug, passcode, session_secret, database_url)):
            return None
        return cls(
            slug=slug,
            display_name=display_name or slug.title(),
            passcode=passcode,
            session_secret=session_secret,
            database_url=database_url,
        )


@dataclass(frozen=True)
class SharedSpace:
    id: int
    slug: str
    display_name: str
    passcode_hash: str


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_passcode(passcode: str, salt: bytes | None = None) -> str:
    chosen_salt = salt or secrets.token_bytes(16)
    derived = hashlib.scrypt(passcode.encode("utf-8"), salt=chosen_salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${_b64encode(chosen_salt)}${_b64encode(derived)}"


def verify_passcode(passcode: str, stored_hash: str) -> bool:
    try:
        algorithm, salt_value, digest_value = stored_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "scrypt":
        return False
    expected = hash_passcode(passcode, salt=_b64decode(salt_value))
    return hmac.compare_digest(expected, stored_hash)


def build_session_cookie(slug: str, secret: str, max_age: int = DEFAULT_SESSION_MAX_AGE) -> str:
    payload = {"slug": slug, "exp": int(datetime.now(tz=timezone.utc).timestamp()) + max_age}
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    return f"{_b64encode(payload_bytes)}.{_b64encode(signature)}"


def read_session_cookie(value: str | None, secret: str) -> str | None:
    if not value or "." not in value:
        return None
    payload_value, signature_value = value.split(".", 1)
    try:
        payload_bytes = _b64decode(payload_value)
        signature = _b64decode(signature_value)
    except Exception:
        return None
    expected_signature = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected_signature):
        return None
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except json.JSONDecodeError:
        return None
    if int(payload.get("exp", 0)) < int(datetime.now(tz=timezone.utc).timestamp()):
        return None
    slug = payload.get("slug")
    return slug if isinstance(slug, str) and slug else None


class SharedSpaceStore:
    def __init__(self, settings: SharedSpaceSettings) -> None:
        self.settings = settings
        self._parsed_url = urlparse(settings.database_url)
        self._dialect = self._parsed_url.scheme.split("+", 1)[0]
        if self._dialect not in {"postgres", "postgresql", "sqlite"}:
            raise SharedSpaceUnavailableError(f"unsupported DATABASE_URL scheme: {self._parsed_url.scheme}")

    def initialize(self) -> None:
        self._create_tables()
        self.upsert_space(
            slug=self.settings.slug,
            display_name=self.settings.display_name,
            passcode_hash=hash_passcode(self.settings.passcode),
        )

    def upsert_space(self, *, slug: str, display_name: str, passcode_hash: str) -> SharedSpace:
        normalized_slug = slug.strip().lower()
        if self._dialect == "sqlite":
            with self._sqlite_connection() as connection:
                connection.execute(
                    """
                    INSERT INTO shared_spaces (slug, display_name, passcode_hash)
                    VALUES (?, ?, ?)
                    ON CONFLICT(slug) DO UPDATE SET
                        display_name = excluded.display_name,
                        passcode_hash = excluded.passcode_hash
                    """,
                    (normalized_slug, display_name, passcode_hash),
                )
                row = connection.execute(
                    "SELECT id, slug, display_name, passcode_hash FROM shared_spaces WHERE slug = ?",
                    (normalized_slug,),
                ).fetchone()
                assert row is not None
                return SharedSpace(id=int(row["id"]), slug=row["slug"], display_name=row["display_name"], passcode_hash=row["passcode_hash"])

        with self._postgres_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO shared_spaces (slug, display_name, passcode_hash)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (slug) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        passcode_hash = EXCLUDED.passcode_hash
                    RETURNING id, slug, display_name, passcode_hash
                    """,
                    (normalized_slug, display_name, passcode_hash),
                )
                row = cursor.fetchone()
                assert row is not None
                connection.commit()
                return SharedSpace(id=int(row[0]), slug=row[1], display_name=row[2], passcode_hash=row[3])

    def get_space(self, slug: str) -> SharedSpace:
        normalized_slug = slug.strip().lower()
        if self._dialect == "sqlite":
            with self._sqlite_connection() as connection:
                row = connection.execute(
                    "SELECT id, slug, display_name, passcode_hash FROM shared_spaces WHERE slug = ?",
                    (normalized_slug,),
                ).fetchone()
                if row is None:
                    raise SharedSpaceNotFoundError(normalized_slug)
                return SharedSpace(id=int(row["id"]), slug=row["slug"], display_name=row["display_name"], passcode_hash=row["passcode_hash"])

        with self._postgres_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, slug, display_name, passcode_hash FROM shared_spaces WHERE slug = %s",
                    (normalized_slug,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise SharedSpaceNotFoundError(normalized_slug)
                return SharedSpace(id=int(row[0]), slug=row[1], display_name=row[2], passcode_hash=row[3])

    def list_symbols(self, slug: str) -> list[str]:
        space = self.get_space(slug)
        if self._dialect == "sqlite":
            with self._sqlite_connection() as connection:
                rows = connection.execute(
                    """
                    SELECT symbol
                    FROM shared_watchlist_symbols
                    WHERE space_id = ?
                    ORDER BY symbol ASC
                    """,
                    (space.id,),
                ).fetchall()
                return [row["symbol"] for row in rows]

        with self._postgres_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT symbol
                    FROM shared_watchlist_symbols
                    WHERE space_id = %s
                    ORDER BY symbol ASC
                    """,
                    (space.id,),
                )
                return [row[0] for row in cursor.fetchall()]

    def add_symbol(self, slug: str, symbol: str) -> list[str]:
        space = self.get_space(slug)
        normalized_symbol = symbol.strip().upper()
        if self._dialect == "sqlite":
            with self._sqlite_connection() as connection:
                connection.execute(
                    """
                    INSERT INTO shared_watchlist_symbols (space_id, symbol)
                    VALUES (?, ?)
                    ON CONFLICT(space_id, symbol) DO NOTHING
                    """,
                    (space.id, normalized_symbol),
                )
            return self.list_symbols(slug)

        with self._postgres_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO shared_watchlist_symbols (space_id, symbol)
                    VALUES (%s, %s)
                    ON CONFLICT (space_id, symbol) DO NOTHING
                    """,
                    (space.id, normalized_symbol),
                )
                connection.commit()
        return self.list_symbols(slug)

    def remove_symbol(self, slug: str, symbol: str) -> list[str]:
        space = self.get_space(slug)
        normalized_symbol = symbol.strip().upper()
        if self._dialect == "sqlite":
            with self._sqlite_connection() as connection:
                connection.execute(
                    "DELETE FROM shared_watchlist_symbols WHERE space_id = ? AND symbol = ?",
                    (space.id, normalized_symbol),
                )
            return self.list_symbols(slug)

        with self._postgres_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM shared_watchlist_symbols WHERE space_id = %s AND symbol = %s",
                    (space.id, normalized_symbol),
                )
                connection.commit()
        return self.list_symbols(slug)

    def _create_tables(self) -> None:
        if self._dialect == "sqlite":
            with self._sqlite_connection() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS shared_spaces (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        slug TEXT NOT NULL UNIQUE,
                        display_name TEXT NOT NULL,
                        passcode_hash TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS shared_watchlist_symbols (
                        space_id INTEGER NOT NULL,
                        symbol TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (space_id) REFERENCES shared_spaces(id) ON DELETE CASCADE,
                        UNIQUE(space_id, symbol)
                    );
                    """
                )
            return

        with self._postgres_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS shared_spaces (
                        id BIGSERIAL PRIMARY KEY,
                        slug TEXT NOT NULL UNIQUE,
                        display_name TEXT NOT NULL,
                        passcode_hash TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS shared_watchlist_symbols (
                        space_id BIGINT NOT NULL REFERENCES shared_spaces(id) ON DELETE CASCADE,
                        symbol TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        UNIQUE(space_id, symbol)
                    )
                    """
                )
                connection.commit()

    @contextmanager
    def _sqlite_connection(self) -> Iterator[sqlite3.Connection]:
        if self._dialect != "sqlite":
            raise SharedSpaceUnavailableError("sqlite connection requested for non-sqlite DATABASE_URL")
        if self._parsed_url.path in {"", "/"}:
            raise SharedSpaceUnavailableError("sqlite DATABASE_URL must include a database path")
        raw_path = unquote(self._parsed_url.path)
        if raw_path == "/:memory:":
            database_path = ":memory:"
        else:
            if self.settings.database_url.startswith("sqlite:////"):
                database_path = raw_path
            else:
                database_path = raw_path.lstrip("/")
        connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    @contextmanager
    def _postgres_connection(self) -> Iterator[object]:
        if self._dialect not in {"postgres", "postgresql"}:
            raise SharedSpaceUnavailableError("postgres connection requested for non-postgres DATABASE_URL")
        if psycopg is None:
            raise SharedSpaceUnavailableError("psycopg is required for Postgres-backed shared spaces")
        connection = psycopg.connect(self.settings.database_url)
        try:
            yield connection
        finally:
            connection.close()
