# finance-monorepo

FastAPI analyst and screener services plus a live React/Vite frontend in `web_ui/`. `execution_engine/` and `portfolio_dashboard/` are still placeholders. If docs conflict with code, trust the code and note the mismatch.

## Read First

- `README.md`
- `MARKET_OPPORTUNITY_SYSTEM_SPEC.md`
- `render.yaml`
- `pyproject.toml`
- `analyst_service/api/routers/analysis.py`
- `screener_service/api/routers/screen.py`
- `shared/shared/models.py`
- `web_ui/src/api/client.ts`
- `skills/`

`AGENTS_ANALYST.md` is historical analyst-service context only. Read it after the monorepo docs and current code, not before.

## Layout

- `analyst_service/` single-symbol analysis, `/entry`, `/entry/confluence`, `/health`, and `/search`
- `screener_service/` discovery, ranking, trending, regime, and `/screen/health`
- `shared/` shared enums, contracts, freshness helpers, and config loading
- `web_ui/` React 19 + Vite + Tailwind frontend used in production
- `backtesting/store.py` append-only logging helpers; `backtesting/recommendations.jsonl` is data, not hand-edited source
- `tools/` OpenAPI dump and Postman sync scripts
- `openapi/` and `postman/` generated artifacts
- `execution_engine/` and `portfolio_dashboard/` are placeholders with `.gitkeep`

## Commands

Setup:

```bash
uv sync
cd web_ui && npm install
```

Verified in this checkout:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync pytest -q
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync python tools/dump_openapi.py
cd web_ui && npm run build
```

Declared by repo config, but not fully re-verified here because this sandbox blocks local port binding:

```bash
uv run uvicorn analyst_service.api.main:app --port 8001
uv run uvicorn screener_service.api.main:app --port 8002
cd web_ui && npm run dev
```

Current caveats:

- Plain `uv run ...` may fail in Codex if `~/.cache/uv` is inaccessible; use `UV_CACHE_DIR=/private/tmp/uv-cache` and `--no-sync`.
- `make postman` calls `npx -y openapi-to-postmanv2`; it needs npm/network access beyond the verified `tools/dump_openapi.py` step.
- `cd web_ui && npm run lint` currently fails on `react-hooks/set-state-in-effect` in `web_ui/src/views/Analyze.tsx`.

## Architecture And Boundaries

- Keep the dependency direction `screener_service -> analyst_service -> external providers`.
- `analyst_service` never calls `screener_service`, `web_ui`, `execution_engine`, or `portfolio_dashboard`.
- Keep deterministic math, scoring, and price levels in Python `core/` modules. LLM use stays narration-only.
- Keep weights, thresholds, and rules in YAML under each service `config/`.
- API/UI boundary lives in `web_ui/src/api/client.ts` and `web_ui/src/api/types.ts`; contract changes must be reflected there.
- `render.yaml` is deploy truth for `finance-analyst`, `finance-screener`, `finance-cache`, and the static `finance-web-ui` site.
- Load `.env` before config reads in both FastAPI entrypoints.

## Generated And Sensitive Files

Do not hand-edit:

- `openapi/*.json`
- `postman/*.json`
- `analyst_service/cache/`
- `screener_service/cache/`
- `backtesting/recommendations.jsonl`
- `.venv/`, `web_ui/node_modules/`, `web_ui/dist/`, `*.egg-info/`

Do not print or commit values from repo-root `.env`, `web_ui/.env.local`, or service credentials. `web_ui/.env.production` is tracked deploy wiring, not a place to store secrets.

## Testing Expectations

- Start with the narrowest affected pytest file or UI command, then broaden.
- Re-run service tests after backend changes.
- Re-run `cd web_ui && npm run build` after UI changes. Run lint too if you touch the failing path or are fixing that rule.
- If routers, shared models, health payloads, or UI-facing contracts change, run `UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync python tools/dump_openapi.py`, then `make postman` when npm/network access is available.
- If local socket binding is blocked, use startup validation plus targeted tests as local proof and use deployed checks for live health behavior.

## Skills

Repo skills live in `skills/`:

- `finance-implementation-workflow`
- `finance-test-debug-workflow`
- `finance-api-contract-sync`
- `finance-guidance-maintenance`
