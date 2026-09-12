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

```
git fetch origin main
git switch -c release/$(date +%Y%m%d) origin/main
git push -u origin release/$(date +%Y%m%d)
```

Then, in GitHub Actions, run "Deploy Production" with that branch selected
and approve the environment gate when prompted.

## Hotfixing a release branch

Commit the fix on the `release/*` branch, then open a PR to backport the same
fix to `main` so the next release branch cut from `main` still has it.

## Retiring a release branch

Delete it once its production deploy is confirmed stable, or keep it briefly
for a hotfix window.
