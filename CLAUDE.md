# finance-monorepo — Claude Code Context

## Repo
/Users/ryan.xu/Developer/finance-monorepo
GitHub → Render auto-deploy on push to main

## Stack
- Backend: FastAPI, Python 3.12, uv workspace (analyst_service, screener_service, shared)
- Frontend: React/TypeScript, Vite, Tailwind CSS (web_ui/)
- Data: yfinance, SEC EDGAR, Alpha Vantage, Marketaux, Gemini (narrative only)
- Infra: Render free tier, Redis cache (finance-cache), file cache fallback

## Services
- analyst_service  → localhost:8001 (prod: https://finance-analyst-x9kj.onrender.com)
- screener_service → localhost:8002 (prod: https://finance-screener.onrender.com)
- web_ui           → localhost:5173 (prod: https://finance-web-ui.onrender.com)

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
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync pytest -v
# Expected: 68 passed
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

## Current state (as of 2026-06-20)
Completed:
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
- yfinance rate-limited on Render datacenter IPs — Redis cache mitigates this
- Alpha Vantage free tier: 25 req/day — cache seeds on first successful request
- put/call ratio, short interest: yfinance options rate-limited on Render
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
