---
name: finance-guidance-maintenance
description: Use when refreshing AGENTS.md, repo skills, README guidance, or other agent-facing docs in finance-monorepo. Covers inspecting current repo state, verifying documented commands, and keeping AGENTS concise while moving repeatable workflows into skills.
---

# Finance Guidance Maintenance

Use this skill when the task is to refresh repo guidance for future Codex sessions.

## Workflow

1. Inspect current repo state before editing docs: `git status`, current branch, recent commits, manifests, `render.yaml`, active app directories, tests, and existing skills.
2. Read `AGENTS.md`, `README.md`, `MARKET_OPPORTUNITY_SYSTEM_SPEC.md`, relevant package manifests, and any Claude guidance as secondary context.
3. Trust current code and deploy wiring over older docs. Call out mismatches instead of copying stale text forward.
4. Keep `AGENTS.md` short. Put repeatable workflows and caveats into `skills/*/SKILL.md`.
5. Update only the docs future sessions will realistically read first: root guidance, relevant skills, and clearly misleading feature README or agent files.
6. Verify the commands you document. If a command is blocked by sandbox, auth, or network, record the caveat instead of presenting it as reliable.
7. Avoid product code changes unless they are truly required to validate or clarify the guidance.

## Useful Checks

```bash
git status --short
git log --oneline --decorate -n 20
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync pytest -q
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync python tools/dump_openapi.py
cd web_ui && npm run build
make postman
```

## Repo-Specific Gotchas

- `web_ui/` is the live frontend; `portfolio_dashboard/` is still a placeholder.
- `make postman` depends on `npx -y openapi-to-postmanv2`, so network access matters.
- Sandboxed Codex sessions may block plain `uv run ...` cache access and local port binding.
- `openapi/` and `postman/` are generated artifacts. Refresh them through scripts rather than hand-editing.
