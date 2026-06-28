from __future__ import annotations

from fastapi.testclient import TestClient

from screener_service.api.main import app
from screener_service.core.shared_spaces import COOKIE_NAME


def _configure_shared_space(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SHARED_WATCHLIST_SLUG", "drama")
    monkeypatch.setenv("SHARED_WATCHLIST_DISPLAY_NAME", "Drama")
    monkeypatch.setenv("SHARED_WATCHLIST_PASSCODE", "swordfish")
    monkeypatch.setenv("SHARED_WATCHLIST_SESSION_SECRET", "very-secret-for-tests")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'shared-space.db'}")


def test_shared_space_session_and_login_flow(monkeypatch, tmp_path) -> None:
    _configure_shared_space(monkeypatch, tmp_path)

    with TestClient(app) as client:
        session_response = client.get("/shared-spaces/drama/session")
        assert session_response.status_code == 200
        assert session_response.json() == {
            "authenticated": False,
            "slug": "drama",
            "display_name": "Drama",
        }

        unauthorized = client.get("/shared-spaces/drama/watchlist")
        assert unauthorized.status_code == 401

        wrong_passcode = client.post("/shared-spaces/drama/login", json={"passcode": "wrong"})
        assert wrong_passcode.status_code == 401

        login_response = client.post("/shared-spaces/drama/login", json={"passcode": "swordfish"})
        assert login_response.status_code == 200
        assert login_response.json() == {
            "authenticated": True,
            "slug": "drama",
            "display_name": "Drama",
        }
        assert COOKIE_NAME in client.cookies

        authenticated_session = client.get("/shared-spaces/drama/session")
        assert authenticated_session.status_code == 200
        assert authenticated_session.json()["authenticated"] is True


def test_shared_space_login_sets_secure_cookie_when_proxied_https(monkeypatch, tmp_path) -> None:
    _configure_shared_space(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/shared-spaces/drama/login",
            json={"passcode": "swordfish"},
            headers={"x-forwarded-proto": "https"},
        )

        assert response.status_code == 200
        set_cookie = response.headers["set-cookie"].lower()
        assert "samesite=none" in set_cookie
        assert "secure" in set_cookie
        assert "httponly" in set_cookie


def test_shared_watchlist_adds_dedupes_and_removes_symbols(monkeypatch, tmp_path) -> None:
    _configure_shared_space(monkeypatch, tmp_path)

    with TestClient(app) as client:
        login_response = client.post("/shared-spaces/drama/login", json={"passcode": "swordfish"})
        assert login_response.status_code == 200

        first_add = client.post("/shared-spaces/drama/watchlist", json={"symbol": "nvda"})
        assert first_add.status_code == 200
        assert first_add.json()["symbols"] == ["NVDA"]

        duplicate_add = client.post("/shared-spaces/drama/watchlist", json={"symbol": "NVDA"})
        assert duplicate_add.status_code == 200
        assert duplicate_add.json()["symbols"] == ["NVDA"]

        second_add = client.post("/shared-spaces/drama/watchlist", json={"symbol": "aapl"})
        assert second_add.status_code == 200
        assert second_add.json()["symbols"] == ["AAPL", "NVDA"]

        removed = client.delete("/shared-spaces/drama/watchlist/nvda")
        assert removed.status_code == 200
        assert removed.json()["symbols"] == ["AAPL"]


def test_shared_space_returns_404_for_unknown_slug(monkeypatch, tmp_path) -> None:
    _configure_shared_space(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.get("/shared-spaces/unknown/session")
        assert response.status_code == 404
