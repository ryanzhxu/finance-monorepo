# finance-monorepo

Two FastAPI services plus shared contracts: `analyst_service` does single-stock analysis, `screener_service` does discovery/ranking, `shared/` holds cross-service models and enums, and `backtesting/store.py` appends results. `execution_engine/` and `portfolio_dashboard/` are placeholders for now.

If docs conflict with code, trust the code first and note the mismatch.

## Source Of Truth

Read these first for most tasks:
- `README.md`
- `MARKET_OPPORTUNITY_SYSTEM_SPEC.md`
- `AGENTS_ANALYST.md`
- `pyproject.toml`
- `render.yaml`
- `shared/shared/models.py`
- `analyst_service/api/routers/analysis.py`
- `screener_service/api/routers/screen.py`

## Layout

- `shared/` shared models, enums, config loading, data-quality, market calendar
- `analyst_service/` single-stock API, deterministic indicators, entry logic, narration
- `screener_service/` universe, filters, scoring, trending, analyst attachment
- `backtesting/` append-only recommendation log
- `tools/` OpenAPI/Postman generation and sync scripts
- `openapi/` generated OpenAPI JSON
- `postman/` generated collections and environments
- `screener_service/cache/` runtime cache files

## Setup And Run

```bash
uv sync
uv run uvicorn analyst_service.api.main:app --port 8001
uv run uvicorn screener_service.api.main:app --port 8002
```

Health checks:

```bash
curl -sS http://127.0.0.1:8001/health
curl -sS http://127.0.0.1:8002/screen/health
```

Verification:

```bash
uv run pytest
make postman
```

`make postman-push` is for syncing to Postman when `POSTMAN_API_KEY` is set.
No lint/typecheck command is currently verified in the repo; verify before relying on one.

## Conventions

- Keep deterministic math in `core/`; keep LLM calls only in `analyst_service/core/narrator.py`.
- Keep all weights, thresholds, and rules in YAML under each service `config/`.
- Use `shared/` models instead of duplicating request/response schemas.
- Preserve the dependency chain: `screener_service -> analyst_service -> external providers`; analyst never calls screener, dashboard, or execution code.
- Load `.env` at the top of both FastAPI entrypoints before config is read.
- Prefer the smallest behavior change that solves the task.
- Do not refactor unrelated code or overwrite other local changes.

## Secrets And Config

- Never print, commit, or hardcode secrets.
- Use env vars only for credentials and host-specific settings.
- Do not edit generated OpenAPI/Postman files by hand.
- Do not hand-edit cache files, `backtesting/recommendations.jsonl`, `__pycache__/`, `.venv/`, or `*.egg-info/`.

## Testing Expectations

- Start with the narrowest useful test, then broaden only if risk warrants it.
- Re-run the affected service tests after code changes.
- If a router or response model changes, regenerate OpenAPI/Postman and re-check the diff.
- If startup or health changes, verify the matching `/health` endpoint.
- Report exact commands run and what was not verified.

## Review And Done

- For review requests, lead with bugs, regressions, risky assumptions, and missing verification.
- A task is done when the code change is in place, the relevant tests pass, and any affected generated artifacts are refreshed.
- Update this file when repo commands, boundaries, generated artifacts, or the recommended workflow change.

## Skills

Repo skills live in `skills/`:
- `finance-implementation-workflow` for normal code changes and feature work.
- `finance-test-debug-workflow` for failing tests, startup errors, and health-check debugging.
- `finance-api-contract-sync` when routers, request/response models, OpenAPI, or Postman artifacts change.
