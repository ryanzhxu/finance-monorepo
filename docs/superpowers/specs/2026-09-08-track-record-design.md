# Composite engine — Vincent's technicals, Ryan's everything else

**Date:** 2026-09-08 · **Branch:** `feat/track-record` · **Base:** `a480abe`

## The decision this implements

Settled by Ryan and Vincent (2026-08-28 call, confirmed 2026-09-08):

> Use Vincent's technical analysis system. Keep all of Ryan's other analysis except
> technical.

So the composite becomes:

| Layer | Owner | Source |
|---|---|---|
| Technical | **Vincent** | `stock-decision-dashboard`, via `decision.v1` |
| Fundamental | Ryan | `analyst_service/core/fundamentals.py` |
| Sentiment | Ryan | `analyst_service/core/sentiment.py` |
| Macro / regime | Ryan | `analyst_service/core/macro.py`, `regime.py` |
| Valuation percentiles | Ryan | `fundamentals.py` (self-5y percentiles) |
| Entry / confluence | Ryan | `entry_engine.py`, `confluence.py`, `fibonacci.py` |
| Data quality / freshness | Ryan | `shared/data_quality.py` |
| Narrative | Ryan | `narrator.py` (LLM, narrative only) |

## Why this is a substitution, not a rewrite

`analyst_service/core/aggregator.py` already partitions every signal into one of four
categories by dimension prefix (`CATEGORY_PREFIXES`, line 19) and computes a separate
weighted vote per category (`_weighted_votes_by_category`, line 43). The technical
category is already an isolated block with its own vote, its own signal list, and its
own line in the response (`Recommendation.technical_vote`).

Replacing that block's contents is a bounded change at an existing seam.

## Phase 1 — the technical provider seam

### 1. `TechnicalVerdict` — the normalized internal type

One type that both providers produce, so the aggregator never learns whose technicals
it is holding:

```
direction         BUY | HOLD | SELL
confidence        0.0–1.0
price_state       decision.v1 priceState, or None
opportunity_range low/high, nullable
reduce_range      low/high, nullable
invalidation      float, nullable
reasons           list[str]
data_quality      0–100, nullable
producer          string, e.g. "vincent-stock-decision-dashboard"
source            LOCAL | EXTERNAL
```

### 2. Providers — `analyst_service/core/technical_provider.py` (new)

- `LocalTechnicalProvider` wraps today's technical signals into a `TechnicalVerdict`.
  It is the default, so behavior is unchanged when nothing external is supplied.
- `ExternalTechnicalProvider` parses a `decision.v1` payload into the same type.

**Two conversions must be exactly right**, both flagged as landmines in the
`consolidation/decision-v1` handover:

- **Confidence scale.** `decision.v1` uses 0–100; `Recommendation.confidence` uses
  0.0–1.0. A missed rescale yields `0.7` where `70` was meant and looks plausible.
  This gets a dedicated test with a boundary case.
- **Action vocabulary.** `decision.v1` has seven actions
  (`strong_buy | buy | accumulate | hold | trim | sell | avoid`); the internal
  `Direction` has three. The mapping is fixed and explicit:
  `strong_buy, buy, accumulate → BUY`; `hold → HOLD`; `trim, sell, avoid → SELL`.
  `accumulate` and `trim` have no local source, which is exactly why they arrive
  from Vincent's side rather than being invented here.

### 3. Transport — push now, pull later

Push works today and needs no network: `/analyze` accepts an optional `technical`
block in the request body, and Vincent's engine posts its verdict alongside the
symbol. Pull is an HTTP adapter against a configured base URL, off by default, ready
for when his engine exposes the endpoint.

Every test uses push, so no test touches the network.

### 4. Weighting — without editing `signal_weights.yaml`

`CLAUDE.md` states the weights are final pending a Phase 4 backtest, so they are not
touched. The seven technical entries sum to **7.6**
(`RSI_14 1.0 + MACD 1.0 + Bollinger_Bands 0.8 + Volume 1.0 + MA_50_200 1.5 +
RSI_Weekly 1.5 + Support_Resistance 0.8`).

When an external verdict is present, its single synthesized technical signal carries
that same 7.6, so the technical-to-non-technical balance is preserved exactly. The
value lives in a **new** file, `analyst_service/config/technical_provider.yaml`,
which adds a key rather than changing an existing one.

### 5. Agreement — the feature Vincent actually asked for

Vincent, 2026-07-10:

> 「比如你和都推荐nvda 那就买。要是他的我自己都不信没啥意思」

When an external verdict is present, Ryan's local technicals are still computed and
reported — but **excluded from the weighted vote**. They become a comparison, which
yields `technical_agreement`: do the two engines independently reach the same
technical direction?

That is Vincent's stated buy condition expressed as a field. It costs nothing extra
to compute, because the local technicals are already calculated.

Substitution, explicitly, is not averaging. When Vincent's verdict is present it
*is* the technical vote; the local one only observes.

## Phase 2 — track record

Still needed, and unchanged by the architecture decision. Vincent asked twice:

> 「加个history功…在dashboard里面 然后做回测」 — 2026-07-24

Two thirds is built and unreachable. `analyst_service/core/persistence.py:133`
already writes every `/analyze` to SQLite. `backtesting/evaluator.py`'s
`evaluate_store()` already computes forward returns, benchmark-relative return, max
drawdown and a hit flag, tested in `tests/test_backtesting_evaluator.py`. **Nothing
imports it** — no endpoint, no UI, no CLI.

- `persistence` gains optional `symbol` / `since` / `limit` filters, in SQL, using
  the existing `(symbol, generated_at)` index. Defaults keep current behavior.
- `backtesting/price_cache.py` adds `BatchPriceLoader`: `evaluate_store()` costs two
  provider calls *per record*, which is fine offline and unacceptable over HTTP.
  Batching by symbol drops it to one call per distinct symbol plus one benchmark.
- `backtesting/track_record.py` serves a per-symbol timeline and an aggregate report,
  adding **by-confidence-bucket** hit rates — the direct answer to "when it says it
  is confident, is it right more often?"
- Routes: `GET /history/coverage` (no provider calls, so the UI can render an honest
  empty state), `GET /history/{symbol}`, `GET /history/performance`.

With Phase 1 landed, the track record also splits by technical source, which answers
the question the 2026-08-28 decision creates: **is the composite better with
Vincent's technicals than with Ryan's?**

## Constraints honored

- No trade execution. Spec §2 constraint 1 holds. The Questrade fork is documented
  in `docs/OPEN-DECISIONS.md` and not acted on.
- The LLM computes nothing. Every number here is pandas arithmetic.
- Nothing fabricated. A skipped record keeps its `skipped_reason` and is excluded
  from every rate, so a thin sample reads as thin.
- `signal_weights.yaml` unchanged.
- No new dependencies.
- `make postman` after the API change, per `CLAUDE.md`.

## Error handling

- Malformed external verdict: rejected with a clear message, and the analysis falls
  back to local technicals with `technical_source: LOCAL` and a risk flag. A bad
  payload must never silently become a confident number.
- External verdict missing fields: nullable fields stay null; a missing `action` is
  a rejection, not a `HOLD`.
- Provider unavailable during evaluation: record returned with `skipped_reason`, no
  fabricated numbers, endpoint still answers 200.
- No stored records: `/history/coverage` reports zero.

## Testing

Test-first, in order:

1. Action mapping — all seven `decision.v1` actions, plus an unknown one.
2. Confidence rescale — including the 0/100 boundary and the `0.7` vs `70` trap.
3. Substitution — external verdict replaces the technical vote; local technicals are
   reported but excluded from `weighted_score`.
4. Agreement — agree, disagree, and local-technicals-absent.
5. Weight preservation — technical block still carries 7.6.
6. Fallback — malformed payload degrades to local, with the risk flag set.
7. Phase 2: persistence filters, batch call counting, bucket boundaries, routes.

Baseline is `138 passed`. The suite must never drop below it.

## Verification

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync pytest -q \
  --ignore=analyst_service/tests/test_stock_research.py
cd web_ui && npm run build
make postman
```
