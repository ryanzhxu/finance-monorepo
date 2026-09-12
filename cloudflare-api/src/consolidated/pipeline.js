// The consolidated decision for one symbol: Vincent's engine in process, the
// index hurdle, and Ryan's fundamentals, composed per horizon.

import { buildConsolidatedDecision, fundamentalStance } from './final-decision.js'
import { runIndexHurdle, seriesFromBars } from './index-hurdle.js'
import { loadDailyBars } from './market-data.js'
import { classificationFor, runTechnicalEngine } from './technical-engine.js'

const defaultFetch = (...args) => fetch(...args)

export function consolidatedEnabled(env = {}) {
  return String(env.CONSOLIDATED_DECISION ?? '').trim().toLowerCase() === 'on'
}

// calendarEvents.earnings.earningsDate is a list of epoch seconds.
export function earningsDateFromQuote(quote) {
  const raw = quote?.calendarEvents?.earnings?.earningsDate
  const first = Array.isArray(raw) ? raw[0] : raw
  const seconds = Number(first)
  return Number.isFinite(seconds) && seconds > 0 ? new Date(seconds * 1000).toISOString().slice(0, 10) : null
}

// How many whole days away the next earnings date is, and whether that falls
// inside Vincent's own near-earnings window (his engine already reads this
// same date as risk input; this only reports it for the UI, no second rule).
export function earningsProximityFrom(earningsDate, now = new Date()) {
  if (!earningsDate) return null
  const target = Date.parse(`${earningsDate}T00:00:00Z`)
  if (!Number.isFinite(target)) return null
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
  const daysToEarnings = Math.round((target - today) / 86_400_000)
  const nearDays = globalThis.DecisionEngine?.config?.market?.earnings?.nearDays
  const near = Number.isFinite(nearDays) ? daysToEarnings >= 0 && daysToEarnings <= nearDays : false
  return { date: earningsDate, days_to_earnings: daysToEarnings, near }
}

// Short, no-stack reason a caller can show to a user (e.g. "unavailable —
// could not load market data (<reason>)"), not a debugging trace.
function shortReason(error) {
  return String(error?.message || error).slice(0, 200)
}

export async function runConsolidated(symbol, { quote = null, fundamentalSignals = [], earnings = {}, fetchImpl = defaultFetch } = {}) {
  const earningsDate = earningsDateFromQuote(quote)
  const traits = classificationFor(symbol, { quoteType: quote?.quoteType }).companyTraits ?? []
  const errors = {}
  const [technical, hurdle] = await Promise.all([
    runTechnicalEngine(symbol, { fetchImpl, metadata: earningsDate ? { earningsDate } : {} }).catch((error) => {
      console.warn(`consolidated technical engine failed for ${symbol}: ${error?.message || error}`)
      errors.technical = shortReason(error)
      return null
    }),
    runIndexHurdle(symbol, {
      sector: quote?.sector ?? null,
      industry: quote?.industry ?? null,
      traits,
      earnings,
      loadSeries: (item) => loadDailyBars(item, { fetchImpl }).then(({ bars }) => seriesFromBars(bars)),
    }).catch((error) => {
      console.warn(`index hurdle failed for ${symbol}: ${error?.message || error}`)
      errors.index_hurdle = shortReason(error)
      return null
    }),
  ])
  return {
    consolidated: buildConsolidatedDecision({
      technical,
      fundamentals: fundamentalStance(fundamentalSignals),
      hurdle,
      errors: Object.keys(errors).length ? errors : null,
      earnings: earningsProximityFrom(earningsDate),
    }),
    decisionV1ByHorizon: technical?.decisionV1 ?? {},
  }
}
