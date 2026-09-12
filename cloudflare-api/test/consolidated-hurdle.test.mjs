import test from 'node:test'
import assert from 'node:assert/strict'
import {
  earningsGuard,
  evaluateHurdle,
  relativeEvidence,
  resolveBenchmarks,
  runIndexHurdle,
} from '../src/consolidated/index-hurdle.js'

// A daily series of `length` points compounding at `dailyPct` per day.
function series(length, dailyPct, start = 100) {
  return Array.from({ length }, (_, index) => ({
    date: new Date(Date.UTC(2024, 0, 1) + index * 86_400_000).toISOString().slice(0, 10),
    close: start * (1 + dailyPct / 100) ** index,
  }))
}

test('benchmarks are SPY, QQQ, the sector ETF and each matching industry ETF, without duplicates', () => {
  const { applicable, benchmarks } = resolveBenchmarks({
    symbol: 'NVDA',
    sector: 'Technology',
    industry: 'Semiconductors',
    traits: ['Semiconductor', 'GPU'],
  })
  assert.equal(applicable, true)
  assert.deepEqual(benchmarks.map((item) => [item.symbol, item.role]), [
    ['SPY', 'index'],
    ['QQQ', 'index'],
    ['XLK', 'sector'],
    ['SMH', 'industry'],
  ])
})

test('a broad index ETF is the benchmark, so the hurdle does not apply to it', () => {
  assert.deepEqual(resolveBenchmarks({ symbol: 'SPY' }), { applicable: false, benchmarks: [] })
  assert.equal(resolveBenchmarks({ symbol: 'voo' }).applicable, false)
})

test('a ticker is never its own benchmark', () => {
  assert.deepEqual(resolveBenchmarks({ symbol: 'QQQ' }).benchmarks.map((item) => item.symbol), ['SPY'])
  assert.deepEqual(
    resolveBenchmarks({ symbol: 'SMH', sector: 'Technology', industry: 'Semiconductors' }).benchmarks.map((item) => item.symbol),
    ['SPY', 'QQQ', 'XLK'],
  )
})

test('a Hong Kong listing also has to beat its local index', () => {
  const symbols = resolveBenchmarks({ symbol: '0700.HK' }).benchmarks.map((item) => item.symbol)
  assert.deepEqual(symbols, ['SPY', 'QQQ', '^HSI'])
})

test('a stock that compounds faster than the benchmark beats it on all three evidence items', () => {
  const evidence = relativeEvidence(series(300, 0.12), series(300, 0.04))
  assert.equal(evidence.result, 'beats')
  assert.equal(evidence.evidence_true, 3)
  assert.ok(evidence.rel_12_1_pct > 0)
  assert.ok(evidence.rel_6m_pct > 0)
  assert.equal(evidence.ratio_above_200d, true)
})

test('a stock that compounds slower than the benchmark lags it', () => {
  const evidence = relativeEvidence(series(300, 0.01), series(300, 0.06))
  assert.equal(evidence.result, 'lags')
  assert.ok(evidence.rel_12_1_pct < 0)
})

test('a short history is not evidence either way', () => {
  assert.equal(relativeEvidence(series(100, 0.2), series(100, 0.01)).result, 'insufficient_data')
  // 150 sessions compute only the 6-month item: one item is still not enough.
  const partial = relativeEvidence(series(150, 0.2), series(150, 0.01))
  assert.equal(partial.rel_12_1_pct, null)
  assert.notEqual(partial.rel_6m_pct, null)
  assert.equal(partial.result, 'insufficient_data')
})

test('a 1-1 split between the computable items is mixed, not beats', () => {
  // Benchmark flat at 100. Ratio climbs, peaks, and falls back: the 6-month
  // relative return is still positive but the ratio ends below its 200-day mean.
  const ratio = (t) => (t <= 100 ? 1 + 0.2 * (t / 100) : t <= 180 ? 1.2 + 0.4 * ((t - 100) / 80) : 1.6 - 0.35 * ((t - 180) / 49))
  const dates = series(230, 0).map((point) => point.date)
  const stock = dates.map((date, t) => ({ date, close: 100 * ratio(t) }))
  const bench = dates.map((date) => ({ date, close: 100 }))
  const evidence = relativeEvidence(stock, bench)
  assert.equal(evidence.rel_12_1_pct, null)
  assert.ok(evidence.rel_6m_pct > 0)
  assert.equal(evidence.ratio_above_200d, false)
  assert.equal(evidence.result, 'mixed')
})

test('the earnings guard fires only on a negative surprise with analysts turning bearish', () => {
  assert.equal(earningsGuard({ epsSurprisePct: -4, upgrades30d: 0, downgrades30d: 2 }).status, 'fired')
  assert.equal(earningsGuard({ epsSurprisePct: 3, upgrades30d: 0, downgrades30d: 2 }).status, 'clear')
  assert.equal(earningsGuard({ epsSurprisePct: -4, upgrades30d: 2, downgrades30d: 0 }).status, 'clear')
  assert.equal(earningsGuard({}).status, 'unavailable')
  const trend = {
    trend: [
      { period: '0m', strongBuy: 1, buy: 2, hold: 5, sell: 2, strongSell: 0 },
      { period: '-3m', strongBuy: 4, buy: 4, hold: 2, sell: 0, strongSell: 0 },
    ],
  }
  assert.equal(earningsGuard({ epsSurprisePct: -1, recommendationTrend: trend }).status, 'fired')
})

test('the hurdle passes only when every benchmark is beaten', () => {
  const benchmarks = [
    { symbol: 'SPY', role: 'index', label: 'S&P 500' },
    { symbol: 'SMH', role: 'industry', label: 'Semiconductors' },
  ]
  const stockSeries = series(300, 0.1)
  const passing = evaluateHurdle({
    benchmarks,
    stockSeries,
    benchmarkSeries: { SPY: series(300, 0.03), SMH: series(300, 0.05) },
  })
  assert.equal(passing.status, 'pass')
  assert.deepEqual(passing.lagging, [])

  const failing = evaluateHurdle({
    benchmarks,
    stockSeries,
    benchmarkSeries: { SPY: series(300, 0.03), SMH: series(300, 0.2) },
  })
  assert.equal(failing.status, 'fail')
  assert.deepEqual(failing.lagging, ['SMH'])
})

test('a fired earnings guard fails a hurdle that every benchmark passes', () => {
  const result = evaluateHurdle({
    benchmarks: [{ symbol: 'SPY', role: 'index', label: 'S&P 500' }],
    stockSeries: series(300, 0.1),
    benchmarkSeries: { SPY: series(300, 0.02) },
    earnings: { epsSurprisePct: -5, upgrades30d: 0, downgrades30d: 3 },
  })
  assert.equal(result.status, 'fail')
  assert.deepEqual(result.lagging, [])
  assert.equal(result.earnings_guard.status, 'fired')
})

test('a benchmark that fails to load fails closed on its own row', async () => {
  const loads = { NVDA: series(300, 0.1), SPY: series(300, 0.02), QQQ: series(300, 0.03), XLK: series(300, 0.03) }
  const result = await runIndexHurdle('NVDA', {
    sector: 'Technology',
    industry: 'Semiconductors',
    loadSeries: async (symbol) => {
      if (!loads[symbol]) throw new Error('offline')
      return loads[symbol]
    },
  })
  assert.equal(result.status, 'fail')
  assert.deepEqual(result.lagging, ['SMH'])
  assert.equal(result.benchmarks.find((row) => row.symbol === 'SMH').result, 'insufficient_data')
})

test('with no stock history the hurdle is unavailable', () => {
  const result = evaluateHurdle({ benchmarks: [{ symbol: 'SPY', role: 'index', label: 'S&P 500' }], stockSeries: [] })
  assert.equal(result.status, 'unavailable')
})
