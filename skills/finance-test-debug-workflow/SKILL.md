---
name: finance-test-debug-workflow
description: Use when tests fail, startup/health checks break, or a behavior needs to be reproduced and verified in finance-monorepo. Covers targeted pytest runs, app health checks, and narrowing failures without broad churn.
---

# Finance Test And Debug Workflow

Use this skill when you need to reproduce, isolate, or verify a failure.

## Workflow

1. Reproduce the issue with the smallest command that exercises the bug.
2. Start with a targeted test file or test node before running the whole suite.
3. If the issue involves startup or health, run the relevant FastAPI app and hit its health endpoint.
4. Trace the real failure path before proposing a fix. Separate symptom, root cause, and verification evidence.
5. After a fix, rerun the exact failing check first, then the smallest relevant broader test set.
6. For API/model changes, also run `make postman`.

## Useful Commands

```bash
uv run pytest path/to/test_file.py -q
uv run pytest -q
uv run uvicorn analyst_service.api.main:app --port 8001
uv run uvicorn screener_service.api.main:app --port 8002
curl -sS http://127.0.0.1:8001/health
curl -sS http://127.0.0.1:8002/screen/health
```

## Notes

- Prefer the narrowest high-signal check first.
- Use `.venv/bin/pytest -q` only as a local fallback if the `uv` cache is blocked in the current environment.
- Keep the diff focused on the actual failure.
- Report commands, outcomes, and any environment limits that prevented full verification.
