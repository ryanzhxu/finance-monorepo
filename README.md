# finance-monorepo

Phase 1 implements the analyst service: shared models/config/data-quality helpers, deterministic indicators and entry levels, weighted signal aggregation, optional narrative isolation, and append-only recommendation logging.

Phase 2 implements the screener core: universe resolution, filters, bulk fundamentals, deterministic opportunity scoring, market regime, and optional analyst entry attachment.

Phase 3 implements trending and buyability: optional mention sources, deterministic acceleration and trend classification, graceful degradation when sources or analyst are unavailable, and trend-aware opportunity boosting.

Future services are placeholders until their phases begin.

## Run

```bash
uv sync
uv run uvicorn analyst_service.api.main:app --port 8001
uv run uvicorn screener_service.api.main:app --port 8002
```

Health check:

```bash
curl -sS http://127.0.0.1:8001/health
```

Run targeted tests:

```bash
uv run pytest
```

## Postman

Generate OpenAPI specs and Postman collections without starting either service:

```bash
make postman
```

This regenerates:

- `openapi/analyst.json`
- `openapi/screener.json`
- `postman/analyst.postman_collection.json`
- `postman/screener.postman_collection.json`
- `postman/local.postman_environment.json`

If you have a Postman API key, push or update the collections and environment in your Postman workspace:

```bash
export POSTMAN_API_KEY='pmak-...'
make postman-push
```

Set `POSTMAN_WORKSPACE_ID` as well if you want a workspace other than `My Workspace`.

## Phase Boundary

Implemented:

- `shared/`
- `analyst_service/`
- `screener_service/`
- `backtesting/store.py`

Not implemented yet:

- dashboard logic
- execution-engine logic
- backtesting evaluation
