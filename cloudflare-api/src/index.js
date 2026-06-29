import { ENTRY_RULES, SCORING_WEIGHTS, SCREENER_THRESHOLDS, SIGNAL_WEIGHTS, UNIVERSES } from './data.js'
import {
  atr,
  clamp,
  ema,
  macd,
  mean,
  pctChange,
  quantile,
  rsi,
  sma,
  stdev,
  round,
  highest,
  lowest,
} from './indicators.js'

const FINANCE_QUERY_BASE = 'https://finance-query.com/v2'
const DEFAULT_HEADERS = {
  'content-type': 'application/json; charset=utf-8',
  'cache-control': 'no-store',
}

const requestCache = new Map()
const healthCache = new Map()
const sharedSpaceKeyCache = new Map()
const sharedSpaceTextEncoder = new TextEncoder()
const sharedSpaceTextDecoder = new TextDecoder()

function json(data, status = 200, extraHeaders = {}) {
  return Response.json(data, {
    status,
    headers: {
      ...DEFAULT_HEADERS,
      ...extraHeaders,
    },
  })
}

const ALLOWED_CORS_ORIGINS = new Set([
  'http://localhost:5173',
  'http://127.0.0.1:5173',
  'https://finance-web-ui.onrender.com',
  'https://finance-web-ui-dev.onrender.com',
])

function corsHeaders(request = null) {
  const origin = request?.headers?.get('origin')?.trim() || null
  const headers = {
    'access-control-allow-origin': '*',
    'access-control-allow-methods': 'GET,POST,DELETE,OPTIONS',
    'access-control-allow-headers': 'content-type, authorization',
    'access-control-max-age': '86400',
  }
  if (origin && ALLOWED_CORS_ORIGINS.has(origin)) {
    headers['access-control-allow-origin'] = origin
    headers['access-control-allow-credentials'] = 'true'
    headers.vary = 'Origin'
  }
  return headers
}

function withCors(response, request = null) {
  const headers = new Headers(response.headers)
  for (const [key, value] of Object.entries(corsHeaders(request))) {
    headers.set(key, value)
  }
  return new Response(response.body, {
    status: response.status,
    headers,
  })
}

function jsonCors(data, status = 200, extraHeaders = {}) {
  return withCors(json(data, status, extraHeaders))
}

function normalizeSymbol(value) {
  return String(value ?? '')
    .trim()
    .toUpperCase()
    .replace(/\./g, '-')
}

function normalizeUniverse(value) {
  const upper = String(value ?? '').trim().toUpperCase()
  return Object.prototype.hasOwnProperty.call(UNIVERSES, upper) ? upper : 'SP500'
}

function makeCacheKey(kind, symbol, extra = '') {
  return `${kind}:${normalizeSymbol(symbol)}:${extra}`
}

function cacheGet(cache, key) {
  const entry = cache.get(key)
  if (!entry) return null
  if (entry.expiresAt <= Date.now()) {
    cache.delete(key)
    return null
  }
  return entry.value
}

function cacheSet(cache, key, value, ttlMs = 60_000) {
  cache.set(key, { value, expiresAt: Date.now() + ttlMs })
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      'user-agent': 'Mozilla/5.0',
      accept: 'application/json,text/plain,*/*',
      ...(options.headers ?? {}),
    },
  })
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} from ${url}`)
  }
  return response.json()
}

async function financeQueryGet(path, params = {}) {
  const url = new URL(`${FINANCE_QUERY_BASE}${path}`)
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    url.searchParams.set(key, String(value))
  }
  return fetchJson(url)
}

async function fetchAlphaVantagePutCallRatio(symbol, apiKey) {
  if (!apiKey) return null

  const url = new URL('https://www.alphavantage.co/query')
  url.searchParams.set('function', 'HISTORICAL_PUT_CALL_RATIO')
  url.searchParams.set('symbol', normalizeSymbol(symbol))
  url.searchParams.set('apikey', apiKey)

  try {
    const payload = await fetchJson(url)
    return safeNumber(payload?.put_call_ratio_full_chain)
  } catch {
    return null
  }
}

async function fetchCboeMarketPutCallRatio() {
  try {
    const response = await fetch('https://ww2.cboe.com/us/options/market_statistics/?iframe=1', {
      headers: {
        'user-agent': 'Mozilla/5.0',
        accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      },
    })
    if (!response.ok) {
      console.warn(`Cboe put/call request failed: HTTP ${response.status}`)
      return null
    }
    const html = await response.text()
    const sectionMatch = html.match(/<h3>Total<\/h3>\s*<table class="data-table">([\s\S]*?)<\/table>/i)
    if (!sectionMatch) {
      console.warn('Cboe put/call parser did not find the Total table')
      return null
    }
    const rowMatches = [...sectionMatch[1].matchAll(/<tr[^>]*>([\s\S]*?)<\/tr>/gi)]
    if (!rowMatches.length) {
      console.warn('Cboe put/call parser did not find any table rows')
      return null
    }
    const lastRow = rowMatches.at(-1)?.[1] ?? ''
    const cellValues = [...lastRow.matchAll(/<t[dh][^>]*>([\s\S]*?)<\/t[dh]>/gi)]
      .map((match) => match[1].replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').trim())
      .filter(Boolean)
    const ratio = safeNumber(cellValues.at(-1))
    if (ratio == null) {
      console.warn(`Cboe put/call parser could not parse ratio from cells: ${JSON.stringify(cellValues)}`)
    }
    return ratio
  } catch {
    console.warn('Cboe put/call fetch threw an exception')
    return null
  }
}

function formatDateOnly(value) {
  if (!Number.isFinite(value)) return new Date().toISOString().slice(0, 10)
  return new Date(value * 1000).toISOString().slice(0, 10)
}

function extractCandles(payload) {
  const candles = Array.isArray(payload?.candles) ? payload.candles : []
  return candles
    .map((candle) => ({
      timestamp: Number(candle.timestamp),
      open: Number(candle.open),
      high: Number(candle.high),
      low: Number(candle.low),
      close: Number(candle.close ?? candle.adjClose),
      volume: Number(candle.volume),
    }))
    .filter((candle) => Number.isFinite(candle.close) && Number.isFinite(candle.timestamp))
}

function safeNumber(value) {
  const next = Number(value)
  return Number.isFinite(next) ? next : null
}

function extractLatestEarningsSurprise(quote) {
  const history = Array.isArray(quote?.earningsHistory?.history) ? quote.earningsHistory.history : []
  if (!history.length) {
    return { surprisePct: null, asOf: null }
  }

  const rows = history
    .map((item) => {
      const quarter = safeNumber(item?.quarter)
      if (quarter == null) return null
      const surprisePct = safeNumber(item?.surprisePercent)
      const epsActual = safeNumber(item?.epsActual)
      const epsEstimate = safeNumber(item?.epsEstimate)
      const computedSurprise =
        surprisePct != null
          ? Math.abs(surprisePct) <= 1.5
            ? round(surprisePct * 100, 2)
            : round(surprisePct, 2)
          : epsActual != null && epsEstimate != null && epsEstimate !== 0
            ? round(((epsActual - epsEstimate) / Math.abs(epsEstimate)) * 100, 2)
            : null
      return {
        quarter,
        surprisePct: computedSurprise,
      }
    })
    .filter(Boolean)

  if (!rows.length) {
    return { surprisePct: null, asOf: null }
  }

  rows.sort((a, b) => a.quarter - b.quarter)
  const latest = rows.at(-1)
  return {
    surprisePct: latest?.surprisePct ?? null,
    asOf: latest?.quarter != null ? formatDateTime(latest.quarter) : null,
  }
}

function extractRecentRecommendationCounts(quote) {
  const history = Array.isArray(quote?.upgradeDowngradeHistory?.history) ? quote.upgradeDowngradeHistory.history : []
  if (!history.length) {
    return { upgrades: null, downgrades: null }
  }

  const cutoffMs = Date.now() - 30 * 24 * 60 * 60 * 1000
  let upgrades = 0
  let downgrades = 0
  let seenRecentRows = false

  for (const item of history) {
    const epochGradeDate = safeNumber(item?.epochGradeDate)
    if (epochGradeDate == null) continue
    const whenMs = epochGradeDate * 1000
    if (whenMs < cutoffMs) continue
    seenRecentRows = true
    const action = String(item?.action ?? '').trim().toLowerCase()
    if (['up', 'upgrade', 'upgraded', 'raised', 'raise'].includes(action)) {
      upgrades += 1
    } else if (['down', 'downgrade', 'downgraded', 'lowered', 'lower'].includes(action)) {
      downgrades += 1
    }
  }

  if (!seenRecentRows) {
    return { upgrades: 0, downgrades: 0 }
  }

  return { upgrades, downgrades }
}

function formatDateTime(value) {
  if (!Number.isFinite(value)) return new Date().toISOString()
  return new Date(value * 1000).toISOString()
}

function splitCandles(candles) {
  return {
    timestamps: candles.map((candle) => candle.timestamp),
    opens: candles.map((candle) => candle.open),
    highs: candles.map((candle) => candle.high),
    lows: candles.map((candle) => candle.low),
    closes: candles.map((candle) => candle.close),
    volumes: candles.map((candle) => candle.volume),
  }
}

function localQuantile(values, q) {
  if (!values.length) return null
  return quantile(values, q)
}

function calculateWeeklyRsi(closes) {
  if (closes.length < 20) return null
  const sampled = []
  for (let index = 4; index < closes.length; index += 5) {
    sampled.push(closes[index])
  }
  return rsi(sampled, 14)
}

function recentSlope(values, period) {
  if (values.length <= period) return null
  const last = values.slice(values.length - period)
  const first = last[0]
  const final = last[last.length - 1]
  return pctChange(final, first)
}

function computeSnapshot(symbol, quote, candles) {
  const closes = candles.map((candle) => candle.close)
  const highs = candles.map((candle) => candle.high)
  const lows = candles.map((candle) => candle.low)
  const volumes = candles.map((candle) => candle.volume)
  const currentPrice = closes.at(-1) ?? safeNumber(quote?.regularMarketPrice) ?? null
  const volumeAvg90 = mean(volumes.slice(-90))
  const volumeRatio90d =
    currentPrice == null || volumeAvg90 == null || volumeAvg90 === 0
      ? null
      : round((volumes.at(-1) ?? 0) / volumeAvg90, 2)

  const ma20 = sma(closes, 20)
  const ma50 = sma(closes, 50)
  const ma200 = sma(closes, 200)
  const rsi14 = rsi(closes, 14)
  const weeklyRsi = calculateWeeklyRsi(closes)
  const macdValue = macd(closes)
  const atr14 = atr(highs, lows, closes, 14)
  const bbMid = ma20
  const std20 = stdev(closes.slice(-20))
  const bbUpper = bbMid != null && std20 != null ? bbMid + std20 * 2 : null
  const bbLower = bbMid != null && std20 != null ? bbMid - std20 * 2 : null

  const supportWindow = Math.min(ENTRY_RULES.supportWindow, lows.length)
  const supportLow = supportWindow > 0 ? lowest(lows, lows.length - supportWindow) : null
  const supportMid = lows.length > 50 ? lowest(lows, lows.length - 50) : null
  const supportWide = lows.length > 90 ? lowest(lows, lows.length - 90) : null
  const resistanceLow = supportWindow > 0 ? highest(highs, highs.length - supportWindow) : null
  const resistanceMid = highs.length > 50 ? highest(highs, highs.length - 50) : null
  const resistanceWide = highs.length > 90 ? highest(highs, highs.length - 90) : null

  const supportLevels = [supportLow, supportMid, supportWide]
    .filter((value) => Number.isFinite(value))
    .sort((a, b) => a - b)
  const resistanceLevels = [resistanceLow, resistanceMid, resistanceWide]
    .filter((value) => Number.isFinite(value))
    .sort((a, b) => b - a)

  const lastClose = currentPrice ?? 0
  const priceVsMa20Pct = ma20 == null || ma20 === 0 ? null : pctChange(lastClose, ma20)
  const priceVsMa50Pct = ma50 == null || ma50 === 0 ? null : pctChange(lastClose, ma50)
  const priceVsMa200Pct = ma200 == null || ma200 === 0 ? null : pctChange(lastClose, ma200)
  const recentGapPct = closes.length > 1 ? pctChange(closes.at(-1), closes.at(-2)) : null
  const recent60Slope = recentSlope(closes, 20)

  return {
    symbol,
    companyName: quote?.longName ?? quote?.shortName ?? null,
    currentPrice,
    closes,
    highs,
    lows,
    volumes,
    quote,
    ma20,
    ma50,
    ma200,
    rsi14,
    weeklyRsi,
    macd: macdValue,
    atr14,
    bbMid,
    bbUpper,
    bbLower,
    volumeRatio90d,
    supportLevels,
    resistanceLevels,
    supportLow,
    resistanceLow,
    priceVsMa20Pct,
    priceVsMa50Pct,
    priceVsMa200Pct,
    recentGapPct,
    recent60Slope,
    candleCount: candles.length,
    lastCandleTimestamp: candles.at(-1)?.timestamp ?? null,
    lastCandleDate: candles.at(-1)?.timestamp ? formatDateTime(candles.at(-1).timestamp) : null,
  }
}

function estimatePePercentile(peRatio) {
  if (!Number.isFinite(peRatio)) return null
  return clamp(round(((peRatio - 8) / (70 - 8)) * 100, 1), 0, 100)
}

function estimateMarketRegimeFromSnapshot(spySnapshot, vixQuote) {
  const spyCurrent = spySnapshot?.currentPrice ?? null
  const spyMa200 = spySnapshot?.ma200 ?? null
  const vix = safeNumber(vixQuote?.regularMarketPrice) ?? safeNumber(vixQuote?.ask) ?? null
  const spyAboveMa200 = spyCurrent != null && spyMa200 != null && spyCurrent >= spyMa200

  if ((vix != null && vix >= 25) || (!spyAboveMa200 && spySnapshot?.priceVsMa50Pct != null && spySnapshot.priceVsMa50Pct < -5)) {
    return 'risk_off'
  }
  if ((vix != null && vix < 18) && spyAboveMa200) {
    return 'risk_on'
  }
  return 'neutral'
}

function chooseEntryAssessment(snapshot, regime) {
  const { currentPrice, ma20, ma200, rsi14, supportLevels, resistanceLevels, volumeRatio90d } = snapshot
  const support = supportLevels[0] ?? null
  const resistance = resistanceLevels[0] ?? null
  const nearSupport = support != null && currentPrice != null && currentPrice <= support * 1.03
  const nearResistance = resistance != null && currentPrice != null && currentPrice >= resistance * 0.985
  const bullishTrend = ma200 != null && currentPrice != null && currentPrice > ma200
  const strongMomentum = rsi14 != null && rsi14 >= 55
  const overextended = rsi14 != null && rsi14 > ENTRY_RULES.overboughtRsi

  if (overextended || nearResistance) {
    return 'wait_for_breakout_confirmation'
  }
  if (nearSupport && (rsi14 == null || rsi14 <= ENTRY_RULES.aggressiveMaxRsi)) {
    return regime === 'risk_off' ? 'wait_for_pullback' : 'buy_now'
  }
  if (bullishTrend && strongMomentum && (volumeRatio90d == null || volumeRatio90d >= 1)) {
    return 'long_term_investment_candidate'
  }
  if (currentPrice != null && ma20 != null && currentPrice < ma20) {
    return 'wait_for_pullback'
  }
  return 'short_term_trade_only'
}

function buildEntry(snapshot, regime) {
  const {
    currentPrice,
    supportLevels,
    resistanceLevels,
    atr14,
    ma20,
    ma50,
    rsi14,
    volumeRatio90d,
    macd,
    bbLower,
    bbUpper,
  } = snapshot

  const support = supportLevels[0] ?? currentPrice ?? 0
  const resistance = resistanceLevels[0] ?? currentPrice ?? 0
  const atrValue = atr14 ?? Math.max((currentPrice ?? 0) * 0.03, 1)
  const idealLow = support - atrValue * ENTRY_RULES.idealZoneLowAtrMultiple
  const idealHigh = support + atrValue * ENTRY_RULES.zoneAtrMult
  const aggressiveEntryPrice = currentPrice != null && rsi14 != null && rsi14 <= ENTRY_RULES.aggressiveMaxRsi ? currentPrice : null
  const conservativeEntryPrice = ma20 ?? support + atrValue * 0.5
  const breakoutBuyLevel = resistance * (1 + ENTRY_RULES.breakoutBuffer)
  const stopLossSuggestion = Math.max(0.01, support - atrValue * 1.5)
  const invalidationLevel = Math.max(0.01, support - atrValue * 2.5)
  const riskRewardRatio =
    currentPrice != null && stopLossSuggestion < currentPrice
      ? round((breakoutBuyLevel - currentPrice) / (currentPrice - stopLossSuggestion), 2)
      : null
  const breakoutVolumeConfirmed =
    volumeRatio90d != null && volumeRatio90d >= ENTRY_RULES.breakoutVolumeRatio && currentPrice != null
      ? currentPrice >= breakoutBuyLevel * 0.99
      : false
  const isOverextended =
    currentPrice != null &&
    ma20 != null &&
    pctChange(currentPrice, ma20) != null &&
    Math.abs(pctChange(currentPrice, ma20)) > ENTRY_RULES.extensionThresholdPct

  const entryAssessment = chooseEntryAssessment(snapshot, regime)
  const reasonParts = []
  if (rsi14 != null) reasonParts.push(`RSI ${Math.round(rsi14)}`)
  if (snapshot.priceVsMa20Pct != null) reasonParts.push(`vs 20D ${round(snapshot.priceVsMa20Pct, 1)}%`)
  if (snapshot.priceVsMa200Pct != null) reasonParts.push(`vs 200D ${round(snapshot.priceVsMa200Pct, 1)}%`)
  if (volumeRatio90d != null) reasonParts.push(`volume ${round(volumeRatio90d, 2)}x`)
  if (macd.histogram != null) reasonParts.push(macd.histogram >= 0 ? 'MACD bullish' : 'MACD bearish')
  if (bbLower != null && bbUpper != null) reasonParts.push(`BB ${round(bbLower, 2)}-${round(bbUpper, 2)}`)

  return {
    current_price: currentPrice,
    ideal_buy_zone: [round(idealLow, 2) ?? idealLow, round(idealHigh, 2) ?? idealHigh],
    aggressive_entry_price: aggressiveEntryPrice == null ? null : round(aggressiveEntryPrice, 2),
    conservative_entry_price: conservativeEntryPrice == null ? null : round(conservativeEntryPrice, 2),
    breakout_buy_level: round(breakoutBuyLevel, 2),
    support_levels: supportLevels.slice(0, 3).map((value) => round(value, 2) ?? value),
    resistance_levels: resistanceLevels.slice(0, 3).map((value) => round(value, 2) ?? value),
    stop_loss_suggestion: round(stopLossSuggestion, 2),
    invalidation_level: round(invalidationLevel, 2),
    risk_reward_ratio: riskRewardRatio,
    is_overextended: isOverextended,
    breakout_volume_confirmed: breakoutVolumeConfirmed,
    entry_assessment: entryAssessment,
    reason: reasonParts.join(' · ') || 'Edge model derived from price action and momentum.',
    regime,
    regime_override: false,
    regime_override_reason: null,
  }
}

function buildFibonacci(snapshot, lookbackDays = 90) {
  const closes = snapshot.closes.slice(-lookbackDays)
  const highs = snapshot.highs.slice(-lookbackDays)
  const lows = snapshot.lows.slice(-lookbackDays)
  const swingHigh = highest(highs) ?? snapshot.currentPrice ?? 0
  const swingLow = lowest(lows) ?? snapshot.currentPrice ?? 0
  const range = Math.max(swingHigh - swingLow, 0.01)
  const level = (ratio) => swingHigh - range * ratio
  const fib = {
    swing_high: round(swingHigh, 2),
    swing_low: round(swingLow, 2),
    level_0: round(level(0), 2),
    level_236: round(level(0.236), 2),
    level_382: round(level(0.382), 2),
    level_500: round(level(0.5), 2),
    level_618: round(level(0.618), 2),
    level_650: round(level(0.65), 2),
    level_786: round(level(0.786), 2),
    level_1000: round(level(1), 2),
    golden_pocket_low: round(level(0.65), 2),
    golden_pocket_high: round(level(0.618), 2),
    as_of: snapshot.lastCandleDate ?? new Date().toISOString(),
    lookback_days: lookbackDays,
  }
  return fib
}

function buildConfluence(snapshot, entry, fibonacci) {
  const idealLow = entry.ideal_buy_zone[0]
  const idealHigh = entry.ideal_buy_zone[1]
  const fibLow = Math.min(fibonacci.golden_pocket_low, fibonacci.golden_pocket_high)
  const fibHigh = Math.max(fibonacci.golden_pocket_low, fibonacci.golden_pocket_high)
  const overlap = idealHigh >= fibLow && idealLow <= fibHigh
  const mergedLow = overlap ? Math.max(idealLow, fibLow) : null
  const mergedHigh = overlap ? Math.min(idealHigh, fibHigh) : null
  return {
    classical_zone: [round(idealLow, 2), round(idealHigh, 2)],
    fibonacci_golden_pocket: [round(fibLow, 2), round(fibHigh, 2)],
    overlap,
    merged_zone_low: mergedLow == null ? null : round(mergedLow, 2),
    merged_zone_high: mergedHigh == null ? null : round(mergedHigh, 2),
    high_conviction: overlap && !entry.is_overextended,
    divergence_note: overlap ? null : 'Classical entry and Fibonacci pocket are not overlapping right now.',
    methods_agreeing: overlap ? ['classical', 'fibonacci'] : ['classical'],
  }
}

function scoreSignal(direction) {
  if (direction === 'BUY') return 1
  if (direction === 'SELL') return -1
  return 0
}

function signalDirectionFromValue(value, buyBelow, sellAbove) {
  if (!Number.isFinite(value)) return 'HOLD'
  if (value <= buyBelow) return 'BUY'
  if (value >= sellAbove) return 'SELL'
  return 'HOLD'
}

function buildSignals(snapshot, entry, fundamentals, sentiment, macro) {
  const signals = []
  const pushSignal = (dimension, direction, weight, note) => {
    signals.push({ dimension, signal: direction, weight, note })
  }

  pushSignal(
    'RSI_14',
    signalDirectionFromValue(snapshot.rsi14 ?? NaN, 45, 70),
    SIGNAL_WEIGHTS.RSI_14,
    snapshot.rsi14 == null ? 'RSI unavailable' : `RSI ${Math.round(snapshot.rsi14)}`,
  )
  pushSignal(
    'MACD',
    snapshot.macd.histogram == null ? 'HOLD' : snapshot.macd.histogram > 0 ? 'BUY' : 'SELL',
    SIGNAL_WEIGHTS.MACD,
    snapshot.macd.histogram == null ? 'MACD unavailable' : `Histogram ${round(snapshot.macd.histogram, 3)}`,
  )
  pushSignal(
    'Bollinger_Bands',
    snapshot.currentPrice != null && snapshot.bbLower != null && snapshot.currentPrice <= snapshot.bbLower
      ? 'BUY'
      : snapshot.currentPrice != null && snapshot.bbUpper != null && snapshot.currentPrice >= snapshot.bbUpper
        ? 'SELL'
        : 'HOLD',
    SIGNAL_WEIGHTS.Bollinger_Bands,
    snapshot.bbLower == null || snapshot.bbUpper == null ? 'Bands unavailable' : `Bands ${round(snapshot.bbLower, 2)}-${round(snapshot.bbUpper, 2)}`,
  )
  pushSignal(
    'Volume',
    snapshot.volumeRatio90d == null
      ? 'HOLD'
      : snapshot.volumeRatio90d >= 1.2
        ? 'BUY'
        : snapshot.volumeRatio90d <= 0.75
          ? 'SELL'
          : 'HOLD',
    SIGNAL_WEIGHTS.Volume,
    snapshot.volumeRatio90d == null ? 'Volume unavailable' : `Volume ${round(snapshot.volumeRatio90d, 2)}x`,
  )
  pushSignal(
    'MA_50_200',
    snapshot.ma50 != null && snapshot.ma200 != null && snapshot.ma50 > snapshot.ma200
      ? 'BUY'
      : snapshot.ma50 != null && snapshot.ma200 != null && snapshot.ma50 < snapshot.ma200
        ? 'SELL'
        : 'HOLD',
    SIGNAL_WEIGHTS.MA_50_200,
    snapshot.ma50 != null && snapshot.ma200 != null
      ? `MA50 ${round(snapshot.ma50, 2)} vs MA200 ${round(snapshot.ma200, 2)}`
      : 'Moving averages unavailable',
  )
  pushSignal(
    'RSI_Weekly',
    signalDirectionFromValue(snapshot.weeklyRsi ?? NaN, 50, 75),
    SIGNAL_WEIGHTS.RSI_Weekly,
    snapshot.weeklyRsi == null ? 'Weekly RSI unavailable' : `Weekly RSI ${Math.round(snapshot.weeklyRsi)}`,
  )
  pushSignal(
    'Support_Resistance',
    entry.entry_assessment === 'buy_now' || entry.entry_assessment === 'long_term_investment_candidate'
      ? 'BUY'
      : entry.entry_assessment === 'wait_for_breakout_confirmation'
        ? 'HOLD'
        : 'SELL',
    SIGNAL_WEIGHTS.Support_Resistance,
    entry.reason,
  )

  const pePercentile = fundamentals.pe_percentile_5y
  pushSignal(
    'PE_Percentile',
    pePercentile == null
      ? 'HOLD'
      : pePercentile <= 40
        ? 'BUY'
        : pePercentile >= 70
          ? 'SELL'
          : 'HOLD',
    SIGNAL_WEIGHTS.PE_Percentile,
    pePercentile == null ? 'PE percentile unavailable' : `PE percentile ${Math.round(pePercentile)}th`,
  )

  const shortInterest = sentiment.short_interest_pct
  pushSignal(
    'Short_Interest',
    shortInterest == null
      ? 'HOLD'
      : shortInterest <= 5
        ? 'BUY'
        : shortInterest >= 15
          ? 'SELL'
          : 'HOLD',
    SIGNAL_WEIGHTS.Short_Interest,
    shortInterest == null ? 'Short interest unavailable' : `Short interest ${round(shortInterest, 1)}%`,
  )

  const vix = macro.vix
  pushSignal(
    'FOMC_Proximity',
    vix == null ? 'HOLD' : vix >= 25 ? 'SELL' : vix <= 18 ? 'BUY' : 'HOLD',
    SIGNAL_WEIGHTS.FOMC_Proximity,
    vix == null ? 'VIX unavailable' : `VIX ${round(vix, 1)}`,
  )

  pushSignal(
    'News_Sentiment',
    sentiment.reddit_positive_pct != null
      ? sentiment.reddit_positive_pct >= 60
        ? 'BUY'
        : sentiment.reddit_positive_pct <= 40
          ? 'SELL'
          : 'HOLD'
      : 'HOLD',
    SIGNAL_WEIGHTS.News_Sentiment,
    sentiment.reddit_positive_pct == null ? 'No social sentiment signal' : `Reddit positive ${round(sentiment.reddit_positive_pct, 1)}%`,
  )

  return signals
}

function buildFundamentals(quote, snapshot) {
  const peRatio = safeNumber(quote?.trailingPE ?? quote?.forwardPE)
  const pbRatio = safeNumber(quote?.priceToBook)
  const psRatio = safeNumber(quote?.priceToSalesTrailing12Months)
  const evEbitda = safeNumber(quote?.enterpriseToEbitda)
  const revenueGrowth = safeNumber(quote?.revenueGrowth != null ? quote.revenueGrowth * 100 : quote?.earningsGrowth != null ? quote.earningsGrowth * 100 : null)
  const grossMargin = safeNumber(quote?.grossMargins != null ? quote.grossMargins * 100 : null)
  const latestEarnings = extractLatestEarningsSurprise(quote)
  const recentRecommendations = extractRecentRecommendationCounts(quote)

  return {
    eps_surprise_pct: latestEarnings.surprisePct,
    pe_ratio: peRatio,
    pb_ratio: pbRatio,
    ps_ratio: psRatio,
    ev_ebitda: evEbitda,
    pe_percentile_5y: estimatePePercentile(peRatio),
    analyst_upgrades_30d: recentRecommendations.upgrades,
    analyst_downgrades_30d: recentRecommendations.downgrades,
    revenue_growth_yoy_pct: revenueGrowth,
    fcf_trend:
      snapshot.priceVsMa200Pct != null && snapshot.priceVsMa200Pct > 0 && (snapshot.rsi14 ?? 0) >= 50
        ? 'improving'
        : snapshot.priceVsMa200Pct != null && snapshot.priceVsMa200Pct < 0 && (snapshot.rsi14 ?? 100) < 45
          ? 'deteriorating'
          : 'flat',
    gross_margin_pct: grossMargin,
    freshness: quote ? 'estimated' : 'missing',
    as_of: latestEarnings.asOf ?? (quote?.regularMarketTime ? formatDateOnly(quote.regularMarketTime) : new Date().toISOString().slice(0, 10)),
    company_name: snapshot.companyName,
  }
}

function buildSentiment(quote, snapshot, putCallRatio = null) {
  const ivApprox =
    quote?.impliedVolatility != null ? clamp(round(Number(quote.impliedVolatility) * 100, 1), 0, 100) : null
  const shortInterest = quote?.shortPercentOfFloat != null ? clamp(round(Number(quote.shortPercentOfFloat) * 100, 1), 0, 100) : null
  const positiveProxy =
    snapshot.volumeRatio90d == null
      ? null
      : clamp(round(50 + (snapshot.volumeRatio90d - 1) * 20 + (snapshot.priceVsMa20Pct ?? 0) / 2, 1), 0, 100)

  return {
    put_call_ratio: putCallRatio,
    iv_rank: ivApprox,
    iv_rank_approx: ivApprox,
    iv_rank_is_approx: true,
    news_sentiment_score: null,
    news_headline_count: null,
    news_sentiment_source: null,
    reddit_mention_spike_24h_pct: snapshot.volumeRatio90d == null ? null : round((snapshot.volumeRatio90d - 1) * 100, 1),
    reddit_positive_pct: positiveProxy,
    short_interest_pct: shortInterest,
    institutional_net_shares_last_13f: null,
    institutional_13f_as_of: null,
    institutional_13f_freshness: null,
    freshness: quote ? 'estimated' : 'missing',
  }
}

async function getQuote(symbol) {
  const key = makeCacheKey('quote', symbol)
  const cached = cacheGet(requestCache, key)
  if (cached) return cached
  const payload = await financeQueryGet(`/quote/${encodeURIComponent(normalizeSymbol(symbol))}`, { logo: 'true' })
  const quote = Array.isArray(payload) ? payload[0] : payload
  cacheSet(requestCache, key, quote, 30_000)
  return quote
}

async function getChart(symbol, range = '6mo', interval = '1d') {
  const key = makeCacheKey('chart', symbol, `${range}:${interval}`)
  const cached = cacheGet(requestCache, key)
  if (cached) return cached
  const payload = await financeQueryGet(`/chart/${encodeURIComponent(normalizeSymbol(symbol))}`, {
    range,
    interval,
  })
  const candles = extractCandles(payload)
  cacheSet(requestCache, key, candles, 30_000)
  return candles
}

async function getSnapshot(symbol) {
  const normalized = normalizeSymbol(symbol)
  const key = makeCacheKey('snapshot', normalized)
  const cached = cacheGet(requestCache, key)
  if (cached) return cached
  const [quote, candles] = await Promise.all([getQuote(normalized), getChart(normalized)])
  const snapshot = computeSnapshot(normalized, quote, candles)
  cacheSet(requestCache, key, snapshot, 30_000)
  return snapshot
}

function buildBuyability(snapshot, entry, fundamentals, sentiment, regime) {
  const momentum = clamp(
    50 +
      (snapshot.priceVsMa20Pct ?? 0) * 1.5 +
      (snapshot.priceVsMa200Pct ?? 0) * 1.0 +
      ((snapshot.rsi14 ?? 50) - 50) * 0.6 +
      ((snapshot.volumeRatio90d ?? 1) - 1) * 10,
    0,
    100,
  )
  const sentimentScore = clamp(
    ((sentiment.reddit_positive_pct ?? 50) - 50) / 50 +
      ((sentiment.short_interest_pct ?? 5) < 5 ? 0.2 : 0) +
      ((sentiment.short_interest_pct ?? 5) > 15 ? -0.2 : 0),
    -1,
    1,
  )
  const technicalState =
    snapshot.rsi14 != null && snapshot.rsi14 < 30
      ? 'oversold'
      : snapshot.rsi14 != null && snapshot.rsi14 > 75
        ? 'overextended'
        : entry.breakout_volume_confirmed
          ? 'breakout'
          : snapshot.priceVsMa20Pct != null && Math.abs(snapshot.priceVsMa20Pct) > 8
            ? 'extended'
            : 'neutral'
  const fundamentalState =
    fundamentals.pe_percentile_5y != null && fundamentals.pe_percentile_5y <= 40
      ? 'strong'
      : fundamentals.pe_percentile_5y != null && fundamentals.pe_percentile_5y >= 70
        ? 'weak'
        : 'mixed'
  const confidence = clamp(0.45 + Math.abs((snapshot.priceVsMa20Pct ?? 0) / 100) + (entry.entry_assessment === 'buy_now' ? 0.1 : 0), 0.25, 0.97)
  return {
    symbol: snapshot.symbol,
    trend_score: round(momentum, 1),
    sentiment_score: round(sentimentScore, 2),
    technical_state: technicalState,
    fundamental_state: fundamentalState,
    entry_assessment: entry.entry_assessment,
    ideal_buy_zone: entry.ideal_buy_zone,
    current_price: snapshot.currentPrice,
    data_quality_score: computeDataQuality(snapshot, quoteQuality(fundamentals, sentiment, snapshot)),
    confidence: round(confidence, 2),
    reason: regime === 'risk_off' ? 'Market regime is cautious, so entries need more confirmation.' : entry.reason,
    risk_flags: buildRiskFlags(snapshot, entry, regime),
  }
}

function quoteQuality(fundamentals, sentiment, snapshot) {
  let score = 0
  if (snapshot.currentPrice != null) score += 20
  if (snapshot.ma20 != null) score += 15
  if (snapshot.ma50 != null) score += 10
  if (snapshot.ma200 != null) score += 10
  if (fundamentals.pe_ratio != null) score += 10
  if (fundamentals.revenue_growth_yoy_pct != null) score += 10
  if (sentiment.iv_rank_approx != null) score += 5
  return clamp(score, 0, 100)
}

function computeDataQuality(snapshot, extraScore = 0) {
  const base =
    (snapshot.currentPrice != null ? 20 : 0) +
    (snapshot.ma20 != null ? 10 : 0) +
    (snapshot.ma50 != null ? 10 : 0) +
    (snapshot.ma200 != null ? 10 : 0) +
    (snapshot.rsi14 != null ? 10 : 0) +
    (snapshot.macd.histogram != null ? 10 : 0) +
    (snapshot.supportLevels.length > 0 ? 5 : 0) +
    (snapshot.resistanceLevels.length > 0 ? 5 : 0) +
    (snapshot.quote ? 10 : 0)
  return Math.round(clamp(base + extraScore * 0.1, 0, 100))
}

function buildRiskFlags(snapshot, entry, regime) {
  const flags = []
  if (entry.is_overextended) flags.push('overextended')
  if (snapshot.priceVsMa200Pct != null && snapshot.priceVsMa200Pct < 0) flags.push('below_200d')
  if (snapshot.rsi14 != null && snapshot.rsi14 > 70) flags.push('overbought')
  if (snapshot.volumeRatio90d != null && snapshot.volumeRatio90d < 0.8) flags.push('thin_volume')
  if (regime === 'risk_off') flags.push('risk_off_regime')
  return flags
}

function computeSignalVote(signals) {
  return signals.reduce(
    (accumulator, signal) => {
      accumulator[signal.signal] = (accumulator[signal.signal] ?? 0) + 1
      return accumulator
    },
    { BUY: 0, HOLD: 0, SELL: 0 },
  )
}

function computeWeightedScore(signals) {
  const totalWeight = signals.reduce((sum, signal) => sum + signal.weight, 0) || 1
  const weighted = signals.reduce((sum, signal) => sum + scoreSignal(signal.signal) * signal.weight, 0)
  return weighted / totalWeight
}

function buildRecommendation(snapshot, signals, entry, regime) {
  const score = computeWeightedScore(signals)
  const direction = score > 0.15 ? 'BUY' : score < -0.15 ? 'SELL' : 'HOLD'
  const confidence = clamp(0.5 + Math.abs(score) * 0.45 + (entry.entry_assessment === 'buy_now' ? 0.05 : 0), 0.2, 0.98)
  const riskFlags = buildRiskFlags(snapshot, entry, regime)
  const reviewAction =
    direction === 'BUY' ? 'BUY' : direction === 'SELL' ? 'AVOID' : entry.entry_assessment === 'wait_for_breakout_confirmation' ? 'WATCH' : 'HOLD'
  return {
    direction,
    confidence: round(confidence, 2),
    signal_vote: computeSignalVote(signals),
    technical_vote: { BUY: 0, HOLD: 0, SELL: 0 },
    fundamental_vote: { BUY: 0, HOLD: 0, SELL: 0 },
    sentiment_vote: { BUY: 0, HOLD: 0, SELL: 0 },
    macro_vote: { BUY: 0, HOLD: 0, SELL: 0 },
    conflict_detected: false,
    conflict_summary: null,
    weighted_score: round(score, 3),
    technical_target_high: round((snapshot.resistanceLevels[0] ?? snapshot.currentPrice ?? 0) * 1.05, 2),
    technical_target_low: round((snapshot.supportLevels[0] ?? snapshot.currentPrice ?? 0) * 0.97, 2),
    stop_loss_suggestion: entry.stop_loss_suggestion,
    horizon: '2-4W',
    review_action: reviewAction,
    risk_flags: riskFlags,
  }
}

function buildAnalysisResponse({ symbol, snapshot, entry, fibonacci, confluence, fundamentals, sentiment, macro, signals, recommendation, includeNarrative = false }) {
  const dataFreshness = {
    price: 'live',
    technicals: 'live',
    fundamentals: fundamentals.freshness ?? 'estimated',
    ratings: fundamentals.freshness ?? 'estimated',
    flows: sentiment.freshness ?? 'estimated',
    sentiment: sentiment.freshness ?? 'estimated',
    macro: macro.freshness ?? 'missing',
  }
  const dataQualityScore = computeDataQuality(snapshot)
  const narrative = includeNarrative
    ? `${symbol} is ${recommendation.direction === 'BUY' ? 'constructive' : recommendation.direction === 'SELL' ? 'fragile' : 'mixed'} with RSI ${snapshot.rsi14 != null ? Math.round(snapshot.rsi14) : 'n/a'} and ${snapshot.priceVsMa20Pct != null ? `${round(snapshot.priceVsMa20Pct, 1)}% vs 20D` : 'limited moving-average context'}.`
    : null

  return {
    symbol,
    company_name: snapshot.companyName,
    generated_at: new Date().toISOString(),
    data_freshness: dataFreshness,
    data_quality_score: dataQualityScore,
    confidence: recommendation.confidence,
    technicals: {
      rsi_14: snapshot.rsi14 == null ? null : round(snapshot.rsi14, 2),
      rsi_weekly: snapshot.weeklyRsi == null ? null : round(snapshot.weeklyRsi, 2),
      macd: {
        macd_line: snapshot.macd.macdLine == null ? null : round(snapshot.macd.macdLine, 4),
        signal_line: snapshot.macd.signalLine == null ? null : round(snapshot.macd.signalLine, 4),
        histogram: snapshot.macd.histogram == null ? null : round(snapshot.macd.histogram, 4),
      },
      ma_20: snapshot.ma20 == null ? null : round(snapshot.ma20, 2),
      ma_50: snapshot.ma50 == null ? null : round(snapshot.ma50, 2),
      ma_200: snapshot.ma200 == null ? null : round(snapshot.ma200, 2),
      support_levels: snapshot.supportLevels.slice(0, 3).map((value) => round(value, 2)),
      resistance_levels: snapshot.resistanceLevels.slice(0, 3).map((value) => round(value, 2)),
      atr_14: snapshot.atr14 == null ? null : round(snapshot.atr14, 2),
      bb_upper: snapshot.bbUpper == null ? null : round(snapshot.bbUpper, 2),
      bb_lower: snapshot.bbLower == null ? null : round(snapshot.bbLower, 2),
      bb_mid: snapshot.bbMid == null ? null : round(snapshot.bbMid, 2),
      volume_ratio_90d: snapshot.volumeRatio90d,
      dist_from_ma20_pct: snapshot.priceVsMa20Pct == null ? null : round(snapshot.priceVsMa20Pct, 2),
      dist_from_ma50_pct: snapshot.priceVsMa50Pct == null ? null : round(snapshot.priceVsMa50Pct, 2),
      dist_from_ma200_pct: snapshot.priceVsMa200Pct == null ? null : round(snapshot.priceVsMa200Pct, 2),
      recent_gap_pct: snapshot.recentGapPct == null ? null : round(snapshot.recentGapPct, 2),
      recent_earnings_gap_pct: null,
      breakout_state: entry.breakout_volume_confirmed ? 'breakout' : snapshot.currentPrice != null && snapshot.ma20 != null && snapshot.currentPrice > snapshot.ma20 ? 'trending' : 'none',
    },
    fundamentals,
    sentiment,
    macro,
    signals,
    entry,
    recommendation,
    narrative,
  }
}

async function getRegimeSnapshot() {
  const key = 'market-regime'
  const cached = cacheGet(requestCache, key)
  if (cached) return cached

  const [spySnapshot, vixQuote] = await Promise.all([
    getSnapshot('SPY').catch(() => null),
    getQuote('^VIX').catch(() => null),
  ])
  const marketRegime = estimateMarketRegimeFromSnapshot(spySnapshot, vixQuote)
  const dataQualityScore = spySnapshot ? computeDataQuality(spySnapshot) : 40
  const result = {
    market_regime: marketRegime,
    generated_at: new Date().toISOString(),
    data_freshness: {
      price: spySnapshot ? 'live' : 'missing',
      technicals: spySnapshot ? 'live' : 'missing',
      fundamentals: 'missing',
      sentiment: 'missing',
      macro: vixQuote ? 'estimated' : 'missing',
    },
    data_quality_score: dataQualityScore,
    confidence: spySnapshot?.priceVsMa200Pct != null ? clamp(0.55 + Math.abs(spySnapshot.priceVsMa200Pct) / 100, 0.3, 0.95) : 0.5,
    sector_leaders: ['XLK', 'XLY', 'XLV'],
    sector_laggards: ['XLE', 'XLF', 'XLP'],
    reason:
      marketRegime === 'risk_on'
        ? 'SPY is above its long-term trend and VIX is subdued.'
        : marketRegime === 'risk_off'
          ? 'SPY weakness and/or elevated VIX suggest a defensive regime.'
          : 'Mixed trend and volatility keep the regime neutral.',
  }
  cacheSet(requestCache, key, result, 60_000)
  return result
}

async function resolvePutCallRatio(symbol, env = {}) {
  const symbolKey = makeCacheKey('put_call_ratio', symbol)
  const marketKey = makeCacheKey('put_call_ratio', 'market')
  const cachedSymbol = cacheGet(requestCache, symbolKey)
  if (cachedSymbol != null) return cachedSymbol
  const cachedMarket = cacheGet(requestCache, marketKey)
  if (cachedMarket != null) return cachedMarket
  const apiKey = env?.ALPHA_VANTAGE_KEY ?? env?.ALPHA_VANTAGE_API_KEY ?? null
  const alphaVantageRatio = await fetchAlphaVantagePutCallRatio(symbol, apiKey)
  const ratio = alphaVantageRatio ?? (await fetchCboeMarketPutCallRatio())
  if (ratio != null) {
    cacheSet(requestCache, symbolKey, ratio, 6 * 60 * 60 * 1000)
    cacheSet(requestCache, marketKey, ratio, 6 * 60 * 60 * 1000)
  }
  return ratio
}

async function buildAnalyze(symbol, { includeNarrative = false, includeEntry = true, lookbackDays = 90, env = {} } = {}) {
  const normalized = normalizeSymbol(symbol)
  const regime = await getRegimeSnapshot()
  const [snapshot, quote] = await Promise.all([getSnapshot(normalized), getQuote(normalized).catch(() => null)])
  const fundamentals = buildFundamentals(quote, snapshot)
  const putCallRatio = await resolvePutCallRatio(normalized, env)
  const sentiment = buildSentiment(quote, snapshot, putCallRatio)
  const [macroQuote, vixQuote] = await Promise.all([
    getQuote('^TNX').catch(() => null),
    getQuote('^VIX').catch(() => null),
  ])
  const macro = {
    days_to_next_fomc: null,
    next_fomc_date: null,
    rate_cut_probability_pct: null,
    rate_cut_probability_source: null,
    treasury_10y: macroQuote?.regularMarketPrice != null ? round(Number(macroQuote.regularMarketPrice) / 10, 2) : null,
    vix: vixQuote?.regularMarketPrice != null ? round(Number(vixQuote.regularMarketPrice), 2) : null,
    freshness: 'estimated',
    market_regime: regime.market_regime,
  }
  const entry = buildEntry(snapshot, regime.market_regime)
  const fibonacci = buildFibonacci(snapshot, lookbackDays)
  const confluence = buildConfluence(snapshot, entry, fibonacci)
  const signals = buildSignals(snapshot, entry, fundamentals, sentiment, macro)
  const recommendation = buildRecommendation(snapshot, signals, entry, regime.market_regime)
  return buildAnalysisResponse({
    symbol: normalized,
    snapshot,
    entry,
    fibonacci,
    confluence,
    fundamentals,
    sentiment,
    macro,
    signals,
    recommendation,
    includeNarrative,
  })
}

function scoreForScreen(snapshot, regime) {
  const valuationScore = clamp(
    100 - (estimatePePercentile(snapshot.quote?.trailingPE ?? snapshot.quote?.forwardPE) ?? 55),
    0,
    100,
  )
  const momentumScore = clamp(
    50 +
      (snapshot.priceVsMa20Pct ?? 0) * 1.2 +
      (snapshot.priceVsMa50Pct ?? 0) * 0.8 +
      ((snapshot.rsi14 ?? 50) - 50) * 0.7,
    0,
    100,
  )
  const qualityScore = clamp(
    45 +
      ((snapshot.volumeRatio90d ?? 1) - 1) * 10 +
      ((snapshot.priceVsMa200Pct ?? 0) > 0 ? 10 : -10) +
      ((snapshot.ma50 != null && snapshot.ma200 != null && snapshot.ma50 > snapshot.ma200) ? 10 : -5),
    0,
    100,
  )
  const growthScore = clamp(
    45 +
      (snapshot.recent60Slope ?? 0) * 0.5 +
      ((snapshot.priceVsMa20Pct ?? 0) * 0.8) +
      ((snapshot.rsi14 ?? 50) - 50) * 0.25,
    0,
    100,
  )
  const analystRevisionScore = clamp(50 + ((snapshot.priceVsMa20Pct ?? 0) * 0.4), 0, 100)
  const institutionalAccumulationScore = clamp(50 + ((snapshot.volumeRatio90d ?? 1) - 1) * 20, 0, 100)
  const insiderActivityScore = 50
  const riskScore = clamp(
    100 -
      ((snapshot.priceVsMa200Pct ?? 0) > 0 ? 20 : 45) -
      ((snapshot.rsi14 ?? 50) > 70 ? 20 : 0) -
      ((snapshot.volumeRatio90d ?? 1) < 0.8 ? 10 : 0),
    0,
    100,
  )

  const weights = SCORING_WEIGHTS.opportunity
  const regimeAdjustments = SCORING_WEIGHTS.regimeAdjustments[regime] ?? {}
  const opportunityScore =
    valuationScore * weights.valuation +
    growthScore * weights.growth +
    qualityScore * weights.quality +
    momentumScore * (weights.momentum + (regimeAdjustments.momentum ?? 0)) +
    analystRevisionScore * weights.analystRevision +
    institutionalAccumulationScore * weights.institutionalAccumulation +
    insiderActivityScore * weights.insiderActivity +
    (100 - riskScore) * weights.risk +
    (regimeAdjustments.quality ?? 0) * qualityScore +
    (regimeAdjustments.growth ?? 0) * growthScore +
    (regimeAdjustments.risk ?? 0) * (100 - riskScore)

  return {
    opportunityScore: clamp(round(opportunityScore, 1) ?? opportunityScore, 0, 100),
    valuationScore,
    growthScore,
    qualityScore,
    momentumScore,
    analystRevisionScore,
    institutionalAccumulationScore,
    insiderActivityScore,
    riskScore,
  }
}

function screenRecommendation(score) {
  if (score >= SCREENER_THRESHOLDS.buyScore) return 'BUY'
  if (score <= SCREENER_THRESHOLDS.sellScore) return 'SELL'
  return 'HOLD'
}

function screenAction(score) {
  if (score >= SCREENER_THRESHOLDS.analyzeDeeperScore) return 'ANALYZE'
  if (score >= SCREENER_THRESHOLDS.watchScore) return 'WATCH'
  return 'PASS'
}

function buildScreenResult(snapshot, marketRegime, screenType, rank) {
  const regime = marketRegime
  const score = scoreForScreen(snapshot, regime)
  const recommendation = screenRecommendation(score.opportunityScore)
  const entry = buildEntry(snapshot, regime)
  const buyability = buildBuyability(snapshot, entry, buildFundamentals(snapshot.quote, snapshot), buildSentiment(snapshot.quote, snapshot), regime)
  const riskFlags = buildRiskFlags(snapshot, entry, regime)
  const reasonParts = []
  if (snapshot.priceVsMa20Pct != null) reasonParts.push(`20D ${round(snapshot.priceVsMa20Pct, 1)}%`)
  if (snapshot.priceVsMa200Pct != null) reasonParts.push(`200D ${round(snapshot.priceVsMa200Pct, 1)}%`)
  if (snapshot.rsi14 != null) reasonParts.push(`RSI ${Math.round(snapshot.rsi14)}`)
  if (snapshot.volumeRatio90d != null) reasonParts.push(`vol ${round(snapshot.volumeRatio90d, 2)}x`)
  return {
    rank,
    symbol: snapshot.symbol,
    screen_type: screenType,
    opportunity_score: round(score.opportunityScore, 1),
    valuation_score: round(score.valuationScore, 1),
    growth_score: round(score.growthScore, 1),
    quality_score: round(score.qualityScore, 1),
    momentum_score: round(score.momentumScore, 1),
    analyst_revision_score: round(score.analystRevisionScore, 1),
    institutional_accumulation_score: round(score.institutionalAccumulationScore, 1),
    insider_activity_score: round(score.insiderActivityScore, 1),
    risk_score: round(score.riskScore, 1),
    score_breakdown: {
      opportunity_score: round(score.opportunityScore, 1),
      trend_score: round(score.momentumScore, 1),
      valuation_score: round(score.valuationScore, 1),
      growth_score: round(score.growthScore, 1),
      quality_score: round(score.qualityScore, 1),
      risk_score: round(score.riskScore, 1),
      price_vs_ma20_pct: snapshot.priceVsMa20Pct,
      price_vs_ma200_pct: snapshot.priceVsMa200Pct,
      rsi_14: snapshot.rsi14,
      volume_ratio_90d: snapshot.volumeRatio90d,
    },
    data_freshness: {
      price: 'live',
      technicals: 'live',
      fundamentals: snapshot.quote ? 'estimated' : 'missing',
      sentiment: snapshot.quote ? 'estimated' : 'missing',
      macro: 'missing',
    },
    data_quality_score: computeDataQuality(snapshot),
    confidence: round(clamp(score.opportunityScore / 100, 0.15, 0.98), 2),
    reason: reasonParts.join(' · ') || 'Edge screen derived from price trend and valuation heuristics.',
    recommended_action: screenAction(score.opportunityScore),
    risk_flags: riskFlags,
    recommendation,
    entry_assessment: entry.entry_assessment,
    ideal_buy_zone: entry.ideal_buy_zone,
    summary: snapshot.companyName ?? snapshot.symbol,
    revenue_accel_pct: snapshot.recent60Slope == null ? null : round(snapshot.recent60Slope, 1),
    analyst_upgrades_30d: null,
    margin_expansion_bps: null,
    components: {
      quote: snapshot.quote,
      buyability,
    },
  }
}

async function buildScreenResponse(screenType, requestBody) {
  const universeName = normalizeUniverse(requestBody?.universe)
  const tickers = Array.isArray(requestBody?.tickers) && requestBody.tickers.length > 0
    ? requestBody.tickers.map(normalizeSymbol)
    : [...(UNIVERSES[universeName] ?? [])]

  const symbols = tickers.slice(0, requestBody?.limit ?? 25)
  const regime = (await getRegimeSnapshot()).market_regime
  const snapshots = []
  for (const symbol of symbols) {
    try {
      snapshots.push(await getSnapshot(symbol))
    } catch {
      continue
    }
  }

  const results = snapshots
    .map((snapshot, index) => buildScreenResult(snapshot, regime, screenType, index + 1))
    .sort((left, right) => right.opportunity_score - left.opportunity_score)
    .slice(0, requestBody?.limit ?? 25)
    .map((result, index) => ({ ...result, rank: index + 1 }))

  const averageConfidence =
    results.length === 0 ? 0.5 : round(results.reduce((sum, item) => sum + item.confidence, 0) / results.length, 2)
  return {
    screen_type: screenType,
    generated_at: new Date().toISOString(),
    universe: universeName,
    market_regime: regime,
    data_quality_score:
      results.length === 0 ? 40 : Math.round(results.reduce((sum, item) => sum + item.data_quality_score, 0) / results.length),
    confidence: averageConfidence,
    data_freshness: {
      price: results.length > 0 ? 'live' : 'missing',
      technicals: results.length > 0 ? 'live' : 'missing',
      fundamentals: results.length > 0 ? 'estimated' : 'missing',
      sentiment: results.length > 0 ? 'estimated' : 'missing',
      macro: 'missing',
    },
    results,
    notes: [
      universeName === 'CUSTOM' && !requestBody?.tickers?.length
        ? 'No custom tickers supplied, so this screen is empty.'
        : 'Edge screen uses finance-query price data and heuristic scoring because the Render runtime is suspended.',
    ],
  }
}

async function buildTrendingResponse(requestBody) {
  const universeName = normalizeUniverse(requestBody?.universe)
  const tickers = Array.isArray(requestBody?.tickers) && requestBody.tickers.length > 0
    ? requestBody.tickers.map(normalizeSymbol)
    : [...(UNIVERSES[universeName] ?? [])]
  const regime = (await getRegimeSnapshot()).market_regime
  const limit = requestBody?.limit ?? 25
  const snapshots = []
  for (const symbol of tickers.slice(0, limit)) {
    try {
      snapshots.push(await getSnapshot(symbol))
    } catch {
      continue
    }
  }

  const results = snapshots
    .map((snapshot) => {
      const mention24h = Math.max(1, Math.round((snapshot.volumeRatio90d ?? 1) * 4 + Math.abs(snapshot.recentGapPct ?? 0)))
      const mention3d = Math.max(mention24h + 2, Math.round(mention24h * 1.6))
      const mention5d = Math.max(mention3d + 2, Math.round(mention3d * 1.3))
      const sentimentScore = clamp(
        ((snapshot.priceVsMa20Pct ?? 0) / 10) + ((snapshot.rsi14 ?? 50) - 50) / 50 + ((snapshot.volumeRatio90d ?? 1) - 1),
        -1,
        1,
      )
      const trendScore = clamp(
        50 +
          (snapshot.priceVsMa20Pct ?? 0) * 1.2 +
          (snapshot.priceVsMa50Pct ?? 0) * 0.7 +
          ((snapshot.rsi14 ?? 50) - 50) * 0.5 +
          ((snapshot.volumeRatio90d ?? 1) - 1) * 15,
        0,
        100,
      )
      const entry = buildEntry(snapshot, regime)
      const buyability = buildBuyability(snapshot, entry, buildFundamentals(snapshot.quote, snapshot), buildSentiment(snapshot.quote, snapshot), regime)
      const accel = round((mention5d / Math.max(mention3d, 1)) * 100, 1)
      const trendQuality =
        trendScore >= 75
          ? 'high_quality_trend'
          : mention5d >= 10 && sentimentScore >= 0.25
            ? 'news_driven_trend'
            : snapshot.rsi14 != null && snapshot.rsi14 > 75
              ? 'too_late_overextended'
              : 'early_accumulation'
      return {
        symbol: snapshot.symbol,
        screen_type: 'trending',
        mention_count_24h: mention24h,
        mention_count_3d: mention3d,
        mention_count_5d: mention5d,
        mention_growth_3d_pct: round(((mention3d - mention24h) / Math.max(mention24h, 1)) * 100, 1),
        mention_growth_5d_pct: round(((mention5d - mention24h) / Math.max(mention24h, 1)) * 100, 1),
        baseline_daily_mentions_30d: round(mention24h / 1.5, 1),
        acceleration: accel,
        sentiment_score: round(sentimentScore, 2),
        sentiment_change: round(sentimentScore * 0.35, 2),
        pos_neu_neg_ratio: [
          clamp(round(50 + sentimentScore * 30, 1), 0, 100),
          clamp(round(30 - Math.abs(sentimentScore) * 10, 1), 0, 100),
          clamp(round(20 - sentimentScore * 20, 1), 0, 100),
        ],
        retail_fomo_risk: round(clamp(mention5d / 2 + Math.max(0, snapshot.priceVsMa20Pct ?? 0), 0, 100), 1),
        news_catalyst: snapshot.recentGapPct != null && snapshot.recentGapPct > 0 ? 'price momentum' : 'none',
        trend_quality: trendQuality,
        institutional_account_participation: snapshot.volumeRatio90d == null ? null : round(clamp(snapshot.volumeRatio90d * 20, 0, 100), 1),
        data_freshness: {
          price: 'live',
          technicals: 'live',
          fundamentals: snapshot.quote ? 'estimated' : 'missing',
          sentiment: 'estimated',
          macro: 'missing',
        },
        data_quality_score: computeDataQuality(snapshot),
        confidence: round(clamp(0.5 + trendScore / 200, 0.25, 0.98), 2),
        risk_flags: buildRiskFlags(snapshot, entry, regime),
        reason: `${snapshot.symbol} is trading ${snapshot.priceVsMa20Pct != null ? `${round(snapshot.priceVsMa20Pct, 1)}%` : 'near'} its 20D average with ${snapshot.volumeRatio90d != null ? `${round(snapshot.volumeRatio90d, 2)}x` : 'normal'} volume.`,
        score_breakdown: {
          trend_score: round(trendScore, 1),
          sentiment_score: round(sentimentScore, 2),
          mention_count_24h: mention24h,
          mention_count_3d: mention3d,
          mention_count_5d: mention5d,
          acceleration: accel,
          price_vs_ma20_pct: snapshot.priceVsMa20Pct,
          price_vs_ma50_pct: snapshot.priceVsMa50Pct,
        },
        buyability,
      }
    })
    .sort((left, right) => right.score_breakdown.trend_score - left.score_breakdown.trend_score)
    .slice(0, limit)

  return {
    screen_type: 'trending',
    generated_at: new Date().toISOString(),
    universe: universeName,
    market_regime: regime,
    data_quality_score:
      results.length === 0 ? 40 : Math.round(results.reduce((sum, item) => sum + item.data_quality_score, 0) / results.length),
    confidence: results.length === 0 ? 0.5 : round(results.reduce((sum, item) => sum + item.confidence, 0) / results.length, 2),
    data_freshness: {
      price: results.length > 0 ? 'live' : 'missing',
      technicals: results.length > 0 ? 'live' : 'missing',
      fundamentals: results.length > 0 ? 'estimated' : 'missing',
      sentiment: results.length > 0 ? 'estimated' : 'missing',
      macro: 'missing',
    },
    results,
    notes: ['Trending is approximated from price momentum and volume because social feeds are not part of the free edge slice.'],
  }
}

async function buildHealthResponse(serviceName, sharedSpacesState = 'disabled') {
  const key = serviceName
  const cached = cacheGet(healthCache, key)
  if (cached) return cached

  const [lookup, quote, chart] = await Promise.all([
    financeQueryGet('/lookup', { q: 'NVDA' }).catch(() => null),
    getQuote('NVDA').catch(() => null),
    getChart('NVDA').catch(() => null),
  ])

  const providers = {
    finance_query: quote && chart ? 'ok' : 'degraded',
    yahoo_lookup: lookup && Array.isArray(lookup.quotes) ? 'ok' : 'degraded',
    alpha_vantage: 'not_configured',
    redis: 'not_available',
    shared_spaces: sharedSpacesState,
  }

  const result = {
    status: 'ok',
    service: serviceName,
    config_valid: true,
    providers,
    llm_available: false,
    cache_backend: 'edge-memory',
  }
  cacheSet(healthCache, key, result, 60_000)
  return result
}

function badRequest(message) {
  return jsonCors({ detail: message }, 400)
}

async function readJson(request) {
  try {
    return await request.json()
  } catch {
    return null
  }
}

async function handleSharedSpaceUnavailability(pathname) {
  return jsonCors(
    {
      detail: `Shared-space route ${pathname} is not available in the free edge slice yet.`,
    },
    503,
  )
}

async function handleScreenRoute(pathname, request, env = {}) {
  if (pathname === '/screen/health') {
    return jsonCors(await buildHealthResponse('finance_api_worker', getSharedSpaceConfig(env) && env.SHARED_WATCHLIST_SPACE ? 'configured' : 'disabled'))
  }
  if (pathname === '/screen/regime') {
    return jsonCors(await getRegimeSnapshot())
  }

  const body = request.method === 'POST' ? await readJson(request) : null
  if (pathname === '/screen/undervalued' || pathname === '/screen/opportunities' || pathname === '/screen/watchlist' || pathname === '/screen/custom' || pathname === '/screen/demand-shock') {
    const screenType =
      pathname === '/screen/demand-shock'
        ? 'demand_shock'
        : pathname === '/screen/opportunities'
          ? 'opportunities'
          : pathname === '/screen/watchlist'
            ? 'watchlist'
            : pathname === '/screen/custom'
              ? 'custom'
              : 'undervalued'
    return jsonCors(await buildScreenResponse(screenType, body))
  }
  if (pathname === '/screen/trending') {
    return jsonCors(await buildTrendingResponse(body))
  }
  return jsonCors({ detail: `Unhandled screen route ${pathname}` }, 404)
}

async function handleAnalyzeRoute(pathname, request, env = {}) {
  if (pathname === '/health') {
    return jsonCors(await buildHealthResponse('finance_api_worker', getSharedSpaceConfig(env) && env.SHARED_WATCHLIST_SPACE ? 'configured' : 'disabled'))
  }
  if (pathname === '/search' && request.method === 'GET') {
    const url = new URL(request.url)
    const q = normalizeSymbol(url.searchParams.get('q'))
    const limit = Math.max(1, Math.min(20, Number(url.searchParams.get('limit') ?? 6)))
    if (!q) return jsonCors([])
    try {
      const payload = await financeQueryGet('/lookup', { q, limit })
      const quotes = Array.isArray(payload?.quotes) ? payload.quotes : []
      return jsonCors(
        quotes
          .filter((quote) => quote?.symbol)
          .slice(0, limit)
          .map((quote) => ({
            symbol: quote.symbol,
            name: quote.longName ?? quote.shortName ?? quote.name ?? '',
            exchange: quote.exchange ?? '',
            type: quote.quoteType ?? '',
          })),
      )
    } catch {
      return jsonCors([])
    }
  }
  if (pathname === '/analyze' && request.method === 'POST') {
    const body = await readJson(request)
    if (!body?.symbol) return badRequest('symbol is required')
    const response = await buildAnalyze(body.symbol, {
      includeNarrative: body.include_narrative !== false,
      includeEntry: body.include_entry !== false,
      lookbackDays: body.lookback_days ?? 90,
      env,
    })
    return jsonCors(response)
  }
  if (pathname === '/batch' && request.method === 'POST') {
    const body = await readJson(request)
    const symbols = Array.isArray(body?.symbols) ? body.symbols.map(normalizeSymbol).filter(Boolean) : []
    const responses = []
    for (const symbol of symbols.slice(0, 20)) {
      try {
        responses.push(
          await buildAnalyze(symbol, {
            includeNarrative: body?.include_narrative !== false,
            includeEntry: body?.include_entry !== false,
            env,
          }),
        )
      } catch {
        continue
      }
    }
    return jsonCors(responses)
  }
  if (pathname === '/entry' && request.method === 'POST') {
    const body = await readJson(request)
    if (!body?.symbol) return badRequest('symbol is required')
    const analysis = await buildAnalyze(body.symbol, {
      includeNarrative: false,
      includeEntry: true,
      env,
    })
    if (!analysis.entry) {
      return jsonCors({ detail: 'entry block was not generated' }, 422)
    }
    return jsonCors({
      ...analysis.entry,
      data_freshness: { price: analysis.data_freshness.price },
      data_quality_score: analysis.data_quality_score,
    })
  }
  if (pathname === '/entry/confluence' && request.method === 'POST') {
    const body = await readJson(request)
    if (!body?.symbol) return badRequest('symbol is required')
    const normalized = normalizeSymbol(body.symbol)
    const lookbackDays = body.lookback_days ?? 90
    const snapshot = await getSnapshot(normalized)
    const entry = buildEntry(snapshot, (await getRegimeSnapshot()).market_regime)
    const fibonacci = buildFibonacci(snapshot, lookbackDays)
    const confluence = buildConfluence(snapshot, entry, fibonacci)
    const fundamentals = buildFundamentals(await getQuote(normalized).catch(() => null), snapshot)
    const putCallRatio = await resolvePutCallRatio(normalized, env)
    const sentiment = buildSentiment(await getQuote(normalized).catch(() => null), snapshot, putCallRatio)
    const macroRegime = await getRegimeSnapshot()
    const macroVix = await getQuote('^VIX').catch(() => null)
    const macroTnx = await getQuote('^TNX').catch(() => null)
    const macro = {
      days_to_next_fomc: null,
      next_fomc_date: null,
      rate_cut_probability_pct: null,
      rate_cut_probability_source: null,
      treasury_10y: macroTnx?.regularMarketPrice != null ? round(Number(macroTnx.regularMarketPrice) / 10, 2) : null,
      vix: macroVix?.regularMarketPrice != null ? round(Number(macroVix.regularMarketPrice), 2) : null,
      freshness: 'estimated',
      market_regime: macroRegime.market_regime,
    }
    const signals = buildSignals(snapshot, entry, fundamentals, sentiment, macro)
    const recommendation = buildRecommendation(snapshot, signals, entry, macroRegime.market_regime)
    return jsonCors({
      symbol: normalized,
      generated_at: new Date().toISOString(),
      current_price: entry.current_price ?? null,
      classical: entry,
      fibonacci,
      confluence,
      data_freshness: {
        price: 'live',
        technicals: 'live',
        fundamentals: fundamentals.freshness ?? 'estimated',
        ratings: fundamentals.freshness ?? 'estimated',
        flows: sentiment.freshness ?? 'estimated',
        sentiment: sentiment.freshness ?? 'estimated',
        macro: macro.freshness,
      },
      data_quality_score: computeDataQuality(snapshot),
    })
  }
  if (pathname.startsWith('/entry/confluence/') && request.method === 'GET') {
    const symbol = pathname.split('/').at(-1)
    if (!symbol) return badRequest('symbol is required')
    const normalized = normalizeSymbol(symbol)
    const snapshot = await getSnapshot(normalized)
    const entry = buildEntry(snapshot, (await getRegimeSnapshot()).market_regime)
    const lookbackDays = 90
    const fibonacci = buildFibonacci(snapshot, lookbackDays)
    const confluence = buildConfluence(snapshot, entry, fibonacci)
    return jsonCors({
      symbol: normalized,
      generated_at: new Date().toISOString(),
      current_price: entry.current_price ?? null,
      classical: entry,
      fibonacci,
      confluence,
      data_freshness: {
        price: 'live',
        technicals: 'live',
        fundamentals: 'estimated',
        ratings: 'estimated',
        flows: 'estimated',
        sentiment: 'estimated',
        macro: 'missing',
      },
      data_quality_score: computeDataQuality(snapshot),
    })
  }
  return jsonCors({ detail: `Unhandled analyst route ${pathname}` }, 404)
}

function normalizeSharedSpaceSlug(value) {
  return String(value ?? '').trim().toLowerCase()
}

function getSharedSpaceConfig(env = {}) {
  const slug = normalizeSharedSpaceSlug(env.SHARED_WATCHLIST_SLUG)
  const displayName = String(env.SHARED_WATCHLIST_DISPLAY_NAME ?? '').trim()
  const passcode = String(env.SHARED_WATCHLIST_PASSCODE ?? '').trim()
  const sessionSecret = String(env.SHARED_WATCHLIST_SESSION_SECRET ?? '').trim()
  const sessionMaxAge = Number(env.SHARED_WATCHLIST_SESSION_MAX_AGE ?? 30 * 24 * 60 * 60)
  if (!slug || !passcode || !sessionSecret) {
    return null
  }
  return {
    slug,
    displayName: displayName || slug.replace(/[-_]+/g, ' ').replace(/\b\w/g, (character) => character.toUpperCase()),
    passcode,
    sessionSecret,
    sessionMaxAge: Number.isFinite(sessionMaxAge) && sessionMaxAge > 0 ? sessionMaxAge : 30 * 24 * 60 * 60,
  }
}

function base64UrlEncode(bytes) {
  let binary = ''
  for (const byte of bytes) {
    binary += String.fromCharCode(byte)
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
}

function base64UrlDecode(value) {
  const normalized = String(value ?? '').replace(/-/g, '+').replace(/_/g, '/')
  const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4)
  const binary = atob(padded)
  return Uint8Array.from(binary, (character) => character.charCodeAt(0))
}

async function importSharedSpaceKey(secret) {
  const cacheKey = `hmac:${secret}`
  if (sharedSpaceKeyCache.has(cacheKey)) {
    return sharedSpaceKeyCache.get(cacheKey)
  }
  const key = await crypto.subtle.importKey(
    'raw',
    sharedSpaceTextEncoder.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign', 'verify'],
  )
  sharedSpaceKeyCache.set(cacheKey, key)
  return key
}

async function buildSharedSpaceSessionCookie(slug, secret, maxAge) {
  const payload = {
    exp: Math.floor(Date.now() / 1000) + maxAge,
    slug,
  }
  const payloadBytes = sharedSpaceTextEncoder.encode(JSON.stringify(payload))
  const key = await importSharedSpaceKey(secret)
  const signature = new Uint8Array(await crypto.subtle.sign('HMAC', key, payloadBytes))
  return `${base64UrlEncode(payloadBytes)}.${base64UrlEncode(signature)}`
}

function readSharedSpaceSessionCookieToken(value) {
  const raw = String(value ?? '')
  const match = raw.match(/(?:^|;\s*)shared_space_session=([^;]+)/)
  return match?.[1] ?? null
}

function readSharedSpaceAuthorizationToken(value) {
  const match = String(value ?? '').match(/^Bearer\s+(.+)$/i)
  return match?.[1]?.trim() || null
}

async function readSharedSpaceSessionToken(token, secret) {
  const rawToken = String(token ?? '').trim()
  if (!rawToken || !rawToken.includes('.')) {
    return null
  }
  const [payloadValue, signatureValue] = rawToken.split('.', 2)
  try {
    const payloadBytes = base64UrlDecode(payloadValue)
    const signatureBytes = base64UrlDecode(signatureValue)
    const key = await importSharedSpaceKey(secret)
    const verified = await crypto.subtle.verify('HMAC', key, signatureBytes, payloadBytes)
    if (!verified) {
      return null
    }
    const payload = JSON.parse(sharedSpaceTextDecoder.decode(payloadBytes))
    if (typeof payload?.slug !== 'string' || typeof payload?.exp !== 'number') {
      return null
    }
    if (payload.exp < Math.floor(Date.now() / 1000)) {
      return null
    }
    return payload.slug
  } catch {
    return null
  }
}

async function readSharedSpaceAuthentication(request, secret) {
  const authorizationToken = readSharedSpaceAuthorizationToken(request.headers.get('authorization'))
  const authorizationSlug = await readSharedSpaceSessionToken(authorizationToken, secret)
  if (authorizationSlug) {
    return { slug: authorizationSlug, token: authorizationToken }
  }

  const cookieToken = readSharedSpaceSessionCookieToken(request.headers.get('cookie'))
  const cookieSlug = await readSharedSpaceSessionToken(cookieToken, secret)
  if (cookieSlug) {
    return { slug: cookieSlug, token: cookieToken }
  }

  return { slug: null, token: null }
}

function sharedSpaceResponsePayload(config, authenticated, sessionToken = null) {
  return {
    authenticated,
    slug: config.slug,
    display_name: config.displayName,
    session_token: authenticated ? sessionToken : null,
  }
}

async function sharedSpaceSessionResponse(config, authenticated, sessionToken = null) {
  return json(sharedSpaceResponsePayload(config, authenticated, sessionToken))
}

async function sharedSpaceWatchlistResponse(config, state) {
  const entries = await readSharedWatchlistEntries(state)
  return json({
    slug: config.slug,
    display_name: config.displayName,
    symbols: entries.map((entry) => entry.symbol),
    entries,
  })
}

function sharedSpaceCookieOptions(request, slug, maxAge) {
  const forwardedProto = (request.headers.get('x-forwarded-proto') ?? '').split(',', 1)[0].trim().toLowerCase()
  const secure = forwardedProto ? forwardedProto === 'https' : new URL(request.url).protocol === 'https:'
  return {
    httponly: true,
    max_age: maxAge,
    path: `/shared-spaces/${slug}`,
    samesite: secure ? 'none' : 'lax',
    secure,
  }
}

function appendSharedSpaceCookie(response, name, value, options) {
  const parts = [`${name}=${value}`]
  if (options.max_age != null) parts.push(`Max-Age=${options.max_age}`)
  if (options.path) parts.push(`Path=${options.path}`)
  if (options.samesite) {
    const sameSite = String(options.samesite)
    parts.push(`SameSite=${sameSite.charAt(0).toUpperCase()}${sameSite.slice(1)}`)
  }
  if (options.secure) parts.push('Secure')
  if (options.httponly) parts.push('HttpOnly')
  response.headers.set('set-cookie', parts.join('; '))
  return response
}

function clearSharedSpaceCookie(response, name, path) {
  response.headers.set(
    'set-cookie',
    `${name}=; Max-Age=0; Path=${path}; Expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax; HttpOnly`,
  )
  return response
}

async function readSharedSpaceSymbols(state) {
  const symbols = await state.storage.get('symbols')
  return Array.isArray(symbols) ? symbols : []
}

function normalizeSharedWatchlistSummary(summary) {
  const normalizedConfidence = summary?.confidence == null ? null : Number(summary.confidence)
  const normalizedDataQualityScore = summary?.data_quality_score == null ? null : Number(summary.data_quality_score)
  const normalizedCurrentPrice = summary?.current_price == null ? null : Number(summary.current_price)
  const rawLastAnalyzedAt = typeof summary?.last_analyzed_at === 'string' ? summary.last_analyzed_at.trim() : ''
  const parsedLastAnalyzedAt = rawLastAnalyzedAt ? new Date(rawLastAnalyzedAt) : null
  return {
    direction: ['BUY', 'HOLD', 'SELL'].includes(summary?.direction) ? summary.direction : null,
    confidence:
      normalizedConfidence != null && Number.isFinite(normalizedConfidence) && normalizedConfidence >= 0 && normalizedConfidence <= 1
        ? normalizedConfidence
        : null,
    data_quality_score:
      normalizedDataQualityScore != null &&
      Number.isInteger(normalizedDataQualityScore) &&
      normalizedDataQualityScore >= 0 &&
      normalizedDataQualityScore <= 100
        ? normalizedDataQualityScore
        : null,
    current_price: normalizedCurrentPrice != null && Number.isFinite(normalizedCurrentPrice) ? normalizedCurrentPrice : null,
    entry_assessment: typeof summary?.entry_assessment === 'string' && summary.entry_assessment.trim() ? summary.entry_assessment.trim() : null,
    last_analyzed_at:
      parsedLastAnalyzedAt && !Number.isNaN(parsedLastAnalyzedAt.getTime()) ? parsedLastAnalyzedAt.toISOString() : null,
  }
}

function hasSharedWatchlistSummary(summary) {
  return Object.values(summary).some((value) => value != null)
}

function normalizeSharedWatchlistSummaries(summaries) {
  if (!summaries || typeof summaries !== 'object') {
    return {}
  }
  const next = {}
  for (const [symbol, summary] of Object.entries(summaries)) {
    const normalizedSymbol = normalizeSymbol(symbol)
    if (!normalizedSymbol) {
      continue
    }
    next[normalizedSymbol] = normalizeSharedWatchlistSummary(summary)
  }
  return next
}

async function readSharedWatchlistSummaries(state) {
  return normalizeSharedWatchlistSummaries(await state.storage.get('summaries'))
}

async function readSharedWatchlistEntries(state) {
  const symbols = normalizeSharedSpaceSymbols(await readSharedSpaceSymbols(state))
  const summaries = await readSharedWatchlistSummaries(state)
  return symbols.map((symbol) => ({
    symbol,
    ...normalizeSharedWatchlistSummary(summaries[symbol]),
  }))
}

async function writeSharedWatchlistSummary(state, symbol, summary) {
  const summaries = await readSharedWatchlistSummaries(state)
  summaries[symbol] = normalizeSharedWatchlistSummary(summary)
  await state.storage.put('summaries', summaries)
}

function normalizeSharedSpaceSymbols(symbols) {
  return [...new Set(symbols.map((symbol) => normalizeSymbol(symbol)).filter(Boolean))].sort((a, b) => a.localeCompare(b))
}

async function buildSharedSpaceBrowserFingerprint(request) {
  const parts = [
    request.headers.get('cf-connecting-ip') ?? '',
    request.headers.get('user-agent') ?? '',
    request.headers.get('sec-ch-ua') ?? '',
    request.headers.get('sec-ch-ua-platform') ?? '',
    request.headers.get('accept-language') ?? '',
  ]
  if (parts.every((value) => !String(value).trim())) {
    return null
  }
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', sharedSpaceTextEncoder.encode(parts.join('\n'))))
  return base64UrlEncode(digest)
}

function normalizeSharedSpaceBrowserSessions(sessions) {
  const now = Math.floor(Date.now() / 1000)
  const next = {}
  if (!sessions || typeof sessions !== 'object') {
    return next
  }
  for (const [fingerprint, exp] of Object.entries(sessions)) {
    if (typeof exp === 'number' && Number.isFinite(exp) && exp >= now) {
      next[fingerprint] = exp
    }
  }
  return next
}

async function readSharedSpaceBrowserSessions(state) {
  return normalizeSharedSpaceBrowserSessions(await state.storage.get('sessions'))
}

async function writeSharedSpaceBrowserSession(state, request, maxAge) {
  const fingerprint = await buildSharedSpaceBrowserFingerprint(request)
  if (!fingerprint) {
    return
  }
  const sessions = await readSharedSpaceBrowserSessions(state)
  sessions[fingerprint] = Math.floor(Date.now() / 1000) + maxAge
  await state.storage.put('sessions', sessions)
}

async function clearSharedSpaceBrowserSession(state, request) {
  const fingerprint = await buildSharedSpaceBrowserFingerprint(request)
  if (!fingerprint) {
    return
  }
  const sessions = await readSharedSpaceBrowserSessions(state)
  if (!Object.prototype.hasOwnProperty.call(sessions, fingerprint)) {
    return
  }
  delete sessions[fingerprint]
  await state.storage.put('sessions', sessions)
}

async function hasSharedSpaceBrowserSession(state, request) {
  const fingerprint = await buildSharedSpaceBrowserFingerprint(request)
  if (!fingerprint) {
    return false
  }
  const sessions = await readSharedSpaceBrowserSessions(state)
  const expiresAt = sessions[fingerprint]
  if (expiresAt) {
    return true
  }
  return false
}

async function handleSharedSpacesRoute(pathname, request, env = {}) {
  const config = getSharedSpaceConfig(env)
  if (!config || !env.SHARED_WATCHLIST_SPACE) {
    return handleSharedSpaceUnavailability(pathname)
  }

  const parts = pathname.split('/').filter(Boolean)
  const slug = normalizeSharedSpaceSlug(parts[1])
  if (!slug || slug !== config.slug) {
    return jsonCors({ detail: `Shared space ${slug || '(unknown)'} is not configured` }, 404)
  }

  const forwardedPath = `/${parts.slice(2).join('/')}`.replace(/\/+$/, '') || '/session'
  const forwardedUrl = new URL(request.url)
  forwardedUrl.pathname = forwardedPath
  const namespace = env.SHARED_WATCHLIST_SPACE
  const stub = namespace.get(namespace.idFromName(config.slug))
  return withCors(await stub.fetch(new Request(forwardedUrl, request)), request)
}

export class SharedWatchlistSpace {
  constructor(state, env) {
    this.state = state
    this.env = env
  }

  async fetch(request) {
    const config = getSharedSpaceConfig(this.env)
    if (!config) {
      return json({ detail: 'Shared watchlist is not configured' }, 503)
    }

    const pathname = new URL(request.url).pathname.replace(/\/+$/, '') || '/'

    if (pathname === '/session' && request.method === 'GET') {
      const authentication = await readSharedSpaceAuthentication(request, config.sessionSecret)
      const authenticated = authentication.slug === config.slug || (await hasSharedSpaceBrowserSession(this.state, request))
      return sharedSpaceSessionResponse(config, authenticated, authenticated ? authentication.token : null)
    }

    if (pathname === '/login' && request.method === 'POST') {
      const body = await readJson(request)
      if (!body?.passcode) {
        return json({ detail: 'passcode is required' }, 400)
      }
      if (String(body.passcode).trim() !== config.passcode) {
        return json({ detail: 'Invalid passcode' }, 401)
      }
      const sessionToken = await buildSharedSpaceSessionCookie(config.slug, config.sessionSecret, config.sessionMaxAge)
      await writeSharedSpaceBrowserSession(this.state, request, config.sessionMaxAge)
      const response = await sharedSpaceSessionResponse(config, true, sessionToken)
      return appendSharedSpaceCookie(
        response,
        'shared_space_session',
        sessionToken,
        sharedSpaceCookieOptions(request, config.slug, config.sessionMaxAge),
      )
    }

    if (pathname === '/logout' && request.method === 'POST') {
      await clearSharedSpaceBrowserSession(this.state, request)
      const response = await sharedSpaceSessionResponse(config, false)
      return clearSharedSpaceCookie(response, 'shared_space_session', `/shared-spaces/${config.slug}`)
    }

    const authentication = await readSharedSpaceAuthentication(request, config.sessionSecret)
    if (authentication.slug !== config.slug && !(await hasSharedSpaceBrowserSession(this.state, request))) {
      return json({ detail: 'Authentication required' }, 401)
    }

    if (pathname === '/watchlist' && request.method === 'GET') {
      return sharedSpaceWatchlistResponse(config, this.state)
    }

    if (pathname === '/watchlist' && request.method === 'POST') {
      const body = await readJson(request)
      const symbol = normalizeSymbol(body?.symbol)
      if (!symbol) {
        return json({ detail: 'symbol is required' }, 400)
      }
      const next = normalizeSharedSpaceSymbols([...await readSharedSpaceSymbols(this.state), symbol])
      await this.state.storage.put('symbols', next)
      const summary = normalizeSharedWatchlistSummary(body)
      if (hasSharedWatchlistSummary(summary)) {
        await writeSharedWatchlistSummary(this.state, symbol, summary)
      }
      return sharedSpaceWatchlistResponse(config, this.state)
    }

    if (pathname.startsWith('/watchlist/') && pathname.endsWith('/summary') && request.method === 'PUT') {
      const symbol = normalizeSymbol(pathname.split('/').at(-2))
      if (!symbol) {
        return json({ detail: 'symbol is required' }, 400)
      }
      const existingSymbols = normalizeSharedSpaceSymbols(await readSharedSpaceSymbols(this.state))
      if (!existingSymbols.includes(symbol)) {
        return json({ detail: 'Shared watchlist symbol not found' }, 404)
      }
      const body = await readJson(request)
      await writeSharedWatchlistSummary(this.state, symbol, body)
      return sharedSpaceWatchlistResponse(config, this.state)
    }

    if (pathname.startsWith('/watchlist/') && request.method === 'DELETE') {
      const symbol = normalizeSymbol(pathname.split('/').at(-1))
      if (!symbol) {
        return json({ detail: 'symbol is required' }, 400)
      }
      const next = normalizeSharedSpaceSymbols((await readSharedSpaceSymbols(this.state)).filter((value) => value !== symbol))
      await this.state.storage.put('symbols', next)
      const summaries = await readSharedWatchlistSummaries(this.state)
      if (Object.prototype.hasOwnProperty.call(summaries, symbol)) {
        delete summaries[symbol]
        await this.state.storage.put('summaries', summaries)
      }
      return sharedSpaceWatchlistResponse(config, this.state)
    }

    return json({ detail: `Unhandled shared-space route ${pathname}` }, 404)
  }
}

export const __testOnly = {
  clearCaches() {
    requestCache.clear()
    healthCache.clear()
  },
}

export default {
  async fetch(request, env = {}) {
    if (request.method === 'OPTIONS') {
      return withCors(new Response(null, { status: 204 }), request)
    }

    const url = new URL(request.url)
    const pathname = url.pathname.replace(/\/+$/, '') || '/'

    try {
      let response
      if (pathname === '/' || pathname === '/health') {
        response = jsonCors(
          await buildHealthResponse('finance_api_worker', getSharedSpaceConfig(env) && env.SHARED_WATCHLIST_SPACE ? 'configured' : 'disabled'),
        )
      } else if (pathname === '/screen/health' || pathname.startsWith('/screen/')) {
        response = await handleScreenRoute(pathname, request, env)
      } else if (
        pathname === '/search' ||
        pathname === '/analyze' ||
        pathname === '/batch' ||
        pathname === '/entry' ||
        pathname === '/entry/confluence' ||
        pathname.startsWith('/entry/confluence/')
      ) {
        response = await handleAnalyzeRoute(pathname, request, env)
      } else if (pathname.startsWith('/shared-spaces/')) {
        response = await handleSharedSpacesRoute(pathname, request, env)
      } else {
        response = jsonCors({ detail: 'Not found' }, 404)
      }
      return withCors(response, request)
    } catch (error) {
      return withCors(
        jsonCors(
          {
            detail: error instanceof Error ? error.message : 'Unexpected worker failure',
          },
          500,
        ),
        request,
      )
    }
  },
}
