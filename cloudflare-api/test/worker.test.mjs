import test from 'node:test'
import assert from 'node:assert/strict'
import worker, { __testOnly, SharedWatchlistSpace } from '../src/index.js'

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
