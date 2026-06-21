---
name: finance-test-debug-workflow
description: Use when tests fail, startup/health checks break, frontend verification fails, or a behavior needs to be reproduced and verified in finance-monorepo. Covers targeted pytest runs, app startup checks, UI verification, and narrowing failures without broad churn.
---

# Finance Test And Debug Workflow

Use this skill when you need to reproduce, isolate, or verify a failure.

## Workflow

1. Reproduce the issue with the smallest command that exercises the bug.
2. Start with a targeted test file or test node before running the whole suite.
3. If the issue involves startup or health, run the relevant FastAPI app. In sandboxed Codex sessions, startup may succeed and socket binding may still fail with `operation not permitted`.
4. If the issue involves the UI, run the narrowest useful frontend command before broader checks.
5. Trace the real failure path before proposing a fix. Separate symptom, root cause, and verification evidence.
6. After a fix, rerun the exact failing check first, then the smallest relevant broader test set.
7. For API/model changes, run `UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync python tools/dump_openapi.py` and `make postman` when network access is available.

## Useful Commands

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync pytest path/to/test_file.py -q
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync pytest -q
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync uvicorn analyst_service.api.main:app --port 8001
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync uvicorn screener_service.api.main:app --port 8002
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync python tools/dump_openapi.py
curl -sS http://127.0.0.1:8001/health
curl -sS http://127.0.0.1:8002/screen/health
cd web_ui && npm run build
cd web_ui && npm run lint
```

## Notes

- Prefer the narrowest high-signal check first.
- Use `.venv/bin/pytest -q` only as a local fallback if the `uv` cache workaround still fails.
- The current lint baseline fails on `web_ui/src/views/Analyze.tsx` with `react-hooks/set-state-in-effect`.
- Keep the diff focused on the actual failure.
- Report commands, outcomes, and any environment limits that prevented full verification.
