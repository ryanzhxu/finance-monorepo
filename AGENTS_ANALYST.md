# AGENTS.md — AI Stock Analyst (`finance-monorepo/analyst-service`)

> **Who built this**: Two high-school friends — one a software engineer (primary developer), one with finance/quant background. The finance partner owns the analytical framework and signal definitions; the engineering partner owns the implementation.
>
> **Who calls this service**:
> - `Portfolio Dashboard` — fetches recommendations to display in the stock detail panel (read-only display).
> - `Execution Engine` — fetches recommendations to decide whether to act on a signal (automated trading decisions).
>
> **Who this service calls**: External data providers (yfinance, Alpha Vantage, SEC EDGAR, optional: Reddit API, StockTwits API, financial news RSS). Optionally calls an LLM (via provider-neutral wrapper) for narrative synthesis. Never calls the Dashboard or Execution Engine.

---

## Project Identity

This is a **standalone analytical microservice** that accepts a stock symbol (and optional context), gathers multi-dimensional data, runs deterministic computations, and returns a structured analytical report with a directional recommendation (BUY / HOLD / SELL), confidence score, key catalysts, and risk flags.

The service is designed to be the **single source of analytical truth** for the whole system. Both the Dashboard and the Execution Engine are consumers; they must not duplicate analytical logic.

**This service never places trades. It only produces structured recommendations.**

---

## Service Architecture

```
analyst-service/
├── api/
│   ├── main.py              # FastAPI app
│   └── routers/
│       └── analysis.py      # /analyze and /batch endpoints
├── core/
│   ├── models.py            # Pydantic models for request/response contracts
│   ├── data_fetcher.py      # All external data fetching (market, fundamental, sentiment)
│   ├── technicals.py        # Deterministic technical indicator computation (NO AI)
│   ├── fundamentals.py      # EPS, valuation, analyst rating logic (NO AI)
│   ├── sentiment.py         # Optional: social/news sentiment scoring
│   ├── signals.py           # Individual signal → BUY/HOLD/SELL per dimension
│   ├── aggregator.py        # Weighted signal aggregation → final recommendation
│   └── narrator.py          # LLM call for narrative synthesis (AI-optional layer)
├── cache/                   # Simple file or Redis cache to avoid repeat API calls
└── tests/
```

The service is a standalone Python FastAPI app. It can live inside `finance-monorepo` as a new top-level package or as a sibling service. It must be startable independently:

```bash
uv run uvicorn analyst-service.api.main:app --port 8001
```

---

## Runtime

Environment variables:

```
# LLM (optional — narrative synthesis only)
AI_PROVIDER=
AI_API_KEY=
AI_MODEL=
AI_BASE_URL=

# Data sources (all optional; service degrades gracefully if missing)
ALPHA_VANTAGE_KEY=
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
STOCKTWITS_API_KEY=

# Cache
CACHE_TTL_SECONDS=300        # 5-minute default for market data
FUNDAMENTAL_CACHE_TTL=86400  # 24h for financials, ratings
```

---

## API Contract

### `POST /analyze`

Primary endpoint. Called by both the Dashboard and the Execution Engine.

**Request:**

```json
{
  "symbol": "NVDA",
  "asset_type": "STOCK",
  "horizon": "2-4W",
  "current_price": 135.20,
  "portfolio_context": {
    "held": true,
    "quantity": 50,
    "avg_cost": 112.40,
    "position_pct": 8.5
  },
  "include_narrative": true
}
```

- `horizon`: `"1D"` | `"1W"` | `"2-4W"` (default) | `"3-6M"`. Affects which indicators are weighted more heavily.
- `portfolio_context`: Optional. If provided, the narrative can comment on concentration risk.
- `include_narrative`: If `false`, skip the LLM call entirely and return only structured signals. The Execution Engine should always pass `false` — it consumes structured signals only.

**Response:**

```json
{
  "symbol": "NVDA",
  "generated_at": "2025-10-15T14:32:00Z",
  "data_freshness": {
    "price": "live",
    "fundamentals": "2025-09-30",
    "sentiment": "2025-10-15T13:00:00Z",
    "13f": "2025-08-14"
  },
  "technicals": {
    "rsi_14": 42.1,
    "macd": { "macd_line": -0.32, "signal_line": -0.18, "histogram": -0.14 },
    "ma_50": 131.50,
    "ma_200": 118.20,
    "support": 128.00,
    "resistance": 140.00,
    "atr_14": 4.21,
    "bb_upper": 143.50,
    "bb_lower": 126.90,
    "volume_ratio_90d": 1.35,
    "rsi_weekly": 51.2
  },
  "fundamentals": {
    "eps_surprise_pct": 18.0,
    "pe_percentile_5y": 62,
    "analyst_upgrades_30d": 2,
    "analyst_downgrades_30d": 0,
    "revenue_growth_yoy_pct": 122.0
  },
  "sentiment": {
    "put_call_ratio": 0.6,
    "iv_rank": 35,
    "reddit_mention_spike_24h_pct": 320,
    "reddit_positive_pct": 78,
    "short_interest_pct": 2.1,
    "institutional_net_shares_last_13f": 2300000
  },
  "macro": {
    "days_to_next_fomc": 12,
    "rate_cut_probability_pct": 68,
    "treasury_10y": 4.32,
    "vix": 18.4
  },
  "signals": [
    { "dimension": "RSI(14)",             "signal": "BUY",  "weight": 1.0, "note": "Approaching oversold at 42" },
    { "dimension": "MACD",                "signal": "SELL", "weight": 1.0, "note": "Bearish cross, histogram narrowing" },
    { "dimension": "MA 50/200",           "signal": "BUY",  "weight": 1.5, "note": "Golden cross in effect" },
    { "dimension": "Bollinger Bands",     "signal": "HOLD", "weight": 0.8, "note": "Price at mid-band" },
    { "dimension": "Volume",              "signal": "BUY",  "weight": 1.0, "note": "35% above 90-day average" },
    { "dimension": "EPS Surprise",        "signal": "BUY",  "weight": 2.0, "note": "+18% beat last quarter" },
    { "dimension": "Analyst Ratings",     "signal": "BUY",  "weight": 1.5, "note": "2 upgrades, 0 downgrades (30d)" },
    { "dimension": "PE Percentile",       "signal": "HOLD", "weight": 1.0, "note": "62nd percentile (5yr) — not cheap" },
    { "dimension": "Put/Call Ratio",      "signal": "BUY",  "weight": 1.0, "note": "0.6 — bullish sentiment" },
    { "dimension": "IV Rank",             "signal": "HOLD", "weight": 0.5, "note": "35% — low vol, options cheap" },
    { "dimension": "Institutional 13F",   "signal": "BUY",  "weight": 1.5, "note": "Net buy 2.3M shares (45d lag)" },
    { "dimension": "Macro (FOMC)",        "signal": "BUY",  "weight": 1.0, "note": "68% rate-cut probability in 12d" },
    { "dimension": "RSI Weekly",          "signal": "HOLD", "weight": 1.5, "note": "51 — neutral long-term momentum" },
    { "dimension": "Support/Resistance",  "signal": "HOLD", "weight": 0.8, "note": "Mid-range between $128–$140" }
  ],
  "recommendation": {
    "direction": "BUY",
    "confidence": 0.72,
    "signal_vote": { "BUY": 8, "HOLD": 5, "SELL": 1 },
    "weighted_score": 0.61,
    "technical_target_high": 140.00,
    "technical_target_low": 128.00,
    "stop_loss_suggestion": 126.00,
    "horizon": "2-4W",
    "review_action": "add_watch",
    "risk_flags": ["export_controls_risk", "pe_elevated"]
  },
  "narrative": "NVDA shows a constructive risk/reward setup into the next FOMC. The 50/200 golden cross and strong institutional buying in the last 13F filing provide long-term structural support, while the short-term MACD cross is a headwind. The +18% EPS beat reduces downside thesis risk. Key risk: elevated PE at the 62nd 5-year percentile and ongoing export control uncertainty. Suggested action: hold current position, watch $128 support; consider adding on a confirmed bounce above $136 with a stop below $126."
}
```

**Rules for the `recommendation` object:**
- `direction` is determined by weighted signal voting. Each signal's `weight` is defined in config, not hardcoded (see Weights Config below).
- `confidence` is the weighted majority fraction (0.0–1.0).
- `stop_loss_suggestion` = support level − 1× ATR (deterministic, no AI).
- `review_action` maps to the Dashboard's action vocabulary: `add_watch` | `hold_monitor` | `trim_review` | `hedge_review` | `rebalance_review` | `exit_review`.
- `risk_flags` is a list of string codes. The Execution Engine uses these to apply additional risk gates.

---

### `POST /batch`

Accepts an array of up to 20 symbols. Returns an array of analysis results. Useful for the Dashboard's overnight pre-computation or the Execution Engine's watchlist scan.

```json
{ "symbols": ["NVDA", "AAPL", "TSLA"], "include_narrative": false }
```

---

### `GET /health`

Returns service status, data provider connectivity, and LLM availability.

---

## Signal Dimensions and Weights Config

Store weights in `analyst-service/config/signal_weights.yaml` (not hardcoded in Python):

```yaml
# Technical (short-term)
RSI_14: 1.0
MACD: 1.0
Bollinger_Bands: 0.8
Volume: 1.0

# Technical (long-term) — always include, weight higher
MA_50_200: 1.5
RSI_Weekly: 1.5

# Support/Resistance
Support_Resistance: 0.8

# Fundamental
EPS_Surprise: 2.0
Analyst_Ratings: 1.5
PE_Percentile: 1.0

# Capital flows / smart money
Institutional_13F: 1.5
Put_Call_Ratio: 1.0
IV_Rank: 0.5
Short_Interest: 0.8

# Macro
FOMC_Proximity: 1.0

# Sentiment (low weight by design — noise-heavy)
Reddit_Sentiment: 0.3
News_Sentiment: 0.5
```

**Rules:**
- Sentiment indicators collectively should not exceed 15–20% of the total weighted score.
- Fundamental indicators are the primary anchor.
- Long-term technical indicators (MA 200, weekly RSI) must always be computed and included.
- Adjust weights via the YAML file. Do not change weights in code.

---

## Computation Rules (Non-Negotiable)

1. **All technical indicators are computed with `pandas-ta` or pure `pandas` math.** No AI calls for any indicator.
2. **Support and resistance** use rolling swing highs/lows on daily OHLCV (20-period default window). Deterministic.
3. **Signal voting** is weighted arithmetic mean over all dimensions. Score > 0.2 → BUY, < -0.2 → SELL, otherwise HOLD. Thresholds configurable in YAML.
4. **LLM is called only in `narrator.py`**, only when `include_narrative=true`, and only after all structured data is assembled. The LLM receives the fully structured context (see prompt template below) and returns only the `narrative` string.
5. **Data freshness**: every data field must have a timestamp. Delayed data (13F: 45-day lag, earnings: quarterly) must be labelled. The `data_freshness` block in the response captures this.
6. **Cache**: market data cached for 5 minutes, fundamental data for 24 hours, sentiment for 1 hour. Never serve expired cache without flagging it.

---

## LLM Prompt Template (`narrator.py`)

Use this structured format to minimise tokens and maximise consistency. Pass the assembled data as context:

```
You are a cautious, evidence-based equity analyst. You do NOT make direct trading instructions.
You summarise the following structured data into a 3–5 sentence trade review note.
Tone: professional, risk-control-first. No fake certainty.

## Symbol: {symbol}
## Horizon: {horizon}
## Direction: {direction} (confidence: {confidence:.0%})

## Signals Summary
{signals_table}

## Key Metrics
- RSI(14): {rsi_14} | RSI Weekly: {rsi_weekly}
- MACD histogram: {macd_histogram}
- EPS Surprise: {eps_surprise_pct:+.1f}%
- Analyst upgrades/downgrades (30d): {upgrades}/{downgrades}
- Institutional 13F net: {institutional_net:,} shares ({13f_age_days}d ago)
- Days to FOMC: {days_to_fomc} | Rate cut probability: {rate_cut_pct:.0f}%

## Risk Flags
{risk_flags}

Write a concise trade review note. Do not repeat every number. Focus on the narrative logic.
End with: "Suggested review action: {review_action}."
```

---

## Data Providers and Fallback Strategy

| Data Type | Primary Source | Fallback | Notes |
|-----------|---------------|---------|-------|
| OHLCV (historical) | `yfinance` | Alpha Vantage | yfinance is free and sufficient |
| Live price | `yfinance` | Alpha Vantage free tier | |
| Fundamental (EPS, revenue) | `yfinance` | SEC EDGAR XBRL | SEC EDGAR is free and authoritative |
| 13F holdings | SEC EDGAR `/submissions/` | Manual parse | 45-day lag is expected and must be labelled |
| Analyst ratings | `yfinance` (summary) | Alpha Vantage premium | Degrade gracefully if unavailable |
| Options (P/C ratio, IV) | `yfinance` options chain | — | Compute IV rank from 52-week range |
| Reddit sentiment | Reddit API (r/wallstreetbets, r/stocks) | — | Optional; skip if no API credentials |
| News sentiment | RSS feeds (Reuters, Bloomberg, Yahoo Finance) | — | NLP via `transformers` (FinBERT) or simple keyword scoring |
| FOMC calendar | Federal Reserve website (static scrape) | Hardcoded near-term dates | Update quarterly |

**Graceful degradation**: if a data source is unavailable, omit that signal from the vote and log a warning. Never crash; never fabricate data.

---

## Adding New Indicators

To add a new signal dimension:

1. Implement computation in the appropriate module (`technicals.py`, `fundamentals.py`, `sentiment.py`).
2. Add a `signal` return value (BUY / HOLD / SELL) and a `note` string.
3. Add the weight to `signal_weights.yaml`.
4. Add the field to the `AnalysisResponse` Pydantic model.
5. Update the narrator prompt template if the field is narratively important.
6. Write a unit test in `tests/`.

---

## Black Swan Event Library (Phase 2)

Maintain a structured database of historical macro shock events:

```json
{
  "event_id": "covid_march_2020",
  "date": "2020-03-16",
  "type": "pandemic",
  "market_drawdown_pct": -34,
  "recovery_days": 126,
  "sectors_hit": ["travel", "hospitality", "energy"],
  "policy_response": "Fed emergency rate cut to 0%, QE unlimited",
  "notes": "VIX peaked at 82"
}
```

This library is a long-term moat asset. Build it incrementally. Do not block Phase 1 on it. When available, the analyst service can flag similarity to historical shock patterns in the narrative.

---

## Implementation Phases

### Phase 1 — MVP (implement first)
- [ ] FastAPI skeleton with `/analyze` and `/health`
- [ ] `data_fetcher.py`: yfinance OHLCV + fundamentals
- [ ] `technicals.py`: RSI, MACD, MA 50/200, Bollinger Bands, ATR, Volume ratio, Support/Resistance, weekly RSI
- [ ] `signals.py`: BUY/HOLD/SELL per indicator with configurable thresholds
- [ ] `aggregator.py`: weighted vote → direction + confidence
- [ ] `narrator.py`: LLM call with structured prompt (skipped if `include_narrative=false`)
- [ ] Cache layer (file-based or Redis)
- [ ] Unit tests for signal voting and indicator computation

### Phase 2 — Extend
- [ ] Fundamental layer: EPS surprise, analyst ratings, PE percentile
- [ ] Options data: Put/Call ratio, IV rank
- [ ] 13F institutional flow from SEC EDGAR
- [ ] Reddit/StockTwits sentiment (optional, low weight)
- [ ] FOMC calendar integration
- [ ] `/batch` endpoint

### Phase 3 — Moat
- [ ] Black swan event library
- [ ] Sector rotation signals (XLK, XLE, XLF relative strength)
- [ ] Backtesting module: compare past recommendations to actual price outcomes
- [ ] SEC Form 4 insider transaction monitoring

---

## What NOT to Do

- Do not use AI to compute RSI, MACD, support/resistance, or any arithmetic indicator.
- Do not call the Dashboard or Execution Engine from this service.
- Do not return a recommendation without a `data_freshness` block.
- Do not allow sentiment signals to dominate the weighted vote.
- Do not fabricate data if a provider is down — degrade gracefully.
- Do not hardcode LLM provider. Always read from environment.
- Do not include direct buy/sell order instructions in the narrative.
