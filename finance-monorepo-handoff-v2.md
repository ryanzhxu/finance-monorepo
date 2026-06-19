# finance-monorepo — Session Handoff

Attach MARKET_OPPORTUNITY_SYSTEM_SPEC.md and AGENTS_ANALYST.md alongside this prompt. They are the authoritative reference for architecture, API contracts, service design, scoring models, and system invariants. Everything in those files is agreed and in effect. This prompt covers only what we discussed, decided, and changed on top of them.

---

## Environment (M4 Pro MacBook)

- Repo: /Users/ryan.xu/Developer/finance-monorepo (own git repo, not nested)
- GitHub: pushed, connected to Render for auto-deploy on push
- uv 0.11.21 at /Users/ryan.xu/.local/bin/uv (takes priority over Homebrew via PATH)
- Node v24.17.0 via NVM
- Python 3.12.13
- .env at repo root (gitignored) — contains AI_PROVIDER=google, AI_API_KEY, AI_MODEL=gemini-2.0-flash, AI_BASE_URL=, ALPHA_VANTAGE_KEY, CACHE_TTL_SECONDS=300, FUNDAMENTAL_CACHE_TTL=86400, SENTIMENT_CACHE_TTL=3600, ANALYST_BASE_URL=http://localhost:8001
- LLM: Gemini free tier, provider-neutral wrapper, reads AI_PROVIDER + AI_API_KEY + AI_MODEL from env

---

## What has been built

- Phase 1 (analyst core), Phase 2 (screener core), Phase 3 (trending + buyability) — all complete per the spec
- Stage 0: market-calendar-aware freshness — added LAST_CLOSE to Freshness enum; price tags LAST_CLOSE (with date) when market closed, DELAYED (~15m) when intraday-open; LAST_CLOSE does NOT penalize data_quality_score; US equity market calendar in shared/time_utils.py + shared/config/us_equity_market_holidays.yaml
- Stage 0.5: entry engine fixes — tightened ideal_buy_zone (capped at support1 + zone_atr_mult×ATR, default 1.0, only extends toward MA20 if within ma20_proximity_atr_tolerance×ATR); conservative_entry_price now populated with support1 when verdict is wait_for_pullback; R/R gate explicit and configurable via rr_min (default 1.0); decision table is internally consistent (price inside zone + not overextended + R/R >= rr_min → buy_now; never price-inside-zone paired with wait_for_pullback); /entry now returns data_freshness + data_quality_score; new YAML knobs in entry_rules.yaml: zone_atr_mult, ma20_proximity_atr_tolerance, rr_min
- Postman + OpenAPI: tools/dump_openapi.py (no server needed), tools/generate_postman.py, Makefile targets postman and postman-push; local and render environment files; rule in AGENTS.md — after any API/model change run make postman and commit openapi/ + postman/
- Render: both services deployed as Blueprint via render.yaml, build at repo root, binds 0.0.0.0:$PORT, screener ANALYST_BASE_URL wired from analyst service host, secrets declared with sync:false
- backtesting/store.py: append-only recommendation log, writing from Phase 1 onward

Test baseline: 38 passed (uv run pytest -v)

---

## Decisions and agreements made this session

- LLM (Gemini) is narrative-only — it never computes indicators, scores, or price levels. It only rephrases structured data into prose. This is a hard architectural rule, not a preference
- All indicators are hand-rolled pure pandas/numpy (pandas-ta was dropped — uv couldn't resolve it). This is fine for correctness IF the canonical formula variants are followed. Known future task: add dev/test-only library to cross-check Wilder's RSI/ATR, MACD EMA seeding, BB stddev variant
- Valuation scoring uses self-5y percentiles + sector-relative percentiles, never absolute P/E
- Trending detection uses acceleration vs each stock's OWN 30-day baseline — not raw popularity (NVDA/TSLA always discussed; the signal is unusual change, not level)
- Reddit API: access request submitted, awaiting approval. Plug-and-play gap already in trending.py — adding credentials is config-only, no code change needed
- StockTwits: API access restricted, skip for now
- Real-time price providers (Alpaca/Finnhub): low-effort optional add, defer until 1D horizon features are needed
- Rename portfolio-dashboard → analysis-console / web-ui. It is NOT a holdings tracker. It is a user-friendly interface: text fields and buttons to make API calls, results displayed as formatted tables/cards/reports instead of raw JSON
- Fibonacci + confluence engine approved (Stage 1): three views — a = classical entry (unchanged), b = Fibonacci levels, a+b = confluence (where independent methods agree on a price zone). Confluence is a generalizable engine; Fibonacci is its first new registered method alongside existing swing S/R and MAs. merged_buy_zone when classical zone overlaps Fibonacci golden pocket (high_conviction: true); divergence shown when they don't overlap. Fibonacci has modest weight pending Phase 4 backtest validation
- web-ui uses progressive disclosure: merged confluence verdict (a+b) as headline, a/b/signals/scores/risk/freshness on drill-down. Entry-zone visual: price ladder showing current price vs support/resistance/buy zones/stop. Surfaces confidence, LAST_CLOSE/DELAYED/MISSING tags, data_quality_score, and risk flags prominently — never buried
- Stage 2 (after web-ui): regime-conditioning the entry verdict (pullback-buying behaves differently in trending vs choppy regime) + conflict-aware narrative (LLM explicitly surfaces tension: "technicals say BUY, fundamentals say HOLD" — not just restating numbers)
- Stage 3 (after Stage 2): multi-timeframe confluence — daily + weekly alignment; a level confluent on both is higher conviction
- Phase 4+ save-it (LLM weight tuning): LLM proposes YAML weight adjustments advisory-only, each backtested by the Phase 4 evaluator before adoption, human commits winning YAML. Gated on Phase 4 backtesting evaluator existing first
- FastAPI deprecation warnings (on_event → lifespan, httpx → httpx2): non-blocking, note for future cleanup pass
- Do NOT write Stage 1 Codex prompt until Stage F is complete and real entry.fibonacci + entry.confluence JSON response shape is known
- Do NOT write web-ui Codex prompt until Stage 1 is complete and real response fields are confirmed

---

## Current blocker — fix first

analyst-service was accidentally omitted from the root pyproject.toml [tool.uv.workspace] members list when the project was scaffolded by Codex. It runs fine (uv run uvicorn works, 38 tests pass) but cannot be managed as a workspace package.

Consequence: python-dotenv cannot be added as a declared dependency. Without it, .env is not loaded at service startup. Both main.py files already have `from dotenv import load_dotenv` / `load_dotenv()` added at the top, but the package is not installed. Result: /health returns llm_available: false and alpha_vantage: not_configured even though .env has the keys.

Root pyproject.toml [tool.uv.workspace] members currently:
```toml
[tool.uv.workspace]
members = [
    "shared",
    "screener_service",
]
```

Fix:
1. Add analyst_service to workspace members
2. Add analyst-service to [tool.uv.sources] and root project dependencies
3. Add [tool.hatch.build.targets.wheel] packages = ["analyst_service"] to analyst_service/pyproject.toml (hatchling cannot auto-resolve hyphen name to underscore directory). Check screener_service/pyproject.toml for the same issue
4. uv add python-dotenv --package analyst-service and --package screener-service
5. uv sync → uv run pytest (38 must pass) → /health must return llm_available: true

---

## Critical gap — Stage F (next after blocker)

The analyst is TECHNICALS-ONLY. A live /analyze returns fundamentals/sentiment/macro all null, data_quality_score: 25, confidence: ~0.13, only 7 technical signals. The signal_weights.yaml already has EPS_Surprise (2.0), Analyst_Ratings (1.5), Institutional_13F (1.5) as primary anchors — the data just isn't fetched.

Stage F must implement in analyst_service:
- fundamentals.py: EPS surprise %, P/E P/B P/S EV/EBITDA percentile vs own 5y history (not absolute), revenue growth YoY, FCF trend, gross margin %, analyst upgrades/downgrades 30d net. Primary: yfinance with retry. Fallback: SEC EDGAR XBRL
- sentiment.py: Put/Call ratio (yfinance options chain), IV rank (52wk range), short interest % (yfinance), institutional 13F net shares (SEC EDGAR /submissions/, ALWAYS label DELAYED 45d). Reddit/StockTwits: skip if no credentials, tag missing, never crash
- macro.py (new): FOMC calendar, days_to_next_fomc, rate_cut_probability_pct, treasury_10y (^TNX), VIX (^VIX). Degrade per field
- Wire all into signals.py: EPS_Surprise, Analyst_Ratings, PE_Percentile, Put_Call_Ratio, IV_Rank, Institutional_13F, Short_Interest, FOMC_Proximity
- data_freshness: fundamentals = quarterly with as-of date, 13F = delayed with 45d lag + as-of, macro = live/delayed per field
- Target: data_quality_score > 70 on NVDA/AAPL/KO
- Run make postman after. Small commits per module

---

## Build order going forward

1. Blocker fix (now)
2. Stage F — fundamentals + macro
3. Stage 1 — confluence engine + Fibonacci
4. web-ui — analysis console (after Stage 1, binds to real response fields)
5. Stage 2 — regime-conditioning + conflict-aware narrative
6. Stage 3 — multi-timeframe confluence
7. Phase 4+ — backtesting evaluator + LLM weight tuning
