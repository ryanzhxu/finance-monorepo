# Market Opportunity Discovery System — Implementation Specification

> **Target audience:** an AI coding agent (Codex) implementing this system end to end.
> **Status:** finalized design spec. Build in the phase order in §17. Do not skip the constraints in §2 and §19.
> **Supersedes:** the standalone `AGENTS_ANALYST.md`. The analyst service described there is now **one service inside a monorepo**; its contract is preserved and extended here.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [System Goals, Non-Goals, and Hard Constraints](#2-system-goals-non-goals-and-hard-constraints)
3. [Architecture & Service Boundaries](#3-architecture--service-boundaries)
4. [Repository Layout](#4-repository-layout)
5. [Shared Package (`shared/`)](#5-shared-package-shared)
6. [Data Provider Strategy & Fallbacks](#6-data-provider-strategy--fallbacks)
7. [Data Freshness & Data Quality Model](#7-data-freshness--data-quality-model)
8. [Analyst Service — Single-Stock Analysis](#8-analyst-service--single-stock-analysis)
9. [Entry-Price Engine (Deterministic)](#9-entry-price-engine-deterministic)
10. [Scoring Models (Deterministic, YAML-Weighted)](#10-scoring-models-deterministic-yaml-weighted)
11. [Screener Service — Undervalued / Opportunity Screens](#11-screener-service--undervalued--opportunity-screens)
12. [Screener Service — Trending / Discussion Screens](#12-screener-service--trending--discussion-screens)
13. [Trending Buyability Pipeline](#13-trending-buyability-pipeline)
14. [Market Regime & Sector Rotation](#14-market-regime--sector-rotation)
15. [API Contracts (All Services)](#15-api-contracts-all-services)
16. [Caching Strategy](#16-caching-strategy)
17. [Implementation Phases](#17-implementation-phases)
18. [Backtesting & Validation](#18-backtesting--validation)
19. [Risk Controls & "What NOT To Do"](#19-risk-controls--what-not-to-do)
20. [Testing Plan](#20-testing-plan)
21. [Codex Implementation Instructions](#21-codex-implementation-instructions)
22. [Additional Recommendations (with rationale)](#22-additional-recommendations-with-rationale)

---

## 1. Project Overview

This system is an **AI-assisted market opportunity discovery platform** for US equities. It does two things:

1. **Deep single-stock analysis** — given a symbol, return a directional call (BUY / HOLD / SELL), confidence, a full deterministic indicator set, practical entry/exit price levels, risk flags, data freshness, and an optional LLM-written narrative.
2. **Market-wide discovery** — scan a universe of stocks and surface the most undervalued, most attractive, and most unusually-discussed names, ranked transparently, then route the best candidates back through the analyst for a buyability verdict.

The analytical philosophy (from the project's design guide) is fixed: **AI's job is to find non-consensus structural skew inside known information**, not to predict black swans. Alpha comes from **data uniqueness and disciplined deterministic scoring**, not from a clever model. Numbers are computed; the LLM only explains.

**The system never places trades.** It emits structured recommendations and risk flags that downstream consumers may act on.

---

## 2. System Goals, Non-Goals, and Hard Constraints

### Goals
- Accuracy, thoroughness, explainability, and risk-awareness, in that priority order.
- Every score and price level is **deterministic and reproducible** from structured data.
- Every result is **explainable**: the user can see the breakdown that produced the rank.
- Graceful degradation when a data source is down; reduced confidence rather than failure.

### Non-Goals
- No trade execution, order routing, or brokerage integration.
- No real-time tick streaming or HFT-grade latency. **Speed is explicitly secondary to quality.** A screen taking minutes is acceptable if it improves the result.
- No options pricing engine of our own; we consume vendor IV/greeks where available.
- No portfolio optimization solver (the dashboard may show concentration warnings only).

### Hard Constraints (non-negotiable — enforce in code review)
1. **The system must not place trades.**
2. **The system must not express fake certainty.** Confidence is always reported; "unknown" is a valid state.
3. **AI/LLM must never compute deterministic indicators or scores.** RSI, MACD, ATR, support/resistance, valuation percentiles, opportunity scores — all pure `pandas`/`numpy`/`pandas-ta`.
4. **The LLM is used only for narrative synthesis and natural-language explanation**, and only after all structured data is assembled.
5. **Never fabricate missing values.** Missing data is labelled `missing` and lowers the data-quality score and confidence.
6. **All numerical price levels come from structured data.** The narrative may *explain* a level but may never *invent* one.

---

## 3. Architecture & Service Boundaries

```text
finance-monorepo/
├── analyst-service       # Deep single-stock analysis (FastAPI :8001)
├── screener-service      # Market-wide discovery & ranking (FastAPI :8002)
├── execution-engine      # Consumes recommendations + risk flags ONLY (no analysis)
├── portfolio-dashboard   # UI: analysis, screens, entry zones, risk, explanations
└── shared                # Pydantic models, enums, scoring config loader, data-quality utils
```

### Dependency direction (must be acyclic)

```text
portfolio-dashboard ─┐
                     ├─► screener-service ─► analyst-service ─► (external data providers)
execution-engine ────┘                    ▲
                                           │
              screener-service also calls ─┘ analyst-service for candidate deep-dives
```

**Rules:**
- `analyst-service` is the **single source of analytical truth**. It depends on **nothing internal** except `shared`. It never calls the screener, dashboard, or execution engine.
- `screener-service` performs discovery and ranking. It **may call `analyst-service`** for deep analysis of shortlisted candidates (`include_analysis=true`). It must function (rank on its own cheaper scores) even if the analyst is unavailable.
- `execution-engine` **performs no analysis**. It consumes structured recommendations + `risk_flags` and applies its own gates. (Implement as a thin stub in this project; it is a consumer contract, not a trading bot.)
- `portfolio-dashboard` is read-only display: single-stock analysis, top undervalued, top trending, top opportunity, best entry zones, risk flags, and a per-stock "why ranked" breakdown.
- All shared types live in `shared/` and are imported by every service — **no duplicated model definitions**.

### Tech stack
- Python 3.11+, managed with `uv`.
- `FastAPI` + `uvicorn` per service.
- `pandas`, `numpy`, `pandas-ta` for indicators; `pydantic` v2 for contracts.
- Data: `yfinance` (primary), Alpha Vantage (fallback), SEC EDGAR (fundamentals/13F/Form 4), Reddit/StockTwits/RSS (sentiment).
- Cache: Redis if available, else file cache (see §16).
- Optional LLM via provider-neutral wrapper (env-configured).
- Frontend: dashboard may be React/TypeScript (developer's existing stack) consuming the two service APIs.

---

## 4. Repository Layout

```text
finance-monorepo/
├── pyproject.toml                 # uv workspace root
├── README.md
├── shared/
│   ├── pyproject.toml
│   └── shared/
│       ├── __init__.py
│       ├── enums.py               # Direction, EntryAssessment, TrendQuality, Freshness, RiskFlag...
│       ├── models.py              # ALL cross-service Pydantic models (request/response/data)
│       ├── config_loader.py       # YAML weight/threshold loading + validation
│       ├── data_quality.py        # freshness tagging + quality scoring helpers
│       └── time_utils.py          # market calendar, age-in-days, staleness math
│
├── analyst-service/
│   ├── pyproject.toml
│   ├── config/
│   │   ├── signal_weights.yaml
│   │   ├── signal_thresholds.yaml
│   │   └── entry_rules.yaml
│   ├── api/
│   │   ├── main.py                # FastAPI app :8001
│   │   └── routers/analysis.py    # /analyze /batch /entry /health
│   ├── core/
│   │   ├── data_fetcher.py        # all external fetching
│   │   ├── technicals.py          # NO AI — RSI/MACD/ATR/BB/MA/S-R/volume/gaps
│   │   ├── fundamentals.py        # NO AI — EPS surprise, valuation percentiles, ratings
│   │   ├── sentiment.py           # optional social/news scoring
│   │   ├── signals.py             # per-dimension BUY/HOLD/SELL
│   │   ├── entry_engine.py        # NO AI — deterministic price levels (§9)
│   │   ├── aggregator.py          # weighted vote → recommendation
│   │   └── narrator.py            # LLM narrative ONLY
│   ├── cache/
│   └── tests/
│
├── screener-service/
│   ├── pyproject.toml
│   ├── config/
│   │   ├── scoring_weights.yaml   # valuation/growth/quality/momentum/... weights (§10)
│   │   ├── universes.yaml         # SP500/Nasdaq100/Dow/Russell membership sources
│   │   ├── filters.yaml           # liquidity / mcap / penny-stock / meme guards
│   │   └── trend_rules.yaml       # trend classification thresholds (§12)
│   ├── api/
│   │   ├── main.py                # FastAPI app :8002
│   │   └── routers/screen.py      # /screen/* endpoints (§15)
│   ├── core/
│   │   ├── universe.py            # resolve & cache universe membership
│   │   ├── fundamentals_bulk.py   # batch valuation/growth/quality metrics
│   │   ├── scoring.py             # NO AI — deterministic factor scores → opportunity score
│   │   ├── trending.py            # mention counts, acceleration, sentiment, classification
│   │   ├── buyability.py          # orchestrates analyst calls for shortlist (§13)
│   │   ├── regime.py              # market regime + sector rotation (§14)
│   │   └── analyst_client.py      # HTTP client to analyst-service
│   ├── cache/
│   └── tests/
│
├── execution-engine/              # consumer stub: reads recs + risk_flags, applies gates
│   ├── pyproject.toml
│   ├── engine.py
│   └── tests/
│
├── portfolio-dashboard/           # UI (React/TS or chosen stack)
│
└── backtesting/                   # shared backtest harness + recommendation store (§18)
    ├── store.py                   # append-only recommendation log
    ├── evaluator.py               # forward-return & hit-rate computation
    └── tests/
```

---

## 5. Shared Package (`shared/`)

All enums and cross-service models live here. Do not redefine them per service.

### `shared/enums.py`
```python
from enum import Enum

class Direction(str, Enum):
    BUY = "BUY"; HOLD = "HOLD"; SELL = "SELL"

class EntryAssessment(str, Enum):
    BUY_NOW = "buy_now"
    WAIT_FOR_PULLBACK = "wait_for_pullback"
    WAIT_FOR_BREAKOUT = "wait_for_breakout_confirmation"
    AVOID = "avoid"
    SHORT_TERM_TRADE_ONLY = "short_term_trade_only"
    LONG_TERM_CANDIDATE = "long_term_investment_candidate"

class TrendQuality(str, Enum):
    HIGH_QUALITY = "high_quality_trend"
    NEWS_DRIVEN = "news_driven_trend"
    EARNINGS_DRIVEN = "earnings_driven_trend"
    MEME_FOMO = "meme_fomo_trend"
    PUMP_RISK = "likely_pump_risk"
    OVEREXTENDED = "too_late_overextended"
    EARLY_ACCUMULATION = "early_accumulation"

class Freshness(str, Enum):
    LIVE = "live"; DELAYED = "delayed"; QUARTERLY = "quarterly"
    STALE = "stale"; MISSING = "missing"; ESTIMATED = "estimated"

class ScreenType(str, Enum):
    UNDERVALUED = "undervalued"; TRENDING = "trending"
    OPPORTUNITIES = "opportunities"; WATCHLIST = "watchlist"; CUSTOM = "custom"

class Universe(str, Enum):
    SP500 = "SP500"; NASDAQ100 = "NASDAQ100"; DOW = "DOW"
    RUSSELL1000 = "RUSSELL1000"; RUSSELL2000 = "RUSSELL2000"
    WATCHLIST = "WATCHLIST"; CUSTOM = "CUSTOM"

class MarketRegime(str, Enum):
    RISK_ON = "risk_on"; NEUTRAL = "neutral"; RISK_OFF = "risk_off"
```

`RiskFlag` is an open string vocabulary (codes, not free text). Reserve at minimum:
`earnings_soon`, `valuation_elevated`, `export_controls_risk`, `low_liquidity`, `penny_stock`,
`meme_behavior`, `overextended`, `high_short_interest`, `sec_investigation`, `insider_selling_cluster`,
`stale_data`, `low_data_quality`, `macro_event_window`, `gap_risk`.

### `shared/models.py`
Holds all request/response models referenced in §8, §9, §11, §12, §13, §15. Build them from the JSON schemas in those sections. Every analysis/screen result model **must** carry:
- `data_freshness: dict[str, Freshness | str]` (per-field tag or ISO timestamp)
- `data_quality_score: int` (0–100, see §7)
- `confidence: float` (0.0–1.0)

---

## 6. Data Provider Strategy & Fallbacks

| Data type | Primary | Fallback | Notes |
|---|---|---|---|
| OHLCV historical | `yfinance` | Alpha Vantage | free, sufficient for indicators |
| Live/last price | `yfinance` | Alpha Vantage free tier | tag `live` vs `delayed` |
| Fundamentals (EPS, revenue, margins, FCF) | `yfinance` | SEC EDGAR XBRL | EDGAR authoritative |
| Valuation history (P/E, P/B, P/S, EV/EBITDA) | computed from price + EDGAR | Alpha Vantage | compute percentiles ourselves |
| Analyst ratings / revisions | `yfinance` | Alpha Vantage premium | degrade gracefully |
| Options (P/C ratio, IV) | `yfinance` options chain | — | compute IV rank from 52wk range |
| 13F institutional holdings | SEC EDGAR `/submissions/` | manual parse | **45-day lag — always label `delayed`** |
| Insider trades (Form 4) | SEC EDGAR | — | cluster detection only |
| Reddit sentiment | Reddit API (r/wallstreetbets, r/stocks, r/investing) | skip | optional; low weight |
| StockTwits | StockTwits API (has sentiment tags) | skip | official sentiment field |
| X / Twitter | API if practical | skip | highest noise; optional |
| Financial news | RSS (Reuters, Bloomberg, Yahoo Finance) | skip | FinBERT or keyword scoring |
| Yahoo trending tickers | Yahoo Finance trending endpoint | skip | seed for trending screen |
| FOMC / econ calendar | Fed website scrape | hardcoded near-term dates | refresh quarterly |
| Universe membership | Wikipedia / index provider lists | cached snapshot | refresh weekly (§11) |

**Fallback strategy:** primary → fallback → omit-and-flag. If a source is unavailable, **omit that signal from the vote**, log a warning, set the field's freshness to `missing`, and reduce `confidence` and `data_quality_score`. Never crash; never fabricate.

---

## 7. Data Freshness & Data Quality Model

Every result carries a `data_freshness` map and a `data_quality_score` (0–100).

**Freshness tagging rules** (compute in `shared/data_quality.py`):
- `live` — price fetched < 1 min ago intraday.
- `delayed` — quote delayed feed, or any data 1 min–same-session old.
- `quarterly` — last reported financials / 13F (label the as-of date; 13F is always `delayed` due to 45-day lag).
- `stale` — past its cache TTL but still served (must be flagged, never served silently).
- `missing` — provider returned nothing.
- `estimated` — derived/interpolated value (e.g., consensus estimate). Must be explicitly tagged; never silently mixed with reported values.

**Data-quality score (deterministic):**
```text
start at 100
for each required field group (price, technicals, fundamentals, ratings, flows, sentiment, macro):
    missing       → subtract group_penalty (configurable; default 15)
    stale          → subtract group_penalty * 0.5
    estimated      → subtract group_penalty * 0.25
clamp to [0, 100]
```
`confidence` reported to the user is multiplied by `data_quality_score/100` so degraded data visibly lowers confidence. A result with quality < 50 must add the `low_data_quality` risk flag.

---

## 8. Analyst Service — Single-Stock Analysis

The existing `/analyze` contract is **preserved** and extended with the entry block (§9). Reproduced and extended here.

### `POST /analyze`
**Request**
```json
{
  "symbol": "NVDA",
  "asset_type": "STOCK",
  "horizon": "2-4W",
  "current_price": 135.20,
  "portfolio_context": { "held": true, "quantity": 50, "avg_cost": 112.40, "position_pct": 8.5 },
  "include_narrative": true,
  "include_entry": true
}
```
- `horizon`: `"1D" | "1W" | "2-4W"(default) | "3-6M"` — reweights short vs long indicators.
- `include_narrative=false` → skip LLM entirely (execution-engine always passes false).
- `include_entry=true` → include the deterministic entry block (§9).

**Response** (extends the original; new/changed fields marked):
```json
{
  "symbol": "NVDA",
  "generated_at": "2026-06-12T14:32:00Z",
  "data_freshness": { "price": "live", "fundamentals": "2026-03-31", "sentiment": "2026-06-12T13:00:00Z", "13f": "2026-05-15" },
  "data_quality_score": 86,
  "technicals": {
    "rsi_14": 42.1, "rsi_weekly": 51.2,
    "macd": { "macd_line": -0.32, "signal_line": -0.18, "histogram": -0.14 },
    "ma_20": 132.10, "ma_50": 131.50, "ma_200": 118.20,
    "support_levels": [128.0, 122.5], "resistance_levels": [140.0, 147.0],
    "atr_14": 4.21, "bb_upper": 143.5, "bb_lower": 126.9, "bb_mid": 135.2,
    "volume_ratio_90d": 1.35,
    "dist_from_ma20_pct": 2.3, "dist_from_ma50_pct": 2.8, "dist_from_ma200_pct": 14.4,
    "recent_gap_pct": 0.0, "recent_earnings_gap_pct": 6.2,
    "breakout_state": "none"
  },
  "fundamentals": {
    "eps_surprise_pct": 18.0, "pe_percentile_5y": 62,
    "analyst_upgrades_30d": 2, "analyst_downgrades_30d": 0,
    "revenue_growth_yoy_pct": 122.0, "fcf_trend": "rising", "gross_margin_pct": 75.0
  },
  "sentiment": { "put_call_ratio": 0.6, "iv_rank": 35, "reddit_mention_spike_24h_pct": 320, "reddit_positive_pct": 78, "short_interest_pct": 2.1, "institutional_net_shares_last_13f": 2300000 },
  "macro": { "days_to_next_fomc": 12, "rate_cut_probability_pct": 68, "treasury_10y": 4.32, "vix": 18.4, "market_regime": "neutral" },
  "signals": [
    { "dimension": "RSI(14)", "signal": "BUY", "weight": 1.0, "note": "Approaching oversold at 42" }
    /* ...full signal list as in original AGENTS_ANALYST.md... */
  ],
  "entry": { /* see §9 */ },
  "recommendation": {
    "direction": "BUY",
    "confidence": 0.72,
    "signal_vote": { "BUY": 8, "HOLD": 5, "SELL": 1 },
    "weighted_score": 0.61,
    "technical_target_high": 140.0,
    "technical_target_low": 128.0,
    "stop_loss_suggestion": 126.0,
    "horizon": "2-4W",
    "review_action": "add_watch",
    "risk_flags": ["export_controls_risk", "pe_elevated"]
  },
  "narrative": "…optional LLM text; explains, never invents numbers…"
}
```

**Recommendation rules (unchanged from original, deterministic):**
- `direction` from weighted signal vote; weights from `signal_weights.yaml`.
- `confidence` = weighted majority fraction × (`data_quality_score`/100).
- `stop_loss_suggestion` = nearest support − 1×ATR.
- `review_action ∈ {add_watch, hold_monitor, trim_review, hedge_review, rebalance_review, exit_review}`.
- Sentiment dimensions collectively ≤ 15–20% of total weight.
- Long-term technicals (MA200, weekly RSI) always computed and included.

### `POST /batch`
Up to 20 symbols, returns array of analyses. `include_narrative` defaults false.

### `POST /entry`
Returns only the entry block (§9) for a symbol — used by the screener's buyability pass when full analysis is not needed.

### `GET /health`
Service status, provider connectivity, LLM availability, cache backend.

---

## 9. Entry-Price Engine (Deterministic)

`analyst-service/core/entry_engine.py`. **No AI.** All levels are computed from OHLCV + indicators. The narrator may explain them; it may not change them.

### Inputs
Daily OHLCV (≥ 1y), `current_price`, ATR(14), Bollinger Bands(20,2), RSI(14), MACD, MA20/50/200, swing-based support/resistance arrays, recent volume ratio, recent earnings gap, recent breakout/breakdown flag.

### Computed levels (formulas; tune constants in `entry_rules.yaml`)
- **Support levels**: rolling swing lows over a 20-bar window, clustered (merge levels within 1×ATR), sorted descending, nearest first.
- **Resistance levels**: rolling swing highs, same clustering.
- **ideal_buy_zone** `[low, high]`: band around the nearest strong support:
  `low = support1 − 0.25×ATR`, `high = max(support1 + 0.5×ATR, MA20)` — only valid if `current_price` is within or above this band and not extended (see extension check).
- **conservative_entry_price**: at/just above `support1` confirmed by RSI > 35 and price reclaiming MA20; the lower-risk fill.
- **aggressive_entry_price**: current price if `current_price ≤ MA20 × 1.03` and RSI < 60 (buying into mild strength).
- **breakout_buy_level**: `resistance1 × (1 + breakout_buffer)` (default buffer 0.5%), requires volume confirmation (`volume_ratio_90d ≥ 1.5`) flagged separately as `breakout_volume_confirmed`.
- **stop_loss_suggestion**: `support1 − 1×ATR` (matches recommendation rule).
- **invalidation_level**: the price below which the bullish thesis is broken — `min(support2, MA50 − 1×ATR)`; if breached, thesis void.
- **resistance_levels / support_levels**: full arrays returned.
- **risk_reward_ratio**: `(technical_target_high − entry) / (entry − stop_loss_suggestion)` using `aggressive_entry_price` as `entry`; report to 2 decimals.
- **is_overextended** (bool): true if any of:
  `dist_from_ma20_pct > extension_threshold` (default 10%), `price > bb_upper`, `rsi_14 > 75`.
- **entry_assessment** (enum, decision table — evaluate top-down, first match wins):

| Condition | `entry_assessment` |
|---|---|
| `is_overextended` and trend strong | `wait_for_pullback` |
| price below `support1` and RSI < 30 and direction not SELL | `buy_now` (oversold reclaim) |
| price consolidating just under `resistance1`, volume rising | `wait_for_breakout_confirmation` |
| inside `ideal_buy_zone`, not overextended | `buy_now` |
| direction SELL, or `invalidation_level` breached, or `meme_behavior` flag | `avoid` |
| trend strong + fundamentals weak | `short_term_trade_only` |
| fundamentals strong + valuation reasonable + long horizon | `long_term_investment_candidate` |
| otherwise | `wait_for_pullback` |

### Entry block schema
```json
{
  "current_price": 135.20,
  "ideal_buy_zone": [127.0, 132.0],
  "aggressive_entry_price": 134.0,
  "conservative_entry_price": 128.5,
  "breakout_buy_level": 140.7,
  "support_levels": [128.0, 122.5],
  "resistance_levels": [140.0, 147.0],
  "stop_loss_suggestion": 123.8,
  "invalidation_level": 119.0,
  "risk_reward_ratio": 2.4,
  "is_overextended": false,
  "breakout_volume_confirmed": false,
  "entry_assessment": "buy_now",
  "reason": "Price inside ideal buy zone near $128 support; RSI 42 not overbought; R/R 2.4."
}
```
`reason` here is a **deterministic templated string**, not LLM output. The LLM narrative (separate field) may elaborate.

---

## 10. Scoring Models (Deterministic, YAML-Weighted)

All factor scores are 0–100, computed in `screener-service/core/scoring.py` with **no AI**. Each factor score is built from sub-metrics normalized to 0–100 (percentile or min-max within the universe), then combined with weights from `scoring_weights.yaml`. The final `opportunity_score` is a weighted blend. Always return the full breakdown.

### Factor definitions
- **valuation_score** — *not absolute P/E.* Blend of: current P/E, P/B, P/S, EV/EBITDA each scored as a **percentile within the stock's own 5-year history** (cheap = high score), plus a **sector-relative percentile**, adjusted up for high growth/margins (a low multiple on a shrinking business is not cheap — penalize via revenue/FCF trend gate).
- **growth_score** — revenue growth YoY, EPS growth YoY, forward revenue/EPS estimate trend, FCF growth.
- **quality_score** — gross/operating margins, ROE/ROIC, debt/equity, FCF positivity & stability, earnings quality (accruals: net income vs operating cash flow divergence).
- **momentum_score** — 3M/6M price return, distance above rising MA50/200, RSI regime (trend, not overbought spike).
- **analyst_revision_score** — net upgrades − downgrades (30/90d), estimate revision direction & magnitude.
- **institutional_accumulation_score** — last-13F net share change (label `delayed` 45d), trend across last 2 filings.
- **insider_activity_score** — Form 4 net buying vs selling, cluster buys positive, cluster sells negative; neutral if none.
- **risk_score** — *higher = riskier* (so it **subtracts**). Built from: volatility (ATR%/beta), short interest, liquidity, earnings proximity, valuation extension, macro-event window, meme behavior. See risk flags in §5.
- **liquidity** and **volatility** feed both filters (§ filters.yaml) and `risk_score`.

### Opportunity score
```text
opportunity_score =
    w_val   * valuation_score
  + w_grw   * growth_score
  + w_qual  * quality_score
  + w_mom   * momentum_score
  + w_rev   * analyst_revision_score
  + w_inst  * institutional_accumulation_score
  + w_ins   * insider_activity_score
  − w_risk  * risk_score
  (then clamp 0–100, normalize by sum of positive weights)
```

### `scoring_weights.yaml` (example; all configurable, never hardcoded)
```yaml
opportunity:
  valuation: 0.22
  growth: 0.16
  quality: 0.16
  momentum: 0.12
  analyst_revision: 0.10
  institutional_accumulation: 0.10
  insider_activity: 0.04
  risk: 0.10            # subtracted
# sentiment/trend weights live in trend_rules.yaml; sentiment capped ≤ 0.20 of any blend
regime_adjustments:
  risk_off: { momentum: -0.04, quality: +0.04, risk: +0.04 }
  risk_on:  { momentum: +0.04, growth: +0.02 }
```

Every screener result must expose `score_breakdown` so the dashboard can show **why** a stock ranked highly.

---

## 11. Screener Service — Undervalued / Opportunity Screens

### Universe resolution (`universe.py`)
Resolve `Universe` enum to ticker lists. Sources: index membership snapshots (Wikipedia/provider lists) cached weekly in `cache/universes/`. `WATCHLIST` and `CUSTOM` come from request payload. Apply **filters before scoring** (`filters.yaml`):
```yaml
min_market_cap_usd: 1000000000      # avoid micro-caps
min_avg_dollar_volume_usd: 5000000  # liquidity floor
exclude_penny_stocks: true          # price < $5 → drop unless explicitly allowed
exclude_otc: true
meme_behavior_guard: true           # flag, don't auto-drop, but cap their score
```

### Pipeline
1. Resolve universe → filter (liquidity, mcap, penny, OTC).
2. Bulk-fetch fundamentals & valuation history (`fundamentals_bulk.py`), batched with caching (fundamentals TTL 24h).
3. Compute factor scores + `opportunity_score` (§10), applying `regime_adjustments` from current regime (§14).
4. Rank descending; take `limit`.
5. If `include_analysis=true`, call `analyst-service /entry` (or `/analyze`) per top candidate to attach entry assessment + risk flags.
6. Build deterministic `reason` strings from the score breakdown; if `include_narrative=true`, ask LLM to phrase the reason more readably (explanation only).

### Result item schema
```json
{
  "rank": 1,
  "symbol": "XYZ",
  "screen_type": "undervalued",
  "opportunity_score": 84,
  "valuation_score": 91,
  "growth_score": 76,
  "quality_score": 82,
  "momentum_score": 64,
  "analyst_revision_score": 70,
  "institutional_accumulation_score": 80,
  "insider_activity_score": 50,
  "risk_score": 38,
  "score_breakdown": { "valuation": {"pe_5y_pctile": 8, "sector_rel_pctile": 22, "...": 0} },
  "data_freshness": { "fundamentals": "2026-03-31", "price": "live" },
  "data_quality_score": 88,
  "reason": "Trading near 5-year low valuation percentile while revenue and FCF continue growing.",
  "recommended_action": "analyze_deeper",
  "risk_flags": ["earnings_soon"]
}
```
`recommended_action ∈ {analyze_deeper, watch, skip}`.

---

## 12. Screener Service — Trending / Discussion Screens

`trending.py`. The goal is **unusual change in discussion**, not raw popularity. Mega-caps (NVDA/TSLA/AAPL) are always discussed — the signal is **acceleration**, not level.

### Metrics (per candidate)
- `mention_count_24h`, `mention_count_3d`, `mention_count_5d`
- `mention_growth_3d_pct`, `mention_growth_5d_pct` (vs trailing baseline — use the stock's own 30-day average daily mentions as the baseline so big names don't dominate)
- `acceleration` = second derivative of mention count (rising fast vs plateauing)
- `sentiment_score` (−1..+1), `sentiment_change` (vs trailing), `positive_neutral_negative_ratio`
- `retail_fomo_risk` (0–100): high when growth is extreme **and** sentiment is euphoric **and** the source is retail-dominated (WSB) → **contrarian caution**, not a buy signal
- `news_catalyst`: detected catalyst type or `none`
- `institutional_account_participation`: share of mentions from credible/pro accounts (raises trend quality)

### Sources
Reddit (WSB/stocks/investing), StockTwits (has sentiment tags), X/Twitter (optional), financial-news RSS, Yahoo trending tickers as a seed list. Sentiment via FinBERT or, if unavailable, keyword scoring. All sentiment-derived inputs are capped (§10) and `delayed`/`estimated`-tagged appropriately.

### Trend classification (`trend_rules.yaml` thresholds → `TrendQuality`)
Decision logic (first match wins):
| Condition | classification |
|---|---|
| strong news_catalyst + positive sentiment + pro participation | `news_driven_trend` |
| catalyst == earnings within window | `earnings_driven_trend` |
| high acceleration + early (still low absolute mentions) + improving fundamentals | `early_accumulation` |
| high quality across the board (catalyst + breadth + pro accounts + fundamentals OK) | `high_quality_trend` |
| extreme growth + euphoric sentiment + retail-dominated + no real catalyst | `meme_fomo_trend` |
| meme + thin liquidity + vertical price + extreme short interest | `likely_pump_risk` |
| trend mature + price overextended (§9 `is_overextended`) | `too_late_overextended` |

### Result item schema
```json
{
  "symbol": "PLTR",
  "screen_type": "trending",
  "mention_count_24h": 4200,
  "mention_count_3d": 11800,
  "mention_count_5d": 16100,
  "mention_growth_3d_pct": 280,
  "mention_growth_5d_pct": 410,
  "acceleration": 1.7,
  "sentiment_score": 0.62,
  "sentiment_change": 0.18,
  "pos_neu_neg_ratio": [0.68, 0.20, 0.12],
  "retail_fomo_risk": 71,
  "news_catalyst": "analyst_upgrade",
  "trend_quality": "news_driven_trend",
  "institutional_account_participation": 0.22,
  "data_freshness": { "sentiment": "2026-06-12T13:00:00Z" },
  "data_quality_score": 74,
  "risk_flags": ["meme_behavior"]
}
```

---

## 13. Trending Buyability Pipeline

`buyability.py`. After trending detection, run each candidate through the analyst (`/analyze` with `include_entry=true`) and combine the trend verdict with the technical+fundamental verdict.

### Logic
- Pull `trend_quality` + `sentiment_score` (from §12) and `technical_state` + `fundamental_state` + entry block (from analyst).
- `technical_state ∈ {oversold, neutral, extended, overextended, breakout}` derived deterministically from §9 (`is_overextended`, RSI, distance from MAs).
- `fundamental_state ∈ {strong, mixed, weak}` from §10 quality+growth+valuation.
- Map to a single `entry_assessment` (reuse §9 enum) via a decision table:

| trend | fundamentals | technicals | verdict |
|---|---|---|---|
| strong | strong | overextended | `wait_for_pullback` ("good company, bad entry") |
| meme/pump | weak | any | `avoid` ("bad company, hype only") |
| early_accumulation | strong | not extended | `long_term_investment_candidate` ("strong trend, still early") |
| any | strong | breakout + volume | `wait_for_breakout_confirmation` |
| strong | mixed | not extended | `short_term_trade_only` |
| overextended (any) | any | overextended | `too_late` → `avoid` or `wait_for_pullback` |

### Output schema
```json
{
  "symbol": "PLTR",
  "trend_score": 94,
  "sentiment_score": 81,
  "technical_state": "overextended",
  "fundamental_state": "strong",
  "entry_assessment": "wait_for_pullback",
  "ideal_buy_zone": [145, 152],
  "current_price": 168,
  "data_quality_score": 79,
  "reason": "Strong trend and fundamentals, but price is extended 14% above 20D MA."
}
```

---

## 14. Market Regime & Sector Rotation

`regime.py`. Used to adjust scoring weights (§10 `regime_adjustments`) and to add macro risk context.

- **Market regime** (`MarketRegime`): deterministic from VIX level/trend, 2Y-10Y yield-curve slope, SPY/QQQ position vs MA200, and FOMC proximity. e.g. VIX > 25 rising + SPY below MA200 → `risk_off`.
- **Sector rotation**: relative strength of sector ETFs (XLK/XLE/XLF/XLV/XLY/XLP/XLI/XLU/XLB/XLRE/XLC) over 1M/3M; report leaders/laggards and rotation direction. Boost momentum scoring for stocks in leading sectors; flag laggards.
- **ETF flow** (if a flow source is available): weekly net creation/redemption for SPY/QQQ as a breadth confirmation; optional, degrade gracefully.
- Regime is attached to analyst `macro` block and to every screen response header.

---

## 15. API Contracts (All Services)

### Analyst service (`:8001`)
- `POST /analyze` — §8
- `POST /batch` — §8
- `POST /entry` — §9 block only
- `GET /health`

### Screener service (`:8002`)
```http
POST /screen/undervalued
POST /screen/trending
POST /screen/opportunities
POST /screen/watchlist
POST /screen/custom
GET  /screen/health
GET  /screen/regime          # current market regime + sector rotation
```

**Request (all `/screen/*` except trending):**
```json
{
  "universe": "SP500",
  "limit": 25,
  "horizon": "2-4W",
  "include_analysis": true,
  "include_narrative": false,
  "tickers": ["...optional for custom/watchlist..."],
  "filters_override": { "min_market_cap_usd": 2000000000 }
}
```

**Trending request adds:** `"lookback_days": [3, 5]`, `"sources": ["reddit","stocktwits","news","yahoo_trending"]`.

**Response envelope (all screens):**
```json
{
  "screen_type": "opportunities",
  "generated_at": "2026-06-12T12:00:00Z",
  "universe": "SP500",
  "market_regime": "neutral",
  "data_quality_score": 83,
  "results": [
    {
      "rank": 1,
      "symbol": "XYZ",
      "opportunity_score": 88,
      "recommendation": "BUY",
      "entry_assessment": "wait_for_pullback",
      "ideal_buy_zone": [101, 106],
      "risk_flags": ["earnings_soon", "valuation_elevated"],
      "score_breakdown": { "valuation": 91, "growth": 76, "quality": 82, "risk": 30 },
      "data_freshness": { "fundamentals": "2026-03-31", "price": "live" },
      "summary": "Strong growth and institutional accumulation, but price is slightly extended."
    }
  ]
}
```

`POST /screen/opportunities` is the blend: it runs undervalued scoring, layers trending acceleration as a tiebreaker/booster, applies regime adjustments, and (if `include_analysis`) attaches entry assessments — producing the top overall opportunity list.

### Execution engine (consumer contract only)
- Accepts an analyst `recommendation` + `risk_flags`; returns a gated decision (`act` / `hold` / `block`) with the gate that fired. **No analysis, no order placement.**

---

## 16. Caching Strategy

| Data | TTL | Backend |
|---|---|---|
| Live/market price | 5 min | Redis or file |
| Technical indicators (derived from OHLCV) | 5 min (recompute on new bar) | memory/file |
| Fundamentals, ratings, valuation history | 24 h | Redis/file |
| 13F holdings | 24 h (data itself is 45d delayed) | file |
| Sentiment aggregates | 1 h | Redis/file |
| Universe membership | 7 d | file (`cache/universes/`) |
| FOMC / econ calendar | until next scheduled event | file |

**Rules:** never serve expired cache silently — if served past TTL, tag `stale` and reduce quality. Cache keys include symbol + date + provider. Screener bulk fetches share the analyst's fundamental cache where co-located, else call over HTTP.

---

## 17. Implementation Phases

Build in this order. Each phase is shippable.

### Phase 1 — Analyst MVP (preserve existing contract)
- [ ] `shared/` package: enums, base models, config loader, data-quality utils.
- [ ] analyst FastAPI skeleton: `/analyze`, `/entry`, `/health`.
- [ ] `data_fetcher`: yfinance OHLCV + fundamentals.
- [ ] `technicals`: RSI, MACD, MA20/50/200, BB, ATR, volume ratio, swing support/resistance, weekly RSI, gap & distance-from-MA metrics.
- [ ] `entry_engine` (§9) — deterministic levels + entry_assessment.
- [ ] `signals` + `aggregator` (weighted vote, YAML weights/thresholds).
- [ ] `narrator` (LLM, skipped when `include_narrative=false`).
- [ ] Cache layer; unit tests for indicators, voting, entry decision table.

### Phase 2 — Screener core
- [ ] screener FastAPI skeleton + `analyst_client`.
- [ ] `universe` resolution + `filters` (liquidity/mcap/penny/OTC).
- [ ] `fundamentals_bulk` + valuation-history percentiles.
- [ ] `scoring` (§10) with `scoring_weights.yaml` + `score_breakdown`.
- [ ] `/screen/undervalued`, `/screen/opportunities`, `/screen/watchlist`, `/screen/custom`, `/screen/health`.
- [ ] `regime` (§14) + `/screen/regime`.

### Phase 3 — Trending & buyability
- [ ] `trending` (Reddit/StockTwits/RSS/Yahoo) with baseline-relative acceleration.
- [ ] trend classification + `/screen/trending`.
- [ ] `buyability` pipeline (§13) wiring trending → analyst.
- [ ] sentiment NLP (FinBERT or keyword fallback), capped weights.

### Phase 4 — Moat & validation
- [ ] Backtesting store + evaluator (§18) — wire recommendation logging from Phase 1 onward.
- [ ] 13F accumulation, Form 4 insider clusters, unusual options activity.
- [ ] Black swan event library (structured macro-shock DB; long-term moat).
- [ ] Sector rotation refinement, ETF flow, alerting/watchlist monitoring.

> **Important:** the recommendation store from §18 should be **written from Phase 1** even though evaluation comes later. Architecture must support it from the start.

---

## 18. Backtesting & Validation

`backtesting/`. Future-proof from day one; does not block MVP.

- **`store.py`** — append-only log of every recommendation and screen result at emit time: symbol, timestamp, direction, confidence, entry block, scores, risk flags, regime, data_quality_score. Immutable; never overwritten.
- **`evaluator.py`** — joins stored recommendations to subsequent OHLCV and computes:
  - forward returns: 1D / 1W / 1M / 3M
  - max drawdown after signal
  - hit rate (did BUY go up; did WAIT produce a better entry than buy-now would have)
  - whether trending picks were too late (price lower N days later)
  - whether undervalued picks outperformed the universe benchmark
  - average return, risk-adjusted return (return / realized vol)
- Outputs per-strategy and per-`entry_assessment` performance tables so weights can be tuned with evidence.

---

## 19. Risk Controls & "What NOT To Do"

**Risk controls (must implement):**
- Liquidity & min-market-cap filters before scoring; penny/OTC excluded by default.
- Meme-behavior flag (vertical price + extreme retail mentions + high short interest) caps a stock's score and adds `meme_behavior`.
- Earnings-proximity flag (`earnings_soon`) when next earnings within the horizon window.
- Confidence decay: confidence × data_quality/100; stale/missing data lowers confidence visibly.
- Regime awareness adjusts weights; `risk_off` raises risk weighting.
- Every recommendation carries explicit `risk_flags`; execution-engine gates on them.

**What NOT to do (hard rules):**
- Do **not** place trades or emit order instructions anywhere, including narrative.
- Do **not** use AI to compute any indicator, score, or price level.
- Do **not** return any analysis/screen result without `data_freshness` and `data_quality_score`.
- Do **not** let sentiment dominate (≤ 15–20% of any weighted blend).
- Do **not** fabricate missing data — tag `missing`, degrade.
- Do **not** hardcode weights, thresholds, or the LLM provider — all from YAML/env.
- Do **not** let the analyst call the screener/dashboard/execution-engine (acyclic deps).
- Do **not** express certainty the data doesn't support; "unknown" is valid.
- Do **not** rank purely on raw popularity for trending — use acceleration vs the stock's own baseline.

---

## 20. Testing Plan

- **Unit (deterministic core):** golden-file tests for every indicator against known fixtures; entry decision-table tests covering each branch; scoring tests with synthetic universes; data-quality scoring tests for each freshness state.
- **Contract tests:** Pydantic schema round-trips for every request/response in §8–§15; analyst↔screener client contract.
- **Degradation tests:** simulate each provider down → assert no crash, correct `missing` tagging, lowered confidence, signal omitted from vote.
- **Determinism tests:** same inputs → identical scores/levels (no nondeterminism, no LLM in numeric paths).
- **Narrator isolation test:** assert narrative path is fully skippable and never alters numeric fields.
- **Regression:** snapshot a few real symbols' analyses; alert on unexpected score drift.

---

## 21. Codex Implementation Instructions

1. **Start with `shared/`.** Implement `enums.py` and `models.py` first; all services import these. No model is defined twice.
2. **Build the analyst service to the §8/§9 contracts** before any screener work. The original `AGENTS_ANALYST.md` contract is authoritative for fields not changed here; this spec only adds the `entry` block, `data_quality_score`, multi-level support/resistance arrays, and distance/gap technicals.
3. **Keep numeric and AI paths physically separate.** `technicals.py`, `fundamentals.py`, `entry_engine.py`, `scoring.py`, `trending.py`, `regime.py`, `aggregator.py` contain **zero** LLM calls. `narrator.py` is the only file that imports the LLM wrapper.
4. **All weights/thresholds in YAML** (`config/*.yaml`), loaded via `shared/config_loader.py` with validation on startup. Fail fast if a config key is missing.
5. **Every external fetch returns `(value, freshness, as_of)`** so the data-quality layer can tag it. No raw value enters a model without a freshness tag.
6. **Write the recommendation to `backtesting/store.py` at emit time** from Phase 1.
7. **Provider-neutral LLM wrapper**, env-configured (`AI_PROVIDER`, `AI_API_KEY`, `AI_MODEL`, `AI_BASE_URL`). The wrapper is the only place provider details live.
8. **Each service runs independently:** `uv run uvicorn <service>.api.main:app --port <port>`. Screener degrades to its own scores if analyst is unreachable.
9. **Deterministic `reason`/`summary` strings are templated in code.** Only when `include_narrative=true` does the LLM rephrase them — and it may not introduce numbers absent from the structured data.
10. **Follow the phase order in §17.** Do not begin trending (Phase 3) before screener core (Phase 2) is contract-complete and tested.

### Environment variables
```
# LLM (optional — narrative only)
AI_PROVIDER=
AI_API_KEY=
AI_MODEL=
AI_BASE_URL=
# Data sources (all optional; degrade gracefully)
ALPHA_VANTAGE_KEY=
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
STOCKTWITS_API_KEY=
# Cache
REDIS_URL=
CACHE_TTL_SECONDS=300
FUNDAMENTAL_CACHE_TTL=86400
SENTIMENT_CACHE_TTL=3600
# Services
ANALYST_BASE_URL=http://localhost:8001
```

---

## 22. Additional Recommendations (with rationale)

These extend the brief. Each notes *why* and *how*.

- **Black swan event library (moat).** *Why:* the design guide names it the system's hardest-to-copy asset. *How:* structured DB of macro shocks (date, type, drawdown %, recovery days, sectors hit, policy response, VIX peak). The analyst flags pattern similarity in narrative; never used to compute scores.
- **News-catalyst classifier.** *Why:* trending quality depends on *why* a stock moves. *How:* RSS + headline NLP labels catalysts (`fda_approval`, `earnings_beat`, `partnership`, `layoff`, `sec_investigation`, `recall`, `analyst_upgrade`, `macro`) feeding §12 classification. Deterministic keyword rules with optional FinBERT.
- **Unusual options activity.** *Why:* large/abnormal options flow often front-runs institutional positioning. *How:* compare today's volume vs open interest and trailing average per strike; flag `unusual_options_activity` (informational, low weight).
- **Watchlist monitoring + alerting.** *Why:* the best entry windows are short. *How:* scheduled re-screen of saved watchlists; emit alerts when a name crosses into its `ideal_buy_zone`, flips `entry_assessment`, or gets a fresh catalyst. Alerts are notifications only — never trades.
- **Confidence decay over time.** *Why:* a recommendation ages. *How:* dashboard applies a decay factor to displayed confidence based on `generated_at` age and data freshness.
- **Portfolio-aware recommendations.** *Why:* the analyst already accepts `portfolio_context`. *How:* if holdings are supplied, the narrative comments on concentration and the screener can down-rank names that worsen sector concentration (display-only; no rebalancing trades).
- **Yield-curve & rate-context variable.** *Why:* the same signal means different things across rate regimes. *How:* 2Y-10Y slope already feeds §14 regime; expose it in the macro block as a backdrop variable for the narrator.
- **Benchmark-relative reporting in backtests.** *Why:* "went up" is meaningless without the market's move. *How:* §18 evaluator always reports forward return vs the universe benchmark (e.g. SPY) so alpha, not beta, is measured.

---

*End of specification. This document, together with the preserved `AGENTS_ANALYST.md` analyst contract, is sufficient to implement the system end to end. When a field is unspecified, prefer determinism, explicit freshness tagging, graceful degradation, and no fabricated certainty.*
