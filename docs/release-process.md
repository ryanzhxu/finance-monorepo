# Release process

Trunk-based development with a cut release branch. Three stages:

1. **main** — trunk. All work lands via PR, gated by CI (`ci.yml`). Every
   merge to `main` auto-deploys to QA (`deploy-qa.yml`):
   Worker → `finance-api-qa.rxlab.workers.dev`, site → `stock.qa.ryanxu.dev`.
2. **release/YYYYMMDD** — a release candidate, branched from `main` once QA
   has soaked the commit you want to ship. Only stabilization fixes land on
   it; backport them to `main` via PR so trunk never regresses.
3. **production** — never deploys automatically. Run `Deploy Production`
   (`deploy-prod.yml`) manually from the Actions tab against the `release/*`
   branch, targeting `stock.ryanxu.dev`. The `production` GitHub environment
   requires a manual approval before the job runs, and the environment's
   branch policy only allows `release/*` refs to use it.

## Cutting a release

Run **Promote to Production** (`promote-to-prod.yml`) from the Actions tab.
It re-runs CI against main, and only if that passes, creates
`release/YYYYMMDD` (UTC date) from main's current tip and dispatches
**Deploy Production** against it. Approve the `production` environment gate
when GitHub prompts - that's the only manual step.

To cut a release branch by hand instead (e.g. CI already ran and you just
want the branch):

```
git fetch origin main
git switch -c release/$(date -u +%Y%m%d) origin/main
git push -u origin release/$(date -u +%Y%m%d)
```

Then, in GitHub Actions, run "Deploy Production" with that branch selected
and approve the environment gate when prompted.

## Hotfixing a release branch

Commit the fix on the `release/*` branch, then open a PR to backport the same
fix to `main` so the next release branch cut from `main` still has it.

## Retiring a release branch

Delete it once its production deploy is confirmed stable, or keep it briefly
for a hotfix window.
