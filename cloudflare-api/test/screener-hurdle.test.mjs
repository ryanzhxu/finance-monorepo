import test from 'node:test'
import assert from 'node:assert/strict'
import { __testOnly } from '../src/index.js'
import { clearMarketDataCache } from '../src/consolidated/market-data.js'

const { applyScreenerHurdle } = __testOnly

test.beforeEach(() => clearMarketDataCache())

// Weekdays only, so the daily bars line up like real trading history.
function weekdays(count, start = Date.UTC(2024, 8, 2)) {
  const days = []
  for (let day = start; days.length < count; day += 86_400_000) {
    const weekday = new Date(day).getUTCDay()
    if (weekday !== 0 && weekday !== 6) days.push(day)
  }
  return days
}

function chart(stamps, closeAt) {
  const closes = stamps.map((_, index) => closeAt(index))
  return {
    chart: {
      result: [
        {
          meta: { regularMarketPrice: closes.at(-1), instrumentType: 'EQUITY', currency: 'USD' },
          timestamp: stamps,
          indicators: {
            quote: [
              {
                open: closes.map((close) => close * 0.998),
                high: closes.map((close) => close * 1.01),
                low: closes.map((close) => close * 0.99),
                close: closes,
                volume: closes.map(() => 1_000_000),
              },
            ],
            adjclose: [{ adjclose: closes }],
          },
        },
      ],
    },
  }
}

const wave = (base, drift) => (index) => base * (1 + drift) ** index

// SPY/QQQ drift modestly upward. WINNER drifts well above them (beats every
// window). LOSER drifts downward (lags every window).
const DRIFT = { SPY: 0.0004, QQQ: 0.0005, WINNER: 0.003, LOSER: -0.0015 }

function mockYahooFetch(url) {
  const parsed = new URL(url)
  const symbol = decodeURIComponent(parsed.pathname.split('/').pop())
  const days = weekdays(504).map((day) => day / 1000 + 13.5 * 3600)
  return Promise.resolve(new Response(JSON.stringify(chart(days, wave(100, DRIFT[symbol] ?? 0)))))
}

function screenRow(symbol, recommendation, quote = {}, entryAssessment = 'wait_for_pullback') {
  return { symbol, recommendation, entry_assessment: entryAssessment, components: { quote } }
}

test('a buy row that beats every benchmark keeps its BUY flag and reports index_hurdle pass', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockYahooFetch
  try {
    const results = [screenRow('WINNER', 'BUY')]
    await applyScreenerHurdle(results)
    assert.equal(results[0].index_hurdle.status, 'pass')
    assert.equal(results[0].recommendation, 'BUY')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('a buy row that lags a benchmark is capped at HOLD and names the lagging benchmark', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockYahooFetch
  try {
    const results = [screenRow('LOSER', 'BUY')]
    await applyScreenerHurdle(results)
    assert.equal(results[0].index_hurdle.status, 'fail')
    assert.deepEqual(results[0].index_hurdle.lagging.sort(), ['QQQ', 'SPY'])
    assert.equal(results[0].recommendation, 'HOLD')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('a non-buy row is never evaluated and keeps its own recommendation, and evaluation is capped at 10 buy rows', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockYahooFetch
  try {
    const buyRows = Array.from({ length: 11 }, (_, index) => screenRow(`WINNER${index}`, 'BUY'))
    const results = [screenRow('HOLDER', 'HOLD'), ...buyRows]
    await applyScreenerHurdle(results)
    assert.equal(results[0].index_hurdle.status, 'not_evaluated')
    assert.equal(results[0].recommendation, 'HOLD')
    assert.equal(results[0].held_by_index_hurdle, undefined)
    const evaluated = buyRows.filter((row) => row.index_hurdle.status !== 'not_evaluated')
    const skipped = buyRows.filter((row) => row.index_hurdle.status === 'not_evaluated')
    assert.equal(evaluated.length, 10)
    assert.equal(skipped.length, 1)
    // Fail closed: a buy row pushed past the evaluation cap must not keep
    // reading as a buy just because it was never evaluated.
    assert.equal(skipped[0].recommendation, 'HOLD')
    assert.equal(skipped[0].held_by_index_hurdle, true)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('a buy row whose hurdle evaluation throws fails closed to HOLD instead of keeping BUY', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockYahooFetch
  try {
    const brokenRow = {
      symbol: 'BROKEN',
      recommendation: 'BUY',
      entry_assessment: 'buy_now',
      get components() {
        throw new Error('boom')
      },
    }
    const results = [brokenRow]
    await applyScreenerHurdle(results)
    assert.equal(results[0].index_hurdle.status, 'not_evaluated')
    assert.equal(results[0].recommendation, 'HOLD')
    assert.equal(results[0].held_by_index_hurdle, true)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('a row flagged as a buy only through entry_assessment (not recommendation) still respects the hurdle', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = mockYahooFetch
  try {
    const results = [screenRow('LOSER', 'WATCH', {}, 'buy_now')]
    await applyScreenerHurdle(results)
    assert.equal(results[0].index_hurdle.status, 'fail')
    assert.equal(results[0].recommendation, 'HOLD')
    assert.equal(results[0].held_by_index_hurdle, true)
  } finally {
    globalThis.fetch = originalFetch
  }
})
