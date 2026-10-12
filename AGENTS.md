# finance-monorepo

FastAPI analyst and screener services plus a live React/Vite frontend in `web_ui/`. `execution_engine/` and `portfolio_dashboard/` are still placeholders. If docs conflict with code, trust the code and note the mismatch.

## Read First

- `README.md`
- `MARKET_OPPORTUNITY_SYSTEM_SPEC.md`
- `cloudflare-api/wrangler.toml`
- `pyproject.toml`
- `analyst_service/api/routers/analysis.py`
- `screener_service/api/routers/screen.py`
- `shared/shared/models.py`
- `web_ui/src/api/client.ts`
- `backtesting/config/forecast.yaml`
- `backtesting/forecast_feature_model.py`
- `backtesting/forecast_provenance.py`
- `tools/evaluate_final_holdout.py`
- `tools/download_sec_edgar_fundamentals.py`
- `skills/`

`AGENTS_ANALYST.md` is historical analyst-service context only. Read it after the monorepo docs and current code, not before.

## Layout

- `analyst_service/` single-symbol analysis (`/analyze`, `/batch`, `/entry`, `/entry/confluence`, `GET /entry/confluence/{symbol}`, `/health`, and `/search`)
- `screener_service/` discovery, ranking, trending, regime, and `/screen/health`
- `shared/` shared enums, contracts, freshness helpers, and config loading
- `web_ui/` React 19 + Vite + Tailwind frontend used in production
- `backtesting/` append-only recommendation logging plus offline forecast research: executable labels, point-in-time dataset assembly, feature models, provenance, diagnostics, private artifacts, and cache-backed SEC/R2 helpers
- `tools/` OpenAPI/Postman helpers plus explicit offline forecast, data-audit, R2-sync, and research CLI entry points
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
cd cloudflare-api && npm test
cd web_ui && npm run build
git diff --check
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
- Forecast-research source is currently local WIP. Keep it separate from deploy/cutover changes until its data-quality and experiment-integrity boundaries have been reviewed.

## Architecture And Boundaries

- Keep the dependency direction `screener_service -> analyst_service -> external providers`.
- `analyst_service` never calls `screener_service`, `web_ui`, `execution_engine`, or `portfolio_dashboard`.
- Keep deterministic math, scoring, and price levels in Python `core/` modules. LLM use stays narration-only.
- Keep weights, thresholds, and rules in YAML under each service `config/`.
- API/UI boundary lives in `web_ui/src/api/client.ts` and `web_ui/src/api/types.ts`; contract changes must be reflected there.
- `cloudflare-api/wrangler.toml` is deploy truth for the `finance-api` Worker; `web_ui/` deploys to the `finance-web-ui` Cloudflare Pages project, served at `https://stock.ryanxu.dev`. The monorepo no longer provisions Render resources.
- Load `.env` before config reads in both FastAPI entrypoints.

## Forecast Research Safety

- Forecast research is offline and experimental. It must remain fail-closed: do not expose numeric forecasts, position sizing, or trade instructions unless both target gates pass and provenance is point-in-time certified.
- Keep numerical features, labels, probabilities, rankings, calibration, and position sizing deterministic in Python. LLMs may gather evidence or explain results; they must not invent forecast numbers or decide trades.
- The executable label is `next_open_low_v2`: signal after the `as_of` close, entry at the next trading-session open, 63-session exit at close, and downside from the holding-period intraday low. Do not change its definition without a separately versioned dataset and evaluation.
- The 2023-2024 final holdout is consumed. Never use it to fit, tune, calibrate, select, inspect candidate outcomes, or rerun a candidate. Candidate work uses only the frozen selection data and an identical label, feature schema, coverage, and walk-forward protocol. A new final holdout is created only after a material data upgrade and explicit approval.
- Retain an experimental candidate only when it has a protocol-compatible manifest and improves both upside and downside primary selection Brier metrics by the configured threshold. Preserve failed-candidate evidence but do not leave its behavior in the code.
- The current Yahoo/yfinance current-listing cache is experimental and must be marked `point_in_time_certified=false`. It has survivorship, delisted-stock, historical-universe, and as-of corporate-action limitations. SEC company facts improve fundamental timing only; they do not certify the price universe.
- No IBKR integration, automatic order execution, or trade simulation is permitted in forecast research work.

## Forecast Data And Artifacts

- Keep caches, raw price data, SEC company-facts payloads, model artifacts, manifests, and reports outside Git. They are private local/R2 research artifacts, not source files.
- Dataset manifests must record source, retrieval time, adjustment mode, requested/completed symbols, benchmark coverage, file hashes, and certification state. R2 stores only private manifests/reports/cache metadata; never secrets or raw credentials.
- SEC collection must be conservative, checkpointed, and resumable. Never launch overlapping bulk downloads; distinguish systemic network failures from missing company facts, and record both in the batch manifest.
- Do not redownload market data or call external providers unless the user has explicitly approved that run or an active approved automation authorizes it. Cache-only checks must not silently fetch data.

## Generated And Sensitive Files

Do not hand-edit:

- `openapi/*.json`
- `postman/*.json`
- `analyst_service/cache/`
- `screener_service/cache/`
- `backtesting/cache/`
- `backtesting/recommendations.jsonl`
- `.venv/`, `web_ui/node_modules/`, `web_ui/dist/`, `*.egg-info/`

Do not print or commit values from repo-root `.env`, `web_ui/.env.local`, or service credentials. `web_ui/.env.production` is tracked deploy wiring, not a place to store secrets.

## Testing Expectations

- Start with the narrowest affected pytest file or UI command, then broaden.
- Re-run service tests after backend changes.
- For forecast/data code, start with the relevant `backtesting/tests/` file. Retained experiment changes require focused tests, the full pytest suite, and `git diff --check`; record a compatible private manifest/report before comparing metrics.
- For Worker changes, run `cd cloudflare-api && npm test`. Research endpoints must stay disabled/fail-closed until the model and data gates are independently satisfied.
- Re-run `cd web_ui && npm run build` after UI changes. Run lint too if you touch the failing path or are fixing that rule.
- If routers, shared models, health payloads, or UI-facing contracts change, run `UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync python tools/dump_openapi.py`, then `make postman` when npm/network access is available.
- If local socket binding is blocked, use startup validation plus targeted tests as local proof and use deployed checks for live health behavior.

## Skills

Repo skills live in `skills/`:

- `finance-implementation-workflow`
- `finance-test-debug-workflow`
- `finance-api-contract-sync`
- `finance-guidance-maintenance`
