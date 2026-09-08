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

1. **Keep Vincent's verdict pure.** His `AGENTS.md` states: fundamental,
   valuation, options and news data must never enter a recommendation; short/mid/
   long are independent and never averaged; there is no overall action. The
   current code violates all three — it blends his technical vote into one
   weighted score with Ryan's fundamentals. Replace that blend with a
   side-by-side model: his technical decision per horizon, unchanged and
   authoritative, and Ryan's layers reported next to it as separate context that
   never alters his action.
2. **Pull-based technical provider.** Today a verdict can only be pushed in on
   the request. Add an HTTP provider that fetches a `decision.v1` verdict from a
   configured base URL, behind the existing provider interface, off by default,
   with timeout, retry and a clean fall back to local technicals. Never call a
   live external host from a test.
3. **Per-horizon decisions.** His engine emits independent short / mid / long
   verdicts. `AnalyzeRequest` takes a single `horizon`. Carry all three through
   the contract without averaging them.
4. **Close a gap in the technical seam** — a `decision.v1` field not yet mapped,
   a legality or landscape invariant not yet enforced, a divergence between
   `analyst_service/core/technical_provider.py` and
   `cloudflare-api/src/technical-provider.js`.
5. **Then, and only then, Ryan's other layers** — surface the fundamental,
   sentiment, macro and valuation verdicts as their own explainable block beside
   the technical one.
6. Fix a reproducible correctness bug, with a failing test written first.
7. Cover an untested path in the technical seam or the aggregator.

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
