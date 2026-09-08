// Pull side of the technical seam: fetch a decision.v1 verdict over HTTP.
//
// Mirrors analyst_service/core/provider_clients/technical_engine.py. The
// verdict can already be pushed in on the /analyze request body. This adds
// the symmetric pull: when the Worker is asked to analyze a symbol and no
// verdict was supplied, it can fetch one from Vincent's engine at a
// configured base URL.
//
// Off by default. Without env.TECHNICAL_ENGINE_BASE_URL set, every call
// returns null and the analysis degrades to the local technicals exactly as
// before. Any network or protocol failure also returns null, so a slow or
// broken engine never takes the analysis down. The returned payload is a raw
// object; validation and rejection stay in technical-provider.js's
// resolveTechnicalVerdict, so a pulled verdict is trusted no more than a
// pushed one.

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

function envRetries(env) {
  const raw = env.TECHNICAL_ENGINE_RETRIES
  if (raw == null) return DEFAULT_RETRIES
  const value = Number(raw)
  return Number.isInteger(value) && value >= 0 ? value : DEFAULT_RETRIES
}

// Fetch a decision.v1 verdict for `symbol`, or null when off/unavailable.
// Returns the raw payload object on success. Returns null when the pull is
// off, the symbol is blank, or every attempt fails, so the caller falls back
// to the local technicals.
export async function fetchExternalTechnicalVerdict(symbol, horizon, env = {}) {
  const baseUrl = technicalEngineBaseUrl(env)
  if (baseUrl == null) return null

  const normalizedSymbol = String(symbol ?? '').trim().toUpperCase()
  if (!normalizedSymbol) return null

  const url = new URL(`${baseUrl}/decision/${normalizedSymbol}`)
  if (horizon != null) url.searchParams.set('horizon', String(horizon))

  const timeoutMs = envTimeoutMs(env)
  const attempts = envRetries(env) + 1
  for (let attempt = 1; attempt <= attempts; attempt++) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    try {
      const response = await fetch(url, { signal: controller.signal })
      if (!response.ok) {
        throw new Error(`HTTP ${response.status} from ${url}`)
      }
      const payload = await response.json()
      if (payload != null && typeof payload === 'object' && !Array.isArray(payload)) {
        return payload
      }
      console.warn(`technical engine returned a non-object payload for ${normalizedSymbol}; ignoring`)
      return null
    } catch (error) {
      console.warn(
        `technical engine request for ${normalizedSymbol} failed (attempt ${attempt}/${attempts}): ${error}`,
      )
    } finally {
      clearTimeout(timer)
    }
  }
  return null
}
