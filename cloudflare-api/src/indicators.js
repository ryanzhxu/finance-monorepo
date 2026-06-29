export function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value))
}

export function mean(values) {
  const filtered = values.filter((value) => Number.isFinite(value))
  if (filtered.length === 0) return null
  return filtered.reduce((sum, value) => sum + value, 0) / filtered.length
}

export function stdev(values) {
  const avg = mean(values)
  if (avg == null) return null
  const filtered = values.filter((value) => Number.isFinite(value))
  if (filtered.length < 2) return 0
  const variance = filtered.reduce((sum, value) => sum + (value - avg) ** 2, 0) / (filtered.length - 1)
  return Math.sqrt(variance)
}

export function sma(values, period) {
  if (!Number.isInteger(period) || period <= 0 || values.length < period) return null
  return mean(values.slice(values.length - period))
}

export function emaSeries(values, period) {
  if (!Number.isInteger(period) || period <= 0 || values.length === 0) return []
  const alpha = 2 / (period + 1)
  const output = []
  let emaValue = values[0]
  output.push(emaValue)
  for (let i = 1; i < values.length; i += 1) {
    emaValue = values[i] * alpha + emaValue * (1 - alpha)
    output.push(emaValue)
  }
  return output
}

export function ema(values, period) {
  const series = emaSeries(values, period)
  return series.length > 0 ? series[series.length - 1] : null
}

export function rsi(values, period = 14) {
  if (!Number.isInteger(period) || period <= 0 || values.length <= period) return null
  let gains = 0
  let losses = 0
  for (let i = 1; i <= period; i += 1) {
    const delta = values[i] - values[i - 1]
    if (delta >= 0) gains += delta
    else losses -= delta
  }
  let avgGain = gains / period
  let avgLoss = losses / period
  for (let i = period + 1; i < values.length; i += 1) {
    const delta = values[i] - values[i - 1]
    const gain = Math.max(delta, 0)
    const loss = Math.max(-delta, 0)
    avgGain = ((avgGain * (period - 1)) + gain) / period
    avgLoss = ((avgLoss * (period - 1)) + loss) / period
  }
  if (avgLoss === 0) return 100
  const rs = avgGain / avgLoss
  return 100 - 100 / (1 + rs)
}

export function macd(values, fast = 12, slow = 26, signal = 9) {
  if (values.length < slow + signal) return { macdLine: null, signalLine: null, histogram: null }
  const fastSeries = emaSeries(values, fast)
  const slowSeries = emaSeries(values, slow)
  const macdSeries = values.map((_, index) => (fastSeries[index] ?? 0) - (slowSeries[index] ?? 0))
  const signalSeries = emaSeries(macdSeries, signal)
  const macdLine = macdSeries[macdSeries.length - 1]
  const signalLine = signalSeries[signalSeries.length - 1]
  return {
    macdLine,
    signalLine,
    histogram: macdLine - signalLine,
  }
}

export function atr(highs, lows, closes, period = 14) {
  if (highs.length !== lows.length || highs.length !== closes.length || highs.length <= period) {
    return null
  }
  const trueRanges = []
  for (let i = 1; i < highs.length; i += 1) {
    const range = Math.max(
      highs[i] - lows[i],
      Math.abs(highs[i] - closes[i - 1]),
      Math.abs(lows[i] - closes[i - 1]),
    )
    trueRanges.push(range)
  }
  return sma(trueRanges, period)
}

export function highest(values, startIndex = 0) {
  let current = -Infinity
  for (let i = startIndex; i < values.length; i += 1) {
    if (Number.isFinite(values[i]) && values[i] > current) {
      current = values[i]
    }
  }
  return current === -Infinity ? null : current
}

export function lowest(values, startIndex = 0) {
  let current = Infinity
  for (let i = startIndex; i < values.length; i += 1) {
    if (Number.isFinite(values[i]) && values[i] < current) {
      current = values[i]
    }
  }
  return current === Infinity ? null : current
}

export function pctChange(current, previous) {
  if (!Number.isFinite(current) || !Number.isFinite(previous) || previous === 0) return null
  return ((current - previous) / previous) * 100
}

export function quantile(values, q) {
  const filtered = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b)
  if (filtered.length === 0) return null
  const position = (filtered.length - 1) * q
  const base = Math.floor(position)
  const rest = position - base
  const baseValue = filtered[base]
  const nextValue = filtered[base + 1]
  if (nextValue === undefined) return baseValue
  return baseValue + rest * (nextValue - baseValue)
}

export function round(value, digits = 2) {
  if (!Number.isFinite(value)) return null
  const factor = 10 ** digits
  return Math.round(value * factor) / factor
}
