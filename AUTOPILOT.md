# AUTOPILOT.md — autobuild descriptor for finance-monorepo

The loop reads this every pass. It is the only project-specific configuration.

## Goal

Build the composite engine agreed by Ryan and Vincent on 2026-08-28: **Vincent's
technical analysis system owns the technical layer; Ryan's other layers —
fundamental, sentiment, macro, valuation, entry/confluence, data quality —
compose *beside* it, never inside it.**

Work Vincent's technical side to a finished state first. Only once the technical
layer is complete and trustworthy should passes move on to layering Ryan's other
analysis on top.

## Value ranking (what "highest-value" means here)

Pick ONE per pass, highest first.

**Done, do not redo:** the pure-verdict split (#21), the pull provider (#23/#24),
per-horizon decisions (#25/#26), the track record (#43), the avoid-is-not-sell
fix (#45), the cutover through a service binding (#46/#47), the per-horizon UI
(#48), and the Chinese locales (#49). His engine is live at
decision-v1.rxlab.workers.dev and owns the technical layer in production.

1. **Close the short-horizon gap.** His short horizon returns
   `INVALID_LANDSCAPE` because it needs native 4h and 1h bars, and Yahoo exposes
   1h but no native 4h. His engine refuses to synthesize one on purpose
   (`validate_native_four_hour_history_frame`). Adding 1h fetching, and a real
   4h source, is the single largest remaining functional gap. Never fabricate a
   4h bar by resampling — report the horizon unavailable instead.
2. **Consolidate the two engines further.** Anything that still duplicates
   between Ryan's local technicals and Vincent's engine, or between
   `analyst_service/core/technical_provider.py` and
   `cloudflare-api/src/technical-provider.js`. Divergence between those two
   mirrors is always a bug.
3. **Surface the track record.** `/history/{symbol}`, `/history/performance` and
   `/history/coverage` exist and are unreachable from the UI. A Track Record
   view answers the question Vincent asked twice, and `/history/coverage` costs
   no provider call so the empty state is free.
4. **Worker parity for the track record.** The history endpoints are Python-only;
   production serves the Worker.
5. **Locale upkeep.** Any new user-facing string needs `en`, `zh-Hans` and
   `zh-Hant-HK`. Never machine-convert one Chinese locale into the other, and
   never reintroduce Cantonese — `web_ui/test/locales.test.mjs` enforces both.
6. Fix a reproducible correctness bug, with a failing test written first.
7. Cover an untested path in the technical seam, the aggregator, or the
   track record.

## Protected paths — NEVER modify

- `analyst_service/config/signal_weights.yaml` — final pending a Phase 4 backtest
- `.github/workflows/**` — CI and deploy wiring is a human decision
- `backtesting/cache/**` and any consumed holdout dataset
- `docs/OPEN-DECISIONS.md` — that file records decisions for Ryan and Vincent;
  append a new open question only, never resolve one
- `MARKET_OPPORTUNITY_SYSTEM_SPEC.md` — the spec is changed deliberately, not by a loop

## Constraints

- **Never place a trade, and never add an order path.** Spec §2 constraint 1.
  Vincent's Questrade request is an open decision, not a backlog item.
- The LLM computes nothing. Every indicator, score and price level is pandas or
  plain arithmetic.
- Never fabricate a missing value. Missing stays missing and lowers confidence.
- `technical_provider.py` and `technical-provider.js` are mirrors. Change one,
  change both, and keep the parity tests passing.
- `decision.v1` confidence is 0-100; `Recommendation.confidence` is 0.0-1.0.
  Always rescale.
- After any API or model change, run `make postman` and commit `openapi/` and
  `postman/`.
- No new dependency unless it is the only reasonable option.
- One logical change per pass. Keep the diff small and reviewable.
- Write a SHORT imperative PR/commit title (under ~70 chars) describing the
  change. Put the analysis in the body. Nine PRs in the 2026-09-08 run shared
  one pasted PROGRESS.md paragraph as their title and were indistinguishable in
  the PR list.
- If a change needs a decision only a human should make, skip it and write why
  in `PROGRESS.md` under `## Needs human`.
- Never call a live market data provider (yfinance, Alpha Vantage, SEC EDGAR,
  Marketaux, Gemini) from a test or from a pass. Use fixtures.

## Machine config (read by autobuild.sh — keep exact key = value format)

```autobuild
verify = uv run pytest -q && (cd cloudflare-api && npm test) && (cd web_ui && npm ci --silent && npm run build)
gate = pr
notify = gh issue create --title "{title}" --body "{body}"
branch_prefix = autobuild
email_to = ryanxu.dev@gmail.com
email_cmd = curl -s -X POST https://api.resend.com/emails -H "Authorization: Bearer $RESEND_API_KEY" -H "Content-Type: application/json" -d "$(jq -n --arg to "$AB_TO" --arg s "$AB_SUBJECT" --arg b "$(cat)" '{from:"onboarding@resend.dev",to:$to,subject:$s,text:$b}')"
```

Notes:

- `gate = pr` is correct and also unavoidable: `main` requires a pull request and
  a green `check` status, enforced for admins too, so a direct push is refused.
- `verify` is the same set CI runs, so a pass that verifies locally should stay
  green in CI.
- `email_cmd` needs `RESEND_API_KEY` exported from `~/.config/autobuild/env`.
  Without it, milestones still arrive as a GitHub issue via `notify`.
