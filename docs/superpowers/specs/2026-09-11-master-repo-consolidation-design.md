# Master repo consolidation — design

Date: 2026-09-11 · Branch: `consolidation/master` · Worktree: `~/Developer/finance-monorepo-master`
QA deploy: `https://stock.qa.ryanxu.dev` · Production (`stock.ryanxu.dev`) is out of scope and must not change.

## 1. Goal

Make `finance-monorepo` the one master repo for Ryan's and Vincent's stock apps.
Today the two apps are separate repos connected by the `decision.v1` contract and a
Worker-to-Worker service binding. After this work, one repo holds both engines, one
Worker serves one decision, and one React UI shows it.

## 2. Decisions (Ryan and Vincent, 2026-09-10/11)

| # | Decision |
|---|---|
| D1 | Technical analysis = Vincent's engine only. A piece of Ryan's technicals moves into it only if it helps and makes nothing worse. |
| D2 | Ryan's fundamental analysis stays. Technical is the majority. |
| D3 | A buy flag must be expected to beat the benchmarks over the **next 12 months**. |
| D4 | Benchmarks = **SPY and QQQ and the stock's sector ETF and matching industry ETFs**. A buy must beat all of them. |
| D5 | The React `web_ui` is the single UI. Vincent's decision views move into it. |
| D6 | Source of Vincent's code = the local clone `~/Developer/vincent-fork` (branch `feat/decision-v1-endpoint`). Never push to, fetch from, or change `github.com/vincentwang0909/stock-decision-dashboard`. |

## 3. Starting state (verified 2026-09-11 00:10 PDT)

- `finance-monorepo` main = `b5f60ca`. Baseline: 271 pytest pass, 80 Worker tests pass.
- Production runtime is the JS Worker `finance-api`. The Python services are mirrors used
  for tests and research. They are not deployed.
- The Worker already pulls Vincent's verdicts over a service binding to the `decision-v1`
  Worker, and falls back to local technicals when the pull fails.
- Vincent's engine is plain JS. Each module attaches to `globalThis`, so a Worker can
  import the files unchanged. The fork's `decision-v1` Worker already does this.
- Vincent's edge Worker feeds his engine only daily bars plus SPY/QQQ trend. It reports
  Short as `INVALID_LANDSCAPE` because it assumed Yahoo has no native 4H bars. **This is
  wrong:** Yahoo's chart API returns `dataGranularity: 4h` (checked: NVDA, 60d, 121 bars).
- Vincent's `tests/decision-engine.test.js` fails before any change: it requires
  `watchlist.shared.json`, which his `.gitignore` excludes.
- Vincent's upstream has one newer commit (`807a25e`, 2026-09-10, company-profile
  classifier) that is not in the local clone. Per D6 it is not imported. Ryan decides.

## 4. Target architecture

```
finance-monorepo/
  technical_engine/          Vincent's app, imported with full history (git subtree).
                             Canonical technical engine. His AGENTS.md rules apply here.
  cloudflare-api/            The one production Worker.
    src/consolidated/        NEW: the consolidated decision pipeline (below).
    config/consolidation.json  NEW: every threshold, benchmark map, and layer rule.
  web_ui/                    The one UI (React). New Final Decision + Index Hurdle panels.
  analyst_service/, screener_service/, shared/, backtesting/   unchanged role:
                             Python mirrors, research, and offline backtests.
  docs/superpowers/specs/    this document.
```

Runtime flow for one symbol:

```
market data (Yahoo chart: 1d 2y, native 4h, 1h; ^VIX, ^TNX; SPY, QQQ)
  → Vincent's engine, in process (no network hop)      → per-horizon technical action
  → fundamentals layer (minority, mid + long only)      → may step a buy down
  → index hurdle (SPY, QQQ, sector ETF, industry ETFs)  → may cap a buy at hold
  → final decision per horizon (short / mid / long, never averaged)
```

The service binding to `decision-v1` stays in config as a fallback until the in-process
path is proven in QA. Then it is removed.

### 4.1 Layer 1 — Technical (Vincent's engine, majority)

- Import his modules from `technical_engine/` in the Worker. Do not copy or fork them.
- His rules are binding inside his engine: independent horizons, no overall action,
  price state gates the action family, no numeric AI score, fundamentals never enter
  *his* action.
- Feed him what his canonical inputs expect, from Yahoo: daily 2y, **native 4h**, 1h,
  and market context (^VIX series, ^TNX series, SPY and QQQ trend). Missing data stays
  unavailable. Never synthesize 4h from 1h.
- Porting rule for Ryan's technicals (D1): a port is allowed only as a new canonical
  input or a new confluence category, with Vincent's full test suite green before and
  after, plus a targeted test. Candidates to evaluate later: none is known to be missing.

### 4.2 Layer 2 — Fundamentals (minority)

- Source: Ryan's fundamental signals (EPS surprise, analyst revisions, PE percentile),
  voted exactly as `analyst_service/core/signals.py` votes them. Before this work the
  Worker emitted only PE, so the layer had almost nothing to vote with. Fixed in
  `buildFundamentalSignals` (a signal with no data does not vote).
- Stance: `supportive` (fundamental vote leans BUY), `neutral`, `weak` (leans SELL), or
  `unavailable` (fewer than 2 fundamental signals).
- Rule — asymmetric, downgrade only, buy family only, **mid and long horizons only**:

| Technical action | supportive / neutral / unavailable | weak |
|---|---|---|
| strong_buy | strong_buy | buy |
| buy | buy | accumulate |
| accumulate | accumulate | hold (`fundamentals_weak`) |
| hold, trim, sell, avoid | unchanged | unchanged |

- Why: technical stays the majority. Fundamentals can never create a buy or a sell. They
  only remove conviction from a buy. Short (1–30 days) ignores fundamentals because
  quarterly data does not move a 1–30 day trade. The stance still shows as context.

### 4.3 Layer 3 — Index hurdle (D3, D4)

Base rate: only ~30% of stocks beat the S&P 500 in 2025 (SPIVA year-end 2025). Most
single stocks lose to the index over their life (Bessembinder). So a buy must show
evidence that it will beat each benchmark over the next 12 months.

Benchmark set for a ticker:
1. `SPY` and `QQQ` (always).
2. The GICS sector SPDR ETF (XLK, XLC, XLY, XLP, XLE, XLF, XLV, XLI, XLB, XLRE, XLU),
   from the Yahoo sector.
3. Every matching industry ETF from the config map (for example SMH semiconductors,
   IGV software, XBI biotech, KRE regional banks, ITA aerospace/defense, XRT retail,
   XOP oil and gas E&P, ITB homebuilders, CIBR cybersecurity, TAN solar).
4. The ticker itself is removed from its own set. A broad index ETF (SPY, VOO, IVV) is
   the benchmark, so the hurdle does not apply to it.
5. Non-US tickers: the local index when mapped (for example `^HSI` for `.HK`). If none is
   mapped, the hurdle is `unavailable`.

Evidence per benchmark `B` (deterministic, from daily closes, thresholds fixed a priori,
never tuned):
- **E1 relative 12-1 momentum:** stock return from t-252 to t-21 minus B's return over the
  same window is above 0. (Jegadeesh–Titman; industry momentum: Moskowitz–Grinblatt.)
- **E2 relative 6-month momentum:** stock 126-day return minus B's is above 0.
- **E3 relative trend:** the ratio line (stock ÷ B) is above its own 200-day average.

Per-benchmark result: `beats` when at least 2 of E1–E3 are true, `lags` when at least 2
are false, `insufficient_data` when fewer than 2 can be computed, and `mixed` when exactly
2 can be computed and they split 1–1. Only `beats` passes.

Stock-level earnings guard: if the latest EPS surprise is negative **and** the analyst
recommendation trend is deteriorating, the hurdle fails with `earnings_deteriorating`.

Hurdle result: `pass` only when every benchmark is `beats` and the earnings guard does not
fire. Otherwise `fail`, with each failing benchmark named. `insufficient_data` fails
closed. `not_applicable` for broad index ETFs.

Application: every buy-family final action (all horizons) with hurdle `fail` becomes
`hold` with reason `index_hurdle_failed` and the benchmarks it lags. `not_applicable`
leaves the action unchanged.

Forecast-safety note: the hurdle shows *historical* relative returns and a pass/fail.
It does not show a numeric 12-month forecast. This keeps the repo's fail-closed forecast
rule (AGENTS.md "Forecast Research Safety") intact.

### 4.4 Final decision shape (API)

`POST /analyze` keeps every current field and adds `consolidated_decision`:

```json
{
  "version": "consolidated.v1",
  "horizons": {
    "short": {
      "technical": { "action": "buy", "confidence": 71, "price_state": "IN_OPPORTUNITY_ZONE",
                     "execution_intent": "enter", "opportunity_range": {"low": 1, "high": 2},
                     "reduce_range": {"low": 3, "high": 4}, "invalidation": 0.9, "reasons": [] },
      "fundamentals": { "stance": "weak", "applied": false },
      "final_action": "hold",
      "adjustments": [ { "layer": "index_hurdle", "from": "buy", "to": "hold",
                         "reason": "index_hurdle_failed", "detail": "lags QQQ, SMH" } ]
    },
    "mid": {}, "long": {}
  },
  "index_hurdle": {
    "status": "fail",
    "benchmarks": [ { "symbol": "QQQ", "role": "index", "result": "lags",
                      "rel_12_1_pct": -4.2, "rel_6m_pct": -1.1, "ratio_above_200d": false } ],
    "earnings_guard": "clear"
  },
  "fundamentals": { "stance": "weak", "vote": {"BUY": 1.5, "SELL": 3.0} },
  "data_quality": { "four_hour": "available", "one_hour": "available", "market": 100 }
}
```

Vincent's technical action is always shown unchanged next to the final action.

### 4.5 UI (D5)

- Analyze view: a new **Final Decision** panel at the top, with three peer columns
  (Short / Mid / Long). Each column shows the final action. Where it differs from
  Vincent's technical action, it shows "Technical: Buy → Final: Hold" and the reason.
  Below each column is Vincent's price landscape (opportunity, reduce, invalidation).
- A new **Index Hurdle** panel: one row per benchmark (role, 12-1 rel, 6m rel, trend,
  result).
- The existing panels stay. All new strings go into all three locales (en, zh-CN, zh-HK).
- Screener (later pass): a buy flag shows only when the hurdle passes.

### 4.6 QA deploy

- Worker: `wrangler deploy --env qa` → `finance-api-qa` with its own Durable Objects, so
  QA never reads or writes the production watchlist. `CORS_EXTRA_ORIGINS` allows
  `https://stock.qa.ryanxu.dev`.
- Pages: project `finance-web-ui-qa` with custom domain `stock.qa.ryanxu.dev`. The build
  sets `VITE_API_BASE_URL` to the QA Worker.
- CI: `.github/workflows/deploy-qa.yml` runs on push to `consolidation/master`. It runs the
  full test set and then deploys both. It never runs on `main`.
- Fallback: if the two-level hostname cannot get a certificate, use `stock-qa.ryanxu.dev`
  and report it.

## 5. Verification

Every change must keep green:
- `uv run pytest -q` (271 baseline)
- `cd cloudflare-api && npm test` (80 baseline, grows)
- Vincent's suite: `node --test technical_engine/tests/*.test.js` (5 of 6 files green at
  baseline, the 6th fixed in the first pass)
- `cd web_ui && npm test && npm run build`

New code gets targeted tests: hurdle evidence math, benchmark resolution, fundamentals
step-down table, final composition, and a Worker test that runs Vincent's real engine in
process on fixture bars.

Descriptive backtest (autobuild backlog): for a fixed universe of current large caps,
monthly 2012–2022, compute the hurdle and the next-12-month return relative to each
benchmark. Report the hit rate for pass vs fail. Thresholds are not tuned on it. The
consumed 2023–2024 forecast holdout is not touched. Survivorship bias is stated.

## 6. Guardrails

- No merge to `main`. No production deploy. No change to `finance-api` or `finance-web-ui`.
- Never touch Vincent's GitHub remote (D6).
- No new runtime dependency without need.
- No numeric forecast in the UI.
- Vincent's `technical_engine/` code changes only to fix his own broken test setup or to
  add an input his canonical feature contract already names, and only with his tests
  green.

## 7. Backlog (ordered, for the autobuild loop)

1. Fix Vincent's `watchlist.shared.json` test dependency with a committed fixture.
2. Run Vincent's engine in process in the Worker, fed daily + native 4h + 1h + market
   context. Short horizon becomes available.
3. Index hurdle module + config + tests.
4. Fundamentals layer + final composition + `consolidated_decision` in `/analyze` + tests.
5. QA Worker env, QA Pages project, `deploy-qa.yml`, CORS. First QA deploy.
6. Final Decision + Index Hurdle panels in the Analyze view (3 locales).
7. Screener buy flags respect the hurdle.
8. Remove the `decision-v1` service-binding hop once in-process is proven.
9. Descriptive hurdle backtest script + report under `docs/`.
10. Evaluate Ryan's technicals for a port into Vincent's engine (D1). Port only with evidence.
11. Docs: README, AGENTS.md, CLAUDE.md updated for the one-repo layout.

## 8. Open items for Ryan and Vincent

- Import Vincent's upstream commit `807a25e` (company-profile classifier)? Not imported (D6).
- Fundamentals on Short: excluded by design (4.2). Change if you disagree.
- Industry ETF map breadth: start with ~25 ETFs. Extend by editing config only.
- Worker PE is always null: it reads `trailingPE`/`forwardPE`, the provider sends
  `trailingPe`/`forwardPe`. Not fixed on purpose: the fix would switch on
  `estimatePePercentile`, an absolute-PE mapping that breaks the repo's
  self-5y-percentile invariant. A real 5-year PE history is needed first.
