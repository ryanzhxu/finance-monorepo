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

- [ ] **1. `contracts/decision/README.md`** — what the contract is, who produces it, who consumes
      it, the versioning rule. Read `contracts/portfolio-research/README.md` first and match tone.
- [ ] **2. `schema/decision.v1.schema.json`** — the response envelope. Required fields:
      `contract_version`, `ticker`, `generated_at`, `horizons` (an object keyed `short`/`mid`/`long`).
- [ ] **3. Horizon object** — `action`, `confidence`, `price_state`, `execution_intent`,
      `opportunity_range`, `reduce_range`, `invalidation`, `reasons`, `data_quality`.
      Vocabularies below. Every price field nullable — missing data must stay missing.
- [ ] **4. Valid fixtures** — at minimum: full three-horizon response; a horizon with an
      unavailable landscape; a technical-only producer (no fundamentals) so Vincent's engine fits.
- [ ] **5. Invalid fixtures** — wrong action for the price state (e.g. `buy` while
      `IN_REDUCE_ZONE`); overlapping opportunity/reduce ranges; unknown enum value; missing
      required field; unsupported version.
- [ ] **6. `tests/test_decision_contract.py`** — validate every fixture against the schema, and
      assert the invalid ones fail *for the stated reason*. Mirror the portfolio-research tests.
- [ ] **7. Cross-engine invariants as tests** — `opportunity_range.high < reduce_range.low`;
      action must be legal for its price state; `short`/`mid`/`long` independent, never averaged.
- [ ] **8. Producer notes** — a short section in the README mapping each engine's native output
      onto the contract, so the mapping work is obvious later.

### Vocabularies (fixed — do not invent new members)

```
action           strong_buy | buy | accumulate | hold | trim | sell | avoid
execution_intent enter | add | hold | reduce | exit | avoid
price_state      IN_OPPORTUNITY_ZONE | NEAR_OPPORTUNITY_ZONE | NEUTRAL_ZONE |
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

---

## Open questions for Ryan

Do not act on these. Log more as you find them.

1. `analyst_service/tests/test_stock_research.py` is tracked while its source module is not.
   The committed branch cannot pass its own suite. Commit the sources or untrack the test.
2. `CLAUDE.md` states "Expected: 68 passed". The main worktree actually runs 267; this worktree
   runs 138 without the untracked WIP. All three numbers disagree.
3. `git worktree list` shows 18 worktrees marked `prunable` — their directories were wiped from
   `/private/tmp`. `git worktree prune` would clear the stale admin entries.
