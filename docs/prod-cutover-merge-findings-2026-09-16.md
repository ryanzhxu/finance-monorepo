# Findings: `codex/prod-cutover` vs `main` — 2026-09-16

Context: `codex/prod-cutover` was the checked-out branch. It is 229 commits
behind `origin/main` and carries 5 commits `main` doesn't have. This
documents what's on each side and what a merge would actually change.

## Uncommitted local changes (on `codex/prod-cutover`)

Modified: `.gitignore`, `AGENTS.md`, `README.md`, `pyproject.toml`,
`uv.lock`, `web_ui/src/api/client.ts`, `web_ui/src/views/Analyze.tsx`,
`web_ui/src/views/Research.tsx`.

Untracked: `.claude/` (includes a worktree, `agent-a529e9cbe96b62fe6`, that
already has a full copy of `technical_engine/`), `docs/`, a stock-research
orchestrator feature (`analyst_service/core/stock_research*.py` + tests +
config), and an uncommitted `backtesting/`/`tools/` forecasting and SEC
EDGAR data pipeline.

## Vincent technical-engine integration — auth & health-check status

Not present on `codex/prod-cutover` at all. Lives entirely on `main` via
PRs #76, #77, #79, #80. Key state as of PR #80 (merged 2026-09-15):

- Client-side `Authorization: Bearer <TECHNICAL_ENGINE_API_KEY>` support
  exists in both the Python client (`analyst_service`) and the Worker's
  dormant legacy HTTP client — sent when the env var is set.
- **No server-side validation exists yet** — that's Vincent's own change to
  make on `stock-decision-dashboard` (`technical_engine/` is imported
  read-only per this repo's CLAUDE.md).
- The silent local-technicals fallback was removed in #80: a pull failure
  now raises/502s instead of degrading quietly.
- Production's primary path doesn't call Vincent's API over HTTP at all —
  it runs his engine in-process via `CONSOLIDATED_DECISION=on`. The remote
  HTTP pull only matters for `analyst_service` (local dev, `:8001`) and the
  Worker's now-dormant legacy fallback path.
- A fully-drafted 3-packet handoff already exists at
  `docs/technical-engine-auth-handoff.md` (untracked, not yet committed on
  any branch): Packet 1 (Vincent's repo — add server-side bearer check),
  Packet 2 (ops — generate/distribute the shared secret), Packet 3
  (finance-monorepo — add a `technical_engine` row to `analyst_service`'s
  `/health` and mirror it in the Worker + Health view).
- Packet 3 is **not done**: `analysis.py`'s `_collect_health_probe_statuses`
  has no `technical_engine` entry. The Worker's existing `technical_engine`
  health field only reports the in-process engine version, not liveness of
  Vincent's remote endpoint.

## Merge analysis: `codex/prod-cutover` → `main`

Dry-run via `git merge-tree --write-tree` (no refs/working tree touched).
No open PR exists for `codex/prod-cutover`.

**Merges cleanly:** the new `portfolio-research.v1` contract (schemas,
fixtures, `test_contract.py`) and `analyst_service`'s stock-research
provider work. None of it overlaps the Vincent technical-engine code.

**6 conflicting files** — real behavioral disagreements, not just textual
noise:

1. `/batch` endpoint contract — see comparison below. Also touches
   `scripts/warm_cache.py` and `tests/test_warm_cache.py` (the caller/test
   side of the same contract).
2. Reddit/sentiment field naming (`cloudflare-api/src/index.js`,
   `web_ui/src/api/types.ts`, `web_ui/src/views/Analyze.tsx`) — both
   branches independently fixed "mislabeled Reddit-proxy metrics" but
   diverged: `main` keeps `reddit_mention_spike_24h_pct` /
   `reddit_positive_pct` as explicit nulls with a clarifying comment;
   `prod-cutover` removes both fields entirely. `Analyze.tsx` also differs
   cosmetically — `main` uses i18n keys (`t('volumeSpike')`, etc.),
   `prod-cutover` uses hardcoded English strings and a different
   percent-formatting call.

Neither conflict is resolvable by taking one side wholesale without a
product decision.

## `/batch` — before vs. after

Example: `POST /batch {"symbols": ["NVDA", "FAIL"]}`, where `NVDA` succeeds
and `FAIL` throws.

### Before (merge-base — common ancestor)

```js
try {
  responses.push(await buildAnalyze(symbol, {...}))
} catch {
  continue   // failure silently dropped
}
```

Response: `[ {...NVDA's raw analyze object...} ]` — array shrinks silently
on failure; caller has no way to know `FAIL` existed.

### After — `main`: envelope is unconditional

```js
responses.push({ symbol, response, error: null })
// on catch:
responses.push({ symbol, response: null, error: serializeBatchError(error) })
```

Response (always, regardless of request params):

```json
[
  { "symbol": "NVDA", "response": {...}, "error": null },
  { "symbol": "FAIL", "response": null, "error": { "code": "analysis_error", "message": "simulated upstream failure" } }
]
```

Fixes the silent-drop bug for every caller, but is a breaking change to the
old raw-array shape. `warm_cache.py` on `main` was updated in lockstep to
always expect the envelope.

### After — `prod-cutover`: envelope is opt-in via `include_errors`

```js
const includeErrors = body?.include_errors === true
responses.push(includeErrors ? { symbol, response, error: null } : response)
// on catch:
if (includeErrors) responses.push({ symbol, response: null, error: serializeBatchError(error) })
```

Default request (no flag) → identical to "before": `FAIL` is still
silently dropped, original bug not fixed for default callers.

Opt-in request (`"include_errors": true`) → same envelope shape as `main`.
`warm_cache.py` on this branch always passes `include_errors: True`, so it
gets the safe behavior; any other caller that doesn't pass the flag keeps
the old silent-drop bug.

### The actual disagreement

Both branches fix the silent-drop bug for `warm_cache.py` specifically.
They disagree on whether every `/batch` caller is forced into the fix
(`main`, breaking the old shape) or opts in per-request (`prod-cutover`,
backward-compatible but still buggy by default). Worth checking whether
anything besides `warm_cache.py` calls `/batch` today, to weigh the actual
cost of `main`'s breaking change against `prod-cutover`'s safer-but-still-
buggy-by-default approach.

## Open items

- A `codex/remove-batch-compatibility` branch/worktree already exists
  (`/private/tmp/finance-monorepo-batch-compat`) and looks directly related
  to the `/batch` contract question above — not yet inspected.
