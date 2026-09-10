import test from 'node:test'
import assert from 'node:assert/strict'
import worker, { __testOnly, ResearchRateLimiter, SharedWatchlistSpace } from '../src/index.js'
import { __researchTestOnly } from '../src/research.js'
import { verdictFromExternal } from '../src/technical-provider.js'

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

function mockBatchFailureFetch(input) {
  const rawUrl =
    typeof input === 'string'
      ? input
      : input instanceof URL
        ? input.href
        : input?.url ?? input?.href ?? String(input)
  const url = new URL(rawUrl)
  if (url.pathname.endsWith('/quote/FAIL')) {
    return Promise.reject(new Error('simulated upstream failure'))
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

test('Pages origin receives credentialed CORS headers', async () => {
  const response = await worker.fetch(
    new Request('https://example.com/health', {
      method: 'OPTIONS',
      headers: {
        Origin: 'https://finance-web-ui.pages.dev',
        'Access-Control-Request-Method': 'GET',
        'Access-Control-Request-Headers': 'content-type, authorization',
      },
    }),
  )
  assert.equal(response.status, 204)
  assert.equal(response.headers.get('access-control-allow-origin'), 'https://finance-web-ui.pages.dev')
  assert.equal(response.headers.get('access-control-allow-credentials'), 'true')
  assert.equal(response.headers.get('vary'), 'Origin')
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

test('research decision support uses separate fail-closed gate and ignores legacy analogy input', () => {
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
  assert.equal(parsed.error, undefined)
  assert.equal(Object.hasOwn(parsed.value ?? {}, 'analogy'), false)
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

test('his verdict is the action; Ryan layers ride beside it, not inside it', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFinanceQueryFetch
  try {
    const response = await worker.fetch(
      new Request('https://example.com/analyze', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          symbol: 'NVDA',
          include_narrative: false,
          technical: {
            producer: 'vincent-stock-decision-dashboard',
            action: 'sell',
            confidence: 80,
            priceState: 'BREAKDOWN_ZONE',
          },
        }),
      }),
      { ALPHA_VANTAGE_KEY: 'test-key' },
    )
    assert.equal(response.status, 200)
    const recommendation = (await response.json()).recommendation

    // His action and his confidence survive verbatim.
    assert.equal(recommendation.direction, 'SELL')
    assert.equal(recommendation.confidence, 0.8)

    // Ryan's layers are reported, and say whether they agree.
    assert.ok(recommendation.supporting_context, 'supporting_context must be present')
    assert.equal(typeof recommendation.supporting_context.agrees_with_action, 'boolean')
    // Never technical - those belong to him.
    const dims = recommendation.supporting_context.signals.map((s) => s.dimension)
    assert.ok(!dims.includes('RSI_14'))
    assert.ok(!dims.includes('Technical_External'))
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('his fractional confidence survives verbatim, not down-rounded to 2 dp', async () => {
  // Same payload, same number from either engine: analyst_service reports 0.667
  // for confidence 66.7, so the Worker must not report 0.67. Mirrors
  // test_confidence_is_his_at_full_precision on the Python side.
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFinanceQueryFetch
  try {
    const response = await worker.fetch(
      new Request('https://example.com/analyze', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          symbol: 'NVDA',
          include_narrative: false,
          technical: {
            producer: 'vincent-stock-decision-dashboard',
            action: 'sell',
            confidence: 66.7,
            priceState: 'BREAKDOWN_ZONE',
          },
        }),
      }),
      { ALPHA_VANTAGE_KEY: 'test-key' },
    )
    assert.equal(response.status, 200)
    const recommendation = (await response.json()).recommendation
    assert.equal(recommendation.confidence, 0.667)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('without his verdict the blended behaviour is unchanged', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFinanceQueryFetch
  try {
    const response = await worker.fetch(
      new Request('https://example.com/analyze', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ symbol: 'NVDA', include_narrative: false }),
      }),
      { ALPHA_VANTAGE_KEY: 'test-key' },
    )
    const recommendation = (await response.json()).recommendation
    assert.equal(recommendation.supporting_context, null)
    assert.equal(recommendation.technical_source, 'local')
  } finally {
    globalThis.fetch = originalFetch
  }
})

// Mirrors test_conflict_detected_when_supporting_context_disagrees_with_his_action
// and test_conflict_not_detected_when_supporting_context_agrees_with_his_action in
// analyst_service/tests/test_pure_technical_verdict.py. buildRecommendation used
// to hardcode conflict_detected: false / conflict_summary: null unconditionally,
// so his BUY against fundamentals that lean SELL never surfaced as a conflict on
// the Worker even though supporting_context already carried the disagreement.
test('conflict is detected when supporting context disagrees with his action', () => {
  const verdict = verdictFromExternal({
    producer: 'vincent-stock-decision-dashboard',
    action: 'buy',
    confidence: 80,
    priceState: 'IN_OPPORTUNITY_ZONE',
  })
  const signals = [
    { dimension: 'RSI_14', signal: 'BUY', weight: 1.0, note: 'oversold' },
    { dimension: 'MACD', signal: 'BUY', weight: 1.0, note: 'histogram positive' },
    { dimension: 'EPS_Surprise', signal: 'SELL', weight: 2.0, note: 'miss' },
    { dimension: 'PE_Percentile', signal: 'SELL', weight: 1.0, note: 'rich' },
    { dimension: 'News_Sentiment', signal: 'SELL', weight: 0.5, note: 'negative' },
    { dimension: 'FOMC_Proximity', signal: 'SELL', weight: 1.0, note: 'event risk' },
  ]

  const recommendation = __testOnly.buildRecommendation(
    { resistanceLevels: [], supportLevels: [], currentPrice: 100 },
    signals,
    {},
    'risk_on',
    verdict,
  )

  assert.equal(recommendation.direction, 'BUY')
  assert.equal(recommendation.conflict_detected, true)
  assert.ok(recommendation.conflict_summary)
  assert.ok(recommendation.conflict_summary.toLowerCase().includes('buy'))
  assert.ok(recommendation.conflict_summary.toLowerCase().includes('sell'))
})

test('conflict is not detected when supporting context agrees with his action', () => {
  const verdict = verdictFromExternal({
    producer: 'vincent-stock-decision-dashboard',
    action: 'buy',
    confidence: 80,
    priceState: 'IN_OPPORTUNITY_ZONE',
  })
  const signals = [
    { dimension: 'RSI_14', signal: 'BUY', weight: 1.0, note: 'oversold' },
    { dimension: 'MACD', signal: 'BUY', weight: 1.0, note: 'histogram positive' },
    { dimension: 'EPS_Surprise', signal: 'BUY', weight: 2.0, note: 'beat' },
  ]

  const recommendation = __testOnly.buildRecommendation(
    { resistanceLevels: [], supportLevels: [], currentPrice: 100 },
    signals,
    {},
    'risk_on',
    verdict,
  )

  assert.equal(recommendation.supporting_context.agrees_with_action, true)
  assert.equal(recommendation.conflict_detected, false)
  assert.equal(recommendation.conflict_summary, null)
})

// Mirrors test_conflict_detection.py in analyst_service/tests. The blended
// (no external verdict) path used to hardcode conflict_detected: false, so the
// production fallback-to-local-technicals path never reported a technical vs
// fundamental split that Python's aggregate_recommendation does.
test('blended path reports a technical vs fundamental conflict like Python', () => {
  const signals = [
    { dimension: 'RSI_14', signal: 'BUY', weight: 1.0, note: 'buy' },
    { dimension: 'MACD', signal: 'BUY', weight: 1.0, note: 'buy' },
    { dimension: 'MA_50_200', signal: 'BUY', weight: 1.0, note: 'buy' },
    { dimension: 'EPS_Surprise', signal: 'SELL', weight: 1.0, note: 'sell' },
    { dimension: 'PE_Percentile', signal: 'SELL', weight: 1.0, note: 'sell' },
    { dimension: 'Analyst_Ratings', signal: 'SELL', weight: 1.0, note: 'sell' },
  ]

  const recommendation = __testOnly.buildRecommendation(
    { resistanceLevels: [], supportLevels: [], currentPrice: 100 },
    signals,
    {},
    'risk_on',
  )

  assert.equal(recommendation.conflict_detected, true)
  assert.equal(
    recommendation.conflict_summary,
    'Technicals lean BUY (3/3 signals) but fundamentals lean SELL (3/3 signals).',
  )
})

test('blended path reports no conflict when technicals and fundamentals align', () => {
  const signals = [
    { dimension: 'RSI_14', signal: 'BUY', weight: 1.0, note: 'buy' },
    { dimension: 'MACD', signal: 'BUY', weight: 1.0, note: 'buy' },
    { dimension: 'MA_50_200', signal: 'BUY', weight: 1.0, note: 'buy' },
    { dimension: 'EPS_Surprise', signal: 'BUY', weight: 1.0, note: 'buy' },
    { dimension: 'PE_Percentile', signal: 'BUY', weight: 1.0, note: 'buy' },
    { dimension: 'Analyst_Ratings', signal: 'BUY', weight: 1.0, note: 'buy' },
  ]

  const recommendation = __testOnly.buildRecommendation(
    { resistanceLevels: [], supportLevels: [], currentPrice: 100 },
    signals,
    {},
    'risk_on',
  )

  assert.equal(recommendation.conflict_detected, false)
  assert.equal(recommendation.conflict_summary, null)
})

test('blended path reports no conflict with only one technical signal', () => {
  const signals = [
    { dimension: 'RSI_14', signal: 'BUY', weight: 1.0, note: 'buy' },
    { dimension: 'EPS_Surprise', signal: 'SELL', weight: 1.0, note: 'sell' },
    { dimension: 'PE_Percentile', signal: 'SELL', weight: 1.0, note: 'sell' },
    { dimension: 'Analyst_Ratings', signal: 'SELL', weight: 1.0, note: 'sell' },
  ]

  const recommendation = __testOnly.buildRecommendation(
    { resistanceLevels: [], supportLevels: [], currentPrice: 100 },
    signals,
    {},
    'risk_on',
  )

  assert.equal(recommendation.conflict_detected, false)
  assert.equal(recommendation.conflict_summary, null)
})

test('worker never reports price/volume proxies as Reddit data', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFinanceQueryFetch
  try {
    const response = await worker.fetch(
      new Request('https://example.com/analyze', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ symbol: 'NVDA', include_narrative: false }),
      }),
      { ALPHA_VANTAGE_KEY: 'test-key' },
    )
    assert.equal(response.status, 200)
    const sentiment = (await response.json()).sentiment

    // The Worker has no Reddit credentials and makes no Reddit call, so it must
    // not populate the social fields with a volume ratio.
    assert.equal(sentiment.reddit_mention_spike_24h_pct, null)
    assert.equal(sentiment.reddit_positive_pct, null)
    // The proxies still ship, under names that say what they are.
    assert.ok('volume_spike_vs_90d_avg_pct' in sentiment)
    assert.ok('price_volume_momentum_pct' in sentiment)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('analyze endpoint substitutes an external technical verdict end to end', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFinanceQueryFetch
  try {
    const response = await worker.fetch(
      new Request('https://example.com/analyze', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          symbol: 'NVDA',
          include_narrative: false,
          technical: {
            contractVersion: 'decision.v1',
            producer: 'vincent-stock-decision-dashboard',
            action: 'sell',
            confidence: 80,
            priceState: 'BREAKDOWN_ZONE',
          },
        }),
      }),
      { ALPHA_VANTAGE_KEY: 'test-key' },
    )
    assert.equal(response.status, 200)
    const payload = await response.json()
    const recommendation = payload.recommendation

    assert.equal(recommendation.technical_source, 'external')
    assert.equal(recommendation.technical_producer, 'vincent-stock-decision-dashboard')
    assert.equal(recommendation.technical_price_state, 'BREAKDOWN_ZONE')
    // Vincent said SELL, so the whole technical weight sits on SELL and nowhere else.
    assert.equal(recommendation.technical_vote.SELL, 7.6)
    assert.equal(recommendation.technical_vote.BUY, 0)
    // Category votes are no longer hardcoded zeros.
    const categoryTotal = ['technical', 'fundamental', 'sentiment', 'macro'].reduce(
      (sum, key) => sum + Object.values(recommendation[`${key}_vote`]).reduce((a, b) => a + b, 0),
      0,
    )
    assert.ok(categoryTotal > 0, 'category votes must be derived, not zeroed')
    // No local technical dimension should remain in the signal set.
    assert.equal(payload.signals.filter((signal) => signal.dimension === 'RSI_14').length, 0)
    assert.equal(payload.signals.filter((signal) => signal.dimension === 'Technical_External').length, 1)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('analyze endpoint falls back to local technicals when the verdict is illegal', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFinanceQueryFetch
  try {
    const response = await worker.fetch(
      new Request('https://example.com/analyze', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          symbol: 'NVDA',
          include_narrative: false,
          technical: {
            producer: 'vincent-stock-decision-dashboard',
            action: 'buy',
            confidence: 70,
            priceState: 'IN_REDUCE_ZONE',
          },
        }),
      }),
      { ALPHA_VANTAGE_KEY: 'test-key' },
    )
    assert.equal(response.status, 200)
    const payload = await response.json()

    assert.equal(payload.recommendation.technical_source, 'local')
    assert.ok(payload.recommendation.risk_flags.includes('external_technical_rejected'))
    // The local technicals must still be doing the work.
    assert.ok(payload.signals.some((signal) => signal.dimension === 'RSI_14'))
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('analyze endpoint pulls all three horizons and reports them beside the driving verdict', async () => {
  const originalFetch = globalThis.fetch
  const engineRequests = []
  globalThis.fetch = (input) => {
    const rawUrl = typeof input === 'string' ? input : input instanceof URL ? input.href : input?.url ?? String(input)
    const url = new URL(rawUrl)
    if (url.pathname.startsWith('/decision/')) {
      const horizon = url.searchParams.get('horizon')
      engineRequests.push(horizon)
      const byHorizon = {
        '1W': { action: 'buy', confidence: 60, priceState: 'IN_OPPORTUNITY_ZONE' },
        '2-4W': { action: 'sell', confidence: 80, priceState: 'BREAKDOWN_ZONE' },
        '3-6M': { action: 'hold', confidence: 50, priceState: 'NEUTRAL_ZONE' },
      }
      return Promise.resolve(
        new Response(
          JSON.stringify({
            contractVersion: 'decision.v1',
            producer: 'vincent-stock-decision-dashboard',
            ...byHorizon[horizon],
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        ),
      )
    }
    return mockFinanceQueryFetch(input)
  }
  try {
    const response = await worker.fetch(
      new Request('https://example.com/analyze', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ symbol: 'NVDA', include_narrative: false }),
      }),
      { ALPHA_VANTAGE_KEY: 'test-key', TECHNICAL_ENGINE_BASE_URL: 'https://engine.example' },
    )
    assert.equal(response.status, 200)
    const payload = await response.json()

    // One pull per horizon, not more, and not a fourth call for '2-4W' again.
    assert.deepEqual(engineRequests.sort(), ['1W', '2-4W', '3-6M'])
    // '2-4W' is what the Worker's own recommendation covers, so it drives the vote.
    assert.equal(payload.recommendation.technical_source, 'external')
    assert.equal(payload.recommendation.technical_price_state, 'BREAKDOWN_ZONE')

    const byHorizon = Object.fromEntries(
      payload.recommendation.technical_by_horizon.map((entry) => [entry.horizon, entry.verdict]),
    )
    assert.deepEqual(Object.keys(byHorizon).sort(), ['1W', '2-4W', '3-6M'])
    assert.equal(byHorizon['1W'].direction, 'BUY')
    assert.equal(byHorizon['2-4W'].direction, 'SELL')
    assert.equal(byHorizon['3-6M'].direction, 'HOLD')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('batch response envelopes preserve order and report symbol errors', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockBatchFailureFetch
  try {
    const response = await worker.fetch(
      new Request('https://example.com/batch', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ symbols: ['NVDA', 'FAIL'], include_narrative: false }),
      }),
    )
    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.equal(payload.length, 2)
    assert.equal(payload[0].symbol, 'NVDA')
    assert.equal(payload[0].error, null)
    assert.equal(payload[1].symbol, 'FAIL')
    assert.equal(payload[1].response, null)
    assert.equal(payload[1].error.code, 'analysis_error')
    assert.equal(payload[1].error.message, 'simulated upstream failure')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('batch always returns response envelopes', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFinanceQueryFetch
  try {
    const response = await worker.fetch(
      new Request('https://example.com/batch', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ symbols: ['NVDA'], include_narrative: false }),
      }),
    )
    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.equal(payload.length, 1)
    assert.equal(payload[0].symbol, 'NVDA')
    assert.equal(payload[0].error, null)
    assert.equal(payload[0].response.symbol, 'NVDA')
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

// The Worker persists no analyses, so `/history/*` must mirror analyst_service
// against an empty store: the just-shipped Track Record view then renders its
// honest "No calls recorded yet" empty state in production instead of erroring.
test('/history/coverage returns an honest empty store', async () => {
  const response = await worker.fetch(new Request('https://example.com/history/coverage'))
  assert.equal(response.status, 200)
  const payload = await response.json()
  assert.deepEqual(payload, {
    record_count: 0,
    distinct_symbols: 0,
    earliest: null,
    latest: null,
  })
})

test('/history/performance mirrors the empty-store report shape', async () => {
  const response = await worker.fetch(new Request('https://example.com/history/performance'))
  assert.equal(response.status, 200)
  const payload = await response.json()
  assert.equal(payload.evaluated_count, 0)
  assert.equal(payload.decision_count, 0)
  assert.equal(payload.hit_rate, null)
  assert.equal(payload.average_forward_return, null)
  assert.equal(payload.average_benchmark_relative_return, null)
  assert.deepEqual(payload.by_direction, [])
  assert.deepEqual(payload.by_entry_assessment, [])
  // The four confidence buckets are always emitted, even empty — mirrors Python.
  assert.deepEqual(
    payload.by_confidence.map((bucket) => bucket.label),
    ['0.0-0.5', '0.5-0.65', '0.65-0.8', '0.8-1.0'],
  )
  assert.ok(payload.by_confidence.every((bucket) => bucket.evaluated_count === 0 && bucket.hit_rate === null))
  // Matches the Python empty-store advisory wording exactly.
  assert.deepEqual(payload.advisory, [
    'No recommendations have enough forward history yet; nothing here is measurable.',
  ])
  assert.equal(typeof payload.generated_at, 'string')
})

test('/history/{symbol} returns an empty timeline for any symbol, not a 404', async () => {
  const response = await worker.fetch(new Request('https://example.com/history/aapl'))
  assert.equal(response.status, 200)
  const payload = await response.json()
  assert.equal(payload.symbol, 'AAPL')
  assert.deepEqual(payload.entries, [])
  assert.equal(typeof payload.generated_at, 'string')
})

test('/history rejects a non-GET method', async () => {
  const response = await worker.fetch(
    new Request('https://example.com/history/coverage', { method: 'POST' }),
  )
  assert.equal(response.status, 405)
})
