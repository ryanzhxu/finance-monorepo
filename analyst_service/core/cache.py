from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

try:
    import redis as redis_lib
except ImportError:  # pragma: no cover - exercised when dependency is absent
    redis_lib = None


_redis_client: redis_lib.Redis | None = None if redis_lib is not None else None
_FILE_CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "data"


def _running_under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ


def _get_redis() -> redis_lib.Redis | None:
    global _redis_client
    if redis_lib is None:
        return None
    if _redis_client is not None:
        return _redis_client
    url = os.getenv("REDIS_URL")
    if not url:
        return None
    try:
        client = redis_lib.from_url(
            url,
            decode_responses=True,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
        )
        client.ping()
        _redis_client = client
        return client
    except Exception:
        return None


def backend_name() -> str:
    return "redis" if _get_redis() is not None else "file"


def redis_status() -> str:
    if not os.getenv("REDIS_URL"):
        return "not_configured"
    return "connected" if _get_redis() is not None else "unreachable"


def _cache_path(key: str) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return _FILE_CACHE_DIR / f"{digest}.json"


def get(key: str) -> str | None:
    if _running_under_pytest():
        return None

    client = _get_redis()
    if client is not None:
        try:
            value = client.get(key)
            if value is not None:
                return value
        except Exception:
            pass

    path = _cache_path(key)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None

    expires_at = payload.get("expires_at")
    value = payload.get("value")
    if not isinstance(expires_at, (int, float)) or not isinstance(value, str):
        return None
    if expires_at <= time.time():
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    return value


def set(key: str, value: str, ttl: int) -> None:
    if _running_under_pytest():
        return

    client = _get_redis()
    if client is not None:
        try:
            client.setex(key, ttl, value)
        except Exception:
            pass

    try:
        _FILE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"expires_at": time.time() + max(ttl, 0), "value": value}
        _cache_path(key).write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass
