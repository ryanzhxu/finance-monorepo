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

export async function runConsolidated(symbol, { quote = null, fundamentalSignals = [], earnings = {}, fetchImpl = defaultFetch } = {}) {
  const earningsDate = earningsDateFromQuote(quote)
  const traits = classificationFor(symbol, { quoteType: quote?.quoteType }).companyTraits ?? []
  const [technical, hurdle] = await Promise.all([
    runTechnicalEngine(symbol, { fetchImpl, metadata: earningsDate ? { earningsDate } : {} }).catch((error) => {
      console.warn(`consolidated technical engine failed for ${symbol}: ${error?.message || error}`)
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
      return null
    }),
  ])
  return {
    consolidated: buildConsolidatedDecision({ technical, fundamentals: fundamentalStance(fundamentalSignals), hurdle }),
    decisionV1ByHorizon: technical?.decisionV1 ?? {},
  }
}
