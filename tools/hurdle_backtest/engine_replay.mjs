// Does the index hurdle improve Vincent's buy signals?
//
// Replays Vincent's production engine (technical_engine/, read-only) at every
// month-end 2012-01..2021-12 for 60 large caps, on daily bars only (mid and long
// horizons; short needs intraday history that does not exist that far back).
// Market context is rebuilt from ^VIX, ^TNX, SPY and QQQ closes with the
// committed market-data.js helpers; Fear & Greed has no history and stays
// unavailable. For every mid/long buy-family action, the committed hurdle is
// evaluated and the next-12-month relative return is measured.
//
// Forward windows end by 2022-12; the consumed 2023-2024 holdout is untouched.
// Nothing is tuned.
//
// Run hurdle_only.mjs first: this script reads the adjusted-close and profile
// cache it writes, and adds full OHLCV series to the same git-ignored .cache/.

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { relativeEvidence, resolveBenchmarks } from '../../cloudflare-api/src/consolidated/index-hurdle.js'
import { classifyChangeTrend, indexTrend, seriesChange } from '../../cloudflare-api/src/consolidated/market-data.js'

const ENGINE = new URL('../../technical_engine', import.meta.url).pathname
for (const file of [
  'technical-features.js', 'profile-definitions.js', 'decision-engine/feature-inputs.js', 'decision-engine/config.js',
  'decision-engine/technical-engine.js', 'decision-engine/exhaustion-engine.js', 'decision-engine/market-engine.js',
  'decision-engine/etf-profile.js', 'decision-engine/company-profile.js', 'decision-engine/execution-engine.js',
  'decision-engine/confidence-engine.js', 'decision-engine/stability-engine.js', 'decision-engine/decision-engine.js',
]) await import(`${ENGINE}/${file}`)

const DIR = new URL('.', import.meta.url).pathname
const CACHE = `${DIR}.cache/`
mkdirSync(CACHE, { recursive: true })
const START = '2012-01-01'
const END = '2021-12-31'
const BUY_FAMILY = new Set(['strong_buy', 'buy', 'accumulate'])
const HEADERS = { 'user-agent': 'Mozilla/5.0' }
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const UNIVERSE = [
  'AAPL', 'MSFT', 'NVDA', 'AMD', 'INTC', 'AVGO', 'QCOM', 'TXN', 'MU', 'ORCL', 'CRM', 'ADBE', 'INTU', 'CSCO', 'IBM',
  'GOOGL', 'META', 'NFLX', 'DIS', 'VZ', 'T', 'CMCSA', 'AMZN', 'TSLA', 'HD', 'NKE', 'MCD', 'SBUX', 'LOW', 'WMT',
  'COST', 'PG', 'KO', 'PEP', 'JPM', 'BAC', 'WFC', 'GS', 'MS', 'JNJ', 'UNH', 'PFE', 'MRK', 'ABBV', 'LLY', 'AMGN',
  'XOM', 'CVX', 'COP', 'SLB', 'CAT', 'BA', 'HON', 'UPS', 'LMT', 'LIN', 'NEE', 'DUK', 'AMT', 'PLD',
]

const readJson = (name) => JSON.parse(readFileSync(`${CACHE}${name}.json`, 'utf8'))

async function ohlcv(symbol) {
  const path = `${CACHE}ohlcv_${symbol.replace(/[^A-Za-z0-9._-]/g, '_')}.json`
  if (existsSync(path)) return JSON.parse(readFileSync(path, 'utf8'))
  const waits = [1_200, 5_000, 15_000, 40_000]
  for (const [attempt, wait] of waits.entries()) {
    await sleep(wait)
    const host = attempt % 2 ? 'query2' : 'query1'
    const response = await fetch(`https://${host}.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?interval=1d&range=20y`, { headers: HEADERS })
    if (!response.ok) continue
    const result = (await response.json()).chart.result[0]
    const quote = result.indicators.quote[0]
    const rows = result.timestamp
      .map((ts, index) => ({
        date: new Date(ts * 1000).toISOString().slice(0, 10),
        open: quote.open[index], high: quote.high[index], low: quote.low[index], close: quote.close[index], volume: quote.volume[index],
      }))
      .filter((row) => [row.open, row.high, row.low, row.close].every(Number.isFinite))
    writeFileSync(path, JSON.stringify(rows))
    return rows
  }
  throw new Error(`ohlcv ${symbol}: gave up`)
}

function indexAtOrBefore(points, target) {
  let low = 0
  let high = points.length - 1
  let found = -1
  while (low <= high) {
    const mid = (low + high) >> 1
    if (points[mid].date <= target) {
      found = mid
      low = mid + 1
    } else high = mid - 1
  }
  return found
}

function barsFrom(rows) {
  return {
    timestamps: rows.map((row) => row.date), opens: rows.map((row) => row.open), highs: rows.map((row) => row.high),
    lows: rows.map((row) => row.low), closes: rows.map((row) => row.close), volumes: rows.map((row) => row.volume ?? 0),
    availability: rows.length ? 'available' : 'unavailable', available: rows.length > 0,
  }
}

const EMPTY = { timestamps: [], opens: [], highs: [], lows: [], closes: [], volumes: [], availability: 'unavailable', available: false }

function marketAt(date, market) {
  const closesTo = (rows, count) => rows.slice(Math.max(0, indexAtOrBefore(rows, date) - count + 1), indexAtOrBefore(rows, date) + 1).map((row) => row.close)
  const vix = closesTo(market.vix, 40)
  const tnxTail = closesTo(market.tnx, 40)
  const yields = tnxTail.length && tnxTail.at(-1) > 20 ? tnxTail.map((value) => value * 0.1) : tnxTail
  const vix5 = seriesChange(vix, 5)
  const vix20 = seriesChange(vix, 20)
  const y5 = seriesChange(yields, 5)
  const y20 = seriesChange(yields, 20)
  const y5b = y5 == null ? null : Math.round(y5 * 1000) / 10
  const y20b = y20 == null ? null : Math.round(y20 * 1000) / 10
  return {
    market_context: {
      vix: { value: vix.at(-1) ?? null, change_5d: vix5, change_20d: vix20, trend: classifyChangeTrend(vix5, vix20, 1.0, 2.5) },
      ten_year_yield: { value: yields.at(-1) ?? null, change_5d_bps: y5b, change_20d_bps: y20b, trend: classifyChangeTrend(y5b, y20b, 10.0, 25.0) },
      fear_greed: { value: null, label: null, trend: null },
      equity_trend: { spy: indexTrend('SPY', closesTo(market.spy, 180)), qqq: indexTrend('QQQ', closesTo(market.qqq, 180)) },
    },
  }
}

function decide(symbol, rows, market) {
  const engine = globalThis.DecisionEngine
  engine.stability?.clear?.()
  const daily = barsFrom(rows)
  const quote = {
    ticker: symbol,
    price: rows.at(-1).close,
    history: { ...daily, intervals: { '1d': daily, '4h': EMPTY, '1h': EMPTY }, daily_history_metadata: { lookback: '2y' } },
    metadata: { quoteType: 'EQUITY' },
    technical: { fibonacci_structure: {} },
  }
  return engine.decide({
    ticker: symbol,
    price: quote.price,
    technicalFeatures: globalThis.CanonicalTechnicalFeatures.buildTechnicalFeatures(globalThis.DecisionFeatureInputs.featureInputs(quote, market)),
    marketContext: market,
    classification: globalThis.ProfileDefinitions.profileFor(symbol, quote.metadata),
    metadata: quote.metadata,
    language: 'en',
    underlyingTechnicalFeatures: null,
    underlyingPrice: null,
  })
}

const pct = (from, to) => (to / from - 1) * 100
const mean = (values) => (values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null)
const median = (values) => {
  if (!values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  const mid = sorted.length >> 1
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}
const fmt = (value, digits = 1) => (value == null ? '—' : value.toFixed(digits))
const rate = (list, test) => (list.length ? (list.filter(test).length / list.length) * 100 : null)

async function main() {
  const market = { vix: await ohlcv('^VIX'), tnx: await ohlcv('^TNX'), spy: await ohlcv('SPY'), qqq: await ohlcv('QQQ') }
  const adj = {}
  const load = (symbol) => (adj[symbol] ??= readJson(`chart_${symbol.replace(/[^A-Za-z0-9._-]/g, '_')}`))
  const signalDates = []
  for (let index = 0; index < market.spy.length; index += 1) {
    const date = market.spy[index].date
    const next = market.spy[index + 1]?.date
    if (date >= START && date <= END && (!next || next.slice(0, 7) !== date.slice(0, 7))) signalDates.push(date)
  }

  const records = []
  let errors = 0
  for (const symbol of UNIVERSE) {
    const rows = await ohlcv(symbol)
    const stockAdj = load(symbol)
    const profile = readJson(`profile_${symbol}`)
    const benchmarks = resolveBenchmarks({ symbol, ...profile }).benchmarks
    for (const date of signalDates) {
      const at = indexAtOrBefore(rows, date)
      const adjAt = indexAtOrBefore(stockAdj, date)
      if (at < 504 || rows[at].date !== date || adjAt < 0 || adjAt + 252 >= stockAdj.length) continue
      let decision
      try {
        decision = decide(symbol, rows.slice(at - 503, at + 1), marketAt(date, market))
      } catch {
        errors += 1
        continue
      }
      const exitDate = stockAdj[adjAt + 252].date
      const midExit = stockAdj[adjAt + 126].date
      const fwd = pct(stockAdj[adjAt].close, stockAdj[adjAt + 252].close)
      const fwd6 = pct(stockAdj[adjAt].close, stockAdj[adjAt + 126].close)
      const window = stockAdj.slice(Math.max(0, adjAt - 320), adjAt + 1)
      const rels = []
      let pass = true
      let relSpy6 = null
      for (const benchmark of benchmarks) {
        const bench = load(benchmark.symbol)
        const bAt = indexAtOrBefore(bench, date)
        const bExit = indexAtOrBefore(bench, exitDate)
        if (bAt < 0 || bExit <= bAt) {
          pass = false
          rels.push(null)
          continue
        }
        const evidence = relativeEvidence(window, bench.slice(Math.max(0, bAt - 320), bAt + 1))
        if (evidence.result !== 'beats') pass = false
        rels.push(fwd - pct(bench[bAt].close, bench[bExit].close))
        if (benchmark.symbol === 'SPY') relSpy6 = fwd6 - pct(bench[bAt].close, bench[indexAtOrBefore(bench, midExit)].close)
      }
      if (rels.some((value) => value == null)) continue
      records.push({
        symbol, date, pass,
        mid: decision.horizons.mid?.action ?? null,
        long: decision.horizons.long?.action ?? null,
        relSpy: rels[0], relSpy6, beatAll: rels.every((value) => value > 0), relWorst: Math.min(...rels),
      })
    }
  }

  const row = (label, list, sixMonth = false) =>
    `| ${label} | ${list.length} | ${fmt(rate(list, (item) => item.beatAll))}% | ${fmt(rate(list, (item) => item.relSpy > 0))}% | ${fmt(mean(list.map((item) => item.relSpy)))} | ${fmt(median(list.map((item) => item.relSpy)))} | ${fmt(mean(list.map((item) => item.relWorst)))} |` +
    (sixMonth ? ` ${fmt(rate(list, (item) => item.relSpy6 > 0))}% | ${fmt(median(list.map((item) => item.relSpy6)))} |` : '')
  const section = (horizon) => {
    const buys = records.filter((item) => BUY_FAMILY.has(item[horizon]))
    const nonBuys = records.filter((item) => item[horizon] && !BUY_FAMILY.has(item[horizon]))
    return [
      `### ${horizon === 'mid' ? 'Mid (1–6 months)' : 'Long (> 6 months)'} horizon`,
      '',
      '| Group | Stock-months | Beat every benchmark 12M | Beat SPY 12M | Mean rel. SPY 12M (pp) | Median rel. SPY 12M (pp) | Mean rel. worst benchmark (pp) | Beat SPY 6M | Median rel. SPY 6M (pp) |',
      '|---|---:|---:|---:|---:|---:|---:|---:|---:|',
      row('All stock-months', records, true),
      row("Vincent's buy-family", buys, true),
      row("Vincent's buy **+ hurdle pass** (final buy)", buys.filter((item) => item.pass), true),
      row("Vincent's buy + hurdle fail (held)", buys.filter((item) => !item.pass), true),
      row("Vincent's non-buy", nonBuys, true),
      '',
    ].join('\n')
  }
  const actionMix = (horizon) => Object.entries(records.reduce((acc, item) => ({ ...acc, [item[horizon]]: (acc[item[horizon]] ?? 0) + 1 }), {}))
    .map(([action, count]) => `${action} ${count}`).join(', ')

  const report = [
    "## Does the hurdle improve Vincent's buys? (engine replay)",
    '',
    `Vincent's production engine replayed at ${signalDates.length} month-ends (${START.slice(0, 7)}..${END.slice(0, 7)}) for ${UNIVERSE.length} large caps on daily bars (2 years each), with market context rebuilt from ^VIX, ^TNX, SPY and QQQ. Short is not replayed (no historical native 4h). Fear & Greed is unavailable historically, which lowers market data quality exactly as it would live. Decisions: ${records.length}; engine errors: ${errors}.`,
    '',
    `Action mix — mid: ${actionMix('mid')}. Long: ${actionMix('long')}.`,
    '',
    section('mid'),
    section('long'),
  ].join('\n')
  writeFileSync(`${CACHE}engine-replay.md`, report)
  // Per-decision rows, for follow-up tests that join other evidence onto the
  // same stock-months (docs/consolidation/hurdle-backtest.md, Test 3).
  writeFileSync(`${CACHE}replay-records.json`, JSON.stringify(records))
  console.log(report)
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
