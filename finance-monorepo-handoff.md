## Project: finance-monorepo — AI Market Opportunity Discovery System

### What this project is
A two-service Python/FastAPI monorepo for AI-assisted US equity market analysis and discovery. Personal side project, separate from Trulioo work. Never places trades, never invents numbers. LLM (Gemini free tier, provider-neutral wrapper) is used ONLY for narrative synthesis. All scoring, indicators, and price levels are deterministic math in pure pandas/numpy.

Two services deployed on Render (auto-deploy on push to GitHub):
- analyst_service (:8001) — deep single-stock analysis: technical indicators, entry/exit price levels, signal voting, BUY/HOLD/SELL recommendation with confidence, optional LLM narrative
- screener_service (:8002) — market-wide discovery: undervalued/opportunity/trending/watchlist/custom screens, factor scoring, buyability pipeline that calls the analyst for shortlisted candidates

### Local environment (M4 Pro MacBook)
- Path: /Users/ryan.xu/Developer/finance-monorepo
- This IS its own git repo (not nested inside ryan-projects anymore)
- GitHub: pushed, connected to Render for auto-deploy
- Python: 3.12.13 via uv 0.11.21 (at /Users/ryan.xu/.local/bin/uv — takes priority over Homebrew uv)
- Node: v24.17.0 via NVM (needed for make postman toolchain)
- Stack: Python 3.11+, uv workspace, FastAPI, pandas/numpy (pandas-ta dropped — indicators are hand-rolled pure pandas), pydantic v2, yfinance, FinBERT for sentiment NLP with keyword fallback, Redis/file cache (currently file)

### .zshrc (relevant parts)
```bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export GEMINI_API_KEY=<raw key>
export RENDER_API_KEY=<raw key>
export POSTMAN_API_KEY=<raw key>
. "$HOME/.local/bin/env"
export PATH="$HOME/.local/bin:$PATH"   # ensures ~/.local/bin wins over Homebrew
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"
```

### .env (repo root, gitignored)
```
AI_PROVIDER=google
AI_API_KEY=<gemini key — same value as GEMINI_API_KEY in .zshrc>
AI_MODEL=gemini-2.0-flash
AI_BASE_URL=
ALPHA_VANTAGE_KEY=<key or blank>
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
STOCKTWITS_API_KEY=
CACHE_TTL_SECONDS=300
FUNDAMENTAL_CACHE_TTL=86400
SENTIMENT_CACHE_TTL=3600
ANALYST_BASE_URL=http://localhost:8001
```

### Architecture rules (non-negotiable, enforce on every change)
1. Never place trades or emit order instructions anywhere including narrative
2. Never fabricate missing data — tag missing, degrade gracefully, never crash
3. LLM calls ONLY in analyst_service/core/narrator.py — zero LLM calls in any numeric/scoring/indicator path
4. All weights, thresholds, config values in config/*.yaml, loaded via shared/config_loader with startup validation. Nothing hardcoded
5. Every analysis result carries data_freshness + data_quality_score
6. Sentiment dimensions collectively ≤ 15–20% of any weighted blend
7. After any API/model change: make postman → commit openapi/ + postman/
8. All git ops scoped to finance-monorepo — never stage/commit in parent directory
9. Acyclic service dependencies: screener may call analyst; analyst never calls screener/dashboard/execution-engine
10. Small targeted commits per module. No unsolicited refactors, no unrelated formatting changes

### Repository layout
```
finance-monorepo/
├── pyproject.toml                 # uv workspace root
├── Makefile                       # make postman, make postman-push targets
├── .env                           # gitignored, loaded via python-dotenv
├── MARKET_OPPORTUNITY_SYSTEM_SPEC.md   # authoritative full system spec
├── AGENTS_ANALYST.md              # authoritative analyst contract
├── shared/
│   ├── pyproject.toml             # name = "shared"
│   └── shared/
│       ├── enums.py               # Direction, EntryAssessment, TrendQuality, Freshness (incl LAST_CLOSE), RiskFlag, ScreenType, Universe, MarketRegime
│       ├── models.py              # ALL cross-service Pydantic v2 models
│       ├── config_loader.py       # YAML loading + startup validation
│       ├── data_quality.py        # freshness tagging + quality scoring
│       └── time_utils.py          # US equity market calendar, last_close date helper
├── shared/config/
│   └── us_equity_market_holidays.yaml  # built-in holiday list, refresh annually
├── analyst_service/
│   ├── pyproject.toml             # name = "analyst-service"
│   ├── config/
│   │   ├── signal_weights.yaml    # per-dimension weights (RSI_14:1.0, EPS_Surprise:2.0, etc.)
│   │   ├── signal_thresholds.yaml # BUY/SELL threshold config
│   │   ├── entry_rules.yaml       # zone_atr_mult, ma20_proximity_atr_tolerance, rr_min, breakout_buffer
│   │   └── confluence.yaml        # (to be created in Stage 1)
│   ├── api/
│   │   ├── main.py                # FastAPI :8001 — NEEDS python-dotenv fix (see current blocker)
│   │   └── routers/analysis.py    # /analyze /batch /entry /health
│   └── core/
│       ├── data_fetcher.py        # yfinance OHLCV + fundamentals (fundamentals currently returning null — see critical gap)
│       ├── technicals.py          # RSI, MACD, MA20/50/200, BB, ATR, volume ratio, swing S/R, weekly RSI, gaps, dist-from-MA
│       ├── fundamentals.py        # EXISTS but returns all nulls — not properly implemented yet
│       ├── sentiment.py           # EXISTS but returns all nulls — not properly implemented yet
│       ├── signals.py             # per-dimension BUY/HOLD/SELL
│       ├── entry_engine.py        # deterministic price levels (fixed in Stage 0.5)
│       ├── aggregator.py          # weighted vote → recommendation
│       ├── narrator.py            # LLM ONLY — skipped when include_narrative=false
│       ├── llm_client.py          # reads AI_PROVIDER, AI_API_KEY, AI_MODEL from env
│       └── settings.py            # fail-fast config validation incl zone_atr_mult, ma20_proximity_atr_tolerance, rr_min
├── screener_service/
│   ├── pyproject.toml             # name = "screener-service"
│   ├── config/
│   │   ├── scoring_weights.yaml   # valuation/growth/quality/momentum/... weights
│   │   ├── universes.yaml         # SP500/Nasdaq100/Dow/Russell membership sources
│   │   ├── filters.yaml           # liquidity/mcap/penny/OTC guards
│   │   └── trend_rules.yaml       # trend classification thresholds
│   ├── api/
│   │   ├── main.py                # FastAPI :8002 — NEEDS python-dotenv fix (see current blocker)
│   │   └── routers/screen.py      # all /screen/* endpoints
│   └── core/
│       ├── universe.py            # resolve + cache universe membership (weekly)
│       ├── fundamentals_bulk.py   # batch valuation/growth/quality metrics for screening
│       ├── scoring.py             # deterministic factor scores → opportunity_score + score_breakdown
│       ├── trending.py            # mention counts, acceleration vs own 30d baseline, sentiment, TrendQuality classification
│       ├── buyability.py          # trend + analyst technical/fundamental/entry → entry_assessment
│       ├── regime.py              # market regime + sector ETF rotation
│       └── analyst_client.py      # HTTP to analyst_service, timeout+graceful degradation, scheme normalization
├── backtesting/
│   └── store.py                   # append-only recommendation log, writes at emit time
├── tools/
│   ├── dump_openapi.py            # generates openapi/*.json without running server
│   └── generate_postman.py        # openapi-to-postman via openapi2postmanv2 CLI
├── openapi/
│   ├── analyst.json
│   └── screener.json
├── postman/
│   ├── analyst.postman_collection.json
│   ├── screener.postman_collection.json
│   ├── local.postman_environment.json     # analyst_base_url: http://localhost:8001, screener_base_url: http://localhost:8002
│   └── render.postman_environment.json    # prod URLs (fill-in placeholders for deployed Render URLs)
└── render.yaml                    # Render Blueprint: two web services, build at root, $PORT binding
```

### Current test baseline
38 passed (uv run pytest -v):
- shared/tests/test_market_calendar.py (5 tests)
- shared/tests/test_request_examples.py (2 tests)
- analyst_service/tests/test_entry_api.py (1 test)
- analyst_service/tests/test_entry_engine.py (7 tests)
- analyst_service/tests/test_indicators.py (2 tests)
- analyst_service/tests/test_price_freshness.py (4 tests)
- analyst_service/tests/test_signal_voting.py (2 tests)
- screener_service/tests/test_analyst_client.py (3 tests)
- screener_service/tests/test_buyability.py (3 tests)
- screener_service/tests/test_degradation.py (1 test)
- screener_service/tests/test_filters_universe.py (2 tests)
- screener_service/tests/test_scoring.py (1 test)
- screener_service/tests/test_trending.py (5 tests)

### Known deprecation warnings (non-blocking, note for future cleanup)
- httpx → httpx2 in FastAPI test client
- on_event → lifespan in FastAPI app startup

### What has been built (completed stages)

#### Phase 1 — Analyst MVP
- FastAPI skeleton: /analyze, /batch, /entry, /health
- data_fetcher.py: yfinance OHLCV + fundamentals fetch attempt
- technicals.py: RSI (hand-rolled — needs Wilder's variant validation), MACD, MA20/50/200, BB, ATR, volume ratio, swing S/R (20-bar window, ATR-clustered), weekly RSI, gap and dist-from-MA metrics
- entry_engine.py: deterministic price levels
- signals.py + aggregator.py: weighted vote → direction + confidence, weights from signal_weights.yaml
- narrator.py: LLM call, skipped when include_narrative=false
- backtesting/store.py: append-only log, writes at emit time

#### Phase 2 — Screener Core
- screener_service as uv workspace member
- universe.py, filters.py, fundamentals_bulk.py, scoring.py, analyst_client.py, regime.py
- Endpoints: /screen/undervalued, /screen/opportunities, /screen/watchlist, /screen/custom, /screen/health, /screen/regime
- Graceful degradation when analyst is down

#### Phase 3 — Trending + Buyability
- trending.py: acceleration vs each stock's OWN 30-day baseline (not raw popularity), sentiment, TrendQuality enum classification
- buyability.py: trend + analyst → entry_assessment via decision table
- /screen/trending endpoint
- /screen/opportunities uses real trend booster
- Sources: Reddit (plug-and-play gap — access request submitted, awaiting approval), StockTwits (access restricted, skip), financial-news RSS, Yahoo trending (degrades gracefully when unavailable)

#### Stage 0 — Market-Calendar-Aware Freshness
- Freshness enum: added LAST_CLOSE
- US equity market calendar in shared/time_utils.py + shared/config/us_equity_market_holidays.yaml
- Price freshness: LAST_CLOSE (with date) when market closed (weekend/holiday/after-hours), DELAYED (~15m) when intraday-open
- LAST_CLOSE does NOT penalize data_quality_score
- Confirmed working: /analyze returns last_close (2026-06-12) on weekend

#### Stage 0.5 — Entry Decision Layer Fixes
- Fixed ideal_buy_zone MA20-ballooning: zone high now capped at support1 + zone_atr_mult*ATR (default 1.0×ATR), only extends toward MA20 if MA20 is within ma20_proximity_atr_tolerance*ATR
- Fixed conservative_entry_price null when verdict is wait_for_pullback — now populated with support1
- R/R gate explicit and configurable: rr_min (default 1.0), if R/R < rr_min → wait_for_pullback with conservative_entry_price pointing to where R/R becomes acceptable
- Decision table internally consistent: price inside tightened zone + not overextended + R/R >= rr_min → buy_now; never price-inside-zone + wait_for_pullback
- /entry now returns data_freshness + data_quality_score
- New YAML knobs: zone_atr_mult, ma20_proximity_atr_tolerance, rr_min in entry_rules.yaml
- settings.py: fail-fast validation for new keys

#### Postman + OpenAPI
- tools/dump_openapi.py: generates openapi/*.json without running server
- tools/generate_postman.py + Makefile target postman: openapi → postman collections via openapi2postmanv2
- Makefile target postman-push: upserts to Postman API if POSTMAN_API_KEY set (it is, in .zshrc)
- postman/local.postman_environment.json: localhost URLs
- postman/render.postman_environment.json: prod URLs
- Rule in AGENTS.md: after any API/model change run make postman and commit artifacts
- All Postman tests verified passing locally for phases 1-3 + stages 0/0.5

### CURRENT BLOCKER — fix this first
analyst-service is not a proper uv workspace member. It was accidentally omitted from the root pyproject.toml [tool.uv.workspace] members list. It runs fine (uv run uvicorn works, all 38 tests pass) but cannot be managed as a workspace package, so uv add --package analyst-service fails with a hatchling build error (hatchling cannot resolve analyst-service hyphen name to analyst_service underscore directory).

Consequence: python-dotenv cannot be added as a declared dependency. Without it, .env is not loaded at service startup, so llm_available: false and alpha_vantage: not_configured in /health even though .env has the keys.

Current root pyproject.toml [tool.uv.workspace] members:
```toml
[tool.uv.workspace]
members = [
    "shared",
    "screener_service",
]
```
analyst_service is missing. Also missing from [tool.uv.sources] and root dependencies.

Fix needed:
1. Add analyst_service to workspace members in root pyproject.toml
2. Add analyst-service to [tool.uv.sources] and root dependencies
3. Add [tool.hatch.build.targets.wheel] packages = ["analyst_service"] to analyst_service/pyproject.toml (resolves hyphen/underscore mismatch for hatchling). Check if screener_service/pyproject.toml has the same issue and fix it too
4. uv add python-dotenv --package analyst-service and --package screener-service
5. Add from dotenv import load_dotenv / load_dotenv() at the TOP of both main.py files, before any other app initialization, before settings/config are read
6. uv sync, uv run pytest (38 must pass), confirm /health returns llm_available: true

### CRITICAL GAP — build after blocker is fixed (Stage F)
The analyst is TECHNICALS-ONLY. Every /analyze response shows:
- fundamentals, ratings, flows, sentiment, macro: ALL null/missing
- data_quality_score: 25/100
- confidence: ~0.13
- Only 7 signals (all technical) — none of: EPS_Surprise, Analyst_Ratings, PE_Percentile, Put_Call_Ratio, IV_Rank, Institutional_13F, Short_Interest, FOMC_Proximity

The signal_weights.yaml already has entries for all these dimensions (EPS_Surprise: 2.0, Analyst_Ratings: 1.5, Institutional_13F: 1.5 — the PRIMARY weight anchors). The signals.py/aggregator.py already wire them. The data just isn't being fetched and computed.

Stage F — build in analyst_service:
- fundamentals.py (proper implementation): per-stock EPS surprise (actual vs consensus, surprise %), PE/PB/PS/EV-EBITDA percentile vs own 5-year history (NOT absolute — compute percentiles ourselves from price history + EDGAR), revenue growth YoY, FCF trend (rising/flat/falling), gross margin %, analyst upgrades/downgrades 30d net, analyst revision direction + magnitude. Primary: yfinance. Fallback: SEC EDGAR XBRL. yfinance fundamentals are flaky — implement retry + fallback rather than returning null
- sentiment.py (proper implementation): per-stock options data (Put/Call ratio from yfinance options chain, IV rank computed from 52-week IV range), short interest % from yfinance, institutional 13F net share change from SEC EDGAR /submissions/ (ALWAYS label DELAYED 45d). Reddit/StockTwits: reuse plug-and-play credential check pattern from screener — skip if no credentials, tag missing, do NOT crash
- macro.py (new): FOMC calendar (Fed website scrape or hardcoded near-term dates, refresh quarterly), days_to_next_fomc, rate_cut_probability_pct (CME FedWatch or free source), treasury_10y yield (yfinance ^TNX), VIX (yfinance ^VIX). Degrade gracefully per field
- Wire all new dimensions into signals.py: EPS_Surprise, Analyst_Ratings, PE_Percentile, Put_Call_Ratio, IV_Rank, Institutional_13F, Short_Interest, FOMC_Proximity — each returning BUY/HOLD/SELL + note, weight from signal_weights.yaml
- data_freshness per new field: fundamentals = quarterly (label as-of date), 13F = delayed (label 45d lag + as-of), macro = live/delayed per field. NEVER label estimated as reported
- Target: data_quality_score > 70 on liquid large-cap (NVDA, AAPL, KO) with available data
- Tests: each new signal dimension with known fixture values, graceful degradation per provider (each down → field missing, quality reduced, no crash), freshness tags for each new field type, quality score improves meaningfully vs 25 baseline
- Run make postman after (response gains populated fields). Small commits per module

### Build order after blocker + Stage F
1. CURRENT BLOCKER — workspace fix + python-dotenv (now)
2. Stage F — analyst fundamentals + macro layer (next, critical)
3. Stage 1 — confluence engine + Fibonacci (a/b/a+b)
4. web-ui — analysis console React/TypeScript (AFTER Stage 1 — binds to Stage 1 response fields)
5. Stage 2 — regime-conditioning entry verdict + conflict-aware narrative
6. Stage 3 — multi-timeframe confluence
7. Phase 4+ — backtest evaluator + backtest-driven weight tuning

### Stage 1 design (for reference when building)
Three views in /analyze and /entry response:
- a = existing classical entry block (unchanged, backward-compatible)
- b = entry.fibonacci: detect dominant recent swing (reuse existing swing logic), compute retracements (23.6, 38.2, 50, 61.8, 78.6%) and extensions (127.2, 161.8, 200, 261.8%), golden pocket = 38.2–61.8% band, pure arithmetic
- a+b = entry.confluence: level registry where methods contribute (method_name, price, kind: support/resistance/target). Three registered methods: swing S/R, MAs (20/50/200), Fibonacci. Cluster within 1×ATR tolerance; ≥2 distinct methods = CONFLUENCE ZONE scored by (method count, diversity, proximity). merged_buy_zone when classical zone overlaps golden pocket (high_conviction: true). Divergence note + both zones when they don't overlap. Confluence is generalizable engine — adding volume profile later is plug-in
- All config in YAML. Fibonacci has modest weight pending Phase 4 backtest validation
- Do NOT write Stage 1 Codex prompt until Stage F is complete

### web-ui design (for reference when building)
React/TypeScript analysis console — NOT a holdings tracker. User-friendly interface with text fields and buttons for API calls, results in formatted tables/cards/reports not raw JSON.
- Progressive disclosure: leads with merged confluence verdict (a+b) as headline, exposes a/b/signals/scores/risk/freshness on drill-down
- Entry-zone visual: price ladder showing current price vs support/resistance/buy zones/stop
- Prominently surface: confidence, data_freshness tags (LAST_CLOSE/DELAYED/MISSING), data_quality_score, risk flags as chips
- Forms: symbol + horizon + toggles for /analyze; universe + limit + filters for /screen/*
- Screener results: sortable table, score_breakdown expandable per row, trend_quality badges
- Do NOT write web-ui Codex prompt until Stage 1 is complete and real entry.fibonacci + entry.confluence JSON response shape is known

### Stage 2 design (for reference)
- Regime-conditioning: feed market_regime (already computed in regime.py) into entry/confluence assessment — pullback-buying in trending vs choppy regime behaves differently; note it in confluence verdict
- Conflict-aware narrative: LLM surfaces TENSION explicitly ("technicals say BUY, fundamentals say HOLD, here's why") rather than just restating numbers — richer and more useful without inventing values

### Future / deferred items
- pandas-ta dropped: hand-rolled indicators. Risk is correctness on canonical variants. Future task: add dev/test-only library (ta-lib or pandas-ta) to cross-check production indicator output within tolerance — especially Wilder's RSI/ATR smoothing, MACD EMA seeding, BB population vs sample stddev
- Real-time price providers (Alpaca free IEX, Finnhub free): low effort, optional adapters behind existing provider interface, only upgrades current-price field. Not needed for 2–4W horizon. Defer until 1D features built. Verify free-tier terms before adding
- Reddit API: access request submitted, awaiting approval. Plug-and-play gap already in trending.py — adding credentials is config-only, no code change
- StockTwits: API access restricted, skip unless changes
- SEC Form 4 insider clusters, unusual options activity, black swan event library, ETF flow: Phase 4 moat items
- Portfolio-aware recommendations (concentration warnings): optional future toggle on web-ui
- LLM-assisted weight tuning (Phase 4+ save-it): LLM proposes YAML weight adjustments (advisory only, never touches live path), each backtested by Phase 4 evaluator before adoption, human commits winning YAML. Gated on Phase 4 backtesting evaluator existing first
- FastAPI deprecation fixes: on_event → lifespan handlers, httpx → httpx2 in test client. Low priority cleanup

### System invariants (enforce on every change, every PR)
1. Never place trades or emit order instructions
2. Never fabricate missing data — tag missing, degrade, never crash
3. LLM only in narrator.py — zero LLM calls in any numeric path
4. All weights/thresholds in YAML, never hardcoded
5. Every result carries data_freshness + data_quality_score
6. Sentiment ≤ 15–20% of any weighted blend
7. After any API/model change: make postman → commit openapi/ + postman/
8. Git ops scoped to finance-monorepo only
9. Acyclic deps: screener → analyst → external only
10. Small targeted commits per module, no unsolicited refactors
