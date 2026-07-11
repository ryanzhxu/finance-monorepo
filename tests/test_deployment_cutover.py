from __future__ import annotations

from pathlib import Path
import tomllib

from analyst_service.api.main import app as analyst_app
from screener_service.api.main import app as screener_app
from scripts import warm_cache


REPO_ROOT = Path(__file__).resolve().parents[1]


def _cors_origins(app) -> list[str]:
    middleware = next(item for item in app.user_middleware if item.cls.__name__ == "CORSMiddleware")
    return list(middleware.kwargs["allow_origins"])


def test_cors_allowlists_keep_prod_ui_and_drop_dev_ui() -> None:
    for app in (analyst_app, screener_app):
        origins = _cors_origins(app)
        assert "http://localhost:5173" in origins
        assert "http://127.0.0.1:5173" in origins
        assert "https://finance-web-ui.onrender.com" in origins
        assert "https://finance-web-ui-dev.onrender.com" not in origins


def test_warm_cache_defaults_to_prod_worker() -> None:
    assert warm_cache.DEFAULT_ANALYST_BASE_URL == "https://finance-api.rxlab.workers.dev"


def test_render_yaml_uses_only_prod_facing_deploy_targets() -> None:
    content = (REPO_ROOT / "render.yaml").read_text()
    assert "finance-analyst" not in content
    assert "finance-screener" not in content
    assert "finance-web-ui-dev" not in content
    assert 'name: finance-web-ui' in content
    assert "branch: main" in content
    assert "VITE_API_BASE_URL" in content
    assert "https://finance-api.rxlab.workers.dev" in content


def test_wrangler_config_only_defines_prod_worker() -> None:
    content = (REPO_ROOT / "cloudflare-api/wrangler.toml").read_text()
    data = tomllib.loads(content)

    assert data["name"] == "finance-api"
    assert data["workers_dev"] is True
    assert "env" not in data
    assert "[env.dev]" not in content
    assert 'name = "finance-api-dev"' not in content


def test_web_ui_production_env_points_at_prod_worker() -> None:
    content = (REPO_ROOT / "web_ui/.env.production").read_text()

    assert "VITE_API_BASE_URL=https://finance-api.rxlab.workers.dev" in content
    assert "finance-api-dev" not in content
