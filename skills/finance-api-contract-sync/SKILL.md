---
name: finance-api-contract-sync
description: Use when changing FastAPI routers, shared request/response models, health payloads, frontend API types, OpenAPI output, Postman collections, or Render-facing API contracts in finance-monorepo.
---

# Finance API Contract Sync

Use this skill when a change affects request/response schemas, router paths, health payloads, search results, or any contract consumed by `web_ui`.

## Workflow

1. Edit the source contracts first: `shared/shared/models.py`, the relevant router, and any source examples.
2. Update `web_ui/src/api/client.ts` and `web_ui/src/api/types.ts` if the UI consumes the changed fields or endpoints.
3. Regenerate OpenAPI with `UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync python tools/dump_openapi.py` when working from a sandboxed Codex session.
4. Run `make postman` when npm/network access is available. It shells out to `npx -y openapi-to-postmanv2`.
5. If you intend to sync a Postman workspace and `POSTMAN_API_KEY` is set, run `make postman-push`.
6. Review the generated diff carefully. Do not hand-edit `openapi/` or `postman/` files.
7. If the change affects deployment wiring or env vars, update `render.yaml` and the repo guidance that references it.

## What To Check

- `shared/shared/models.py`
- `web_ui/src/api/client.ts`
- `web_ui/src/api/types.ts`
- `openapi/analyst.json`
- `openapi/screener.json`
- `postman/analyst.postman_collection.json`
- `postman/screener.postman_collection.json`
- `postman/local.postman_environment.json`
- `postman/render.postman_environment.json`

## When To Use

- Adding, removing, or renaming request/response fields
- Changing router paths, methods, or examples
- Updating `/health`, `/search`, startup/config behavior, or other payloads that affect API consumers
- Refreshing Postman collections after API changes
