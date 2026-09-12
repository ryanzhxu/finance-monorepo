import type { ConsolidatedHorizon, FundamentalStance, IndexHurdle } from './api/types'

// Mirrors cloudflare-api/config/consolidation.json's buyFamily (fixed a
// priori, protected per AUTOPILOT.md — change one, change both). Needed here
// because a passing hurdle leaves no adjustment record server-side
// (composeHorizon in final-decision.js only records a hurdle adjustment when
// it changes the action), so this is the only way the client can tell "the
// hurdle passed for a buy" apart from "the hurdle never applied".
const BUY_FAMILY = new Set(['strong_buy', 'buy', 'accumulate'])

export type HorizonSummaryPart =
  | { kind: 'unavailable' }
  | { kind: 'technical'; action: string; priceState: string | null }
  | { kind: 'fundamentals'; stance: FundamentalStance }
  | { kind: 'hurdle_beats'; benchmarks: string[] }
  | { kind: 'hurdle_lags'; benchmarks: string[] }
  | { kind: 'hurdle_earnings_guard' }
  | { kind: 'hurdle_unavailable' }

export interface HorizonSummary {
  parts: HorizonSummaryPart[]
  finalAction: string | null
}

/**
 * One plain-language line per horizon, composed deterministically from data
 * the panel already has: what Vincent's engine says, whether fundamentals
 * apply and their stance, and whether the index hurdle cleared, lagged, was
 * blocked by the earnings guard, or could not run — ending at the final
 * action. No LLM; every clause traces to a field already on the horizon or
 * the symbol-level hurdle.
 */
export function composeHorizonSummary(horizon: ConsolidatedHorizon, hurdle: IndexHurdle | null): HorizonSummary {
  if (!horizon.technical?.available || !horizon.technical.action) {
    return { parts: [{ kind: 'unavailable' }], finalAction: horizon.final_action }
  }

  const parts: HorizonSummaryPart[] = [
    { kind: 'technical', action: horizon.technical.action, priceState: horizon.technical.price_state ?? null },
  ]

  if (horizon.fundamentals.applied && horizon.fundamentals.stance !== 'unavailable') {
    parts.push({ kind: 'fundamentals', stance: horizon.fundamentals.stance })
  }

  const fundamentalsAdjustment = horizon.adjustments.find((adjustment) => adjustment.layer === 'fundamentals')
  const preHurdleAction = fundamentalsAdjustment?.to ?? horizon.technical.action

  const hurdleAdjustment = horizon.adjustments.find((adjustment) => adjustment.layer === 'index_hurdle')
  if (hurdleAdjustment) {
    if (hurdleAdjustment.reason === 'index_hurdle_unavailable') {
      parts.push({ kind: 'hurdle_unavailable' })
    } else if (hurdle?.lagging?.length) {
      parts.push({ kind: 'hurdle_lags', benchmarks: hurdle.lagging })
    } else {
      parts.push({ kind: 'hurdle_earnings_guard' })
    }
  } else if (hurdle && hurdle.status === 'pass' && preHurdleAction != null && BUY_FAMILY.has(preHurdleAction)) {
    const beating = hurdle.benchmarks.filter((row) => row.result === 'beats').map((row) => row.symbol)
    if (beating.length) parts.push({ kind: 'hurdle_beats', benchmarks: beating })
  }

  return { parts, finalAction: horizon.final_action }
}
