import test from 'node:test'
import assert from 'node:assert/strict'
import worker, { __testOnly } from '../src/index.js'
import { clearMarketDataCache } from '../src/consolidated/market-data.js'

test.beforeEach(() => {
  __testOnly.clearCaches()
  clearMarketDataCache()
})

const LEGAL_ACTIONS = ['strong_buy', 'buy', 'accumulate', 'hold', 'trim', 'sell', 'avoid']
const CONSOLIDATED_ENV = { CONSOLIDATED_DECISION: 'on' }

// Weekdays only, so daily/4h/1h bars line up like real trading history.
function weekdays(count, start = Date.UTC(2024, 8, 2)) {
  const days = []
  for (let day = start; days.length < count; day += 86_400_000) {
    const weekday = new Date(day).getUTCDay()
    if (weekday !== 0 && weekday !== 6) days.push(day)
  }
  return days
}

function yahooChart(stamps, closeAt, meta = {}) {
  const closes = stamps.map((_, index) => closeAt(index))
  return {
    chart: {
      result: [
        {
          meta: { regularMarketPrice: closes.at(-1), instrumentType: 'EQUITY', currency: 'USD', exchangeTimezoneName: 'America/New_York', ...meta },
          timestamp: stamps,
          indicators: {
            quote: [
              {
                open: closes.map((close) => close * 0.998),
                high: closes.map((close) => close * 1.01),
                low: closes.map((close) => close * 0.99),
                close: closes,
                volume: closes.map((_, index) => 1_000_000 + (index % 7) * 50_000),
              },
            ],
            adjclose: [{ adjclose: closes }],
          },
        },
      ],
    },
  }
}

const wave = (base, drift) => (index) => base * (1 + drift) ** index * (1 + 0.04 * Math.sin(index / 6))

function mockYahoo(url) {
  const parsed = new URL(url)
  if (parsed.hostname.includes('cnn.io')) return new Response('blocked', { status: 418 })
  const symbol = decodeURIComponent(parsed.pathname.split('/').pop())
  const interval = parsed.searchParams.get('interval')
  const drift = { SPY: 0.0004, QQQ: 0.0005, '^VIX': 0, '^TNX': 0 }[symbol] ?? 0.0009
  const base = { '^VIX': 16, '^TNX': 4.3 }[symbol] ?? 190
  if (interval === '1d') {
    const days = weekdays(504, Date.UTC(2024, 8, 2)).map((day) => day / 1000 + 13.5 * 3600)
    return new Response(JSON.stringify(yahooChart(days, wave(base, drift))))
  }
  const days = weekdays(84)
  if (interval === '4h') {
    const stamps = days.flatMap((day) => [day / 1000 + 13.5 * 3600, day / 1000 + 17.5 * 3600])
    return new Response(JSON.stringify(yahooChart(stamps, wave(base, drift / 2), { dataGranularity: '4h' })))
  }
  const stamps = days.flatMap((day) => [0, 1, 2, 3, 4, 5, 6].map((hour) => day / 1000 + (13.5 + hour) * 3600))
  return new Response(JSON.stringify(yahooChart(stamps, wave(base, drift / 7), { dataGranularity: '1h' })))
}

function financeQueryCandles(count = 240) {
  return Array.from({ length: count }, (_, index) => {
    const close = 190 + index * 0.4
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

// Routes both the finance-query.com host (getQuote/getSnapshot, via global
// fetch) and the Yahoo hosts Vincent's engine and the index hurdle read
// (also via global fetch, since buildAnalyze never overrides fetchImpl).
function mockCombinedFetch(input) {
  const rawUrl = typeof input === 'string' ? input : input instanceof URL ? input.href : (input?.url ?? String(input))
  const url = new URL(rawUrl)
  if (url.hostname.includes('finance.yahoo.com') || url.hostname.includes('cnn.io')) {
    return Promise.resolve(mockYahoo(rawUrl))
  }
  if (url.hostname !== 'finance-query.com') {
    return Promise.reject(new Error(`Unexpected fetch URL: ${rawUrl}`))
  }
  if (url.pathname.includes('/quote/')) {
    const symbol = decodeURIComponent(url.pathname.split('/').at(-1) ?? '')
    if (symbol === 'FAIL') return Promise.reject(new Error('simulated upstream failure'))
    return Promise.resolve(
      new Response(
        JSON.stringify({
          longName: `${symbol} Holdings`,
          shortName: symbol,
          sector: 'Technology',
          industry: 'Semiconductors',
          quoteType: 'EQUITY',
          regularMarketPrice: { '^VIX': 16, '^TNX': 43 }[symbol] ?? 190,
          regularMarketTime: 1_700_100_000,
          trailingPE: 30,
          priceToBook: 12,
          priceToSalesTrailing12Months: 10,
          enterpriseToEbitda: 20,
          revenueGrowth: 0.15,
          grossMargins: 0.5,
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    )
  }
  if (url.pathname.includes('/chart/')) {
    return Promise.resolve(
      new Response(JSON.stringify({ candles: financeQueryCandles() }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
  }
  return Promise.reject(new Error(`Unexpected fetch URL: ${rawUrl}`))
}

test('/decisions 404s when CONSOLIDATED_DECISION is not on', async () => {
  const response = await worker.fetch(
    new Request('https://example.com/decisions', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ symbols: ['NVDA'] }),
    }),
    {},
  )
  assert.equal(response.status, 404)
})

test('/decisions requires at least one symbol', async () => {
  const response = await worker.fetch(
    new Request('https://example.com/decisions', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ symbols: [] }),
    }),
    CONSOLIDATED_ENV,
  )
  assert.equal(response.status, 400)
})

test('/decisions returns a consolidated_decision per symbol, in order, and one bad symbol never fails the batch', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockCombinedFetch
  try {
    const response = await worker.fetch(
      new Request('https://example.com/decisions', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ symbols: ['NVDA', 'FAIL'] }),
      }),
      CONSOLIDATED_ENV,
    )
    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.equal(payload.results.length, 2)

    const [nvda, fail] = payload.results
    assert.equal(nvda.symbol, 'NVDA')
    assert.equal(nvda.company_name, 'NVDA Holdings')
    assert.equal(typeof nvda.current_price, 'number')
    assert.ok(nvda.consolidated_decision)
    for (const horizon of ['short', 'mid', 'long']) {
      assert.ok(LEGAL_ACTIONS.includes(nvda.consolidated_decision.horizons[horizon].final_action) || nvda.consolidated_decision.horizons[horizon].final_action === null)
    }

    assert.equal(fail.symbol, 'FAIL')
    assert.equal(fail.consolidated_decision, undefined)
    assert.equal(fail.error.code, 'analysis_error')
    assert.equal(fail.error.message, 'simulated upstream failure')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('/decisions caps a request at 3 symbols and reports max_symbols', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockCombinedFetch
  try {
    const response = await worker.fetch(
      new Request('https://example.com/decisions', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ symbols: ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'] }),
      }),
      CONSOLIDATED_ENV,
    )
    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.equal(payload.max_symbols, 3)
    assert.equal(payload.results.length, 3)
    assert.deepEqual(
      payload.results.map((row) => row.symbol),
      ['A', 'B', 'C'],
    )
  } finally {
    globalThis.fetch = originalFetch
  }
})

// finance-query.com (quote/snapshot) succeeds so buildAnalyze reaches
// runConsolidated; only the Yahoo/CNN calls the technical engine and index
// hurdle depend on fail, isolating the errors surfaced from runConsolidated.
function mockFetchYahooDown(input) {
  const rawUrl = typeof input === 'string' ? input : input instanceof URL ? input.href : (input?.url ?? String(input))
  const url = new URL(rawUrl)
  if (url.hostname.includes('finance.yahoo.com') || url.hostname.includes('cnn.io')) {
    return Promise.reject(new Error('simulated network failure'))
  }
  return mockCombinedFetch(input)
}

test('/decisions surfaces a short, no-stack reason when the technical engine fails, instead of failing silently', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFetchYahooDown
  try {
    const response = await worker.fetch(
      new Request('https://example.com/decisions', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ symbols: ['NVDA'] }),
      }),
      CONSOLIDATED_ENV,
    )
    assert.equal(response.status, 200)
    const payload = await response.json()
    const [nvda] = payload.results
    assert.equal(nvda.symbol, 'NVDA')
    assert.ok(nvda.consolidated_decision, 'the quote/entry lookup failing does not fail the whole row')
    const { errors } = nvda.consolidated_decision
    // The index hurdle fails closed per-benchmark on its own (status 'fail'
    // with insufficient_data rows) rather than throwing, so only the
    // technical engine's harder failure shows up in `errors` here.
    assert.ok(errors, 'errors is populated instead of silently null')
    assert.equal(errors.technical, 'simulated network failure')
    assert.doesNotMatch(errors.technical, /\n\s+at /, 'no stack trace, just the message')
    assert.notEqual(nvda.consolidated_decision.index_hurdle.status, 'pass')
    for (const horizon of ['short', 'mid', 'long']) {
      assert.equal(nvda.consolidated_decision.horizons[horizon].final_action, null)
    }
  } finally {
    globalThis.fetch = originalFetch
  }
})
