# finance-monorepo

Market opportunity monorepo with FastAPI analyst/screener service code, a Cloudflare Worker API, shared contracts/utilities, and a deployed React/Vite frontend in `web_ui/`.

## Services

- `analyst_service/` single-symbol analysis, entry/confluence, provider health, and ticker search
- `screener_service/` undervalued/opportunity/trending screens, watchlist/custom screens, regime, and screener health
- `cloudflare-api/` production Worker API and shared-watchlist endpoints
- `shared/` cross-service models, enums, freshness/config helpers
- `web_ui/` production frontend for Analyze, Screener, Health, and Watchlist views
- `backtesting/store.py` append-only logging helpers

`execution_engine/` and `portfolio_dashboard/` are still placeholders.

## Local Run

```bash
uv sync
uv run uvicorn analyst_service.api.main:app --port 8001
uv run uvicorn screener_service.api.main:app --port 8002
cd web_ui && npm install && npm run dev
```

Health endpoints:

```bash
curl -sS http://127.0.0.1:8001/health
curl -sS http://127.0.0.1:8002/screen/health
```

`web_ui` reads:

- `VITE_ANALYST_URL` with fallback `http://localhost:8001`
- `VITE_SCREENER_URL` with fallback `http://localhost:8002`

## Verification

Backend tests:

```bash
uv run pytest
```

Frontend build:

```bash
cd web_ui && npm run build
```

Frontend lint:

```bash
cd web_ui && npm run lint
```

At the time of the latest guidance refresh, the build passed and lint failed on `react-hooks/set-state-in-effect` in `web_ui/src/views/Analyze.tsx`.

## API Artifacts

Dump OpenAPI directly from the FastAPI apps:

```bash
uv run python tools/dump_openapi.py
```

Generate Postman collections and environments:

```bash
make postman
```

This writes:

- `openapi/analyst.json`
- `openapi/screener.json`
- `postman/analyst.postman_collection.json`
- `postman/screener.postman_collection.json`
- `postman/local.postman_environment.json`

`make postman` shells out to `npx -y openapi-to-postmanv2`, so it depends on npm/network access. Do not hand-edit `openapi/` or `postman/`.

If `POSTMAN_API_KEY` is set, you can sync the generated collections and environment:

```bash
make postman-push
```

Set `POSTMAN_WORKSPACE_ID` as well if you want a workspace other than `My Workspace`.

## Deployment

`render.yaml` is the deploy source of truth for:

- `finance-cache`
- `finance-web-ui`

`cloudflare-api/wrangler.toml` is the deploy source of truth for `finance-api`.
