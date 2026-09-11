import test from 'node:test'
import assert from 'node:assert/strict'
import {
  clearMarketDataCache,
  fearGreedLabel,
  fetchYahooChart,
  loadMarketContext,
  seriesChange,
  validateNativeFourHour,
} from '../src/consolidated/market-data.js'
import { runTechnicalEngine } from '../src/consolidated/technical-engine.js'
import { runConsolidated } from '../src/consolidated/pipeline.js'
import { verdictFromExternal } from '../src/technical-provider.js'

const LEGAL_ACTIONS = ['strong_buy', 'buy', 'accumulate', 'hold', 'trim', 'sell', 'avoid']

test.beforeEach(() => clearMarketDataCache())

// Weekdays from 2026-03-16 onward are all in US daylight time, so 13:30 UTC is
// 09:30 ET and 17:30 UTC is 13:30 ET.
function weekdays(count, start = Date.UTC(2026, 2, 16)) {
  const days = []
  for (let day = start; days.length < count; day += 86_400_000) {
    const weekday = new Date(day).getUTCDay()
    if (weekday !== 0 && weekday !== 6) days.push(day)
  }
  return days
}

function chart(stamps, closeAt, meta = {}) {
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
  const base = { '^VIX': 16, '^TNX': 4.3 }[symbol] ?? 100
  if (interval === '1d') {
    const days = weekdays(504, Date.UTC(2024, 8, 2)).map((day) => day / 1000 + 13.5 * 3600)
    return new Response(JSON.stringify(chart(days, wave(base, drift))))
  }
  const days = weekdays(84)
  if (interval === '4h') {
    const stamps = days.flatMap((day) => [day / 1000 + 13.5 * 3600, day / 1000 + 17.5 * 3600])
    return new Response(JSON.stringify(chart(stamps, wave(base, drift / 2), { dataGranularity: '4h' })))
  }
  const stamps = days.flatMap((day) => [0, 1, 2, 3, 4, 5, 6].map((hour) => day / 1000 + (13.5 + hour) * 3600))
  return new Response(JSON.stringify(chart(stamps, wave(base, drift / 7), { dataGranularity: '1h' })))
}

test('native 4h validation keeps 09:30/13:30 sessions and drops malformed days', () => {
  const [monday, tuesday, wednesday] = weekdays(3).map((day) => day / 1000)
  const stamps = [
    monday + 13.5 * 3600, monday + 17.5 * 3600, // normal session
    tuesday + 13.5 * 3600, tuesday + 15.5 * 3600, // 11:30 ET is not a native session bar, so all of Tuesday is dropped
    wednesday + 13.5 * 3600, // 09:30-only early close is kept
  ]
  const payload = chart(stamps, () => 100, { dataGranularity: '4h' }).chart.result[0]
  const result = validateNativeFourHour(payload)
  assert.equal(result.normalSessionDays, 1)
  assert.equal(result.singleSessionDays, 1)
  assert.equal(result.invalidSessionDays, 1)
  assert.equal(result.bars.closes.length, 3)

  const resampled = validateNativeFourHour({ ...payload, meta: { ...payload.meta, dataGranularity: '1h' } })
  assert.equal(resampled.bars.available, false)
  assert.equal(resampled.unavailableReason, 'invalid_source_data')
})

test('series change and fear/greed labels match server.py', () => {
  assert.equal(seriesChange([10, 11, 12, 13, 14, 15, 16], 5), 5)
  assert.equal(seriesChange([1], 5), null)
  assert.equal(fearGreedLabel(25), 'Extreme Fear')
  assert.equal(fearGreedLabel(50), 'Neutral')
  assert.equal(fearGreedLabel(80), 'Extreme Greed')
})

test('Yahoo chart requests use a bare Mozilla/5.0 UA, not a full Chrome string that Yahoo 429s', async () => {
  let seenHeaders
  await fetchYahooChart('SPY', {
    fetchImpl: async (url, init) => {
      seenHeaders = init.headers
      return mockYahoo(url)
    },
  })
  assert.equal(seenHeaders['user-agent'], 'Mozilla/5.0')
})

test('market context carries VIX, 10Y, SPY and QQQ, and a blocked fear/greed stays unavailable', async () => {
  const { market_context: context } = await loadMarketContext({ fetchImpl: async (url) => mockYahoo(url) })
  assert.ok(Number.isFinite(context.vix.value))
  assert.ok(Number.isFinite(context.ten_year_yield.value))
  assert.ok(context.ten_year_yield.value < 20, 'yield is in percent, not tenths')
  assert.ok(Number.isFinite(context.equity_trend.spy.change_120d_pct))
  assert.equal(context.fear_greed.value, null)
})

test("Vincent's engine runs in process and decides all three horizons from native 4h, 1h and daily bars", async () => {
  const result = await runTechnicalEngine('NVDA', { fetchImpl: async (url) => mockYahoo(url) })
  assert.equal(result.producer, 'vincent-stock-decision-dashboard')
  assert.equal(result.dataQuality.four_hour, 'available')
  assert.equal(result.dataQuality.one_hour, 'available')
  for (const horizon of ['short', 'mid', 'long']) {
    const summary = result.horizons[horizon]
    assert.equal(summary.available, true, `${horizon} is decided`)
    assert.ok(LEGAL_ACTIONS.includes(summary.action), `${horizon} action ${summary.action} is legal`)
  }
  // The in-process verdicts go through the same decision.v1 seam as a pulled one.
  assert.deepEqual(Object.keys(result.decisionV1).sort(), ['1W', '2-4W', '3-6M'])
  for (const payload of Object.values(result.decisionV1)) {
    const verdict = verdictFromExternal(payload)
    assert.equal(verdict.source, 'external')
  }
})

test('the technical engine exposes a compact technical-details subset per horizon, computed once', async () => {
  const result = await runTechnicalEngine('NVDA', { fetchImpl: async (url) => mockYahoo(url) })
  for (const horizon of ['short', 'mid', 'long']) {
    const details = result.horizons[horizon].technical_details
    assert.ok(details, `${horizon} carries technical_details`)
    assert.ok(['unavailable', 'strong_bullish', 'bullish', 'strong_bearish', 'bearish', 'mixed'].includes(details.moving_averages.alignment))
    assert.equal(details.rsi.available, true)
    assert.ok(Number.isFinite(details.rsi.value))
    assert.equal(details.macd.available, true)
    assert.ok(Number.isFinite(details.macd.macd_line))
    assert.equal(details.adx.available, true)
    assert.ok(Number.isFinite(details.adx.adx))
    assert.equal(details.bollinger.available, true)
    assert.ok(Number.isFinite(details.bollinger.upper_band))
    assert.ok(details.relative_strength, `${horizon} carries relative_strength`)
    assert.ok(details.fibonacci, `${horizon} carries fibonacci`)
  }
  assert.ok(['very_low', 'low', 'normal', 'elevated', 'high', 'extreme'].includes(result.marketStructure.relative_volume.state))
  assert.ok(Number.isFinite(result.marketStructure.fifty_two_week.high))
  assert.ok(Number.isFinite(result.marketStructure.fifty_two_week.low))
})

test('the consolidated pipeline composes technical, fundamentals and the hurdle', async () => {
  const quote = { sector: 'Technology', industry: 'Semiconductors', quoteType: 'EQUITY' }
  const { consolidated, decisionV1ByHorizon } = await runConsolidated('NVDA', {
    quote,
    fundamentalSignals: [
      { signal: 'BUY', weight: 2 },
      { signal: 'HOLD', weight: 1 },
    ],
    fetchImpl: async (url) => mockYahoo(url),
  })
  assert.equal(consolidated.version, 'consolidated.v1')
  assert.equal(consolidated.fundamentals.stance, 'supportive')
  assert.deepEqual(consolidated.index_hurdle.benchmarks.map((row) => row.symbol), ['SPY', 'QQQ', 'XLK', 'SMH'])
  assert.equal(consolidated.errors, null, 'no failures happened, so errors stays null rather than an empty object')
  for (const horizon of ['short', 'mid', 'long']) {
    const entry = consolidated.horizons[horizon]
    assert.ok(LEGAL_ACTIONS.includes(entry.final_action))
    assert.ok(entry.technical.technical_details, `${horizon} technical carries technical_details`)
    if (['strong_buy', 'buy', 'accumulate'].includes(entry.final_action)) {
      assert.equal(consolidated.index_hurdle.status, 'pass', 'a final buy implies the hurdle passed')
    }
  }
  assert.ok(consolidated.market_structure, 'consolidated_decision carries market_structure')
  assert.ok(decisionV1ByHorizon['2-4W'])
})

test('the consolidated pipeline reports a short, no-stack reason instead of silently swallowing a technical-engine failure', async () => {
  const quote = { sector: 'Technology', industry: 'Semiconductors', quoteType: 'EQUITY' }
  const failingFetch = async () => {
    throw new Error('simulated network failure')
  }
  const { consolidated } = await runConsolidated('NVDA', { quote, fetchImpl: failingFetch })
  assert.ok(consolidated.errors, 'errors is populated instead of null')
  assert.equal(consolidated.errors.technical, 'simulated network failure')
  assert.doesNotMatch(consolidated.errors.technical, /\n\s+at /, 'a message, not a stack trace')
  for (const horizon of ['short', 'mid', 'long']) {
    assert.equal(consolidated.horizons[horizon].final_action, null)
  }
})
