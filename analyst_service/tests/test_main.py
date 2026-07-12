from fastapi.testclient import TestClient

from analyst_service.api import main


def test_lifespan_validates_service_config(monkeypatch) -> None:
    calls: list[None] = []

    monkeypatch.setattr(main, "load_service_config", lambda: calls.append(None))

    with TestClient(main.app):
        pass

    assert calls == [None]
