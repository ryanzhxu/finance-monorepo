# finance-monorepo — Claude Code Context

## Repo
/Users/ryan.xu/Developer/finance-monorepo
Cloudflare Worker + Pages deployment; no Render resources

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
