import test from 'node:test'
import assert from 'node:assert/strict'
import worker, { __testOnly, ResearchRateLimiter, SharedWatchlistSpace } from '../src/index.js'
import { __researchTestOnly } from '../src/research.js'

test.beforeEach(() => {
  __testOnly.clearCaches()
})

function buildCandles(start = 100, step = 1, count = 240) {
  return Array.from({ length: count }, (_, index) => {
    const close = start + index * step
    return {
      timestamp: 1_700_000_000 + index * 86_400,
      open: close - 0.5,
      high: close + 1,
      low: close - 1,
      close,
      volume: 100_000 + index * 500,
    }
  })
}

function mockFinanceQueryFetch(input) {
  const rawUrl =
    typeof input === 'string'
      ? input
      : input instanceof URL
        ? input.href
        : input?.url ?? input?.href ?? String(input)
  const url = new URL(rawUrl)
  const now = Math.floor(Date.now() / 1000)
  if (url.pathname.includes('/lookup')) {
    return Promise.resolve(
      new Response(
        JSON.stringify({
          quotes: [
            { symbol: 'NVDA', longName: 'NVIDIA Corporation', exchange: 'NMS', quoteType: 'equity' },
            { symbol: 'SPY', longName: 'SPDR S&P 500 ETF', exchange: 'PCX', quoteType: 'etf' },
          ],
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    )
  }
  if (url.pathname.includes('/quote/')) {
    const symbol = decodeURIComponent(url.pathname.split('/').at(-1) ?? '')
    const marketPrice = symbol === '^VIX' ? 17.5 : symbol === '^TNX' ? 43.2 : symbol === 'SPY' ? 730 : 200
    return Promise.resolve(
      new Response(
        JSON.stringify({
          longName: symbol === 'NVDA' ? 'NVIDIA Corporation' : `${symbol} Holdings`,
          shortName: symbol,
          regularMarketPrice: marketPrice,
          regularMarketTime: 1_700_100_000,
          trailingPE: symbol === 'NVDA' ? 42.1 : 18.4,
          priceToBook: 12.4,
          priceToSalesTrailing12Months: 15.2,
          enterpriseToEbitda: 30.3,
          revenueGrowth: 0.22,
          grossMargins: 0.58,
          shortPercentOfFloat: 0.04,
          impliedVolatility: 0.32,
          earningsHistory: {
            history: [
              { quarter: now - 60 * 60 * 24 * 90, epsActual: 0.91, epsEstimate: 0.9, surprisePercent: 0.0111 },
              { quarter: now - 60 * 60 * 24 * 30, epsActual: 1.05, epsEstimate: 1.0, surprisePercent: 0.0554 },
            ],
          },
          upgradeDowngradeHistory: {
            history: [
              { epochGradeDate: now - 60 * 60 * 24 * 10, action: 'up', firm: 'Example Bank' },
              { epochGradeDate: now - 60 * 60 * 24 * 8, action: 'down', firm: 'Example Capital' },
            ],
          },
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    )
  }
  if (url.pathname.includes('/chart/')) {
    return Promise.resolve(
      new Response(JSON.stringify({ candles: buildCandles() }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
  }
  if (url.hostname === 'www.alphavantage.co') {
    return Promise.resolve(
      new Response(
        JSON.stringify({
          put_call_ratio_full_chain: 0.84,
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    )
  }
  return Promise.reject(new Error(`Unexpected fetch URL: ${url.toString()}`))
}

function mockCboeFallbackFetch(input) {
  const rawUrl =
    typeof input === 'string'
      ? input
      : input instanceof URL
        ? input.href
        : input?.url ?? input?.href ?? String(input)
  const url = new URL(rawUrl)
  if (url.hostname === 'www.alphavantage.co') {
    return Promise.resolve(
      new Response(
        JSON.stringify({
          Note: 'We have detected your API key as MRCATICKTTY5M9RR and our standard API rate limit is 25 requests per day.',
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    )
  }
  if (url.hostname === 'www.cboe.com' || url.hostname === 'ww2.cboe.com') {
    return Promise.resolve(
      new Response(
        `<!doctype html><html><body><h3>Total</h3><table class="data-table"><thead><tr><th>TIME</th><th>CALLS</th><th>PUTS</th><th>TOTAL</th><th>P/C RATIO</th></tr></thead><tbody><tr><td>03:00 PM</td><td>100</td><td>116</td><td>216</td><td>1.16</td></tr></tbody></table></body></html>`,
        { status: 200, headers: { 'content-type': 'text/html' } },
      ),
    )
  }
  return mockFinanceQueryFetch(input)
}

function createSharedWatchlistEnv() {
  const storage = new Map()
  const state = {
    storage: {
      async get(key) {
        return storage.get(key) ?? null
      },
      async put(key, value) {
        storage.set(key, value)
      },
    },
  }
  const env = {
    SHARED_WATCHLIST_SLUG: 'drama',
    SHARED_WATCHLIST_DISPLAY_NAME: 'Drama',
    SHARED_WATCHLIST_PASSCODE: 'swordfish',
    SHARED_WATCHLIST_SESSION_SECRET: 'very-secret-for-tests',
  }
  env.SHARED_WATCHLIST_SPACE = {
    idFromName() {
      return 'shared-watchlist-drama'
    },
    get() {
      return new SharedWatchlistSpace(state, env)
    },
  }
  return env
}

test('health endpoint returns worker status', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFinanceQueryFetch
  try {
    const response = await worker.fetch(new Request('https://example.com/health'))
    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.equal(payload.status, 'ok')
    assert.equal(payload.service, 'finance_api_worker')
    assert.equal(payload.providers.finance_query, 'ok')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('research jobs fail closed while decision support is disabled and do not call Cursor', async () => {
  const originalFetch = globalThis.fetch
  let cursorCalled = false
  globalThis.fetch = async () => {
    cursorCalled = true
    throw new Error('Cursor must not be called')
  }
  try {
    const response = await worker.fetch(
      new Request('https://example.com/research/jobs', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          question: 'Find AI infrastructure beneficiaries',
          mode: 'upside_discovery',
          universe: 'SP500',
          max_candidates: 5,
        }),
      }),
      { RESEARCH_ENABLED: 'false', CURSOR_API_KEY: 'should-not-be-used' },
    )
    assert.equal(response.status, 503)
    const payload = await response.json()
    assert.equal(payload.model_status, 'unavailable')
    assert.equal(cursorCalled, false)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('research decision support uses separate fail-closed gate and accepts analogy input', () => {
  assert.deepEqual(
    __researchTestOnly.researchGate({ RESEARCH_DECISION_SUPPORT_ENABLED: 'false', RESEARCH_MODEL_STATUS: 'validated' }),
    { ok: false, status: 503, detail: 'Research decision support is disabled' },
  )

  const parsed = __researchTestOnly.validateJobInput({
    question: 'Find durable demand growth.',
    mode: 'upside_discovery',
    universe: 'US-listed common stocks',
    analogy: 'Sandisk',
    max_candidates: 3,
  })
  assert.equal(parsed.value?.analogy, 'Sandisk')
  assert.equal(__researchTestOnly.validateJobInput({
    question: 'Find durable demand growth.',
    mode: 'upside_discovery',
    universe: 'US-listed common stocks',
    analogy: 'x'.repeat(241),
    max_candidates: 3,
  }).error, 'analogy must be at most 240 characters')
})

test('research result normalization emits evidence-backed decision support fields', () => {
  const discovery = __researchTestOnly.normalizeDiscovery({
    evidence: [{ id: 'filing-q1', title: 'Quarterly report', url: 'https://sec.gov/example' }],
    candidates: [{ symbol: 'mu', thesis: 'Memory demand could accelerate.', demand_driver: 'AI infrastructure demand.', evidence_ids: ['filing-q1'], disqualifiers: ['Supply risk.'] }],
  })
  const support = __researchTestOnly.buildDecisionSupport(
    discovery.candidates[0],
    discovery,
    {
      candidate_reviews: [{
        symbol: 'MU',
        analogy_comparison: { statement: 'Similar demand pattern, outcome unproven.', evidence_ids: ['filing-q1'] },
        thesis: 'Demand inflection remains plausible.',
        catalysts: [{ statement: 'AI buildout supports demand.', evidence_ids: ['filing-q1'] }],
        entry_conditions: [{ statement: 'Fresh filings must confirm demand.', evidence_ids: ['filing-q1'] }],
        reasons_to_avoid: [{ statement: 'Avoid if pricing weakens.', evidence_ids: ['filing-q1'] }],
        risks: [{ statement: 'Supply can outpace demand.', evidence_ids: ['filing-q1'] }],
        unknowns: ['Long-term margin durability.'],
        verdict: 'needs_more_evidence',
        risk_summary: 'Evidence remains narrow.',
      }],
    },
    { verdict: 'needs_more_evidence' },
  )

  assert.equal(support.candidate_rank, 1)
  assert.equal(support.symbol, 'MU')
  assert.equal(support.analogy_comparison.statement, 'Similar demand pattern, outcome unproven.')
  assert.equal(support.entry_conditions[0].evidence_ids[0], 'filing-q1')
  assert.equal(support.evidence[0].url, 'https://sec.gov/example')
})

test('research result normalization accepts Cursor single-candidate review shape', () => {
  const discovery = __researchTestOnly.normalizeDiscovery({
    evidence: [{ id: 'filing-q1', title: 'Quarterly report', url: 'https://sec.gov/example' }],
    candidates: [{ symbol: 'vrt', thesis: 'AI infrastructure demand may persist.', demand_driver: 'Data-center buildout.', evidence_ids: ['filing-q1'] }],
  })
  const support = __researchTestOnly.buildDecisionSupport(
    discovery.candidates[0],
    discovery,
    {
      candidate_review: {
        symbol: 'VRT',
        thesis: { statement: 'Near-term demand is supported.', evidence_ids: ['filing-q1'] },
        entry_conditions: [{ statement: 'Backlog execution must remain strong.', evidence_ids: ['filing-q1'] }],
        unknowns: ['Long-term demand duration.'],
      },
    },
    {
      analysis_verdict: {
        candidate: { symbol: 'VRT' },
        verdict: 'needs_more_evidence',
        risk_summary: 'Durability beyond backlog remains uncertain.',
      },
    },
  )

  assert.equal(support.thesis, 'Near-term demand is supported.')
  assert.equal(support.entry_conditions[0].statement, 'Backlog execution must remain strong.')
  assert.equal(support.review_verdict, 'needs_more_evidence')
  assert.equal(support.review_risk_summary, 'Durability beyond backlog remains uncertain.')
  assert.deepEqual(support.unknowns, ['Long-term demand duration.'])
})

test('research rate limiter permits three sequential runs but only one active run', async () => {
  const storage = new Map()
  const limiter = new ResearchRateLimiter({
    storage: {
      async get(key) {
        return storage.get(key) ?? null
      },
      async put(key, value) {
        storage.set(key, value)
      },
    },
  })
  const acquire = (jobId) =>
    limiter.fetch(
      new Request('https://quota.local', {
        method: 'POST',
        body: JSON.stringify({ operation: 'acquire', job_id: jobId }),
      }),
    )
  const release = (jobId) =>
    limiter.fetch(
      new Request('https://quota.local', {
        method: 'POST',
        body: JSON.stringify({ operation: 'release', job_id: jobId }),
      }),
    )

  assert.equal((await (await acquire('one')).json()).ok, true)
  assert.equal((await (await acquire('two')).json()).ok, false)
  await release('one')
  assert.equal((await (await acquire('two')).json()).ok, true)
  await release('two')
  await acquire('three')
  await release('three')
  assert.equal((await (await acquire('four')).json()).ok, false)
  assert.equal((await (await acquire('five')).json()).ok, false)
})

test('analyze endpoint falls back to cboe put/call ratio when alpha vantage is rate limited', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockCboeFallbackFetch
  try {
    const response = await worker.fetch(
      new Request('https://example.com/analyze', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ symbol: 'NVDA', include_narrative: true }),
      }),
      { ALPHA_VANTAGE_KEY: 'test-key' },
    )
    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.equal(payload.sentiment.put_call_ratio, 1.16)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('analyze endpoint returns a shaped response', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFinanceQueryFetch
  try {
    const response = await worker.fetch(
      new Request('https://example.com/analyze', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ symbol: 'NVDA', include_narrative: true }),
      }),
      { ALPHA_VANTAGE_KEY: 'test-key' },
    )
    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.equal(payload.symbol, 'NVDA')
    assert.ok(payload.entry)
    assert.ok(payload.recommendation)
    assert.equal(typeof payload.technicals.ma_20, 'number')
    assert.equal(typeof payload.recommendation.direction, 'string')
    assert.equal(payload.fundamentals.eps_surprise_pct, 5.54)
    assert.equal(payload.fundamentals.analyst_upgrades_30d, 1)
    assert.equal(payload.fundamentals.analyst_downgrades_30d, 1)
    assert.equal(payload.sentiment.put_call_ratio, 0.84)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('shared watchlist routes support session, login, add, and remove', async () => {
  const env = createSharedWatchlistEnv()
  const browserHeaders = {
    'cf-connecting-ip': '203.0.113.7',
    'user-agent': 'Mozilla/5.0 Test Browser',
    'sec-ch-ua': '"Chromium";v="149"',
    'sec-ch-ua-platform': '"macOS"',
    'accept-language': 'en-CA,en;q=0.9',
  }

  const unauthenticated = await worker.fetch(new Request('https://example.com/shared-spaces/drama/session'), env)
  assert.equal(unauthenticated.status, 200)
  assert.deepEqual(await unauthenticated.json(), {
    authenticated: false,
    slug: 'drama',
    display_name: 'Drama',
    session_token: null,
  })

  const loginResponse = await worker.fetch(
    new Request('https://example.com/shared-spaces/drama/login', {
      method: 'POST',
      headers: { 'content-type': 'application/json', ...browserHeaders },
      body: JSON.stringify({ passcode: 'swordfish' }),
    }),
    env,
  )
  assert.equal(loginResponse.status, 200)
  assert.match(loginResponse.headers.get('set-cookie') ?? '', /shared_space_session=/)
  const loginPayload = await loginResponse.json()
  assert.equal(loginPayload.authenticated, true)
  assert.equal(loginPayload.slug, 'drama')
  assert.equal(loginPayload.display_name, 'Drama')
  assert.match(loginPayload.session_token ?? '', /\./)

  const sessionCookie = loginResponse.headers.get('set-cookie')?.split(';', 1)[0] ?? ''
  const sessionToken = loginPayload.session_token

  const authenticatedSession = await worker.fetch(
    new Request('https://example.com/shared-spaces/drama/session', {
      headers: {
        authorization: `Bearer ${sessionToken}`,
      },
    }),
    env,
  )
  assert.equal(authenticatedSession.status, 200)
  assert.deepEqual(await authenticatedSession.json(), {
    authenticated: true,
    slug: 'drama',
    display_name: 'Drama',
    session_token: sessionToken,
  })

  const browserSession = await worker.fetch(
    new Request('https://example.com/shared-spaces/drama/session', {
      headers: browserHeaders,
    }),
    env,
  )
  assert.equal(browserSession.status, 200)
  assert.deepEqual(await browserSession.json(), {
    authenticated: true,
    slug: 'drama',
    display_name: 'Drama',
    session_token: null,
  })

  const addResponse = await worker.fetch(
    new Request('https://example.com/shared-spaces/drama/watchlist', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        authorization: `Bearer ${sessionToken}`,
      },
      body: JSON.stringify({ symbol: 'nvda' }),
    }),
    env,
  )
  assert.equal(addResponse.status, 200)
  assert.deepEqual((await addResponse.json()).symbols, ['NVDA'])

  const browserWatchlist = await worker.fetch(
    new Request('https://example.com/shared-spaces/drama/watchlist', {
      headers: browserHeaders,
    }),
    env,
  )
  assert.equal(browserWatchlist.status, 200)
  assert.deepEqual((await browserWatchlist.json()).symbols, ['NVDA'])

  const removeResponse = await worker.fetch(
    new Request('https://example.com/shared-spaces/drama/watchlist/nvda', {
      method: 'DELETE',
      headers: {
        authorization: `Bearer ${sessionToken}`,
      },
    }),
    env,
  )
  assert.equal(removeResponse.status, 200)
  assert.deepEqual((await removeResponse.json()).symbols, [])

  const cookieSession = await worker.fetch(
    new Request('https://example.com/shared-spaces/drama/session', {
      headers: {
        cookie: sessionCookie,
      },
    }),
    env,
  )
  assert.equal(cookieSession.status, 200)
  assert.equal((await cookieSession.json()).authenticated, true)
})
