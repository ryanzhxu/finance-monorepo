# Archived Session Memory

Content pulled out of Claude Code's per-project auto-memory before a factory
reset (2026-09-13), for anything that was not already covered by
`README.md`, `CLAUDE.md`, or `AGENTS.md`. See those files first; this doc is
the only remaining record of what follows.

## Branch and deploy staleness is a recurring trap here

As of 2026-09-12, the branch `codex/prod-cutover` (frequently the branch
checked out locally) was **223 commits behind `origin/main`**, and dozens of
other stale `codex/*` feature branches/worktrees were also lingering (most
`git worktree list` entries showed `prunable`). `origin/main` is the branch
that actually reflects what should be live.

Separately, at the same time, the **deployed production frontend** (Cloudflare
Pages, `stock.ryanxu.dev`) **and backend** (Cloudflare Worker,
`finance-api.rxlab.workers.dev`) were themselves behind `origin/main` — e.g.
prod's screener had no "Opportunities" tab yet, and the live API still
returned raw `signal_weights.yaml`-style signal keys (`"EPS_Surprise"`)
instead of the human-readable names (`"EPS Surprise"`) that `origin/main`'s
`analyst_service/core/signals.py` already produced. So there can be **two
independent staleness gaps at once**: local-branch vs. `main`, and `main` vs.
what's actually deployed.

**Why this matters:** a bug reported against the live app may already be
fixed on `main` but not yet deployed, or may live in code that does not exist
on whatever branch happens to be checked out locally. Editing the checked-out
branch's stale copy of a file can silently fix nothing real.

**How to apply**, before fixing any live/production bug report in this repo:
1. `git fetch origin` and diff the checked-out branch against `origin/main`
   to check for staleness.
2. If stale, reproduce the bug directly against the live site/API (not the
   local checkout) to confirm current deployed behavior.
3. Do the fix in a fresh `git worktree` branched from `origin/main`, rather
   than on top of whatever WIP branch happens to be checked out — especially
   if that branch has uncommitted work that should not be disturbed.

Related but separate: `CLAUDE.md`'s test count is also known to drift out of
date (see below) — another instance of "trust a live check, not the doc."

## CLAUDE.md's expected pytest count has been stale before

`CLAUDE.md` states the pytest suite is "Expected: 68 passed" (still true in
the checked-out copy as of this writing). As of 2026-08-26, the real result
was **267 passed in ~27s**, via:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync pytest -q
```

The gap was caused by the untracked `backtesting/` forecast-research work
(~9.2k lines, 29 test files) landing after the "68 passed" line was written.
(A sibling worktree/branch, `finance-monorepo-autobuild`, has since recorded
"176 passed" with a different `--ignore` flag for `test_stock_research.py` —
another data point that this number moves and should not be trusted without
re-running.)

**How to apply:** always trust a fresh test run over the number written in
`CLAUDE.md`. If touching `CLAUDE.md` for another reason, fix the stale count
while there.

## Collaboration with Vincent Wang (shared ownership and an architecture conflict)

This context does not appear anywhere in `README.md`, `CLAUDE.md`, or
`AGENTS.md`, which only describe the technical stack. It is important
background for anyone (human or agent) touching recommendation-scoring logic.

**Who and why:** Ryan is building `finance-monorepo` jointly with **Vincent
Wang** (GitHub `vincentwang0909`, `vincent.wang@vanderlande.com`, at
Vanderlande, US/Georgia office). Ryan is in Vancouver at Trulioo; they sync
over WeChat across timezones, and the collaboration started around end of May
2026. Ryan's scheduling calendar for this is `ryan.xu@trulioo.com`.

They deliberately built **two separate apps with the same goal**, so each can
double-check the other. Stated test: "if both your app and mine recommend
NVDA, buy it." Verbally agreed division of labor: **Vincent owns product
ideas and the recommendation model; Ryan owns the technical/infrastructure
side.** Vincent's own framing: "主要的产品和想法你来 技术我可以稍微给点意见" — in
context, Ryan is the stronger engineer and Vincent leans on him for
architecture advice.

Coordination tooling: Ryan created a Jira board and invited Vincent (Ryan's
company uses Jira + Zoom + Google Calendar; Vincent's uses Microsoft DevOps +
Teams).

**The blocking architectural conflict, as last recorded:**

- Vincent's repo, `https://github.com/vincentwang0909/stock-decision-dashboard`
  (Flask `server.py` + browser-side JS decision engine, deployed on Render,
  512MB RAM / 0.5 CPU / 1GB disk — his configs are shaped by that limit), has
  an `AGENTS.md` that states: "Fundamental, valuation, options, and news data
  must never enter a recommendation." His pipeline is Technical ->
  Direction/Confirmation/Risk/Exhaustion -> Price Landscape -> Price State ->
  Action Family -> Action -> Confidence. Short/Mid/Long stay fully independent
  and are never averaged. There is deliberately no overall action and no
  numeric "AI score."
- Ryan's engine does the opposite: `analyst_service/config/signal_weights.yaml`
  blends technical, fundamental (`EPS_Surprise` 2.0, `Analyst_Ratings` 1.5,
  `PE_Percentile`, `Institutional_13F`), and sentiment (`News_Sentiment`,
  `Reddit_Sentiment`) into one weighted vote.

Neither approach is wrong — they answer different questions: Vincent answers
"when do I act," Ryan answers "is this worth owning." **Any consolidation
must keep them as separate layers, not merge the weights.** Do not propose
flattening one into the other without an explicit decision from both.

**Note on staleness of this conflict:** the `finance-monorepo-autobuild`
worktree (branch with work not yet on `main`) shows this was partly
addressed on 2026-08-28: "Technical layer ownership (decided 2026-08-28):
Vincent's engine supplies technicals; every other layer stays here. An
external decision.v1 verdict *replaces* the local technical vote — never
average the two," implemented as a `technical` block seam in `/analyze`
(`analyst_service/core/technical_provider.py`,
`cloudflare-api/src/technical-provider.js`) with a `technical_agreement`
field. That worktree's `docs/OPEN-DECISIONS.md` also tracks live open
questions with Vincent (auto-trading via Questrade, delivery shape, whether
the `decision.v1` contract is actually agreed with him yet, and a
horizon-mismatch question). Treat the "blocking conflict" framing above as
the last-fully-confirmed state on `main` — verify against current code and
that worktree's docs before assuming it still fully applies.

## Live URLs and access for both apps, and an unrelated side project

Not documented elsewhere in this repo's docs:

- Ryan's shared watchlist ("drama" space): `https://stock.ryanxu.dev/drama`,
  password `pg2018`. Backed by
  `screener_service/api/routers/shared_spaces.py`. Frontend is Cloudflare
  Pages (`finance-web-ui` project, custom domain added 2026-09-11), API is
  Cloudflare Workers (`finance-api.rxlab.workers.dev`, no custom domain) —
  both on the `ryanxu.dev` Cloudflare zone/account. Render was fully
  decommissioned before this; an old `onrender.com` URL was already stale
  when first recorded (this matches README/AGENTS.md's "no longer provisions
  Render resources," so only the specific URLs/password above are new here).
- Vincent's dashboard: `https://stock-decision-dashboard.onrender.com`
  (Render, 512MB RAM / 0.5 CPU / 1GB disk).
- Vincent's repo: `https://github.com/vincentwang0909/stock-decision-dashboard`
- Ryan's unrelated side project, an AI learning inbox:
  `https://ai-learning-inbox.rxlab.workers.dev/` — a phone shortcut posts a
  link, and the cheapest OpenAI model reads it and returns actionable steps.
