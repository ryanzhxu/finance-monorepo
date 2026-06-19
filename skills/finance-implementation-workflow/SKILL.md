---
name: finance-implementation-workflow
description: Use for normal code changes in finance-monorepo, including analyst_service, screener_service, shared, backtesting, and repo wiring. Covers reading the source of truth, making the smallest safe change, preserving service boundaries, and verifying with targeted tests.
---

# Finance Implementation Workflow

Use this skill for feature work, refactors, and bug fixes in this repo.

## Workflow

1. Read the source of truth first: `AGENTS.md`, `README.md`, `MARKET_OPPORTUNITY_SYSTEM_SPEC.md`, `pyproject.toml`, and the files in the service you are touching.
2. Confirm whether the change belongs in `shared/`, `analyst_service/`, `screener_service/`, or `backtesting/`.
3. Keep deterministic logic in `core/` modules and avoid hardcoded weights or thresholds when a YAML config already exists.
4. Keep the analyst/screener boundary intact. `screener_service` may call `analyst_service`; analyst should not call screener, dashboard, or execution code.
5. If the change touches routers, request models, or response models, use `finance-api-contract-sync`.
6. Do not edit generated files by hand. Regenerate them instead.
7. Verify the narrowest affected path first, then broaden only if needed.

## Practical Defaults

- Prefer the smallest behavior change that solves the problem.
- Preserve unrelated local edits.
- If a command fails because the local `uv` cache is unavailable, use the repo venv only as a verification fallback.
- Report exactly what you checked and what remains unverified.

## Good Signals To Re-read

- `shared/shared/models.py`
- `shared/shared/enums.py`
- `shared/shared/config_loader.py`
- `analyst_service/core/settings.py`
- `screener_service/core/settings.py`
- the relevant router or `core/` module
