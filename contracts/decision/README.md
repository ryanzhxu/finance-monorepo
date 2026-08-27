# decision.v1 contract

Canonical JSON Schema and fixtures for `decision.v1` — the payload two
independently-written stock engines use to exchange a decision without either
one changing its internal model.

- Producers: **both** engines (see "Producers" below).
- Consumer: the agreement layer, which surfaces where the two producers concur
  and where they disagree.
- Target endpoint: none yet. Schema and fixtures only, like
  `contracts/portfolio-research/` was at its first slice.

Unlike `portfolio-research.v1`, this contract has two producers rather than
one. That is the whole point of it: neither engine gets to impose its model on
the other, so the contract carries only what both can honestly emit.

## Status

This directory is being built incrementally. Current state:

- [x] `README.md` — this file
- [x] `schema/decision.schema.json`
- [x] `fixtures/valid-*.json` — 3 files
- [x] `fixtures/invalid-*.json` — 5 files
- [x] `tests/test_contract.py` — schema layer, 21 checks
- [x] `tests/test_invariants.py` — invariant layer, 12 checks
- [ ] `schema/error.schema.json` — **never built.** The Layout section below lists it and no
      plan item ever covered it. Decide whether this contract needs an error envelope at all: it
      may not, since it is currently a payload shape rather than an endpoint response.

## What this contract is not

It is a **data contract, not a model**. It must not encode either producer's
scoring logic.

The two engines disagree about what a recommendation may be built from, and
that disagreement is deliberate on both sides:

- **`analyst_service` (this repo)** scores a blended weighted vote across
  technical, fundamental and sentiment signals — see
  `analyst_service/config/signal_weights.yaml`, where `EPS_Surprise` carries
  the heaviest weight at `2.0`.
- **`stock-decision-dashboard`** (`github.com/vincentwang0909/stock-decision-dashboard`,
  not vendored here) is technical-only by written rule: *"Fundamental,
  valuation, options, and news data must never enter a recommendation."* Its
  pipeline runs Technical → Direction/Confirmation/Risk/Exhaustion → Price
  Landscape → Price State → Action Family → Action → Confidence.

So the contract carries the **decision and its price context**, never the
inputs that produced it. A field that only one producer could ever populate
does not belong here.

## Layout

```
contracts/decision/
  schema/
    decision.schema.json   # the decision payload
    error.schema.json      # error envelope
  fixtures/
    valid-three-horizon.json          # full short/mid/long response
    valid-unavailable-landscape.json  # a horizon with no usable price structure
    valid-technical-only.json         # a producer that emits no fundamentals
    invalid-action-for-price-state.json  # buy while IN_REDUCE_ZONE
    invalid-overlapping-ranges.json      # opportunityRange.high >= reduceRange.low
    invalid-unknown-enum.json
    invalid-missing-required-field.json
    invalid-unsupported-version.json
  tests/
    test_contract.py       # schema layer: fixtures vs JSON Schema
    test_invariants.py     # invariant layer: the rules JSON Schema cannot express
```

## Vocabularies

Closed enums. A producer that needs a member not listed here needs a new
contract version, not a new member.

```
action           strong_buy | buy | accumulate | hold | trim | sell | avoid
executionIntent  enter | add | hold | reduce | exit | avoid
priceState       IN_OPPORTUNITY_ZONE | NEAR_OPPORTUNITY_ZONE | NEUTRAL_ZONE |
                 NEAR_REDUCE_ZONE | IN_REDUCE_ZONE | BEYOND_REDUCE_ZONE |
                 BREAKDOWN_ZONE | INVALID_LANDSCAPE
horizon          short | mid | long
```

## Enforced boundaries

- **Action legality is gated by price state.** This is the contract's one real
  constraint, and it is what `analyst_service` currently lacks entirely — its
  weighted vote can emit BUY at any price. Encoded as a schema-level
  `allOf`/`if`/`then` so an illegal pairing is rejected, not merely discouraged:

  | `priceState` | actions permitted |
  |---|---|
  | `IN_OPPORTUNITY_ZONE` | `strong_buy`, `buy`, `accumulate` |
  | `NEAR_OPPORTUNITY_ZONE`, `NEUTRAL_ZONE`, `NEAR_REDUCE_ZONE` | `hold` |
  | `IN_REDUCE_ZONE`, `BEYOND_REDUCE_ZONE` | `trim`, `sell` |
  | `BREAKDOWN_ZONE` | `sell`, `avoid` |
  | `INVALID_LANDSCAPE` | `hold`, `avoid` |

- **Horizons are independent.** `short`, `mid` and `long` each carry their own
  complete decision. Nothing in this contract expresses an "overall" action,
  and a consumer must never average or vote across the three.
- **Missing data stays missing.** Every price field is nullable. A producer
  that cannot form a price landscape emits `priceState: INVALID_LANDSCAPE`
  with null ranges — never a fabricated neutral or a fake-precision range.
- **`opportunityRange.high < reduceRange.low`** whenever both are present.
  Overlapping zones make the legality table above ambiguous — one price would
  sit in two mutually exclusive states at once. Enforced by
  `tests/test_invariants.py`, **not** by the schema: draft 2020-12 cannot
  compare two numeric fields. `fixtures/invalid-overlapping-ranges.json` is
  schema-valid and is rejected only by that layer.
- **`contractVersion` is a `const` exact match** on `"decision.v1"`. Any other
  value is rejected outright, never best-effort parsed as v1.
- **`additionalProperties: false`** on every object, so an engine cannot
  quietly smuggle its internal scores across the boundary.

## Producers

Both engines emit the same payload from different internals. Neither mapping
requires changing the engine that produces it.

The `analyst_service` column below was verified against the code in this
worktree, not from recollection: `analyst_service/core/entry_engine.py`,
`analyst_service/core/confluence.py`, `shared/shared/enums.py` and
`shared/shared/models.py`.

| Contract field | `analyst_service` (verified) | `stock-decision-dashboard` |
|---|---|---|
| `action` | `Direction` gives only BUY / HOLD / SELL. `EntryAssessment.AVOID` supplies `avoid`. **`accumulate` and `trim` have no source at all.** | native `action`, already this vocabulary |
| `confidence` | `Recommendation.confidence`, but **0.0-1.0, not 0-100** — needs scaling. Computed as `majority_fraction * (data_quality_score / 100)`, so it already folds in data quality | native, recalculated after action selection |
| `priceState` | **3 of 8 states are already computed, as unnamed booleans inside `compute_entry`** — see below | native `priceState`, already this vocabulary |
| `executionIntent` | `EntryAssessment`, partially. `BUY_NOW`→`enter`, `WAIT_FOR_PULLBACK`/`WAIT_FOR_BREAKOUT`→`hold`, `AVOID`→`avoid`. `SHORT_TERM_TRADE_ONLY` and `LONG_TERM_CANDIDATE` are horizon-suitability judgments, not intents, and map to nothing | native `executionIntent` |
| `opportunityRange` | `EntryBlock.ideal_buy_zone`, a `tuple[float, float]` built from `ideal_low`/`ideal_high` in `compute_entry` | native `priceLandscape.opportunityRange` |
| `reduceRange` | **no equivalent.** `EntryBlock` carries `resistance_levels` and `breakout_buy_level`, neither of which is a reduce band | native `priceLandscape.reduceRange` |
| `invalidation` | `EntryBlock.invalidation_level`, computed as `min(support2, ma50 - atr)` | native |
| `dataQuality.state` | `data_quality_score`, an int 0-100 — needs thresholds to become the three-state enum | per-horizon technical data quality |
| `horizons` | **shape mismatch.** `Horizon` has four members (`1D`, `1W`, `2-4W`, `3-6M`) and is a *request parameter*: one horizon per call | all three computed every refresh |

### The priceState finding

The earlier claim that `analyst_service` cannot produce `priceState` at all was
too strong. Reading `compute_entry` shows three of the eight states are already
derived, just never named or exposed:

- `inside_zone = ideal_low <= current_price <= ideal_high` is exactly
  `IN_OPPORTUNITY_ZONE`.
- `is_overextended` (distance from MA20 over threshold, or price above the upper
  Bollinger band, or RSI over `overbought_rsi`) is close to an extended state.
- `current_price < invalidation_level` is already computed and passed to
  `decide_entry_assessment` as `invalidation_breached` — close to
  `BREAKDOWN_ZONE`.

The five remaining states all depend on a reduce band, which does not exist
here. So Phase 3 is smaller than it looked for the opportunity side and
unavoidable for the reduce side.

The right-hand column is close to a direct serialization; the left-hand column
needs real work. That asymmetry is expected — the dashboard's decision model is
further along, and this contract is deliberately shaped to what it already
produces rather than to a lowest common denominator.

## Running the tests

Same approach as `portfolio-research`: the repo does not depend on a JSON
Schema validator, and a schema-and-fixtures slice does not justify adding a
pinned dependency. The test pulls `jsonschema` in as an ephemeral `uv`
dependency that does not touch `pyproject.toml` or `uv.lock`:

Two commands, because the contract has two independent layers. Run both.

```bash
# schema layer - needs jsonschema
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-project --with jsonschema \
    python contracts/decision/tests/test_contract.py

# invariant layer - pure arithmetic, no dependency
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-project \
    python contracts/decision/tests/test_invariants.py
```

Exit code is `0` on success, `1` if any fixture does not match its expected
valid/invalid outcome.

Note this test does **not** run under `pytest`, so it does not appear in the
repo's pytest count. Run it explicitly.

## Judgment calls made in this slice

Each was resolved conservatively and is called out so a reviewer can override.

- **camelCase, not snake_case.** The build plan that seeded this work wrote
  field names as `contract_version` / `price_state`. Overridden to camelCase
  for two reasons: `contracts/portfolio-research/` — the only existing contract
  in this repo — is camelCase throughout (`contractVersion`, `generatedAt`,
  `providerStatus`), and the dashboard producer is JavaScript and already emits
  camelCase natively (`priceLandscape`, `executionIntent`, `opportunityRange`).
  snake_case would have cost a rename on both sides for no gain.
- **No request envelope in v1.** `portfolio-research` has request/response/error.
  This slice defines only the decision payload and an error envelope, because
  the producer boundary is not settled: the dashboard currently recomputes every
  watchlist ticker on a refresh and writes a daily EOD snapshot, which is a
  *published feed* shape, not a *request/response* shape. Adding a request
  envelope now would guess at a transport neither side has agreed to. Deferred
  rather than invented.
- **Action legality lives in the schema, not just the docs.** It could have been
  left as a producer-side rule. Encoding it as `if`/`then` makes an illegal
  pairing a validation failure, which is the single most valuable thing this
  contract can enforce given `analyst_service` has no such gate today.
- **`confidence` is a bounded number, not a probability.** The dashboard's
  written rule is that confidence means support consistency and stability, not a
  calibrated likelihood. Documented as `0-100` with that meaning stated in the
  field description, so a consumer cannot mistake it for a forecast probability.
- **No `reasonCodes` enum yet.** Both engines emit free-text reasons today
  (the dashboard caps at 5 supporting and 5 limiting). A closed enum would be
  invented rather than derived. Left as bounded free-text strings for v1; worth
  revisiting once real reason strings from both sides can be compared.

## Open questions for Ryan

1. **`priceState` has no producer in this repo.** `analyst_service` computes
   support/resistance in `confluence.py` and zones in `entry_engine.py`, but
   nothing classifies current price into the eight states. Until that exists,
   this repo can only emit `INVALID_LANDSCAPE`, which makes the contract
   one-directional in practice. That work is Phase 3 of the consolidation plan
   and is deliberately out of this loop's scope.
2. **Is `decision.v1` the right version string?** It is unprefixed, unlike
   `portfolio-research.v1` which is named for its endpoint. If this contract
   will sit alongside others, `stock-decision.v1` may age better.
3. **Vincent has not reviewed any of this.** The vocabularies here are read off
   his `AGENTS.md` and engine source, not agreed with him. He should see the
   contract before either side writes a mapping against it.
