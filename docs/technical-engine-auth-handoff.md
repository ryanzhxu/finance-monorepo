# Handoff: technical-engine auth + dependency health check

Context: finance-monorepo PR #80 (merged into `main` at `387632c`) removed the
silent degrade-to-local-technicals fallback for Vincent's decision.v1 pull.
`analyst_service` and the `cloudflare-api` Worker now send
`Authorization: Bearer <TECHNICAL_ENGINE_API_KEY>` when that env var is set,
but nothing validates it yet — his API is still fully unauthenticated, and a
failure now surfaces as a hard `502` instead of a silent local fallback.
Three work packets follow, per this repo's work-packet format.

---

## Packet 1 — Vincent: authenticate the decision.v1 endpoints

Mode: Feature
Goal: Require the shared bearer-token secret on the decision.v1 endpoints, since the finance-monorepo client now sends one and has a hard, no-fallback dependency on this API.
Repo: `stock-decision-dashboard` (Vincent's own repo/deployment) — NOT finance-monorepo. `technical_engine/` is imported into finance-monorepo read-only per its CLAUDE.md ("never edit it here — porting changes into it is a human decision"), so this change has to happen on his side.
Paths: the Flask route handlers for `/api/decision/<ticker>` and `/api/decisions`; the equivalent routes in his Cloudflare edge Worker deployment, if that's kept in sync separately.
Constraints:
- Gate only the two decision.v1 machine endpoints. Do not require the key on dashboard/watchlist/static routes — those serve his own browser users unauthenticated.
- Constant-time comparison (e.g. Python `hmac.compare_digest`) to avoid timing attacks.
- Missing header, missing env var, or mismatch → `401` JSON matching his existing error shape (e.g. `{"success": false, "error": "unauthorized"}`).
- Read the secret from an env var (e.g. `TECHNICAL_ENGINE_API_KEY`); never hardcode it.
Done:
- A request to `/api/decision/<ticker>` without a valid `Authorization: Bearer <key>` returns 401.
- A request with the correct header behaves exactly as today.
- Dashboard/watchlist routes are unaffected.

---

## Packet 2 — Ryan: generate and distribute the shared secret

Mode: Fix
Goal: Turn on the auth handshake once Vincent's side (Packet 1) is ready.
Repo: finance-monorepo + Vincent's deployment + Cloudflare
Paths: none (operational, not code)
Steps:
1. Generate one secret: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. Set `TECHNICAL_ENGINE_API_KEY` to that value in:
   - Render dashboard env var, for Vincent's `stock-decision-dashboard` service.
   - `analyst_service`'s own env (same mechanism as `ALPHA_VANTAGE_KEY` / `MARKETAUX_API_KEY` — plain env var, wherever that's set for the running deployment).
   - `wrangler secret put TECHNICAL_ENGINE_API_KEY` for the `cloudflare-api` Worker.
3. Confirm both ends agree: hit `/api/decision/<ticker>` once with the header (expect 200) and once without (expect 401).
Constraints: never commit the real value anywhere; never log it.
Done: `analyst_service` and the Worker successfully authenticate against Vincent's endpoint in a live request; a request with a wrong/missing key from anywhere else is rejected.

---

## Packet 3 — Feature: health-check for the technical-engine dependency

Mode: Feature
Goal: Surface Vincent's technical-engine API as a monitored dependency in the existing Health view. Since PR #80, `analyst_service` and the Worker hard-fail (502) if it's unreachable — that should be visible in Health before a user hits a broken `/analyze` call, not discovered only via a customer-facing error.
Repo: finance-monorepo
Paths:
- `analyst_service/api/routers/analysis.py` — extend the existing `/health` provider-status block (the one already reporting marketaux/alpha_vantage/reddit/stocktwits configured-vs-not) with a `technical_engine` row.
- `cloudflare-api` — mirror the same check wherever the Worker's own health/status endpoint lives.
- `web_ui`'s Health view — render the new row using the existing per-provider row component (icon + last-checked timestamp).
Constraints:
- This is a liveness/reachability check, not a full decision computation — keep it cheap (e.g. a lightweight request against a known ticker, or a dedicated health endpoint on his side if one exists) and don't hit his free-tier Render instance harder than necessary. Reuse the existing `HEALTH_PROBE_TTL_SECONDS` caching pattern already used for other providers rather than probing on every request.
- Don't add retries/backoff beyond what `technical_engine.py`'s client already does — this is a status check, not the real pull path.
- No new dependencies without approval (per CLAUDE.md).
Done:
- Health view shows a "Technical Engine (Vincent)" row with configured/reachable/unreachable state and a last-checked timestamp, following the existing provider-row pattern.
- Verify by pointing `TECHNICAL_ENGINE_BASE_URL` at an unreachable host and confirming the row flips to unreachable.
Context: this matters more now than it used to — an outage on Vincent's free-tier Render instance (cold start, downtime) surfaces as a hard 502 on `/analyze` instead of a silent degrade, so catching it proactively in Health is now worth doing.
