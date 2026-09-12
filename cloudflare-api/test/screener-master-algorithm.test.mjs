import test from 'node:test'
import assert from 'node:assert/strict'
import { __testOnly } from '../src/index.js'

const { buildScreenResponse } = __testOnly

// Mirrors mockFinanceQueryFetch in worker.test.mjs: generic enough to answer
// getSnapshot/getQuote/getChart for any symbol, which is all buildScreenResult
// and buildAnalyze need.
function mockFinanceQueryFetch(input) {
  const rawUrl = typeof input === 'string' ? input : input?.url ?? String(input)
  const url = new URL(rawUrl)
  if (url.pathname.includes('/quote/')) {
    const symbol = decodeURIComponent(url.pathname.split('/').at(-1) ?? '')
    const marketPrice = symbol === '^VIX' ? 17.5 : symbol === '^TNX' ? 43.2 : 200
    return Promise.resolve(
      new Response(
        JSON.stringify({
          longName: `${symbol} Inc.`,
          shortName: symbol,
          regularMarketPrice: marketPrice,
          regularMarketTime: 1_700_100_000,
          trailingPE: 18.4,
          priceToBook: 12.4,
          priceToSalesTrailing12Months: 15.2,
          enterpriseToEbitda: 30.3,
          revenueGrowth: 0.22,
          grossMargins: 0.58,
          shortPercentOfFloat: 0.04,
          impliedVolatility: 0.32,
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    )
  }
  if (url.pathname.includes('/chart/')) {
    const closes = Array.from({ length: 260 }, (_, index) => 100 + index * 0.1)
    const stamps = closes.map((_, index) => 1_700_000_000 + index * 86_400)
    return Promise.resolve(
      new Response(
        JSON.stringify({
          chart: {
            result: [
              {
                meta: { regularMarketPrice: closes.at(-1), instrumentType: 'EQUITY', currency: 'USD' },
                timestamp: stamps,
                indicators: {
                  quote: [
                    {
                      open: closes.map((c) => c * 0.998),
                      high: closes.map((c) => c * 1.01),
                      low: closes.map((c) => c * 0.99),
                      close: closes,
                      volume: closes.map(() => 1_000_000),
                    },
                  ],
                  adjclose: [{ adjclose: closes }],
                },
              },
            ],
          },
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    )
  }
  if (url.hostname === 'www.alphavantage.co' || url.hostname === 'www.cboe.com' || url.hostname === 'ww2.cboe.com') {
    return Promise.resolve(new Response(JSON.stringify({}), { status: 200, headers: { 'content-type': 'application/json' } }))
  }
  return Promise.reject(new Error(`Unexpected fetch URL: ${url.toString()}`))
}

const TICKERS = ['AAA', 'BBB', 'CCC', 'DDD']

test('opportunities + include_analysis attaches the master algorithm to the top slice only', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFinanceQueryFetch
  try {
    const response = await buildScreenResponse(
      'opportunities',
      { tickers: TICKERS, limit: TICKERS.length, include_analysis: true },
      {},
    )
    assert.equal(response.results.length, TICKERS.length)
    const withVerdict = response.results.filter((row) => row.master_direction !== null)
    const withoutVerdict = response.results.filter((row) => row.master_direction === null)
    // SCREENER_MASTER_ALGORITHM_LIMIT caps how many rows pay for the full
    // pipeline; the rest fail closed to null rather than a fabricated call.
    assert.equal(withVerdict.length, 3)
    assert.equal(withoutVerdict.length, 1)
    for (const row of response.results) {
      assert.ok('master_direction' in row, 'every row must carry the field, even when null')
      assert.ok('master_confirms' in row)
      if (row.master_direction !== null) {
        assert.ok(['BUY', 'HOLD', 'SELL'].includes(row.master_direction))
        assert.equal(row.master_confirms, row.master_direction === row.recommendation)
      } else {
        assert.equal(row.master_confirms, null)
      }
    }
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('without include_analysis, opportunities rows report no master verdict', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFinanceQueryFetch
  try {
    const response = await buildScreenResponse('opportunities', { tickers: TICKERS, limit: TICKERS.length }, {})
    for (const row of response.results) {
      assert.equal(row.master_direction, null)
      assert.equal(row.master_confirms, null)
    }
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('include_analysis on a non-opportunities screen does not run the master algorithm', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockFinanceQueryFetch
  try {
    const response = await buildScreenResponse(
      'undervalued',
      { tickers: TICKERS, limit: TICKERS.length, include_analysis: true },
      {},
    )
    for (const row of response.results) {
      assert.equal(row.master_direction, null)
      assert.equal(row.master_confirms, null)
    }
  } finally {
    globalThis.fetch = originalFetch
  }
})
