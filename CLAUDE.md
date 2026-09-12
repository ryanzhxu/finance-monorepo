# finance-monorepo — Claude Code Context

## Repo
/Users/ryan.xu/Developer/finance-monorepo
Cloudflare Worker + Pages deployment; no Render resources

## Read First
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

## Current architecture
This is a market-analysis monorepo with two implementation surfaces:

- `cloudflare-api/` is the production `finance-api` Worker. It serves the public analysis, screener, health, batch, entry/confluence, shared-space, decisions, and research-job route contracts. `cloudflare-api/src/consolidated/` runs `technical_engine/` in-process as the sole technical layer and applies the index hurdle; when `CONSOLIDATED_DECISION` is on, its verdict replaces the local technical vote and Ryan's fundamentals become a minority layer that can only step a buy down, never up.
- `technical_engine/` is Vincent's technical-analysis engine, imported into this repo with its git history. Protected: read and import it freely, never edit it here — porting changes into it is a human decision.
- `web_ui/` is the production React 19/Vite/Tailwind single-page app on Cloudflare Pages (`finance-web-ui`). Its production build uses `VITE_API_BASE_URL=https://finance-api.rxlab.workers.dev`.

The Worker owns public runtime behavior. It calls its configured market-data upstreams and stores shared watchlist membership in the `SharedWatchlistSpace` Durable Object. The public UI has its normal console route and a passcode-protected shared watchlist route at `/drama`.

The FastAPI services remain the Python source/service implementation used for local development, tests, contracts, and offline work:

- `analyst_service/` owns single-symbol analysis, search, entries/confluence, data freshness, and deterministic scoring.
- `screener_service/` owns discovery/ranking, trending, regime, and screener health. Its dependency direction is `screener_service -> analyst_service -> external providers`.
- `shared/` owns shared Python models, enums, freshness helpers, and config utilities.

`backtesting/` is private, offline research infrastructure. Main contains append-only recommendation logging plus safe foundations for event contracts/ingestion, holdout-consumption and SEC checkpoint ledgers, and cache-only provenance manifests. Caches, raw inputs, manifests, reports, and model artifacts stay out of Git. `execution_engine/` and `portfolio_dashboard/` remain placeholders.

## Stack
- Backend: FastAPI, Python 3.12, uv workspace (analyst_service, screener_service, shared)
- Frontend: React/TypeScript, Vite, Tailwind CSS (web_ui/)
- Data: yfinance, SEC EDGAR, Alpha Vantage, Marketaux, Gemini (narrative only)
- Infra: Cloudflare Worker + Pages, file cache fallback

## Services
- analyst_service  → localhost:8001
- screener_service → localhost:8002
- web_ui           → localhost:5173 (prod: Cloudflare Pages)
- cloudflare-api   → production Worker API (`npm run dev` for local wrangler)
- technical_engine → Vincent's technical-analysis engine, imported with git
  history; the Worker runs it in-process as the sole technical layer (spec D1).
  Protected: read and import freely, never edit.

## Production boundaries
- `cloudflare-api/wrangler.toml` is deploy truth for `finance-api`; it binds the shared watchlist and disabled research Durable Objects.
- `RESEARCH_ENABLED=false` and `RESEARCH_DECISION_SUPPORT_ENABLED=false` in Worker configuration. Do not enable research, make provider calls, fetch market data, or expose forecast/trade guidance without explicit approval and the corresponding model/provenance gates.
- The Worker supports `GET /health`, `GET /screen/health`, the screener endpoints under `/screen/*`, `/analyze`, `/batch`, `/search`, `/entry`, `/entry/confluence`, `/shared-spaces/*`, and `/research/jobs/*`. Research jobs must remain fail-closed while disabled.
- API/UI contracts live in `web_ui/src/api/client.ts` and `web_ui/src/api/types.ts`. Update generated OpenAPI/Postman artifacts only through their generators when those contracts change.

## Local dev
```bash
# Terminal 1
uv run uvicorn analyst_service.api.main:app --port 8001

# Terminal 2
uv run uvicorn screener_service.api.main:app --port 8002

# Terminal 3
cd web_ui && npm run dev
```

## Tests
```bash
# Python
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync pytest -q
# Expected: 271 passed

# Vincent's engine
node --test technical_engine/tests/*.test.js
# Expected: 6 suites passing

# Worker
cd cloudflare-api && npm test
# Expected: 149 passing

# Frontend
cd web_ui && npm test && npm run build
```
Use the narrowest command first, then broaden to the full suite. Also run `git diff --check`, and if routers, shared models, or UI-facing contracts changed, `UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync python tools/dump_openapi.py`. Local port binding can be sandbox-restricted — use build/tests for local proof and deployed QA/prod health checks for live behavior.

## After any API/model change
```bash
make postman
git add openapi/ postman/
```

## Architectural invariants — never violate
- LLM (Gemini) is narrative-only — never computes indicators, scores, or price levels
- All indicators are pure pandas/numpy — no pandas-ta
- Valuation scoring uses self-5y percentiles, never absolute thresholds
- signal_weights.yaml values are final — do not change without Phase 4 backtest
- fcf_trend values: "improving" | "flat" | "deteriorating" (never "rising")
- After any API/model change: run make postman and commit openapi/ + postman/
- No unsolicited refactors, no extra tests unless tasked, no new dependencies without approval
- The system must not place trades (spec §2 constraint 1). Vincent's Questrade
  auto-trade request is an open decision, not a backlog item — see docs/OPEN-DECISIONS.md
- **Technical layer ownership (decided 2026-08-28):** Vincent's engine supplies
  technicals; every other layer stays here. An external decision.v1 verdict
  *replaces* the local technical vote — never average the two
- cloudflare-api/src/technical-provider.js mirrors
  analyst_service/core/technical_provider.py. Change one, change both: the action
  map, legality table and confidence rescale must stay identical
- decision.v1 confidence is 0-100; Recommendation.confidence is 0.0-1.0. Always rescale

## Known divergence — Worker vs Python
`cloudflare-api/` is a **re-implementation** of the analysis, not a proxy to
`analyst_service`. They can disagree about the same symbol:

| | Python | Worker |
|---|---|---|
| Vote thresholds | `signal_thresholds.yaml` | hardcoded ±0.15 |
| Confidence | `majority_fraction × data_quality/100` | `0.5 + abs(score)×0.45` |
| `review_action` | `add_watch`/`trim_review`/`hold_monitor` | `BUY`/`AVOID`/`WATCH`/`HOLD` |

Production serves the Worker. Treat any Python-only change as not shipped until
the Worker matches.

## Change rules
- Preserve backwards compatibility for API/UI changes unless a removal is explicitly approved and every caller is verified.
- Keep research/private artifacts, credentials, `.env` values, caches, generated reports, and `web_ui/.env.local` out of output and commits.
- Never hand-edit `openapi/*.json`, `postman/*.json`, caches, `backtesting/recommendations.jsonl`, `.venv/`, `web_ui/node_modules/`, or `web_ui/dist/`.
- A dirty shared checkout may contain unrelated provider or forecast WIP. Use a new worktree from current `origin/main` for independent work and preserve all unrelated changes.

## Current state (as of 2026-09-08)
Completed:
- Composite engine Phase 1: external technical provider seam. `/analyze` accepts an
  optional `technical` block (decision.v1); it replaces the local technical vote and
  reports `technical_agreement` — whether both engines reached the same direction.
  Implemented on both the Python and Worker sides, with parity tests.
- Worker category votes: `technical_vote`/`fundamental_vote`/`sentiment_vote`/
  `macro_vote` were hardcoded zeros in production; now derived from real signals.

Earlier (as of 2026-06-20):
- Stage 0: market-calendar-aware freshness
- Stage 0.5: entry engine fixes
- Stage F: fundamentals + sentiment + macro data layers (yfinance + SEC EDGAR + Alpha Vantage fallback)
- Stage 1: Fibonacci + confluence engine
- News sentiment: Marketaux integration (keyword scoring, News_Sentiment signal)
- Frontend: Analyze view, Screener, Health, Watchlist sidebar, dark/light/system theme
- Frontend fixes: Stop button (no form wrapper, abortedRef/fetchIdRef guards), company name display
- Health view: per-provider rows with icons, Refresh button, last-checked timestamp
- Cache: Redis-first with file fallback (REDIS_URL → Redis, absent → file)

Known gaps (do not fix unless tasked):
- yfinance provider rate limits remain possible — file caching mitigates repeat requests
- Alpha Vantage free tier: 25 req/day — cache seeds on first successful request
- put/call ratio, short interest: yfinance options may be rate-limited
- institutional_net_shares_last_13f: EDGAR parsing fragile
- iv_rank_approx: HV-based approximation only
- rate_cut_probability_pct: ZQ futures derived, not official CME
- Reddit/StockTwits: no credentials yet

## Build order
1. Health endpoint enrichment — richer provider rows (Marketaux, Redis, yfinance status)
2. Ticker autocomplete — Yahoo Finance search proxy in analyst_service
3. Stage 2 — regime-conditioned entry verdict + conflict-aware LLM narrative
4. Stage 3 — multi-timeframe confluence (daily + weekly)
5. Phase 4 — backtesting evaluator (gated on evaluator existing)
6. Cleanup — FastAPI deprecation warnings (on_event → lifespan)

## Work packet format
Mode: Fix | Feature | Debug | Review
Goal: one sentence
Repo: finance-monorepo
Paths: files to touch
Constraints: hard limits
Done: acceptance criteria
Context: only what's not in this file
