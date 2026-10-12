# Release process

GitHub Flow: `main` is the only branch that matters. Every merge to `main`
runs the full automated test suite (`deploy.yml`: Python tests, the
technical-engine tests, Worker tests, frontend tests and build) and, if it
passes, deploys straight to production — Worker to
`finance-api.rxlab.workers.dev`, site to `stock.ryanxu.dev`.

There is no QA environment, no release branch, and no manual approval gate.
That staged pipeline (`deploy-qa.yml` → `promote-to-prod.yml` →
`deploy-prod.yml`, retired 2026-10-12) existed for a solo project with one
production version and no compliance requirement — the only thing it
produced was a production release (`release/20260915`) that sat parked at
the manual-approval gate for a month, completely unreviewed, three commits
behind what QA had already soaked. The gate added latency, not safety.

If a change is risky enough to want a safety net, ship it dark behind a
feature flag and turn it on for yourself (or a canary) before enabling it
for everyone, rather than holding the whole merge back in a branch.

Reintroduce a staged pipeline only if one of these becomes true: multiple
production versions need to be supported in parallel, a compliance/audit
requirement mandates a formal QA sign-off, or there are paying customers
with a real uptime SLA who'd be hurt by a bad deploy. See the
`lean-release-pipeline` skill for the full decision criteria.

## Hotfixing

There's only one branch. Fix forward on `main`; it deploys on merge like
anything else.
