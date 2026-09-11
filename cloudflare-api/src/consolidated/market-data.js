// Market data for the consolidated pipeline, from Yahoo's public chart API.
//
// Bars are shaped the way technical_engine/technical-features.js reads them
// (columnar arrays under history.intervals), and the market context carries the
// fields technical_engine/decision-engine/market-engine.js evaluates, computed
// the way technical_engine/server.py computes them. Missing data stays
// unavailable: no bar is interpolated, and 4h is never synthesized from 1h.

const CHART_HOSTS = ['https://query1.finance.yahoo.com', 'https://query2.finance.yahoo.com']
const FEAR_GREED_URL = 'https://production.dataviz.cnn.io/index/fearandgreed/graphdata'
// Yahoo's chart API answers 429 to a full Chrome UA without browser cookies,
// but 200 to a bare Mozilla/5.0 (matches the rest of the Worker, src/index.js).
const YAHOO_HEADERS = {
  'user-agent': 'Mozilla/5.0',
  accept: 'application/json,text/plain,*/*',
}
// CNN's Fear & Greed endpoint needs a browser UA plus referer/origin.
const BROWSER_HEADERS = {
  'user-agent':
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36',
  accept: 'application/json,text/plain,*/*',
}
// Matches server.py: TECHNICAL_DAILY_HISTORY_PERIOD=2y, TECHNICAL_INTRADAY_HISTORY_PERIOD=120d.
export const RANGES = { daily: '2y', intraday: '120d' }
const TTL_MS = { ticker: 5 * 60_000, market: 15 * 60_000 }
const EDGE_CACHE_SECONDS = 300
// Bounded like the engine's own caches (technical_engine/AGENTS.md).
const MAX_CACHE_ENTRIES = 300

const cache = new Map()

export function clearMarketDataCache() {
  cache.clear()
}

function cached(key, ttlMs, load) {
  const entry = cache.get(key)
  if (entry && entry.expiresAt > Date.now()) {
    return entry.settled ? Promise.resolve(entry.value) : entry.promise
  }
  if (cache.size >= MAX_CACHE_ENTRIES) cache.delete(cache.keys().next().value)
  const fresh = { settled: false, value: undefined, expiresAt: Date.now() + ttlMs }
  fresh.promise = Promise.resolve()
    .then(load)
    .then(
      (value) => {
        fresh.settled = true
        fresh.value = value
        return value
      },
      (error) => {
        if (cache.get(key) === fresh) cache.delete(key)
        throw error
      },
    )
  cache.set(key, fresh)
  return fresh.promise
}

const defaultFetch = (...args) => fetch(...args)

const finite = (value) =>
  value == null || value === '' ? null : Number.isFinite(Number(value)) ? Number(value) : null

const round2 = (value) => Math.round(value * 100) / 100
const round1 = (value) => Math.round(value * 10) / 10

export async function fetchYahooChart(symbol, { interval = '1d', range = RANGES.daily, fetchImpl = defaultFetch } = {}) {
  let lastError = null
  for (const host of CHART_HOSTS) {
    const url = `${host}/v8/finance/chart/${encodeURIComponent(symbol)}?interval=${interval}&range=${range}&includePrePost=false&events=div%2Csplits`
    try {
      const response = await fetchImpl(url, {
        headers: YAHOO_HEADERS,
        cf: { cacheTtl: EDGE_CACHE_SECONDS, cacheEverything: true },
      })
      if (!response.ok) throw new Error(`HTTP ${response.status} from Yahoo chart for ${symbol} ${interval}`)
      const payload = await response.json()
      const result = payload?.chart?.result?.[0]
      if (!result) throw new Error(`no chart result for ${symbol} ${interval}`)
      return result
    } catch (error) {
      lastError = error
    }
  }
  throw lastError
}

function emptyBars(reason = 'source_unavailable') {
  return {
    timestamps: [],
    opens: [],
    highs: [],
    lows: [],
    closes: [],
    adjCloses: [],
    volumes: [],
    availability: 'unavailable',
    available: false,
    reason,
  }
}

// Yahoo's columnar chart → bars. A row with any missing OHLC value is dropped,
// never interpolated: a fabricated bar is worse than a short history.
export function barsFromChart(result, { intraday = false } = {}) {
  const timestamps = result?.timestamp || []
  const quote = result?.indicators?.quote?.[0] || {}
  const adjclose = result?.indicators?.adjclose?.[0]?.adjclose || null
  const out = emptyBars()
  for (let index = 0; index < timestamps.length; index += 1) {
    const open = finite(quote.open?.[index])
    const high = finite(quote.high?.[index])
    const low = finite(quote.low?.[index])
    const close = finite(quote.close?.[index])
    if (open == null || high == null || low == null || close == null) continue
    const stamp = new Date(timestamps[index] * 1000).toISOString()
    out.timestamps.push(intraday ? stamp : stamp.slice(0, 10))
    out.opens.push(open)
    out.highs.push(high)
    out.lows.push(low)
    out.closes.push(close)
    out.adjCloses.push(finite(adjclose?.[index]) ?? close)
    out.volumes.push(finite(quote.volume?.[index]) ?? 0)
  }
  const available = out.closes.length > 0
  return { ...out, availability: available ? 'available' : 'unavailable', available, reason: available ? null : 'source_unavailable' }
}

const EASTERN = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

function easternParts(epochSeconds) {
  const parts = Object.fromEntries(EASTERN.formatToParts(new Date(epochSeconds * 1000)).map((part) => [part.type, part.value]))
  return { day: `${parts.year}-${parts.month}-${parts.day}`, time: `${parts.hour}:${parts.minute}` }
}

// Mirrors server.py validate_native_four_hour_history_frame: keep only
// provider-native US regular-session 4h bars. A normal day has 09:30 and 13:30
// bars. A 09:30-only day is kept (early close). Any other shape, a duplicate,
// or invalid OHLCV excludes the whole day rather than repairing it.
export function validateNativeFourHour(result) {
  const meta = result?.meta || {}
  const counts = { normalSessionDays: 0, singleSessionDays: 0, invalidSessionDays: 0 }
  if (!result?.timestamp?.length) return { bars: emptyBars('source_unavailable'), ...counts, unavailableReason: 'source_unavailable' }
  if (meta.dataGranularity !== '4h' || meta.exchangeTimezoneName !== 'America/New_York') {
    return { bars: emptyBars('invalid_source_data'), ...counts, unavailableReason: 'invalid_source_data' }
  }
  const quote = result.indicators?.quote?.[0] || {}
  const dayRows = new Map()
  const invalidDays = new Set()
  result.timestamp.forEach((epochSeconds, index) => {
    const open = finite(quote.open?.[index])
    const high = finite(quote.high?.[index])
    const low = finite(quote.low?.[index])
    const close = finite(quote.close?.[index])
    const volume = finite(quote.volume?.[index])
    // An all-empty row is an absent bar (Yahoo pads the live candle), not a
    // malformed one.
    if (open == null && high == null && low == null && close == null) return
    const { day, time } = easternParts(epochSeconds)
    const valid =
      open != null &&
      high != null &&
      low != null &&
      close != null &&
      volume != null &&
      high >= Math.max(open, close) &&
      low <= Math.min(open, close) &&
      volume >= 0
    if (!valid || (time !== '09:30' && time !== '13:30')) {
      invalidDays.add(day)
      return
    }
    if (!dayRows.has(day)) dayRows.set(day, [])
    dayRows.get(day).push({ time, index })
  })

  const keep = []
  for (const [day, rows] of [...dayRows.entries()].sort(([left], [right]) => left.localeCompare(right))) {
    const times = rows.map((row) => row.time)
    if (invalidDays.has(day) || new Set(times).size !== times.length) {
      counts.invalidSessionDays += 1
      continue
    }
    if (times.join(',') === '09:30,13:30') {
      counts.normalSessionDays += 1
      keep.push(...rows.map((row) => row.index))
    } else if (times.join(',') === '09:30') {
      counts.singleSessionDays += 1
      keep.push(rows[0].index)
    } else {
      counts.invalidSessionDays += 1
    }
  }
  if (!keep.length) return { bars: emptyBars('invalid_source_data'), ...counts, unavailableReason: 'invalid_source_data' }

  const bars = emptyBars()
  for (const index of keep) {
    bars.timestamps.push(new Date(result.timestamp[index] * 1000).toISOString())
    bars.opens.push(finite(quote.open[index]))
    bars.highs.push(finite(quote.high[index]))
    bars.lows.push(finite(quote.low[index]))
    bars.closes.push(finite(quote.close[index]))
    bars.adjCloses.push(finite(quote.close[index]))
    bars.volumes.push(finite(quote.volume[index]))
  }
  return {
    bars: {
      ...bars,
      availability: 'available',
      available: true,
      reason: null,
      interval: '4h',
      source: 'yahoo_chart_native_4h',
      bar_method: 'provider_native_v1',
    },
    ...counts,
    unavailableReason: null,
  }
}

export function loadDailyBars(symbol, { fetchImpl = defaultFetch } = {}) {
  return cached(`daily:${symbol}`, TTL_MS.ticker, async () => {
    const result = await fetchYahooChart(symbol, { interval: '1d', range: RANGES.daily, fetchImpl })
    return { bars: barsFromChart(result), meta: result.meta || {} }
  })
}

function loadFourHourBars(symbol, fetchImpl) {
  return cached(`4h:${symbol}`, TTL_MS.ticker, async () =>
    validateNativeFourHour(await fetchYahooChart(symbol, { interval: '4h', range: RANGES.intraday, fetchImpl })),
  )
}

function loadHourlyBars(symbol, fetchImpl) {
  return cached(`1h:${symbol}`, TTL_MS.ticker, async () =>
    barsFromChart(await fetchYahooChart(symbol, { interval: '1h', range: RANGES.intraday, fetchImpl }), { intraday: true }),
  )
}

// The quote object technical_engine's feature-inputs.js consumes.
export async function loadQuoteInputs(symbol, { fetchImpl = defaultFetch, metadata = {} } = {}) {
  const [{ bars: daily, meta }, fourHour, hourly] = await Promise.all([
    loadDailyBars(symbol, { fetchImpl }),
    loadFourHourBars(symbol, fetchImpl).catch(() => ({ bars: emptyBars('source_unavailable'), unavailableReason: 'source_unavailable' })),
    loadHourlyBars(symbol, fetchImpl).catch(() => emptyBars('source_unavailable')),
  ])
  return {
    ticker: symbol,
    price: finite(meta.regularMarketPrice) ?? daily.closes.at(-1) ?? null,
    quote_status: daily.available ? 'available' : 'unavailable',
    history: {
      ...daily,
      intervals: { '1d': daily, '4h': fourHour.bars, '1h': hourly },
      daily_history_metadata: { lookback: RANGES.daily },
    },
    metadata: {
      quoteType: meta.instrumentType || 'EQUITY',
      sharesOutstanding: null,
      currency: meta.currency || null,
      exchangeName: meta.fullExchangeName || meta.exchangeName || null,
      ...metadata,
    },
    technical: { fibonacci_structure: {} },
    dataQuality: {
      daily: daily.available ? 'available' : 'unavailable',
      four_hour: fourHour.bars.available ? 'available' : fourHour.unavailableReason || 'unavailable',
      one_hour: hourly.available ? 'available' : 'unavailable',
    },
  }
}

// server.py series_change: an absolute difference against the value
// `sessionsBack` points earlier.
export function seriesChange(values, sessionsBack = 5) {
  if (!values || values.length < 2) return null
  const latest = values.at(-1)
  if (latest == null) return null
  const anchorIndex = Math.max(0, values.length - 1 - Math.max(1, sessionsBack))
  for (let index = anchorIndex; index >= 0; index -= 1) {
    if (values[index] != null) return round2(latest - values[index])
  }
  return null
}

// server.py classify_change_trend.
export function classifyChangeTrend(change5d, change20d, shortThreshold, longThreshold) {
  if (change5d == null && change20d == null) return 'neutral'
  const shortValue = change5d || 0
  const longValue = change20d || 0
  if (shortValue >= shortThreshold || longValue >= longThreshold) return 'rising'
  if (shortValue <= -shortThreshold || longValue <= -longThreshold) return 'falling'
  return 'neutral'
}

// server.py build_index_trend.
export function indexTrend(symbol, closes) {
  const current = closes.at(-1) ?? null
  const pct = (lookback) => {
    if (current == null || closes.length <= lookback) return null
    const base = closes[Math.max(0, closes.length - lookback - 1)]
    return base ? round2(((current - base) / base) * 100) : null
  }
  const change5 = pct(5)
  const change20 = pct(20)
  const trend =
    (change5 ?? 0) >= 1.5 && (change20 ?? 0) >= 0 ? 'rising' : (change5 ?? 0) <= -1.5 && (change20 ?? 0) <= 0 ? 'falling' : 'neutral'
  return {
    symbol,
    label: symbol,
    value: current,
    change_5d_pct: change5,
    change_20d_pct: change20,
    change_60d_pct: pct(60),
    change_120d_pct: pct(120),
    trend,
  }
}

// server.py fear_greed_label.
export function fearGreedLabel(value) {
  if (value == null) return null
  if (value <= 25) return 'Extreme Fear'
  if (value <= 45) return 'Fear'
  if (value <= 55) return 'Neutral'
  if (value <= 75) return 'Greed'
  return 'Extreme Greed'
}

const UNAVAILABLE_FEAR_GREED = { value: null, label: null, trend: null }

async function loadFearGreed(fetchImpl) {
  try {
    const response = await fetchImpl(FEAR_GREED_URL, {
      headers: { ...BROWSER_HEADERS, referer: 'https://www.cnn.com/', origin: 'https://www.cnn.com' },
    })
    if (!response.ok) return UNAVAILABLE_FEAR_GREED
    const current = (await response.json())?.fear_and_greed || {}
    const value = finite(current.score)
    if (value == null) return UNAVAILABLE_FEAR_GREED
    const previous = finite(current.previous_close)
    const delta = previous == null ? null : value - previous
    const trend = delta == null ? null : delta >= 3 ? 'rising' : delta <= -3 ? 'falling' : 'neutral'
    return { value: round2(value), label: fearGreedLabel(value), trend }
  } catch {
    return UNAVAILABLE_FEAR_GREED
  }
}

export function loadMarketContext({ fetchImpl = defaultFetch } = {}) {
  return cached('market-context', TTL_MS.market, async () => {
    const closes = (symbol) =>
      loadDailyBars(symbol, { fetchImpl })
        .then(({ bars }) => bars.closes)
        .catch(() => [])
    const [vixCloses, tnxCloses, spyCloses, qqqCloses, fearGreed] = await Promise.all([
      closes('^VIX'),
      closes('^TNX'),
      closes('SPY'),
      closes('QQQ'),
      loadFearGreed(fetchImpl),
    ])
    const vixSeries = vixCloses.slice(-40)
    const tnxTail = tnxCloses.slice(-40)
    // server.py fetch_treasury_history_points: a quote above 20 is in tenths.
    const yieldSeries = tnxTail.length && tnxTail.at(-1) > 20 ? tnxTail.map((value) => value * 0.1) : tnxTail
    const vix5 = seriesChange(vixSeries, 5)
    const vix20 = seriesChange(vixSeries, 20)
    const yield5 = seriesChange(yieldSeries, 5)
    const yield20 = seriesChange(yieldSeries, 20)
    const yield5Bps = yield5 == null ? null : round1(yield5 * 100)
    const yield20Bps = yield20 == null ? null : round1(yield20 * 100)
    return {
      market_context: {
        vix: {
          value: vixSeries.at(-1) ?? null,
          change_5d: vix5,
          change_20d: vix20,
          trend: classifyChangeTrend(vix5, vix20, 1.0, 2.5),
        },
        ten_year_yield: {
          value: yieldSeries.length ? round2(yieldSeries.at(-1)) : null,
          change_5d_bps: yield5Bps,
          change_20d_bps: yield20Bps,
          trend: classifyChangeTrend(yield5Bps, yield20Bps, 10.0, 25.0),
        },
        fear_greed: fearGreed,
        equity_trend: {
          spy: indexTrend('SPY', spyCloses.slice(-180)),
          qqq: indexTrend('QQQ', qqqCloses.slice(-180)),
        },
      },
    }
  })
}
