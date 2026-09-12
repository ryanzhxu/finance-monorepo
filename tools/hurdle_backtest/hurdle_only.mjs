// Descriptive backtest of the index hurdle (consolidated.v1).
//
// Question: when the hurdle says a stock beats every benchmark (SPY, QQQ, its
// sector ETF, its industry ETF), does it beat them over the NEXT 12 months more
// often than when the hurdle fails?
//
// Runs the production hurdle code unchanged. Signal dates are month-ends
// 2012-01..2021-12, so every 12-month forward window ends by 2022-12 and never
// touches the consumed 2023-2024 holdout. Thresholds are the fixed a-priori
// ones; nothing is tuned here. Universe = current large caps, so results carry
// survivorship bias (stated in the report).
//
// Run: node tools/hurdle_backtest/hurdle_only.mjs   (one Yahoo request per
// symbol, cached in the git-ignored .cache/; reruns reuse the cache)

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { relativeEvidence, resolveBenchmarks } from '../../cloudflare-api/src/consolidated/index-hurdle.js'

const DIR = new URL('.', import.meta.url).pathname
const CACHE = `${DIR}.cache/`
mkdirSync(CACHE, { recursive: true })
const FORWARD = 252
const START = '2012-01-01'
const END = '2021-12-31'

const UNIVERSE = [
  'AAPL', 'MSFT', 'NVDA', 'AMD', 'INTC', 'AVGO', 'QCOM', 'TXN', 'MU', 'ORCL', 'CRM', 'ADBE', 'INTU', 'CSCO', 'IBM',
  'GOOGL', 'META', 'NFLX', 'DIS', 'VZ', 'T', 'CMCSA', 'AMZN', 'TSLA', 'HD', 'NKE', 'MCD', 'SBUX', 'LOW', 'WMT',
  'COST', 'PG', 'KO', 'PEP', 'JPM', 'BAC', 'WFC', 'GS', 'MS', 'JNJ', 'UNH', 'PFE', 'MRK', 'ABBV', 'LLY', 'AMGN',
  'XOM', 'CVX', 'COP', 'SLB', 'CAT', 'BA', 'HON', 'UPS', 'LMT', 'LIN', 'NEE', 'DUK', 'AMT', 'PLD',
]

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
// Yahoo answers 429 to a full Chrome user-agent sent without browser cookies,
// and 200 to a bare one (verified 2026-09-11 01:00 PDT).
const HEADERS = { 'user-agent': 'Mozilla/5.0' }

async function cachedJson(name, load) {
  const path = `${CACHE}${name.replace(/[^A-Za-z0-9._-]/g, '_')}.json`
  if (existsSync(path)) return JSON.parse(readFileSync(path, 'utf8'))
  const value = await load()
  writeFileSync(path, JSON.stringify(value))
  await sleep(350)
  return value
}

// Yahoo rate-limits bursts (HTTP 429). Alternate hosts and back off; give up
// after a few tries rather than hammering it.
async function fetchChart(symbol) {
  const waits = [0, 5_000, 15_000, 40_000]
  let lastStatus = null
  for (const [attempt, wait] of waits.entries()) {
    if (wait) await sleep(wait)
    const host = attempt % 2 ? 'query2' : 'query1'
    const url = `https://${host}.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?interval=1d&range=20y&events=div%2Csplits`
    const response = await fetch(url, { headers: HEADERS })
    if (response.ok) return response.json()
    lastStatus = response.status
    if (response.status !== 429 && response.status < 500) break
  }
  throw new Error(`chart ${symbol}: HTTP ${lastStatus}`)
}

async function series(symbol) {
  return cachedJson(`chart_${symbol}`, async () => {
    await sleep(1_200)
    const result = (await fetchChart(symbol)).chart.result[0]
    const adj = result.indicators.adjclose?.[0]?.adjclose || result.indicators.quote[0].close
    return result.timestamp
      .map((ts, index) => ({ date: new Date(ts * 1000).toISOString().slice(0, 10), close: adj[index] }))
      .filter((point) => Number.isFinite(point.close) && point.close > 0)
  })
}

async function profile(symbol) {
  return cachedJson(`profile_${symbol}`, async () => {
    const response = await fetch(`https://finance-query.com/v2/quote/${symbol}`, { headers: HEADERS })
    if (!response.ok) throw new Error(`quote ${symbol}: HTTP ${response.status}`)
    const payload = await response.json()
    const quote = Array.isArray(payload) ? payload[0] : payload
    return { sector: quote.sector ?? null, industry: quote.industry ?? null }
  })
}

function monthEnds(dates) {
  const ends = []
  for (let index = 0; index < dates.length; index += 1) {
    const date = dates[index]
    const next = dates[index + 1]
    if (date < START || date > END) continue
    if (!next || next.slice(0, 7) !== date.slice(0, 7)) ends.push(date)
  }
  return ends
}

// Latest index whose date <= target, by binary search.
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

const pct = (from, to) => (to / from - 1) * 100
const mean = (values) => (values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null)
const median = (values) => {
  if (!values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  const mid = sorted.length >> 1
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}
const fmt = (value, digits = 1) => (value == null ? '—' : value.toFixed(digits))

async function main() {
  const profiles = {}
  const benchmarksBySymbol = {}
  for (const symbol of UNIVERSE) {
    profiles[symbol] = await profile(symbol)
    benchmarksBySymbol[symbol] = resolveBenchmarks({ symbol, ...profiles[symbol] }).benchmarks
  }
  const needed = [...new Set([...UNIVERSE, ...Object.values(benchmarksBySymbol).flat().map((item) => item.symbol)])]
  const data = {}
  for (const symbol of needed) data[symbol] = await series(symbol)

  const signalDates = monthEnds(data.SPY.map((point) => point.date))
  const observations = []
  for (const symbol of UNIVERSE) {
    const stock = data[symbol]
    for (const date of signalDates) {
      const at = indexAtOrBefore(stock, date)
      if (at < 0 || stock[at].date !== date || at + FORWARD >= stock.length) continue
      const exitDate = stock[at + FORWARD].date
      const stockFwd = pct(stock[at].close, stock[at + FORWARD].close)
      const stockWindow = stock.slice(Math.max(0, at - 320), at + 1)
      const rows = benchmarksBySymbol[symbol].map((benchmark) => {
        const bench = data[benchmark.symbol]
        const bAt = indexAtOrBefore(bench, date)
        const bExit = indexAtOrBefore(bench, exitDate)
        const evidence = bAt < 0 ? { result: 'insufficient_data' } : relativeEvidence(stockWindow, bench.slice(Math.max(0, bAt - 320), bAt + 1))
        const benchFwd = bAt >= 0 && bExit > bAt ? pct(bench[bAt].close, bench[bExit].close) : null
        return { symbol: benchmark.symbol, role: benchmark.role, result: evidence.result, fwdRel: benchFwd == null ? null : stockFwd - benchFwd }
      })
      if (rows.some((row) => row.fwdRel == null)) continue
      observations.push({
        symbol,
        date,
        pass: rows.every((row) => row.result === 'beats'),
        insufficient: rows.some((row) => row.result === 'insufficient_data'),
        beatAllFwd: rows.every((row) => row.fwdRel > 0),
        relSpy: rows.find((row) => row.symbol === 'SPY').fwdRel,
        relWorst: Math.min(...rows.map((row) => row.fwdRel)),
        rows,
      })
    }
  }

  const summarize = (list) => ({
    n: list.length,
    beatAll: list.length ? (list.filter((item) => item.beatAllFwd).length / list.length) * 100 : null,
    beatSpy: list.length ? (list.filter((item) => item.relSpy > 0).length / list.length) * 100 : null,
    meanRelSpy: mean(list.map((item) => item.relSpy)),
    medianRelSpy: median(list.map((item) => item.relSpy)),
    meanRelWorst: mean(list.map((item) => item.relWorst)),
  })
  const all = summarize(observations)
  const passed = summarize(observations.filter((item) => item.pass))
  const failed = summarize(observations.filter((item) => !item.pass))
  const failedData = summarize(observations.filter((item) => !item.pass && !item.insufficient))

  // Per-benchmark calibration: when the evidence says `beats` for benchmark B,
  // how often does the stock beat B over the next 12 months?
  const perBench = {}
  for (const item of observations) {
    for (const row of item.rows) {
      const key = row.role === 'index' ? row.symbol : row.role
      perBench[key] ??= { beats: [], other: [] }
      perBench[key][row.result === 'beats' ? 'beats' : 'other'].push(row.fwdRel)
    }
  }
  const byYear = {}
  for (const item of observations) {
    const year = item.date.slice(0, 4)
    byYear[year] ??= []
    byYear[year].push(item)
  }

  const line = (label, s) =>
    `| ${label} | ${s.n} | ${fmt(s.beatAll)}% | ${fmt(s.beatSpy)}% | ${fmt(s.meanRelSpy)} | ${fmt(s.medianRelSpy)} | ${fmt(s.meanRelWorst)} |`
  const report = [
    '# Index hurdle — descriptive backtest',
    '',
    `Generated ${new Date().toISOString().slice(0, 10)} Code under test: the committed hurdle (\`cloudflare-api/src/consolidated/index-hurdle.js\`, as checked out), unchanged thresholds.`,
    '',
    `- Universe: ${UNIVERSE.length} current US large caps. Benchmarks per stock: SPY, QQQ, sector ETF, industry ETF (config map).`,
    `- Signals: month-ends ${START.slice(0, 7)} to ${END.slice(0, 7)} (${signalDates.length} months). Outcome: the next ${FORWARD} sessions, dividend-adjusted.`,
    '- Every forward window ends by 2022-12. The consumed 2023-2024 holdout is not used.',
    '- The earnings guard is not replayed (no point-in-time EPS surprise history), so this tests the price evidence only.',
    '',
    '## Result',
    '',
    '| Group | Stock-months | Beat every benchmark next 12M | Beat SPY next 12M | Mean rel. vs SPY (pp) | Median rel. vs SPY (pp) | Mean rel. vs worst benchmark (pp) |',
    '|---|---:|---:|---:|---:|---:|---:|',
    line('All', all),
    line('Hurdle **pass**', passed),
    line('Hurdle fail (any reason)', failed),
    line('Hurdle fail, full data', failedData),
    '',
    '## Per benchmark',
    '',
    'When the evidence says `beats` for a benchmark, how often did the stock beat that benchmark over the next 12 months?',
    '',
    '| Benchmark | `beats` n | Beat rate after `beats` | Mean rel. after `beats` (pp) | Other n | Beat rate otherwise | Mean rel. otherwise (pp) |',
    '|---|---:|---:|---:|---:|---:|---:|',
    ...Object.entries(perBench).map(([key, value]) => {
      const rate = (list) => (list.length ? (list.filter((rel) => rel > 0).length / list.length) * 100 : null)
      return `| ${key} | ${value.beats.length} | ${fmt(rate(value.beats))}% | ${fmt(mean(value.beats))} | ${value.other.length} | ${fmt(rate(value.other))}% | ${fmt(mean(value.other))} |`
    }),
    '',
    '## By signal year',
    '',
    '| Year | n pass | Pass: beat all | Pass: mean rel. SPY | n fail | Fail: beat all | Fail: mean rel. SPY |',
    '|---|---:|---:|---:|---:|---:|---:|',
    ...Object.entries(byYear).map(([year, list]) => {
      const p = summarize(list.filter((item) => item.pass))
      const f = summarize(list.filter((item) => !item.pass))
      return `| ${year} | ${p.n} | ${fmt(p.beatAll)}% | ${fmt(p.meanRelSpy)} | ${f.n} | ${fmt(f.beatAll)}% | ${fmt(f.meanRelSpy)} |`
    }),
    '',
    '## Caveats',
    '',
    '- Survivorship bias: the universe is today\'s large caps, which by construction did well. Absolute beat rates are inflated for every group; compare pass vs fail, not against 50%.',
    '- Overlapping 12-month windows (monthly signals) are autocorrelated, so the effective sample is far smaller than the stock-month count. Treat differences as descriptive, not significant.',
    '- Benchmarks without 253 sessions of history (for example XLC before mid-2019) make the hurdle fail closed, as in production. The "full data" row removes those.',
    '- Sector/industry come from today\'s Yahoo classification, not point-in-time.',
    '',
  ].join('\n')
  writeFileSync(`${CACHE}hurdle-only.md`, report)
  writeFileSync(`${CACHE}hurdle-only-summary.json`, JSON.stringify({ all, passed, failed, failedData, months: signalDates.length }, null, 2))
  console.log(report)
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
