// Index hurdle: a buy must show evidence that it will beat every benchmark over
// the next 12 months.
//
// Benchmarks are SPY, QQQ, the stock's sector ETF, and every matching industry
// ETF (config/consolidation.json). Evidence per benchmark is deterministic and
// comes from daily closes, with thresholds fixed a priori (0 = beat it) and
// never tuned:
//   E1 relative 12-1 momentum  (Jegadeesh-Titman; industry: Moskowitz-Grinblatt)
//   E2 relative 6-month momentum
//   E3 the stock/benchmark ratio line is above its own 200-day average
// The output is historical relative returns plus pass/fail. It is not a
// numeric forecast (AGENTS.md "Forecast Research Safety").

import config from '../../config/consolidation.json' with { type: 'json' }

const HURDLE = config.indexHurdle
const INDEX_LABELS = { SPY: 'S&P 500', QQQ: 'Nasdaq-100' }

const round2 = (value) => Math.round(value * 100) / 100

export function resolveBenchmarks({ symbol, sector = null, industry = null, traits = [] } = {}) {
  const normalized = String(symbol || '').trim().toUpperCase()
  if (HURDLE.notApplicable.includes(normalized)) return { applicable: false, benchmarks: [] }
  const benchmarks = []
  const add = (ticker, role, label) => {
    if (!ticker || ticker === normalized || benchmarks.some((item) => item.symbol === ticker)) return
    benchmarks.push({ symbol: ticker, role, label })
  }
  for (const core of HURDLE.coreBenchmarks) add(core, 'index', INDEX_LABELS[core] ?? core)
  for (const [suffix, index] of Object.entries(HURDLE.localIndexBySuffix)) {
    if (normalized.endsWith(suffix)) add(index, 'local_index', index)
  }
  if (sector && HURDLE.sectorEtfs[sector]) add(HURDLE.sectorEtfs[sector], 'sector', sector)
  if (industry) {
    for (const [etf, industries] of Object.entries(HURDLE.industryEtfs)) {
      if (industries.includes(industry)) add(etf, 'industry', industry)
    }
  }
  for (const trait of traits || []) {
    if (HURDLE.traitEtfs[trait]) add(HURDLE.traitEtfs[trait], 'industry', trait)
  }
  return { applicable: true, benchmarks }
}

// Daily bars → [{ date, close }], preferring dividend-adjusted closes so a
// 12-month comparison counts total return, not price alone.
export function seriesFromBars(bars) {
  const dates = bars?.timestamps || []
  return dates
    .map((date, index) => ({ date, close: bars.adjCloses?.[index] ?? bars.closes?.[index] }))
    .filter((point) => Number.isFinite(point.close) && point.close > 0)
}

function align(stockSeries, benchSeries) {
  const benchByDate = new Map(benchSeries.map((point) => [point.date, point.close]))
  const pairs = []
  for (const point of stockSeries) {
    const bench = benchByDate.get(point.date)
    if (bench != null) pairs.push({ stock: point.close, bench })
  }
  return pairs
}

const pctReturn = (from, to) => (to / from - 1) * 100

export function relativeEvidence(stockSeries, benchSeries, windows = HURDLE.windows, minEvidence = HURDLE.minEvidence) {
  const pairs = align(stockSeries || [], benchSeries || [])
  const last = pairs.length - 1
  const { momentumLookback, momentumSkip, sixMonth, ratioAverage } = windows
  let rel121 = null
  let rel6m = null
  let ratioAbove = null
  if (pairs.length > momentumLookback) {
    const from = pairs[last - momentumLookback]
    const to = pairs[last - momentumSkip]
    rel121 = round2(pctReturn(from.stock, to.stock) - pctReturn(from.bench, to.bench))
  }
  if (pairs.length > sixMonth) {
    const from = pairs[last - sixMonth]
    const to = pairs[last]
    rel6m = round2(pctReturn(from.stock, to.stock) - pctReturn(from.bench, to.bench))
  }
  if (pairs.length >= ratioAverage) {
    const ratios = pairs.slice(-ratioAverage).map((pair) => pair.stock / pair.bench)
    const average = ratios.reduce((sum, value) => sum + value, 0) / ratios.length
    ratioAbove = ratios.at(-1) > average
  }
  const evidence = [rel121 == null ? null : rel121 > 0, rel6m == null ? null : rel6m > 0, ratioAbove]
  const known = evidence.filter((value) => value != null)
  const trueCount = known.filter(Boolean).length
  const falseCount = known.length - trueCount
  // Fewer than minEvidence computable items is not evidence either way. A 1-1
  // split is mixed. Both fail closed: only `beats` passes.
  const result =
    known.length < minEvidence
      ? 'insufficient_data'
      : trueCount >= minEvidence
        ? 'beats'
        : falseCount >= minEvidence
          ? 'lags'
          : 'mixed'
  return {
    rel_12_1_pct: rel121,
    rel_6m_pct: rel6m,
    ratio_above_200d: ratioAbove,
    evidence_true: trueCount,
    evidence_known: known.length,
    sessions: pairs.length,
    result,
  }
}

// Share of analysts net bullish in one recommendationTrend row, or null.
export function recommendationNetScore(row) {
  if (!row) return null
  const strongBuy = Number(row.strongBuy) || 0
  const buy = Number(row.buy) || 0
  const hold = Number(row.hold) || 0
  const sell = Number(row.sell) || 0
  const strongSell = Number(row.strongSell) || 0
  const total = strongBuy + buy + hold + sell + strongSell
  return total > 0 ? (strongBuy + buy - sell - strongSell) / total : null
}

// Fires only when the latest EPS surprise is negative AND analysts are turning
// against the stock. Without enough data it cannot fire, and says so.
export function earningsGuard({ epsSurprisePct = null, recommendationTrend = null, upgrades30d = null, downgrades30d = null } = {}) {
  const rows = Array.isArray(recommendationTrend?.trend) ? recommendationTrend.trend : []
  const nowScore = recommendationNetScore(rows.find((row) => row.period === '0m'))
  const beforeScore = recommendationNetScore(rows.find((row) => row.period === '-3m') ?? rows.find((row) => row.period === '-2m'))
  const trendDeteriorating =
    nowScore != null && beforeScore != null ? nowScore < beforeScore - HURDLE.earningsGuard.minNetDrop : null
  const downgradesLead = upgrades30d != null && downgrades30d != null ? downgrades30d > upgrades30d : null
  const analystsKnown = trendDeteriorating != null || downgradesLead != null
  const analystsDeteriorating = trendDeteriorating === true || downgradesLead === true
  const surprise = Number.isFinite(Number(epsSurprisePct)) && epsSurprisePct !== null ? Number(epsSurprisePct) : null
  const status =
    surprise == null || !analystsKnown ? 'unavailable' : surprise < 0 && analystsDeteriorating ? 'fired' : 'clear'
  return { status, eps_surprise_pct: surprise, analysts_deteriorating: analystsKnown ? analystsDeteriorating : null }
}

export function evaluateHurdle({ applicable = true, benchmarks = [], stockSeries = [], benchmarkSeries = {}, earnings = {} } = {}) {
  const guard = earningsGuard(earnings)
  if (!applicable) return { status: 'not_applicable', benchmarks: [], lagging: [], earnings_guard: guard }
  if (!stockSeries?.length || !benchmarks.length) {
    return { status: 'unavailable', benchmarks: [], lagging: benchmarks.map((item) => item.symbol), earnings_guard: guard }
  }
  const rows = benchmarks.map((benchmark) => ({
    ...benchmark,
    ...relativeEvidence(stockSeries, benchmarkSeries[benchmark.symbol] || []),
  }))
  const lagging = rows.filter((row) => row.result !== 'beats').map((row) => row.symbol)
  const status = lagging.length === 0 && guard.status !== 'fired' ? 'pass' : 'fail'
  return { status, benchmarks: rows, lagging, earnings_guard: guard }
}

export async function runIndexHurdle(symbol, { sector = null, industry = null, traits = [], earnings = {}, loadSeries }) {
  const { applicable, benchmarks } = resolveBenchmarks({ symbol, sector, industry, traits })
  if (!applicable) return evaluateHurdle({ applicable: false, earnings })
  const symbols = [symbol, ...benchmarks.map((item) => item.symbol)]
  // One benchmark that fails to load must not sink the others; it simply has
  // no evidence and fails closed on its own row.
  const [stockSeries, ...benchmarkLoads] = await Promise.all(symbols.map((item) => loadSeries(item).catch(() => [])))
  const benchmarkSeries = Object.fromEntries(benchmarks.map((item, index) => [item.symbol, benchmarkLoads[index]]))
  return evaluateHurdle({ applicable, benchmarks, stockSeries, benchmarkSeries, earnings })
}
