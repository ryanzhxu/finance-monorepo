# Index hurdle — backtest evidence

Run 2026-09-11 by the supervising session during the overnight consolidation
loop. Scripts: `tools/hurdle_backtest/hurdle_only.mjs` and
`tools/hurdle_backtest/engine_replay.mjs`. Both run the committed code
unchanged: the hurdle from `cloudflare-api/src/consolidated/index-hurdle.js`
and Vincent's engine from `technical_engine/`.

## Answer first

- **The hurdle works as specified.** A buy shows only when the stock is
  stronger than SPY, QQQ, its sector ETF and its industry ETF on relative
  12-1 momentum, 6-month momentum and its ratio line.
- **It does not predict 12-month outperformance in this test.** Stocks that
  passed beat every benchmark over the next 12 months slightly *less* often
  than stocks that failed (33.9% vs 36.8%, 60 large caps, 2012–2021).
- **On Vincent's buy signals it removes about 70% of buys** (Mid 834 of 1,163;
  Long 516 of 702) without improving 12-month results. The one sign of an edge:
  Mid buys that passed beat SPY over the next **6** months more often (54.4% vs
  50.5%; median +2.2 vs +0.3 pp). Overlapping windows make this weak evidence.
- **A fundamentals screen does no better (Test 3).** Latest quarterly EPS and
  revenue both up year-on-year, from SEC filings available on the signal date:
  stock-months that passed beat SPY over 12 months *less* often (51.1% vs
  58.9%). This universe punishes any "avoid weak stocks" rule, because a
  company with a bad year only made today's large-cap list by recovering.
- **One pattern repeats:** Mid buys that clear both the momentum hurdle and the
  fundamentals screen beat SPY over Mid's own 6 months 64.4% of the time
  (median +4.2 pp, n = 118) against ~50–54% for the other groups. It is one
  comparison among several on overlapping windows: a hypothesis to score live,
  not a finding.
- **Read the hurdle as a conservative filter**, not as evidence that a stock
  will beat the index this year.

## Options for Ryan and Vincent

1. **Keep it as it is.** Fewer buys and a better worst case (mean relative to the
   worst benchmark −1.9 vs −5.2 pp), but no proven gain. This is the current
   QA behavior.
2. **Add forward-looking fundamental evidence to the hurdle.** Earnings-estimate
   revisions and profitability (ROE) are the factors with the strongest record
   next to momentum. The repo already has SEC EDGAR tooling for point-in-time
   fundamentals, which a fair test needs.
3. **Match the hurdle to each horizon's own window** (6 months for Mid). Choosing
   this after seeing the 6-month result above is data snooping, so it needs a
   separately versioned test on data this run did not use.
4. **Measure it live from now on.** Record every final buy with its benchmarks
   and score it after 6 and 12 months. That is the only test free of
   survivorship bias.

## Method

- Universe: 60 current US large caps across all 11 sectors. Benchmarks per
  stock from the production config (SPY, QQQ, sector ETF, industry ETF).
- Signals: month-ends 2012-01 to 2021-12. Outcome: the next 252 sessions
  (and 126 for the 6-month columns), dividend-adjusted.
- Every forward window ends by 2022-12. The consumed 2023–2024 forecast holdout
  is not used. No threshold was tuned.
- Vincent's engine replay uses daily bars only (Mid and Long horizons). Short
  needs native 4h history, which does not exist that far back. Fear & Greed has
  no history, so market data quality is lower than live. The earnings guard
  and Ryan's fundamentals layer are not replayed (no point-in-time data).

## Test 1 — the hurdle on every stock-month


### Result

| Group | Stock-months | Beat every benchmark next 12M | Beat SPY next 12M | Mean rel. vs SPY (pp) | Median rel. vs SPY (pp) | Mean rel. vs worst benchmark (pp) |
|---|---:|---:|---:|---:|---:|---:|
| All | 6559 | 35.8% | 53.8% | 7.5 | 2.2 | -4.1 |
| Hurdle **pass** | 2263 | 33.9% | 52.4% | 9.6 | 1.5 | -1.9 |
| Hurdle fail (any reason) | 4296 | 36.8% | 54.5% | 6.5 | 2.6 | -5.2 |
| Hurdle fail, full data | 4199 | 36.7% | 54.2% | 6.5 | 2.5 | -5.3 |

### Per benchmark

When the evidence says `beats` for a benchmark, how often did the stock beat that benchmark over the next 12 months?

| Benchmark | `beats` n | Beat rate after `beats` | Mean rel. after `beats` (pp) | Other n | Beat rate otherwise | Mean rel. otherwise (pp) |
|---|---:|---:|---:|---:|---:|---:|
| SPY | 3463 | 52.3% | 7.7 | 3096 | 55.4% | 7.4 |
| QQQ | 2869 | 43.0% | 2.9 | 3690 | 47.9% | 1.8 |
| sector | 3548 | 55.0% | 6.8 | 3011 | 56.8% | 6.6 |
| industry | 2557 | 57.9% | 5.8 | 1932 | 59.8% | 7.7 |

### By signal year

| Year | n pass | Pass: beat all | Pass: mean rel. SPY | n fail | Fail: beat all | Fail: mean rel. SPY |
|---|---:|---:|---:|---:|---:|---:|
| 2012 | 218 | 25.2% | -1.2 | 382 | 45.5% | 13.5 |
| 2013 | 233 | 33.5% | 14.4 | 379 | 28.2% | 4.0 |
| 2014 | 188 | 33.5% | 4.2 | 424 | 32.1% | 2.7 |
| 2015 | 202 | 49.0% | 9.5 | 416 | 42.5% | 6.8 |
| 2016 | 266 | 35.0% | 19.7 | 370 | 35.1% | 8.4 |
| 2017 | 231 | 47.6% | 13.8 | 405 | 38.3% | 5.4 |
| 2018 | 260 | 41.9% | 2.0 | 425 | 47.8% | 6.1 |
| 2019 | 291 | 17.9% | 13.8 | 429 | 21.4% | 8.8 |
| 2020 | 152 | 27.6% | 18.8 | 568 | 25.5% | 2.5 |
| 2021 | 222 | 29.7% | 0.1 | 498 | 52.4% | 8.1 |

### Caveats

- Survivorship bias: the universe is today's large caps, which by construction did well. Absolute beat rates are inflated for every group; compare pass vs fail, not against 50%.
- Overlapping 12-month windows (monthly signals) are autocorrelated, so the effective sample is far smaller than the stock-month count. Treat differences as descriptive, not significant.
- Benchmarks without 253 sessions of history (for example XLC before mid-2019) make the hurdle fail closed, as in production. The "full data" row removes those.
- Sector/industry come from today's Yahoo classification, not point-in-time.

## Test 2 — the hurdle on Vincent's buys (engine replay)

Vincent's production engine replayed at 120 month-ends (2012-01..2021-12) for 60 large caps on daily bars (2 years each), with market context rebuilt from ^VIX, ^TNX, SPY and QQQ. Short is not replayed (no historical native 4h). Fear & Greed is unavailable historically, which lowers market data quality exactly as it would live. Decisions: 6530; engine errors: 0.

Action mix — mid: hold 4597, trim 495, accumulate 1140, sell 244, avoid 31, buy 23. Long: avoid 82, hold 5124, trim 443, sell 179, accumulate 606, buy 87, strong_buy 9.

### Mid (1–6 months) horizon

| Group | Stock-months | Beat every benchmark 12M | Beat SPY 12M | Mean rel. SPY 12M (pp) | Median rel. SPY 12M (pp) | Mean rel. worst benchmark (pp) | Beat SPY 6M | Median rel. SPY 6M (pp) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| All stock-months | 6530 | 35.8% | 53.7% | 7.5 | 2.2 | -4.1 | 52.1% | 0.8 |
| Vincent's buy-family | 1163 | 34.8% | 53.4% | 5.2 | 2.1 | -6.4 | 51.6% | 0.7 |
| Vincent's buy **+ hurdle pass** (final buy) | 329 | 34.3% | 53.2% | 5.4 | 1.7 | -5.6 | 54.4% | 2.2 |
| Vincent's buy + hurdle fail (held) | 834 | 35.0% | 53.5% | 5.1 | 2.5 | -6.6 | 50.5% | 0.3 |
| Vincent's non-buy | 5367 | 36.1% | 53.7% | 8.0 | 2.2 | -3.6 | 52.3% | 0.8 |

### Long (> 6 months) horizon

| Group | Stock-months | Beat every benchmark 12M | Beat SPY 12M | Mean rel. SPY 12M (pp) | Median rel. SPY 12M (pp) | Mean rel. worst benchmark (pp) | Beat SPY 6M | Median rel. SPY 6M (pp) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| All stock-months | 6530 | 35.8% | 53.7% | 7.5 | 2.2 | -4.1 | 52.1% | 0.8 |
| Vincent's buy-family | 702 | 35.2% | 54.1% | 6.0 | 2.2 | -5.3 | 49.3% | -0.2 |
| Vincent's buy **+ hurdle pass** (final buy) | 186 | 31.2% | 53.8% | 5.4 | 2.2 | -6.0 | 50.5% | 0.5 |
| Vincent's buy + hurdle fail (held) | 516 | 36.6% | 54.3% | 6.3 | 2.2 | -5.1 | 48.8% | -0.3 |
| Vincent's non-buy | 5828 | 35.9% | 53.6% | 7.7 | 2.2 | -4.0 | 52.5% | 0.8 |

## Test 3 — fundamental evidence (hurdle option 2, exploratory)

Pre-registered rule: **latest quarterly diluted EPS and revenue both up year-on-year**, from filings available on the signal date. It ran against the filing-date-aware SEC builder in Ryan's main checkout (`backtesting/sec_edgar.py`, `backtesting/sec_fundamental_features.py`) and its local SEC cache. Those modules are uncommitted forecast-research work, so this test's script is not in the repo; the rule and outputs are recorded here in full. Secondary: EPS growth alone. Same stock-months and outcomes as Test 2.
Coverage: 46 of 60 stocks have cached SEC company facts (missing: DUK, HON, INTU, LIN, LMT, MRK, NEE, PFE, PG, SBUX, SLB, T, UPS, WFC).

### Every stock-month

| Group | n | Beat every benchmark 12M | Beat SPY 12M | Median vs SPY 12M (pp) | Beat SPY 6M | Median vs SPY 6M (pp) |
|---|---:|---:|---:|---:|---:|---:|
| Fundamentals **pass** | 2192 | 34.1% | 51.1% | +0.6 | 51.5% | +0.6 |
| Fundamentals fail | 2199 | 41.3% | 58.9% | +5.6 | 56.5% | +2.5 |
| Fundamentals unavailable | 536 | 38.4% | 52.2% | +1.2 | 48.7% | -0.3 |
| (secondary) EPS growth pass | 2689 | 34.6% | 52.2% | +1.2 | 50.9% | +0.5 |
| (secondary) EPS growth fail | 1924 | 41.9% | 58.7% | +6.0 | 57.8% | +2.9 |

### Vincent's mid buys

| Group | n | Beat every benchmark 12M | Beat SPY 12M | Median vs SPY 12M (pp) | Beat SPY 6M | Median vs SPY 6M (pp) |
|---|---:|---:|---:|---:|---:|---:|
| Buy + fundamentals **pass** | 385 | 35.6% | 54.3% | +1.6 | 54.3% | +2.2 |
| Buy + fundamentals fail | 371 | 35.8% | 55.3% | +3.0 | 52.8% | +0.9 |
| Buy + momentum hurdle pass + fundamentals pass | 118 | 34.7% | 55.1% | +1.8 | 64.4% | +4.2 |
| Buy + momentum hurdle fail + fundamentals pass | 267 | 36.0% | 53.9% | +1.6 | 49.8% | -0.0 |

### Vincent's long buys

| Group | n | Beat every benchmark 12M | Beat SPY 12M | Median vs SPY 12M (pp) | Beat SPY 6M | Median vs SPY 6M (pp) |
|---|---:|---:|---:|---:|---:|---:|
| Buy + fundamentals **pass** | 216 | 34.3% | 50.5% | +0.6 | 50.9% | +1.3 |
| Buy + fundamentals fail | 236 | 41.1% | 60.6% | +5.0 | 53.0% | +1.3 |
| Buy + momentum hurdle pass + fundamentals pass | 66 | 36.4% | 47.0% | -0.3 | 53.0% | +3.8 |
| Buy + momentum hurdle fail + fundamentals pass | 150 | 33.3% | 52.0% | +1.5 | 50.0% | +0.2 |

Same caveats as Tests 1–2 (today's large caps, overlapping windows). The fundamentals rule uses reported quarterly figures only; it is a screen, not an earnings-estimate revision signal (no point-in-time analyst data).
