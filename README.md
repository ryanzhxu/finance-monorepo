# finance-monorepo

Phase 1 implements the analyst service: shared models/config/data-quality helpers, deterministic indicators and entry levels, weighted signal aggregation, optional narrative isolation, and append-only recommendation logging.

Phase 2 implements the screener core: universe resolution, filters, bulk fundamentals, deterministic opportunity scoring, market regime, and optional analyst entry attachment. Trending and buyability remain future phases.

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
- trending and buyability logic
