import test from 'node:test'
import assert from 'node:assert/strict'
import { fetchExternalTechnicalVerdict, fetchExternalTechnicalVerdicts } from '../src/technical-engine-client.js'
import { resolveTechnicalVerdict } from '../src/technical-provider.js'

// These tests mirror analyst_service/tests/test_technical_engine_pull.py. The
// two implementations must agree, or the Worker and the Python service will
// give different answers for the same pull configuration.

function payload(overrides = {}) {
  return {
    contractVersion: 'decision.v1',
    producer: 'vincent-stock-decision-dashboard',
    action: 'buy',
    confidence: 70,
    priceState: 'IN_OPPORTUNITY_ZONE',
    opportunityRange: { low: 100, high: 110 },
    reduceRange: { low: 140, high: 150 },
    invalidation: 95,
    reasons: ['Weekly trend intact'],
    dataQuality: 88,
    ...overrides,
  }
}

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

test('off by default returns null without calling out', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = () => {
    throw new Error('pull must not touch the network when off')
  }
  try {
    const result = await fetchExternalTechnicalVerdict('NVDA', '2-4W', {})
    assert.equal(result, null)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('pulls payload and builds the url with horizon', async () => {
  const originalFetch = globalThis.fetch
  let capturedUrl = null
  globalThis.fetch = (url) => {
    capturedUrl = url instanceof URL ? url : new URL(String(url))
    return Promise.resolve(jsonResponse(payload()))
  }
  try {
    const result = await fetchExternalTechnicalVerdict('nvda', '2-4W', {
      TECHNICAL_ENGINE_BASE_URL: 'https://engine.example/api/',
    })
    assert.equal(result.action, 'buy')
    // Trailing slash trimmed, symbol upper-cased, horizon forwarded.
    assert.equal(capturedUrl.origin + capturedUrl.pathname, 'https://engine.example/api/decision/NVDA')
    assert.equal(capturedUrl.searchParams.get('horizon'), '2-4W')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('blank symbol returns null without a network call', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = () => {
    throw new Error('blank symbol must not touch the network')
  }
  try {
    const result = await fetchExternalTechnicalVerdict('   ', '2-4W', {
      TECHNICAL_ENGINE_BASE_URL: 'https://engine.example',
    })
    assert.equal(result, null)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('network failure retries then falls back to null', async () => {
  const originalFetch = globalThis.fetch
  let calls = 0
  globalThis.fetch = () => {
    calls += 1
    return Promise.reject(new Error('boom'))
  }
  try {
    const result = await fetchExternalTechnicalVerdict('NVDA', '2-4W', {
      TECHNICAL_ENGINE_BASE_URL: 'https://engine.example',
      TECHNICAL_ENGINE_RETRIES: '2',
    })
    assert.equal(result, null)
    // 2 retries means 3 attempts total, and no exception escapes.
    assert.equal(calls, 3)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('non-object payload is ignored without retry', async () => {
  const originalFetch = globalThis.fetch
  let calls = 0
  globalThis.fetch = () => {
    calls += 1
    return Promise.resolve(jsonResponse(['not', 'an', 'object']))
  }
  try {
    const result = await fetchExternalTechnicalVerdict('NVDA', '2-4W', {
      TECHNICAL_ENGINE_BASE_URL: 'https://engine.example',
      TECHNICAL_ENGINE_RETRIES: '2',
    })
    assert.equal(result, null)
    // A well-formed but wrong-shaped response is a producer bug, not transient.
    assert.equal(calls, 1)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('pulled payload flows through the same seam', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = () => Promise.resolve(jsonResponse(payload()))
  try {
    const pulled = await fetchExternalTechnicalVerdict('NVDA', '2-4W', {
      TECHNICAL_ENGINE_BASE_URL: 'https://engine.example',
    })
    const { verdict, riskFlags } = resolveTechnicalVerdict(pulled)
    assert.deepEqual(riskFlags, [])
    assert.ok(verdict != null)
    assert.equal(verdict.source, 'external')
    assert.equal(verdict.direction, 'BUY')
    // decision.v1 0-100 confidence rescaled to 0.0-1.0.
    assert.equal(verdict.confidence, 0.7)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('pulled payload that violates the contract is rejected', async () => {
  const originalFetch = globalThis.fetch
  // SELL is illegal in an opportunity zone: the seam must reject, not accept.
  globalThis.fetch = () => Promise.resolve(jsonResponse(payload({ action: 'sell' })))
  try {
    const pulled = await fetchExternalTechnicalVerdict('NVDA', '2-4W', {
      TECHNICAL_ENGINE_BASE_URL: 'https://engine.example',
    })
    const { verdict, riskFlags } = resolveTechnicalVerdict(pulled)
    assert.equal(verdict, null)
    assert.deepEqual(riskFlags, ['external_technical_rejected'])
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('a decimal retries value falls back to the default', async () => {
  const originalFetch = globalThis.fetch
  let calls = 0
  globalThis.fetch = () => {
    calls += 1
    return Promise.reject(new Error('boom'))
  }
  try {
    // Python's int("3.0") raises ValueError, unlike JS's Number("3.0"), so this
    // must fall back to the default (1 retry) rather than silently using 3.
    const result = await fetchExternalTechnicalVerdict('NVDA', '2-4W', {
      TECHNICAL_ENGINE_BASE_URL: 'https://engine.example',
      TECHNICAL_ENGINE_RETRIES: '3.0',
    })
    assert.equal(result, null)
    assert.equal(calls, 2)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('fetchExternalTechnicalVerdicts makes one call per horizon', async () => {
  const originalFetch = globalThis.fetch
  const requested = []
  globalThis.fetch = (url) => {
    const parsed = url instanceof URL ? url : new URL(String(url))
    requested.push(parsed.searchParams.get('horizon'))
    return Promise.resolve(jsonResponse(payload()))
  }
  try {
    const horizons = ['1W', '2-4W', '3-6M']
    const result = await fetchExternalTechnicalVerdicts('NVDA', horizons, {
      TECHNICAL_ENGINE_BASE_URL: 'https://engine.example',
    })
    assert.deepEqual(requested, ['1W', '2-4W', '3-6M'])
    assert.deepEqual(Object.keys(result).sort(), horizons.slice().sort())
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('fetchExternalTechnicalVerdicts omits horizons that fail', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = (url) => {
    const parsed = url instanceof URL ? url : new URL(String(url))
    if (parsed.searchParams.get('horizon') === '3-6M') {
      return Promise.reject(new Error('boom'))
    }
    return Promise.resolve(jsonResponse(payload()))
  }
  try {
    const horizons = ['1W', '2-4W', '3-6M']
    const result = await fetchExternalTechnicalVerdicts('NVDA', horizons, {
      TECHNICAL_ENGINE_BASE_URL: 'https://engine.example',
      TECHNICAL_ENGINE_RETRIES: '0',
    })
    assert.deepEqual(Object.keys(result).sort(), ['1W', '2-4W'])
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('the service binding is used when present, and plain fetch when not', async () => {
  // Regression guard for a real outage: a public *.workers.dev subrequest on the
  // same account loops back to the calling Worker and 404s, which silently
  // degraded the technical layer to local technicals.
  const payload = { producer: 'p', action: 'hold', confidence: 50 }
  let bindingCalls = 0
  let globalCalls = 0

  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => { globalCalls += 1; return new Response(JSON.stringify(payload)) }
  try {
    const env = {
      TECHNICAL_ENGINE_BASE_URL: 'https://engine.example.com/api',
      TECHNICAL_ENGINE: {
        fetch: async () => { bindingCalls += 1; return new Response(JSON.stringify(payload)) },
      },
    }
    const viaBinding = await fetchExternalTechnicalVerdict('NVDA', '2-4W', env)
    assert.deepEqual(viaBinding, payload)
    assert.equal(bindingCalls, 1, 'binding must be used when bound')
    assert.equal(globalCalls, 0, 'global fetch must not be used when bound')

    // No binding (engine hosted elsewhere) -> plain fetch.
    const viaFetch = await fetchExternalTechnicalVerdict('NVDA', '2-4W', {
      TECHNICAL_ENGINE_BASE_URL: 'https://engine.example.com/api',
    })
    assert.deepEqual(viaFetch, payload)
    assert.equal(globalCalls, 1, 'plain fetch is the fallback')
  } finally {
    globalThis.fetch = originalFetch
  }
})
