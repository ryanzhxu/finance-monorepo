# decision.v1 — unattended build loop

**Started:** 2026-08-26 07:40 PDT · **Runs until:** 22:43 tonight · **Cadence:** ~90 min
**Owner:** finance-monorepo-d2 (Claude). Ryan is AFK — this file is the handoff.

> **You have no memory of any conversation.** Everything you need is in this file and on disk.
> Read this file first, every cycle, before doing anything else.

---

## Mission

Build **`decision.v1`** — a shared contract that lets two independently-written stock engines
exchange a decision without either one changing its internal model.

- **Ryan's engine** (this repo) scores a blended weighted vote across technical, fundamental and
  sentiment signals. See `analyst_service/config/signal_weights.yaml`.
- **Vincent's engine** (`github.com/vincentwang0909/stock-decision-dashboard`, not in this repo)
  is technical-only by rule, and runs Technical → Direction/Confirmation/Risk/Exhaustion →
  Price Landscape → **Price State** → Action Family → Action → Confidence.

The contract must be expressible by both. It is a **data contract, not a model**. Do not encode
either side's scoring logic in it.

**Copy the existing pattern exactly.** `contracts/portfolio-research/` is a finished, committed
contract in this repo with README, `schema/`, `fixtures/` (valid + invalid), and `tests/`.
Mirror its structure, naming and test style into `contracts/decision/`.

---

## Hard guardrails — never violate

1. **Work only in this worktree**, `~/Developer/finance-monorepo-consolidation`, on branch
   `consolidation/decision-v1`. **Never** touch `/Users/ryan.xu/Developer/finance-monorepo`.
2. **Never `git push`.** Never deploy. Never run `make postman`.
3. **Never call an external data provider** (yfinance, Alpha Vantage, SEC EDGAR, Marketaux, FRED,
   Gemini). Repo policy forbids unapproved provider runs and you cannot get approval while Ryan
   is away. Contract work needs no network.
4. **Never touch the consumed 2023–24 final holdout** or anything under `backtesting/`.
5. **Additive only.** Create files under `contracts/decision/`. Do not modify
   `analyst_service/`, `screener_service/`, `shared/`, or `web_ui/` — changing live decision
   behaviour unattended is out of scope for this loop.
6. **One unit of work per cycle.** Then stop and wait for the next tick. Do not start a second.
7. If the test suite is red at step 2, **fix only that** and stop.

---

## The falsifier

The test suite is what proves the previous cycle honest. Run it **first**, every cycle:

```bash
cd ~/Developer/finance-monorepo-consolidation
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync pytest -q \
  --ignore=analyst_service/tests/test_stock_research.py
```

**Baseline: `138 passed`** (established 2026-08-26 07:37 PDT, commit `a480abe`).

Fewer than 138, or any error: you broke something. Fix it before new work.
More than 138: you added tests. Update the baseline number in this file.

### Why that file is excluded

`analyst_service/tests/test_stock_research.py` is **tracked**, but the module it imports
(`analyst_service/core/stock_research.py`) is **untracked** and therefore absent from this
worktree. The branch cannot pass without the ignore flag. This is a pre-existing defect in the
repo, not something you caused. **Do not try to fix it** — the missing sources are local WIP in
Ryan's main worktree. Just keep the ignore flag. It is logged for Ryan under Open Questions.

---

## Per-cycle procedure

1. Read this file. Read the Cycle Log from the bottom — the last entry says what to do next.
2. Run the falsifier. Record the number.
3. Do **one** bounded unit of work from the Plan.
4. Run the falsifier again. It must be ≥ baseline.
5. `git add -A && git commit -m "loop cycle N: <what changed>"`
6. Append a Cycle Log entry using the template. Commit that too.
7. Stop.

Keep each cycle tight. A small, correct, committed increment beats an ambitious broken one.

---

## Plan

Work top to bottom. Tick off as you go.

- [x] **1. `contracts/decision/README.md`** — what the contract is, who produces it, who consumes
      it, the versioning rule. Read `contracts/portfolio-research/README.md` first and match tone.
- [x] **2. `schema/decision.schema.json`** — the response envelope. Required fields:
      `contractVersion`, `ticker`, `generatedAt`, `horizons` (an object keyed `short`/`mid`/`long`).
- [x] **3. Horizon object** — `action`, `confidence`, `priceState`, `executionIntent`,
      `opportunityRange`, `reduceRange`, `invalidation`, `reasons`, `dataQuality`.
      Vocabularies below. Every price field nullable — missing data must stay missing.
- [x] **4. Valid fixtures** — at minimum: full three-horizon response; a horizon with an
      unavailable landscape; a technical-only producer (no fundamentals) so Vincent's engine fits.
- [ ] **5. Invalid fixtures** — wrong action for the price state (e.g. `buy` while
      `IN_REDUCE_ZONE`); overlapping opportunity/reduce ranges; unknown enum value; missing
      required field; unsupported version.
- [ ] **6. `tests/test_contract.py`** — validate every fixture against the schema, and
      assert the invalid ones fail *for the stated reason*. Mirror the portfolio-research tests.
- [ ] **7. Cross-engine invariants as tests** — `opportunityRange.high < reduceRange.low`;
      action must be legal for its price state; `short`/`mid`/`long` independent, never averaged.
- [ ] **8. Producer notes** — a short section in the README mapping each engine's native output
      onto the contract, so the mapping work is obvious later.

### Vocabularies (fixed — do not invent new members)

**camelCase**, matching `contracts/portfolio-research/` and the JS producer. Settled cycle 1.

```
action           strong_buy | buy | accumulate | hold | trim | sell | avoid
executionIntent  enter | add | hold | reduce | exit | avoid
priceState       IN_OPPORTUNITY_ZONE | NEAR_OPPORTUNITY_ZONE | NEUTRAL_ZONE |
                 NEAR_REDUCE_ZONE | IN_REDUCE_ZONE | BEYOND_REDUCE_ZONE |
                 BREAKDOWN_ZONE | INVALID_LANDSCAPE
horizon          short | mid | long
```

Legality rule the schema and tests must enforce:

| Price state | Actions permitted |
|---|---|
| `IN_OPPORTUNITY_ZONE` | `strong_buy`, `buy`, `accumulate` |
| `NEAR_OPPORTUNITY_ZONE`, `NEUTRAL_ZONE`, `NEAR_REDUCE_ZONE` | `hold` only |
| `IN_REDUCE_ZONE`, `BEYOND_REDUCE_ZONE` | `trim`, `sell` |
| `BREAKDOWN_ZONE` | `sell`, `avoid` |
| `INVALID_LANDSCAPE` | `hold`, `avoid` |

---

## Cycle log

Newest at the bottom. Append, never rewrite history.

### Template

```
### Cycle N — HH:MM PDT
- **Tests before / after:** 138 / 138
- **Did:** one sentence
- **Commit:** <sha>
- **Changed vs last cycle:** what is now different in the contract
- **Uncertain about:** anything a human should check
- **Next cycle should:** the single next unit of work
```

### Cycle 0 — 07:40 PDT (seed, by the interactive session)
- **Tests before / after:** — / 138
- **Did:** created the worktree and branch, verified the falsifier, wrote this file.
- **Changed vs last cycle:** n/a, first entry.
- **Uncertain about:** nothing yet.
- **Next cycle should:** do Plan item 1 — write `contracts/decision/README.md`, modelled closely
  on `contracts/portfolio-research/README.md`. Read that file before writing.

### Cycle 1 — 07:43 PDT
- **Tests before / after:** 138 / 138
- **Did:** Plan item 1 — wrote `contracts/decision/README.md`.
- **Commit:** `e38bb3b`
- **Changed vs last cycle:** the contract now has a written definition: purpose, layout,
  closed vocabularies, the price-state legality table, a producer mapping for both engines,
  and a Judgment calls section. No schema or fixtures yet.
- **Uncertain about:** I overrode the seed plan's field casing. The seed wrote
  `contract_version` / `price_state`; I used camelCase (`contractVersion`, `priceState`)
  because `contracts/portfolio-research/` is camelCase throughout and the dashboard producer
  is JavaScript emitting camelCase natively. **Later cycles must use camelCase** — the
  vocabulary block below still shows snake_case in one place and the README is now the
  authority. Also: I deferred a request envelope entirely, reasoning that the dashboard
  publishes a feed rather than answering requests. Both calls are logged in the README for
  Ryan to override.
- **Next cycle should:** do Plan item 2 — write `contracts/decision/schema/decision.schema.json`.
  Read `contracts/portfolio-research/schema/response.schema.json` first and match it exactly:
  draft 2020-12, `$id` under `https://finance-monorepo.internal/contracts/decision/v1/`,
  `contractVersion` as a `const`, `additionalProperties: false`, Z-suffixed timestamp pattern.
  Envelope only this cycle (`contractVersion`, `ticker`, `generatedAt`, `producer`, `horizons`);
  leave the horizon object itself to Plan item 3.

### Cycle 2 — 09:03 PDT
- **Tests before / after:** 138 / 138
- **Did:** Plan item 2 — wrote `contracts/decision/schema/decision.schema.json` (envelope only).
- **Commit:** `66c38b0`
- **Changed vs last cycle:** the contract is now machine-checkable at the envelope level.
  `contractVersion` is a `const`, `ticker` reuses the portfolio-research symbol pattern,
  `generatedAt` requires a Z suffix, and `additionalProperties: false` blocks an engine from
  smuggling internal scores across. All three horizon keys are required. Verified the schema is
  valid draft 2020-12 and that 10 envelope cases behave (share-class ticker, null price, wrong
  version, missing horizon, unknown field, underscore producer id, lowercase ticker, non-Z
  timestamp, negative price).
- **Uncertain about:** I added two fields the plan's item-2 list did not name.
  (a) `producer` — an object with `id` and optional `engineVersion`. This contract has two
  producers and the agreement layer cannot report concurrence without knowing who emitted what.
  `id` is a slug-patterned open string rather than a closed enum, so a third engine needs no
  version bump, while the pattern prevents `analyst_service` vs `analyst-service` drift.
  (b) `currentPrice` — one value per snapshot, so it belongs in the envelope not the horizon;
  item 7's legality invariants cannot be checked without it.
  Also considered and rejected: a top-level `status` (complete/partial/unavailable) as in
  portfolio-research. Per-horizon `dataQuality` from item 3 should cover it; adding both risks
  two sources of truth. Flag if you disagree.
  `$defs.horizonDecision` is deliberately unconstrained, so fixtures written before item 3
  lands will validate loosely. Item 3 must add `additionalProperties: false` and a required list.
- **Next cycle should:** do Plan item 3 — define `$defs.horizonDecision` in the same schema file.
  Fields: `action`, `confidence` (0-100, support consistency not a probability), `priceState`,
  `executionIntent`, `opportunityRange`, `reduceRange`, `invalidation`, `reasons`
  (supporting/limiting, max 5 each), `dataQuality`. Use the closed vocabularies in the Plan
  above. Every price field nullable. Add `additionalProperties: false` and a required list.
  Encode the price-state action legality table as `allOf` / `if` / `then` — that gate is the
  single most valuable thing this contract enforces. Re-run the same inline verification style
  as cycle 2 before committing.

### Cycle 3 — 10:43 PDT
- **Tests before / after:** 138 / 138
- **Did:** Plan item 3 — defined `$defs.horizonDecision` and encoded the price-state action
  legality table.
- **Commit:** `3bdd636`
- **Changed vs last cycle:** the contract now enforces its central rule. `buy` or `hold` inside
  `IN_REDUCE_ZONE` is a validation failure, and `INVALID_LANDSCAPE` additionally forces null
  ranges so a producer cannot emit fake-precision bands while claiming no landscape. All nine
  horizon fields are required including the nullable ones, so a consumer can tell "no zone" from
  "field not implemented". Verified exhaustively: all 56 priceState x action combinations behave,
  plus 9 edge cases (confidence bounds, reason caps, unknown fields, missing nullable key).
- **Uncertain about:**
  (a) **Two invariants are NOT schema-enforced and must land in item 7 tests**, or they will be
  silently unchecked: `priceRange.low < priceRange.high`, and
  `opportunityRange.high < reduceRange.low`. JSON Schema draft 2020-12 cannot compare two
  numeric fields. The schema descriptions say so, but a description enforces nothing.
  (b) `executionIntent` is enum-checked but NOT gated against `action`. A payload can legally
  say `action: sell` with `executionIntent: enter`. The Plan's legality table covers action
  only, so gating the pair would have been inventing a rule neither engine has written down.
  Logged as open question 9 — it probably should be gated, but by agreement, not by my guess.
  (c) `dataQuality.state` reuses portfolio-research's complete/partial/unavailable rather than a
  new vocabulary. `unavailable` is documented as expecting `INVALID_LANDSCAPE` but that pairing
  is not enforced either — another candidate for item 7.
- **Next cycle should:** do Plan item 4 — write the valid fixtures under
  `contracts/decision/fixtures/`. At minimum three files: `valid-three-horizon.json` (a full
  short/mid/long payload with real-looking ranges), `valid-unavailable-landscape.json` (one
  horizon at `INVALID_LANDSCAPE` with null ranges and `dataQuality.state: unavailable`), and
  `valid-technical-only.json` (producer id `stock-decision-dashboard`, no fundamentals anywhere,
  proving the contract fits an engine that forbids them). Use the filenames already listed in
  `contracts/decision/README.md` under Layout. Validate each against the schema before
  committing. Do NOT write the invalid fixtures — that is item 5.

### Cycle 4 — 12:03 PDT
- **Tests before / after:** 138 / 138
- **Did:** Plan item 4 — wrote the three valid fixtures.
- **Commit:** `2a1a8d3`
- **Changed vs last cycle:** the contract now has worked examples.
  `valid-three-horizon.json` (NVDA, dashboard) deliberately emits **buy / hold / trim** across
  short / mid / long on one ticker — a concrete demonstration of why averaging the horizons
  would be wrong. `valid-unavailable-landscape.json` (SBUX, analyst-service) shows honest
  degradation: short at `INVALID_LANDSCAPE` with null ranges and `dataQuality.state:
  unavailable`, mid `partial`, long `complete`. `valid-technical-only.json` (MU, dashboard)
  carries technical reasons only.
  Verified beyond schema validation: `low < high` and `opportunityRange.high < reduceRange.low`
  hold on all 9 horizons, `currentPrice` is coherent with every declared `priceState`, and a
  keyword scan finds no fundamentals vocabulary in the technical-only fixture.
- **Uncertain about:**
  (a) I hand-verified the coherence invariants with a throwaway script this cycle. **That script
  was not kept.** Item 7 must re-implement those checks as committed tests or the guarantee dies
  with this cycle. The specific checks: `low < high`; `opportunityRange.high < reduceRange.low`;
  `INVALID_LANDSCAPE` implies null ranges; `IN_OPPORTUNITY_ZONE` implies price inside the
  opportunity band; `IN_REDUCE_ZONE` implies price inside the reduce band; the three neutral and
  near states imply `opportunityRange.high < price < reduceRange.low`.
  (b) `valid-unavailable-landscape.json` shows `analyst-service` emitting a real landscape on
  mid and long. Per open question 1 it **cannot do that today** — it has no price-state
  classifier at all. The fixture is aspirational, describing the post-Phase-3 target rather than
  current behaviour. That is defensible for a contract fixture but a reader could mistake it for
  a capability claim. Say if you want it relabelled.
  (c) The near-zone boundary is producer-defined and ATR-normalized, so the coherence check can
  only assert `NEAR_*` sits somewhere in the neutral band, not that it is genuinely "near".
  That is unfalsifiable from the payload alone and probably should stay that way.
- **Next cycle should:** do Plan item 5 — write the invalid fixtures under
  `contracts/decision/fixtures/`, using the filenames already listed in
  `contracts/decision/README.md` under Layout: `invalid-action-for-price-state.json` (buy while
  `IN_REDUCE_ZONE`), `invalid-overlapping-ranges.json` (`opportunityRange.high >=
  reduceRange.low`), `invalid-unknown-enum.json`, `invalid-missing-required-field.json`,
  `invalid-unsupported-version.json`. Each must fail for exactly one stated reason — derive each
  from a copy of `valid-three-horizon.json` with a single mutation, so the reason is unambiguous.
  Note `invalid-overlapping-ranges.json` will NOT fail schema validation (JSON Schema cannot
  compare the two numbers); it is the fixture that proves item 7's test is doing real work, so
  write it and expect it to pass the schema and fail the invariant test. Do NOT write the test
  file — that is item 6.

---

## Open questions for Ryan

Do not act on these. Log more as you find them.

1. `analyst_service/tests/test_stock_research.py` is tracked while its source module is not.
   The committed branch cannot pass its own suite. Commit the sources or untrack the test.
2. `CLAUDE.md` states "Expected: 68 passed". The main worktree actually runs 267; this worktree
   runs 138 without the untracked WIP. All three numbers disagree.
3. `git worktree list` shows 18 worktrees marked `prunable` — their directories were wiped from
   `/private/tmp`. `git worktree prune` would clear the stale admin entries.
4. Field casing: the seed plan said snake_case, the repo's existing contract is camelCase.
   Resolved as camelCase in cycle 1. Say if you want it flipped before the schema is written.
5. `decision.v1` vs `stock-decision.v1` as the version string — the existing contract is named
   for its endpoint, this one is not named for anything yet.
6. Contract tests run standalone (`uv run --no-project --with jsonschema`), not under pytest,
   matching portfolio-research. So the 138 pytest baseline will not move as this work lands —
   the contract has its own separate exit-code check.
7. The envelope gained `producer` and `currentPrice` beyond the seeded field list (cycle 2).
   Both are justified in the cycle log; say if you want either dropped.
8. Rejected a top-level `status` field in cycle 2, on the grounds that per-horizon `dataQuality`
   covers it. Worth a second opinion once item 3 defines `dataQuality`.
9. `executionIntent` is not gated against `action` (cycle 3). `action: sell` with
   `executionIntent: enter` currently validates. The legality table you seeded covers action
   only. Worth agreeing a pairing rule with Vincent rather than inventing one.
10. Two numeric invariants cannot live in JSON Schema (`low < high`, and
   `opportunityRange.high < reduceRange.low`). They must be enforced in the item 7 tests or
   they are unchecked in practice.
11. `valid-unavailable-landscape.json` shows `analyst-service` emitting real opportunity and
   reduce bands on two horizons. It cannot do that until Phase 3 ports price-state
   classification. The fixture describes the target, not today. Relabel if that is misleading.
