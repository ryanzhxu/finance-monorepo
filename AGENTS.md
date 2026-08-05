# finance-monorepo

## Current architecture

This is a market-analysis monorepo with two implementation surfaces:

- `cloudflare-api/` is the production `finance-api` Worker. It serves the public analysis, screener, health, batch, entry/confluence, shared-space, and research-job route contracts.
- `web_ui/` is the production React 19/Vite/Tailwind single-page app on Cloudflare Pages (`finance-web-ui`). Its production build uses `VITE_API_BASE_URL=https://finance-api.rxlab.workers.dev`.

The Worker owns public runtime behavior. It calls its configured market-data upstreams and stores shared watchlist membership in the `SharedWatchlistSpace` Durable Object. The public UI has its normal console route and a passcode-protected shared watchlist route at `/drama`.

The FastAPI services remain the Python source/service implementation used for local development, tests, contracts, and offline work:

- `analyst_service/` owns single-symbol analysis, search, entries/confluence, data freshness, and deterministic scoring.
- `screener_service/` owns discovery/ranking, trending, regime, and screener health. Its dependency direction is `screener_service -> analyst_service -> external providers`.
- `shared/` owns shared Python models, enums, freshness helpers, and config utilities.

`backtesting/` is private, offline research infrastructure. Main contains append-only recommendation logging plus safe foundations for event contracts/ingestion, holdout-consumption and SEC checkpoint ledgers, and cache-only provenance manifests. Caches, raw inputs, manifests, reports, and model artifacts stay out of Git. `execution_engine/` and `portfolio_dashboard/` remain placeholders.

## Production boundaries

- `cloudflare-api/wrangler.toml` is deploy truth for `finance-api`; it binds the shared watchlist and disabled research Durable Objects.
- `RESEARCH_ENABLED=false` and `RESEARCH_DECISION_SUPPORT_ENABLED=false` in Worker configuration. Do not enable research, make provider calls, fetch market data, or expose forecast/trade guidance without explicit approval and the corresponding model/provenance gates.
- The Worker supports `GET /health`, `GET /screen/health`, the screener endpoints under `/screen/*`, `/analyze`, `/batch`, `/search`, `/entry`, `/entry/confluence`, `/shared-spaces/*`, and `/research/jobs/*`. Research jobs must remain fail-closed while disabled.
- Cloudflare Pages is the frontend deployment target. The monorepo has no active Render configuration or dependency.
- API/UI contracts live in `web_ui/src/api/client.ts` and `web_ui/src/api/types.ts`. Update generated OpenAPI/Postman artifacts only through their generators when those contracts change.

## Read first

- `README.md`
- `MARKET_OPPORTUNITY_SYSTEM_SPEC.md`
- `cloudflare-api/wrangler.toml`
- `cloudflare-api/src/index.js`
- `analyst_service/api/routers/analysis.py`
- `screener_service/api/routers/screen.py`
- `shared/shared/models.py`
- `web_ui/src/App.tsx`
- `web_ui/src/api/client.ts`
- `web_ui/src/api/types.ts`
- `backtesting/event_library.py`
- `backtesting/event_ingestion.py`
- `backtesting/experiment_integrity.py`
- `backtesting/provenance_manifest.py`

`AGENTS_ANALYST.md` is historical analyst-service context. Read it after these current files.

## Change rules

- Keep deterministic math, scoring, price levels, and risk logic in Python core modules or deterministic Worker code. LLMs may narrate or gather evidence only; they must not invent numbers, make trades, or size positions.
- Preserve backwards compatibility for API/UI changes unless a removal is explicitly approved and every caller is verified.
- Keep research/private artifacts, credentials, `.env` values, caches, generated reports, and `web_ui/.env.local` out of output and commits.
- Never hand-edit `openapi/*.json`, `postman/*.json`, caches, `backtesting/recommendations.jsonl`, `.venv/`, `web_ui/node_modules/`, or `web_ui/dist/`.
- A dirty shared checkout may contain unrelated provider or forecast WIP. Use a new worktree from current `origin/main` for independent work and preserve all unrelated changes.

## Verification

Use the narrowest command first, then broaden for the touched surface:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync pytest -q
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync python tools/dump_openapi.py
cd cloudflare-api && npm test
cd web_ui && npm run build
git diff --check
```

Local port binding can be sandbox-restricted, so use build/tests for local proof and separately authorized deployed checks for live behavior.
