// Pull side of the technical seam: fetch a decision.v1 verdict over HTTP.
//
// Mirrors analyst_service/core/provider_clients/technical_engine.py. The
// verdict can already be pushed in on the /analyze request body. This adds
// the symmetric pull: when the Worker is asked to analyze a symbol and no
// verdict was supplied, it can fetch one from Vincent's engine at a
// configured base URL.
//
// Always requires env.TECHNICAL_ENGINE_BASE_URL (or the default, once set) to
// resolve — there is no off switch, and no degrade to local technicals on
// failure. Any network or protocol failure throws instead of returning null,
// so a broken engine fails the analysis loudly. The returned payload is a raw
// object; validation and rejection stay in technical-provider.js's
// resolveTechnicalVerdict, so a pulled verdict is trusted no more than a
// pushed one.
//
// KNOWN GAP (tracked separately, not fixed here): this issues one request per
// horizon with a `horizon` query param, but Vincent's real endpoint ignores
// that param and always returns all three horizons under `horizons` — see
// analyst_service/core/provider_clients/technical_engine.py, which was fixed
// to match his real shape. Until this file is fixed the same way, hitting a
// configured TECHNICAL_ENGINE_BASE_URL here will validate-fail in
// technical-provider.js and now, per the hard cutover, throw rather than
// degrade. Not reachable in production today: CONSOLIDATED_DECISION is "on"
// in wrangler.toml, which runs Vincent's engine in process and never reaches
// this client.

const DEFAULT_TIMEOUT_MS = 5000
// One retry: a single transient hiccup is common, a persistent outage should
// not stall the analysis behind a long retry chain.
const DEFAULT_RETRIES = 1

export function technicalEngineBaseUrl(env = {}) {
  const raw = env.TECHNICAL_ENGINE_BASE_URL
  if (raw == null) return null
  const trimmed = String(raw).trim().replace(/\/+$/, '')
  return trimmed || null
}

function envTimeoutMs(env) {
  const raw = env.TECHNICAL_ENGINE_TIMEOUT
  if (raw == null) return DEFAULT_TIMEOUT_MS
  const seconds = Number(raw)
  return Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : DEFAULT_TIMEOUT_MS
}

// Mirrors Python's int(raw): a decimal string like "3.0" is not a valid int
// literal there and raises ValueError, falling back to the default. Number()
// would parse it to a whole number and silently accept a different retry
// count than the Python service for the same env var.
function envRetries(env) {
  const raw = env.TECHNICAL_ENGINE_RETRIES
  if (raw == null) return DEFAULT_RETRIES
  if (!/^\s*[+-]?\d+\s*$/.test(String(raw))) return DEFAULT_RETRIES
  const value = Number(raw)
  return value >= 0 ? value : DEFAULT_RETRIES
}

export class TechnicalEngineUnavailable extends Error {}

// Fetch a decision.v1 verdict for `symbol`. Returns null only when the pull
// itself is not configured (no base URL) or the symbol is blank — neither is
// a failure. A configured pull that fails (network, protocol, or an unusable
// response) throws TechnicalEngineUnavailable instead of returning null, so a
// broken engine cannot masquerade as "no opinion".
export async function fetchExternalTechnicalVerdict(symbol, horizon, env = {}) {
  const baseUrl = technicalEngineBaseUrl(env)
  if (baseUrl == null) return null

  const normalizedSymbol = String(symbol ?? '').trim().toUpperCase()
  if (!normalizedSymbol) return null

  const url = new URL(`${baseUrl}/decision/${normalizedSymbol}`)
  if (horizon != null) url.searchParams.set('horizon', String(horizon))

  const timeoutMs = envTimeoutMs(env)
  const attempts = envRetries(env) + 1
  let lastError = null
  for (let attempt = 1; attempt <= attempts; attempt++) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    try {
      const headers = env.TECHNICAL_ENGINE_API_KEY ? { Authorization: `Bearer ${env.TECHNICAL_ENGINE_API_KEY}` } : {}
      // Prefer the service binding. A subrequest to a *.workers.dev host on the
      // same account is routed back to this Worker, which 404s because it has
      // no /api/decision route — so a public-URL fetch silently degrades to
      // local technicals. The binding routes straight to the target Worker.
      // Plain fetch remains the path for an engine hosted elsewhere.
      const response = env.TECHNICAL_ENGINE?.fetch
        ? await env.TECHNICAL_ENGINE.fetch(url, { headers, signal: controller.signal })
        : await fetch(url, { headers, signal: controller.signal })
      if (!response.ok) {
        throw new Error(`HTTP ${response.status} from ${url}`)
      }
      const payload = await response.json()
      if (payload != null && typeof payload === 'object' && !Array.isArray(payload)) {
        return payload
      }
      throw new TechnicalEngineUnavailable(`technical engine returned a non-object payload for ${normalizedSymbol}`)
    } catch (error) {
      if (error instanceof TechnicalEngineUnavailable) throw error
      lastError = error
      console.warn(
        `technical engine request for ${normalizedSymbol} failed (attempt ${attempt}/${attempts}): ${error}`,
      )
    } finally {
      clearTimeout(timer)
    }
  }
  throw new TechnicalEngineUnavailable(
    `technical engine request for ${normalizedSymbol} failed after ${attempts} attempt(s): ${lastError}`,
  )
}

// Fetch a decision.v1 verdict per horizon, keyed by the horizon requested.
// Mirrors analyst_service...fetch_external_technical_verdicts. Each horizon is
// an independent call through fetchExternalTechnicalVerdict; a horizon is
// absent from the result only when the pull is not configured or blank —
// any real failure throws rather than silently omitting that horizon.
export async function fetchExternalTechnicalVerdicts(symbol, horizons, env = {}) {
  const results = {}
  for (const horizon of horizons) {
    const payload = await fetchExternalTechnicalVerdict(symbol, horizon, env)
    if (payload != null) results[horizon] = payload
  }
  return results
}
