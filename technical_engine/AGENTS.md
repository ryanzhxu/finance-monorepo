# Stock Decision Dashboard

## Project overview

This is a lightweight stock decision dashboard. It displays a shared watchlist, complete canonical Technical and Market data, and an independent Short/Mid/Long Decision Engine. It is designed for Render's 512 MB RAM, 0.5 CPU, and 1 GB disk limits.

## Architecture

- `server.py` fetches, normalizes, caches, and serves market, quote, earnings, and independent page data.
- `main.js` owns application state, data integration, and DOM rendering. It must never calculate a recommendation.
- `technical-features.js` produces the canonical technical feature object used by both the Technical tab and the Decision Engine.
- `profile-definitions.js` is the reviewable source of stock classifications, Company Traits, and ETF profiles.
- `decision-engine/` contains the calibrated V1 recommendation model. `etf-profile.js` supplies ETF-specific behavior modifiers.
- `decision-presentation.js` is a pure UI helper for execution labels, reason translation, and the native DOM/CSS Price Landscape model.
- `scripts/` contains bounded, read-only audit/shadow tooling, not production history storage.
- `tests/` contains deterministic regression, feature, engine, and server checks.
- `index.html` loads browser modules in dependency order; `styles.css` provides the restrained dark theme.

## Decision Engine principles

1. A final recommendation may use only Technical data, Market data, and Profile modifiers.
2. Fundamental, valuation, options, and news data must never enter a recommendation.
3. Short, Mid, and Long are fully independent; never average or vote across them.
4. There is no overall action.
5. The only actions are `strong_buy`, `buy`, `accumulate`, `hold`, `trim`, `sell`, and `avoid`.
6. Recommendation Confidence is support consistency and stability, not a probability.
7. Traits modify model behavior; they never add fixed points.
8. Exhaustion is a contrarian modifier, not an automatic reversal rule.
9. Strong Buy must remain rare and guarded.
10. Market data is primarily a risk regime, not a separate buy/sell engine.
11. Final Action is jointly determined by Direction, Confirmation, Risk, Exhaustion, and Price Landscape / Price State; it is not calculated before the landscape.
12. Never reintroduce Action Score or an equivalent numeric AI score.

## Technical horizons and roles

- Short (1–30 days): primarily 4H data with 1H support.
- Mid (1–6 months): primarily Daily data with 4H support.
- Long (>6 months): Weekly / long-Daily structure.

The technical roles are Direction, Confirmation, Risk, Price Opportunity, and Exhaustion. The Technical tab is the complete raw/interpreted technical-data view; the AI Decision tab presents only the final decision and its reasons.

## Price Landscape and execution semantics

`enter`, `add`, `hold`, `reduce`, `exit`, and `avoid` are the only execution intents. Decision UI may expose only:

- `opportunityRange`
- `currentPrice`
- `reduceRange`
- `invalidation`

Technical structure still supplies zone calculations, but never expose a remote support/resistance level as a predictive decision output. A positive action is permitted only inside the opportunity range; proximity alone is Hold. Hold occupies the Neutral space and both Near zones. Trim/Sell is permitted only inside or beyond the Reduce range unless a confirmed breakdown/invalidation path applies. A structural Sell uses an executable current-area exit after breakdown; it never waits for a distant rebound. Avoid is not Sell and must not produce a fake exit plan.

`Price State` is the mandatory Action-Family input: `IN_OPPORTUNITY_ZONE`, `NEAR_OPPORTUNITY_ZONE`, `NEUTRAL_ZONE`, `NEAR_REDUCE_ZONE`, `IN_REDUCE_ZONE`, `BEYOND_REDUCE_ZONE`, `BREAKDOWN_ZONE`, or `INVALID_LANDSCAPE`.

- `IN_OPPORTUNITY_ZONE` permits only Strong Buy, Buy, or Accumulate. Direction, Confirmation, Risk, Exhaustion, Market and Profile modifiers choose intensity inside that family. Opportunity itself never automatically creates Buy.
- `NEAR_OPPORTUNITY_ZONE`, `NEUTRAL_ZONE`, and `NEAR_REDUCE_ZONE` all produce Hold. Near zones are informational analysis states only; they can affect reasons and confidence but cannot trigger an early entry or reduction.
- `IN_REDUCE_ZONE` and `BEYOND_REDUCE_ZONE` permit only Trim or Sell. Hold and every positive Action are prohibited; if the model needs Hold, rebuild the final landscape rather than add an exception.
- Breakdown / invalidation permits Sell or Avoid. Sell requires bearish confirmation or a structural/material breakdown; price being high alone cannot create Sell.
- Near-zone tolerance is ATR-normalized but capped by the Neutral buffer, so it cannot consume the entire Neutral state.
- When a breakdown occurs, the exit range must re-anchor near the executable current area.

Final Confidence is calculated only after this Action-Family selection and must include data quality, stability, landscape quality, and legitimate price-state/signal tension. It must never be copied from a pre-landscape candidate action.

Landscape invariants are mandatory: `opportunityRange.high < reduceRange.low`, with an ATR-, horizon-, and confluence-aware neutral buffer between them. If independent support/resistance clusters cannot form this separation, lower-quality clusters are discarded; if that still fails, the landscape is marked low/invalid and no fake precision range is emitted.

## Refresh and stateless Price Landscape contract

Every dashboard data refresh rebuilds the entire current decision pipeline for
every valid ticker and horizon:

```
latest Quote / OHLCV / Market
→ canonical Technical normalization
→ Direction / Confirmation / Risk / Exhaustion
→ unified Price Structure / Confluence Engine
→ Opportunity / Reduce / Invalidation
→ Price State
→ Final Action
→ Final Confidence
```

Price Landscape construction is stateless. A prior Opportunity range, Reduce
range, selected cluster, or cluster score may be used only for offline debug
comparison; it must never be an input to a new production decision. Do not add
cluster switching margins, previous-cluster preferences, range hysteresis, or
stale landscape reuse. Action hysteresis remains separate and may only smooth
actions inside the current Price State family.

The single unified Price Structure Engine collects all available legitimate
structure candidates, then ranks category-aware confluence zones. Current V1
categories are Fibonacci (including Short Daily confirmation as the same
category), confirmed swing, moving average, Bollinger, and 52-week/ATH
historical structure. Add breakout/retest or volume-supported categories only
when they exist as reliable canonical Technical data; do not invent them from
current price. Multiple levels in one category refine a zone's location but are
contribution-capped. Cross-category agreement, not a stack of nearby EMAs, is
what raises confluence quality. ATR controls zone width and distance
normalization, never zone center; current price alone must not drag an
Opportunity range upward.

Material conditions are checked on every refresh: earnings/event proximity,
post-event gap, abnormal RVOL, ATR shock, major support breakdown/breakout,
and market shock. They may invalidate the current landscape and bypass
family-internal action hysteresis immediately.

## Refresh completion contract

A refresh is not complete when its HTTP request resolves. It proceeds through:

```
latest snapshot obtained
→ canonical Technical normalization
→ all Short/Mid/Long Decision, Landscape, Action, and Confidence calculations
→ Dashboard DOM render
→ browser paint
→ Refreshing state ends and Last Refresh is updated
```

Manual and hourly automatic refreshes must call the same full refresh
transaction. Both send the existing `force=true` live-data request; Auto
Refresh must never be cache-only while Manual Refresh is live/forced. Manual
and automatic refreshes share one in-flight promise, and a monotonic refresh
generation prevents a stale response from applying over a newer snapshot.
This also prevents an automatic timer from overlapping a manual refresh (and
vice versa). A failed automatic refresh leaves the prior successful Dashboard
and Last Refresh unchanged, releases the loading state, and does not stop the
next hourly attempt.

A browser-triggered live refresh is a **full requested-watchlist** server
transaction, not one provider-limited request. The server may use small
provider-safe batches, but it must force-refresh every requested ticker before
returning the final cache snapshot. A later batch/newly added ticker must never
be marked deferred merely because it was not in the first batch. Fetch shared
market context once per batch transaction, then reuse it for the final snapshot
instead of multiplying macro requests.

The UI's Last Refresh uses the applied snapshot's server freshness
(`last_dashboard_refresh` first), but is committed only after the whole
transaction has applied the snapshot, recalculated all horizons, rendered the
Dashboard, and completed a browser paint. Display it explicitly in
`America/New_York`, with the `ET` label so daylight saving is correct; never
use browser-local time, server-local time, or a fixed UTC-5 offset. The client
may persist this single current timestamp to retain the displayed freshness
across a reload; it must not become refresh history.

## EOD Decision History contract

Daily Decision History is an **offline-only** recorder for later validation;
it is not a Dashboard UI/data source and must never become an input to a live
Recommendation. The Render Web Service—not a browser timer, local Mac task,
or client cron—runs it at **4:30 PM `America/New_York`**. The timezone must be
named (DST-safe), never a fixed UTC offset.

For each run, the server performs the production full live refresh first,
then uses the same JavaScript `technical-features.js` and `decision-engine/`
modules to calculate all Short/Mid/Long decisions, and only then atomically
writes compact rows to SQLite:

```
full live refresh
→ latest valid current-day market snapshot
→ canonical Technical features / production Decision Engine
→ Short, Mid, Long Decision snapshots
→ one SQLite transaction / commit
```

The database is persistent-disk only: `DECISION_HISTORY_DB_PATH` has priority;
otherwise use Render's writable `/var/data/历史记录.sqlite`, with
`历史记录/历史记录.sqlite` as local-only fallback. SQLite files and exports must
remain ignored by Git. No normal Dashboard request may open or preload this
database. The recorder uses short connections/transactions, has no history
cache, and discards temporary provider payloads and JS process state after a
run. The one-shot Node serializer is heap-capped by
`EOD_HISTORY_NODE_MAX_OLD_SPACE_MB` (Render Blueprint: `192`) and exits after
each write.

`decision_history` has exactly one official row per
`market_date + ticker + horizon`; repeat same-day runs UPSERT rather than
duplicate. Store compact final Decision state, Price Landscape, core model
states, market context, compact canonical technical features/reason codes, and
stock/ETF profile context. Never store raw OHLCV arrays or complete indicator
series. `eod_runs` is a small operational table recording started/completed
status, counts, error summary, and SQLite size. Unavailable tickers receive
explicit unavailable rows after a valid market-day run.

Before writing, validate that latest valid Daily data has the current ET
trading date. Weekends and exchange holidays/no valid session are skipped;
never copy yesterday's cache as today's EOD data. A ticker whose own latest
Daily bar is stale is persisted as an explicit unavailable row, not an old
Decision. The EOD run shares the full
refresh lock with hourly provider refresh, so it cannot mix cache generations;
the scheduler may safely catch up only for the current date after 4:30 PM and
still must pass this session validation. Scheduler/API failure leaves no
partial success: all rows and the success state are committed together or
rolled back.

`历史记录/README-历史记录.md` documents operation, export, storage and the
complete removal procedure. `历史记录/导出历史记录.py` is an offline-only CSV /
JSON / JSONL exporter.

## Fibonacci horizon provenance

- Short Fibonacci: native 4H confirmed pivots first, with Daily only as a named secondary confirmation or explicit fallback.
- Mid Fibonacci: independently derived Daily confirmed pivots.
- Long Fibonacci: independently derived completed Weekly pivots; long-Daily is an explicit fallback only when Weekly cannot form a valid swing.

Every horizon Fibonacci object has independent derivation/source identifiers. Equal anchors across horizons are allowed only when independently derived; never share a mutable Fibonacci object or silently map Short to Daily.

## Profiles

Individual stocks use exactly three profile layers:

- Primary Classification
- Company Traits (business plus size/style/behavior traits)
- Lifecycle

Every individual stock must have a Primary Classification and at least three Company Traits. Profiles are reviewed annually, not changed on every refresh and not forced to change when reviewed. A profile update must alter the modifiers used by the engine, not merely the UI.

ETFs do not receive Company Traits or a Lifecycle. ETF profile fields are `isETF`, `leveraged`, `direction` (`long` or `inverse`), `underlying`, and optional `underlyingTicker`. Ordinary long ETFs reuse the V1 technical/market model. Leveraged ETFs use stricter gates and higher risk, exhaustion, and market sensitivity. Inverse ETFs use inverted underlying direction only as bounded confirmation; their own Technical states remain the Direction source.

## Stability and performance

The engine uses hysteresis and material-change overrides. Its bounded stability/profile caches have a 300-entry limit. Hysteresis may only smooth actions within the current Price State family (Buy↔Accumulate, Trim↔Sell); it must never retain an action across Opportunity, Neutral, Reduce, or Breakdown family boundaries. Restarting may remove hysteresis history but must not make decisions incorrect because signal persistence is derived from existing technical history.

Do not add unbounded recommendation history, duplicate Technical normalization/fetches, large deep clones, or heavy client chart libraries without a demonstrated need. Reuse normalized Technical/Market payloads once per refresh.

Temporary price candidates and confluence clusters belong only to the active
calculation. Do not retain candidate, cluster, debug, or landscape history in
production; final Decision debug may retain only compact selected-zone
provenance and candidate counts. The compact stability/profile caches remain capped at 300 entries;
every decision must be correct after a restart even without either cache.

## Coding rules

- Keep Decision Engine parameters centralized in `decision-engine/config.js`; do not scatter magic numbers.
- UI reads final Decision Objects only and never derives an action itself.
- Preserve complete canonical Technical data: Fibonacci, MA, RSI, MACD, ADX/DI, ATR, Bollinger, KDJ, OBV, Volume/RVOL, Relative Strength, and 52-week/history structure.
- Missing data must remain unavailable; never fake neutral/bullish values.
- Keep Chinese and English presentation strings synchronized, with a safe fallback for unknown reasons.
- Delete dead legacy code rather than wrapping it for compatibility.
- Every changed Decision behavior needs targeted tests.
- Never add ticker-specific recommendation hardcodes.

## Common mistakes to avoid

- `RSI > 70 => Sell` or `RSI < 30 => Buy`
- `ATR high => Bearish`
- `Fear & Greed => Buy/Sell`
- allowing the market to override an individual stock
- averaging Short/Mid/Long
- trait `+5/-5` scoring
- fixed-percentage buy zones
- separate formulas for action and execution zones
- previous-landscape reuse, cluster switching margins, or range hysteresis
- counting a stack of same-category moving averages as independent confluence
- allowing current price alone to manufacture a new Opportunity-zone centre
- calculating a complete Action before Price State and patching it with reconciliation exceptions
- treating a Near Opportunity or Near Reduce state as an actionable zone
- allowing Buy/Accumulate outside the exact Opportunity range
- allowing Trim/Sell outside the exact Reduce range without Breakdown/Invalidation
- Buy while current price is in a Reduce zone
- Hold while current price is in a Reduce zone
- overlapping Opportunity and Reduce zones, or a $0.01 fake neutral buffer
- assuming Opportunity automatically means Buy
- Current price between opportunity and reduce ranges but still Sell without breakdown
- Sell caused only by a high price
- showing remote technical support as a prediction
- reintroducing removed decision-target concepts under another name
- using Daily-only Fibonacci for Short without an explicit fallback reason
- sharing a Fibonacci object across horizons, or forcing different anchors merely to make horizons look different
- ETF using fake company traits
- inverse ETF ignoring its underlying
- leveraged ETF using identical risk rules as a 1x ETF
- rendering Hold as Buy or Avoid as Sell

## Testing

Run from the repository root:

```bash
/Users/vincentwang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/decision-engine.test.js
/Users/vincentwang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/technical-features.test.js
/Users/vincentwang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/dashboard-regression.test.js
/Users/vincentwang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/decision-ui.test.js
/private/tmp/stock-dashboard-test-venv/bin/python3 -m unittest discover -s tests -p 'server_availability_test.py'
/Users/vincentwang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node scripts/decision-audit.js
/Users/vincentwang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node scripts/decision-shadow.js
/Users/vincentwang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node scripts/fibonacci-audit.js
/Users/vincentwang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node scripts/refresh-memory-audit.js
/private/tmp/stock-dashboard-test-venv/bin/python3 -m unittest discover -s tests -p 'eod_history_test.py'
/Users/vincentwang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/eod-history-node.test.js
```

`decision-engine.test.js` includes joint price/action consistency, stateless-refresh, category-aware confluence, annual-review, ETF, and coverage checks. `technical-features.test.js` protects canonical data completeness and independent Fibonacci provenance. `dashboard-regression.test.js` protects data/UI regressions. `decision-audit.js`, `decision-shadow.js`, `fibonacci-audit.js`, and `refresh-memory-audit.js` are bounded cache-only audits.
`eod_history_test.py` and `eod-history-node.test.js` protect the independent
SQLite scheduler/write path and compact production-engine snapshot serializer.
