# AUTOPILOT.md — autobuild descriptor for finance-monorepo (consolidation branch)

The loop reads this every pass. It is the only project-specific configuration.
This file is for the `consolidation/master` branch and its QA deploy only.

## Goal

Make `finance-monorepo` the one master repo for Ryan's and Vincent's stock apps,
per `docs/superpowers/specs/2026-09-11-master-repo-consolidation-design.md`
(read it first, every pass). The decisions in its section 2 are final:

- Technical analysis = Vincent's engine only (`technical_engine/`), run in
  process in the Worker. Technical is the majority.
- Ryan's fundamentals stay as a minority layer: weak fundamentals step a mid or
  long buy down one step. They never create a buy or a sell.
- Index hurdle: a buy must show evidence that it beats SPY, QQQ, its sector ETF
  and every matching industry ETF over the next 12 months. Otherwise it is held.
- The React `web_ui` is the single UI.

Every landed pass deploys to QA (`https://stock.qa.ryanxu.dev`, API
`https://finance-api-qa.rxlab.workers.dev`) through `.github/workflows/deploy-qa.yml`.
Ryan tests QA in the morning, so a working QA site beats a clever half-feature.

## Supervisor notes

Read `.autobuild/SUPERVISOR.md` every pass if it exists. A supervising session
writes priority notes there. A note there overrides the ranking below.

## Value ranking (what "highest-value" means here)

Pick ONE per pass, highest first. **Done, do not redo:** Vincent's engine in
process with native 4h/1h + market context; index hurdle; fundamentals layer
and Worker fundamental signals; `consolidated_decision` in `/analyze`; Final
Decision + Index Hurdle panel (3 locales); QA Worker, QA site, QA workflow;
Vincent's test-fixture fix; CI running Vincent's tests.

1. **QA is broken → fix it first.** Check `gh run list --branch consolidation/master --limit 3`.
   If the newest Deploy QA run failed, fix the cause in code (you cannot edit
   workflows). A smoke check of the live QA API with `curl` is allowed.
2. **Screener buy flags respect the hurdle** (spec backlog 7). A screen result
   the Worker flags as a buy must carry the hurdle status, and the UI must not
   present it as a buy when the hurdle fails. Mind the Worker subrequest budget:
   evaluate the hurdle only for rows that are buy candidates, at most 10 per
   response, and mark the rest `not_evaluated`. Benchmarks are shared, so load
   each benchmark series once per request.
3. **ETF underlying context.** Vincent's engine takes `underlyingTechnicalFeatures`
   and `underlyingPrice` for leveraged and inverse ETFs (`profile-definitions.js`
   `underlyingTicker`). The Worker passes null. Load the underlying's bars and pass
   them, exactly the way `technical_engine/server.py` does. Add a test.
4. **Localize Vincent's action labels in the UI.** His engine has
   `config.actionLabels` (en/zh). The new panel shows English action slugs in
   every locale. Use proper labels in `en`, `zh-Hans`, `zh-Hant-HK`.
5. **Descriptive hurdle backtest** (spec backlog 9). A script under `tools/`
   that, for a fixed list of at most 60 current large caps plus the benchmark
   ETFs, computes the hurdle monthly from 2012 to 2022 and the next-12-month
   return relative to each benchmark, and writes `docs/consolidation/hurdle-backtest.md`
   with the pass-vs-fail hit rates and a survivorship-bias caveat. One Yahoo chart
   request per symbol, cached under a git-ignored directory, run once (reuse the
   cache on reruns). Never tune a threshold on it. Never touch the consumed
   2023–2024 forecast holdout. Tests for the script use fixtures.
6. **Remove the service-binding hop** once in-process is proven: the production
   (top-level) `wrangler.toml` still points `TECHNICAL_ENGINE_BASE_URL` and the
   `TECHNICAL_ENGINE` binding at the `decision-v1` Worker. Switch the top-level
   config to `CONSOLIDATED_DECISION = "on"` and drop the binding, so a future
   merge serves the consolidated decision. Update the tests that pin the config.
7. **Docs for the one-repo layout**: README, CLAUDE.md (AGENTS.md is now merged
   into it; its test count is stale), and a short `technical_engine/README` note
   that the directory is Vincent's app imported with history from the local clone.
8. **UI quality** on the Final Decision panel: mobile layout, a readable "why"
   line per horizon (Vincent's top reasons), empty and error states.
9. Fix a reproducible correctness bug, with a failing test written first.
10. Cover an untested path in `cloudflare-api/src/consolidated/`.

## Protected paths — NEVER modify

- `technical_engine/**` — Vincent's engine. Porting into it is a human decision
  (spec D1). Read it freely; import it; never edit it.
- `.github/workflows/**` — CI and deploy wiring is a human decision
- `docs/superpowers/specs/**` — the agreed design
- `cloudflare-api/config/consolidation.json` → `windows`, `minEvidence`,
  `earningsGuard`, `fundamentals` values. These are fixed a priori. You MAY add
  ETF mappings (`sectorEtfs`, `industryEtfs`, `traitEtfs`, `localIndexBySuffix`).
- `analyst_service/config/signal_weights.yaml` and the `SIGNAL_WEIGHTS` values in
  `cloudflare-api/src/data.js` — final pending a Phase 4 backtest
- `backtesting/cache/**` and any consumed holdout dataset
- `MARKET_OPPORTUNITY_SYSTEM_SPEC.md`, `docs/OPEN-DECISIONS.md`

## Constraints

- **Never touch Vincent's GitHub remote** (`github.com/vincentwang0909/...`). Never
  fetch from it or push to it.
- **Never deploy production.** Never run `wrangler deploy` without `--env qa`,
  never deploy `finance-web-ui`, never touch `stock.ryanxu.dev`. Do not deploy by
  hand at all: the runner pushes, and `deploy-qa.yml` deploys QA.
- **Never open a PR and never push to `main`.** Do not commit or push yourself;
  the runner does.
- **Never place a trade, and never add an order path.**
- The LLM computes nothing. Every indicator, score and price level is code.
- Never fabricate a missing value. Missing stays missing and fails closed.
- Vincent's rules hold for his layer: horizons are independent and never
  averaged, there is no overall action, price state gates the action family.
- No numeric 12-month forecast in the UI. The hurdle shows historical relative
  returns and pass/fail only.
- Tests never call a live provider. Use fixtures. A pass may `curl` the QA API
  for a smoke check.
- No new dependency unless it is the only reasonable option.
- One logical change per pass. Keep the diff small and reviewable.
- Write a SHORT imperative first clause in your PROGRESS.md line (it becomes the
  commit title, capped at 72 chars). Put the analysis after the first " — ".
- New user-facing strings need `en`, `zh-Hans` and `zh-Hant-HK`. Never
  machine-convert one Chinese locale into the other, never write Cantonese.
- If a change needs a decision only a human should make, skip it and write why
  in `PROGRESS.md` under `## Needs human`.

## Machine config (read by autobuild.sh — keep exact key = value format)

```autobuild
verify = UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync pytest -q && node --test technical_engine/tests/*.test.js && (cd cloudflare-api && npm test) && (cd web_ui && npm test && npm run build) && git diff --check
gate = direct
notify = gh issue create --title "{title}" --body "{body}"
branch_prefix = autobuild
email_to = ryanxu.dev@gmail.com
email_cmd = curl -s -X POST https://api.resend.com/emails -H "Authorization: Bearer $RESEND_API_KEY" -H "Content-Type: application/json" -d "$(jq -n --arg to "$AB_TO" --arg s "$AB_SUBJECT" --arg b "$(cat)" '{from:"onboarding@resend.dev",to:$to,subject:$s,text:$b}')"
```

Notes:

- `gate = direct` is right here: the runner pushes to `consolidation/master`,
  which is unprotected, and `deploy-qa.yml` re-runs every test before it deploys.
  `main` is untouched.
- `verify` is the same set `deploy-qa.yml` runs, so a pass that verifies locally
  deploys.
- `email_cmd` needs `RESEND_API_KEY` from `~/.config/autobuild/env`.
