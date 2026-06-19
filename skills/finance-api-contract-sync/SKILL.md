---
name: finance-api-contract-sync
description: Use when changing FastAPI routers, request/response models, OpenAPI output, Postman collections, or Render-facing API contracts in finance-monorepo.
---

# Finance API Contract Sync

Use this skill when a change affects request/response schemas, router paths, or API examples.

## Workflow

1. Edit the source contracts first: `shared/shared/models.py`, the relevant router, and any source examples.
2. Regenerate OpenAPI and Postman artifacts with `make postman`.
3. If you intend to sync a Postman workspace and `POSTMAN_API_KEY` is set, run `make postman-push`.
4. Review the generated diff carefully. Do not hand-edit `openapi/` or `postman/` files.
5. If the change affects deployment wiring or env vars, update `render.yaml` and the repo guidance that references it.

## What To Check

- `openapi/analyst.json`
- `openapi/screener.json`
- `postman/analyst.postman_collection.json`
- `postman/screener.postman_collection.json`
- `postman/local.postman_environment.json`
- `postman/render.postman_environment.json`

## When To Use

- Adding, removing, or renaming request/response fields
- Changing router paths, methods, or examples
- Updating health endpoints or startup/config behavior that affects API consumers
- Refreshing Postman collections after API changes
