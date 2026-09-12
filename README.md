# finance-monorepo

Market opportunity monorepo with FastAPI analyst/screener service code, a Cloudflare Worker API, shared contracts/utilities, and a deployed React/Vite frontend in `web_ui/`.

## Services

- `analyst_service/` single-symbol analysis, entry/confluence, provider health, and ticker search
- `screener_service/` undervalued/opportunity/trending screens, watchlist/custom screens, regime, and screener health
- `cloudflare-api/` production Worker API and shared-watchlist endpoints
- `technical_engine/` Vincent's technical-analysis engine, imported into this repo
  with its git history. The Worker runs it in-process as the sole technical layer
  (`cloudflare-api/src/consolidated/`); protected — read and import it freely,
  never edit it here
- `shared/` cross-service models, enums, freshness/config helpers
- `web_ui/` production frontend for Analyze, Screener, Health, Watchlist, and
  Decision Board views
- `backtesting/store.py` append-only logging helpers

`execution_engine/` and `portfolio_dashboard/` are still placeholders.

## Composite engine — whose analysis is whose

Decided by Ryan and Vincent on 2026-08-28: **Vincent's technical analysis system
supplies the technical layer; every other layer stays here.**

| Layer | Owner |
|---|---|
| Technical | Vincent's engine, via `decision.v1` |
| Fundamental, sentiment, macro, valuation, entry/confluence, data quality | this repo |

Post a `technical` block on `/analyze` and it replaces the local technical vote:

```bash
curl -sS -X POST http://127.0.0.1:8001/analyze \
  -H 'content-type: application/json' \
  -d '{
        "symbol": "NVDA",
        "horizon": "3-6M",
        "technical": {
          "contractVersion": "decision.v1",
          "producer": "vincent-stock-decision-dashboard",
          "action": "buy",
          "confidence": 70,
          "priceState": "IN_OPPORTUNITY_ZONE",
          "opportunityRange": {"low": 100.0, "high": 110.0},
          "reduceRange": {"low": 140.0, "high": 150.0},
          "invalidation": 95.0,
          "reasons": ["Weekly trend intact"],
          "dataQuality": 88
        }
      }'
```

Notes for the producer side:

- `confidence` is **0-100** in `decision.v1`, rescaled to 0.0-1.0 internally.
- `action` must be legal for `priceState`. `buy` inside `IN_REDUCE_ZONE` is refused.
- A refused verdict does not fail the request. The analysis falls back to the local
  technicals, reports `technical_source: "local"`, and adds the
  `external_technical_rejected` risk flag, so a bad payload is visible, never silent.
- The response reports **`technical_agreement`**: whether Vincent's engine and the
  local technicals independently reached the same direction. It is `null` when there
  is nothing to compare.

Substitution is not averaging. When Vincent's verdict is present it *is* the
technical vote, and the local technicals are computed only for that comparison.

The same contract is implemented in the Worker
(`cloudflare-api/src/technical-provider.js`), which serves production. Keep the two
in step.

Open decisions that need both of them are in
[`docs/OPEN-DECISIONS.md`](docs/OPEN-DECISIONS.md).

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

`cloudflare-api/wrangler.toml` is the deploy source of truth for `finance-api`; `web_ui/` deploys to the `finance-web-ui` Cloudflare Pages project. This repository no longer provisions or depends on Render resources.
