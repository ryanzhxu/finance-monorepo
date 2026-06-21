---
name: finance-implementation-workflow
description: Use for normal code changes in finance-monorepo, including analyst_service, screener_service, shared, web_ui, backtesting, and repo wiring. Covers reading the source of truth, making the smallest safe change, preserving service boundaries, and verifying with targeted tests.
---

# Finance Implementation Workflow

Use this skill for feature work, refactors, and bug fixes in this repo.

## Workflow

1. Read the source of truth first: `AGENTS.md`, `README.md`, `MARKET_OPPORTUNITY_SYSTEM_SPEC.md`, `render.yaml`, the relevant `pyproject.toml`, and the files in the area you are touching.
2. Confirm whether the change belongs in `shared/`, `analyst_service/`, `screener_service/`, `web_ui/`, `backtesting/`, or repo wiring. `execution_engine/` and `portfolio_dashboard/` are still placeholders.
3. Keep deterministic backend logic in `core/` modules and avoid hardcoded weights or thresholds when a YAML config already exists.
4. Keep the analyst/screener boundary intact. `screener_service` may call `analyst_service`; analyst should not call screener, UI, or placeholder directories.
5. If the change touches routers, shared models, health payloads, or UI-facing response shapes, use `finance-api-contract-sync`.
6. Do not edit generated files by hand. Regenerate them instead.
7. Verify the narrowest affected path first, then broaden only if needed.

## Practical Defaults

- Prefer the smallest behavior change that solves the problem.
- Preserve unrelated local edits.
- If a command fails because the local `uv` cache is unavailable, use `UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync ...` before falling back to the repo venv.
- Re-run `cd web_ui && npm run build` after UI changes. Lint exists, but the current baseline fails on `web_ui/src/views/Analyze.tsx`.
- Report exactly what you checked and what remains unverified.

## Good Signals To Re-read

- `shared/shared/models.py`
- `shared/shared/enums.py`
- `shared/shared/config_loader.py`
- `analyst_service/core/settings.py`
- `screener_service/core/settings.py`
- `web_ui/src/api/client.ts`
- `web_ui/src/api/types.ts`
- the relevant router or `core/` module
