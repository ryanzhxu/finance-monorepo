# consolidated.v1 contract

Canonical JSON Schema and fixtures for `consolidated.v1` — the
`consolidated_decision` object `cloudflare-api` emits from `/analyze` and
`/decisions` for one symbol, across three independent horizons.

- Producer: **one** — `cloudflare-api/src/consolidated/pipeline.js`
  (`runConsolidated`), which runs Vincent's engine in process
  (`technical_engine/`, the majority), applies Ryan's fundamentals
  (`analyst_service`-derived signals, a minority that can only step a buy down
  one step) and the index hurdle, and composes the three into one decision per
  horizon. Nothing here is computed twice: every field is read off that
  pipeline's real output, never re-derived.
- Consumer: `web_ui` — `FinalDecisionPanel.tsx`, `DecisionBoard.tsx`,
  `Screener.tsx`, `TrackRecord.tsx`.
- Target endpoints: `GET /analyze` (`consolidated_decision` field) and
  `POST /decisions` (`results[].consolidated_decision`), both in
  `cloudflare-api/src/index.js`, only when `CONSOLIDATED_DECISION=on`.

## Status

This directory is being built incrementally, matching the pattern
`contracts/decision/` used (see `git show consolidation/decision-v1:contracts/decision/README.md`
for that precedent — it predates consolidation and is not on this branch).
Current state:

- [x] `README.md` — this file
- [x] `schema/consolidated.schema.json`
- [x] `fixtures/valid-*.json` — `valid-pass-with-buy.json`, `valid-fail-holds-buy.json`, `valid-engine-failure.json`
- [x] `fixtures/invalid-*.json` — `invalid-buy-with-failed-hurdle.json`, `invalid-unknown-action.json`, `invalid-missing-horizon.json`
- [x] `tests/test_contract.py` — schema layer (all 6 fixtures round-trip; run with
      `UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-project --with jsonschema python contracts/consolidated/tests/test_contract.py`)
- [x] `schema/error.schema.json` — decided, not needed. Writing the fixtures
      confirmed `errors` is an ordinary field of `consolidated.schema.json`
      (`$defs/errors`), not a separate transport envelope: `/analyze` and
      `/decisions` still return their own existing error shapes for a hard
      failure (missing symbol, engine off), and a partially-failed pipeline
      returns 200 with `errors` populated inline, already covered by
      `valid-engine-failure.json`.
- [ ] A Worker test that validates a real `runConsolidated` output against this
      schema, so the contract cannot drift from what the code actually emits.
      Deferred to the next slice.

## What this contract is not

It is a **data contract, not a model**. It documents the shape one already-built
pipeline emits, so `web_ui` and any future consumer can validate against it
instead of guessing from `cloudflare-api/src/index.js` reads. It must not
encode scoring logic — the schema records legality (e.g. action vs. price
state, action vs. hurdle status) as constraints because those are already
enforced in code (`final-decision.js`, `index-hurdle.js`), not because this
schema invents them.

Unlike `contracts/decision/` (a design for two independently-scored engines to
agree, superseded once Vincent's engine moved in-process — see spec D1 in
`docs/superpowers/specs/2026-09-11-master-repo-consolidation-design.md`), this
contract has exactly one producer. `decision.v1` still exists as a narrower,
per-horizon flattened shape (`technicalDetails.toDecisionV1` in
`cloudflare-api/src/consolidated/technical-engine.js`) kept only for the
`technical-provider.js` validation seam; `consolidated.v1` is the full object
the UI actually renders.

## Layout

```
contracts/consolidated/
  schema/
    consolidated.schema.json   # the consolidated_decision payload
  fixtures/
    valid-pass-with-buy.json          # hurdle passes, a buy survives
    valid-fail-holds-buy.json         # technical says buy, hurdle fails it to hold
    valid-engine-failure.json         # technical engine threw; errors populated
    invalid-buy-with-failed-hurdle.json
    invalid-unknown-action.json
    invalid-missing-horizon.json
  tests/
    test_contract.py       # schema layer: fixtures vs JSON Schema
```

## Vocabularies

Closed enums, read off the code that emits them, not invented for this
contract.

```
action            strong_buy | buy | accumulate | hold | trim | sell | avoid
                  (technical_engine/decision-engine/config.js `actions`)
executionIntent   enter | add | hold | reduce | exit | avoid
                  (technical_engine/decision-engine/execution-engine.js `executionIntent()`)
priceState        IN_OPPORTUNITY_ZONE | NEAR_OPPORTUNITY_ZONE | NEUTRAL_ZONE |
                  NEAR_REDUCE_ZONE | IN_REDUCE_ZONE | BEYOND_REDUCE_ZONE |
                  BREAKDOWN_ZONE | INVALID_LANDSCAPE
                  (technical_engine/decision-engine/execution-engine.js)
horizon           short | mid | long (cloudflare-api/config/consolidation.json `horizons`)
hurdleStatus      not_applicable | unavailable | pass | fail
                  (cloudflare-api/src/consolidated/index-hurdle.js `evaluateHurdle`)
benchmarkResult   insufficient_data | beats | lags | mixed
benchmarkRole     index | local_index | sector | industry
fundamentalStance unavailable | supportive | neutral | weak
                  (cloudflare-api/src/consolidated/final-decision.js `fundamentalStance`)
adjustmentLayer   technical | fundamentals | index_hurdle
adjustmentReason  technical_unavailable | fundamentals_weak |
                  index_hurdle_unavailable | index_hurdle_failed
dailyQuality      available | unavailable
fourHourQuality   available | unavailable | source_unavailable | invalid_source_data
earningsGuard     unavailable | fired | clear
```

`action` and `executionIntent` and `priceState` are the same vocabularies
`contracts/decision/` already used (verified against the same source files,
which have not changed), kept identical on purpose rather than reworded, so a
future reconciliation between the two contracts is a rename check, not a
re-derivation.

## Enforced boundaries

- **A `final_action` in the buy family requires the index hurdle to have
  passed or be not applicable.** This is the contract's central invariant and
  the one Ryan's rule depends on ("nothing reads as a buy unless it beats the
  indices"). Encoded as a schema-level `if`/`then`: `final_action` in
  `{strong_buy, buy, accumulate}` requires `index_hurdle.status` to be `pass`
  or `not_applicable`. `technical.action` (Vincent's own pre-hurdle call) is
  exempt — it is documentary, not a decision, and is gated only by
  `technical.price_state` the same way `contracts/decision/` gates `action`.
- **Horizons are independent.** `short`, `mid`, `long` each carry a complete,
  separately-computed decision. Nothing here expresses an overall action, and
  a consumer must never average or vote across the three
  (`technical_engine/AGENTS.md`, spec D1).
- **`technical.action` legality is gated by `technical.price_state`**, exactly
  the table `contracts/decision/README.md` documents (his engine has not
  changed): `IN_OPPORTUNITY_ZONE` → buy family only; the three neutral/near
  states → `hold` only; `IN_REDUCE_ZONE`/`BEYOND_REDUCE_ZONE` → `trim`/`sell`;
  `BREAKDOWN_ZONE` → `sell`/`avoid`; `INVALID_LANDSCAPE` → `hold`/`avoid` with
  null ranges.
- **Missing data stays missing.** `opportunity_range`, `reduce_range` and
  `invalidation` are nullable, and null whenever `price_state` is
  `INVALID_LANDSCAPE`. A horizon the pipeline could not evaluate at all sets
  `technical: null` and a single `adjustments` entry explaining why, rather
  than fabricating a landscape.
- **`version` is a `const` exact match** on `"consolidated.v1"`
  (`cloudflare-api/config/consolidation.json`).
- **`additionalProperties: false`** on every object, so a pipeline change that
  adds a field silently is a contract break, not a silent drift.

## Two different meanings of "data quality" in one payload

Read carefully before consuming this contract — the same English words appear
at two levels with different shapes and different meanings:

- `consolidated_decision.data_quality` (symbol-level, from
  `technical.dataQuality` in `market-data.js`): `{ daily, four_hour, one_hour,
  market }` — whether each price-history interval loaded, plus a 0-100
  percentage for market-context inputs (VIX, SPY, QQQ, 10Y yield, Fear &
  Greed).
- `consolidated_decision.horizons.<h>.technical.data_quality` (per-horizon,
  from `value.debug.dataQuality.score` inside Vincent's engine): a single
  0-100 number describing that horizon's own feature confidence. It is not
  the same score, not derived from the symbol-level object above, and not
  comparable across horizons the way a shared quality tier would be.

## Judgment calls made in this slice

- **snake_case, not camelCase**, unlike `contracts/decision/`. This contract
  documents what the Worker's Python-influenced side already emits
  (`cloudflare-api/src/consolidated/*.js` writes `final_action`,
  `opportunity_range`, `price_state`, matching `analyst_service`'s
  `shared/shared/models.py` snake_case, not the dashboard's camelCase) — the
  opposite reasoning `contracts/decision/README.md` gave for choosing
  camelCase there (it mirrored the dashboard's native JS shape). Renaming the
  Worker's actual JSON to fit the older contract's casing would make this
  document describe a payload that does not exist.
  - **`technical_details` and `market_structure` are typed loosely**
  (`available: boolean` plus untyped indicator fields, not closed enums), on
  purpose. Their string values (`crossover_state`, `squeeze_state`,
  `directional_bias`, …) are Vincent's internal vocabulary
  (`technical_engine/technical-features.js`, protected, read-only) surfaced
  read-only for a UI detail panel; enumerating every value here would pin this
  contract to his internals rather than to the pipeline's own decision
  boundary, which is `action`/`price_state`/`execution_intent`. `fibonacci.fib_zone`
  is documented as free text for the same reason — his engine composes it
  ("Between 61.8% and 78.6%"), it is not a fixed set.
- **No fixtures or tests in this slice.** Matching the `contracts/decision/`
  precedent of building README then schema before fixtures, and the
  supervisor's own instruction to split this contract into 2-3 passes. Next
  slice: 3 valid + 3 invalid fixtures and `tests/test_contract.py`, plus a
  Worker test (`cloudflare-api/test/`) that validates a real `runConsolidated`
  output against this schema so the contract cannot silently drift from the
  code it documents.

## Open questions for Ryan

1. **Should `decision.v1` be retired once this contract has tests?** It is
   currently kept alive only for the `technical-provider.js` fallback seam
   (pulling from the old standalone `decision-v1` Worker when
   `CONSOLIDATED_DECISION` is off). If that fallback path is ever removed,
   `contracts/decision/` (on the `consolidation/decision-v1` branch, never
   merged here) may be worth deleting rather than mirroring.
2. **Is `errors` a real error envelope or a degraded-decision field?** See the
   `schema/error.schema.json` status note above — this needs a decision before
   the next slice's fixtures are written, since an "engine failure" fixture
   depends on which shape is correct.
