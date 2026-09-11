// The final decision per horizon: Vincent's technical action (the majority),
// then Ryan's fundamentals (a minority that can only remove conviction from a
// buy), then the index hurdle (a buy that is not expected to beat every
// benchmark is capped at hold). Short, mid and long stay independent and are
// never averaged. Vincent's own action is always reported unchanged beside the
// final one.

import config from '../../config/consolidation.json' with { type: 'json' }

const FUNDAMENTALS = config.fundamentals
const BUY_FAMILY = new Set(config.buyFamily)

const round4 = (value) => Math.round(value * 10_000) / 10_000

// Stance from Ryan's fundamental signals ({ signal: BUY|HOLD|SELL, weight }).
// Ties break BUY > HOLD > SELL, matching the Worker's dominantDirection.
export function fundamentalStance(fundamentalSignals = []) {
  const vote = { BUY: 0, HOLD: 0, SELL: 0 }
  for (const item of fundamentalSignals) {
    if (item?.signal in vote) vote[item.signal] = round4(vote[item.signal] + (Number(item.weight) || 0))
  }
  const signalCount = fundamentalSignals.length
  if (signalCount < FUNDAMENTALS.minSignals) return { stance: 'unavailable', vote, signal_count: signalCount }
  let best = 'BUY'
  for (const direction of ['HOLD', 'SELL']) {
    if (vote[direction] > vote[best]) best = direction
  }
  const stance = best === 'BUY' ? 'supportive' : best === 'SELL' ? 'weak' : 'neutral'
  return { stance, vote, signal_count: signalCount }
}

function hurdleDetail(hurdle) {
  if (hurdle?.lagging?.length) return `does not beat ${hurdle.lagging.join(', ')}`
  if (hurdle?.earnings_guard?.status === 'fired') return 'negative EPS surprise and analysts turning bearish'
  return null
}

export function composeHorizon(horizon, technical, fundamentals, hurdle) {
  const appliesFundamentals = FUNDAMENTALS.appliesToHorizons.includes(horizon)
  const fundamentalsView = { stance: fundamentals?.stance ?? 'unavailable', applied: appliesFundamentals }
  if (!technical?.available || !technical.action) {
    return {
      technical: technical ?? null,
      fundamentals: fundamentalsView,
      final_action: null,
      adjustments: [{ layer: 'technical', from: null, to: null, reason: 'technical_unavailable', detail: null }],
    }
  }

  const adjustments = []
  let action = technical.action
  if (appliesFundamentals && fundamentals?.stance === 'weak' && FUNDAMENTALS.stepDown[action]) {
    const next = FUNDAMENTALS.stepDown[action]
    adjustments.push({ layer: 'fundamentals', from: action, to: next, reason: 'fundamentals_weak', detail: null })
    action = next
  }

  // Fail closed: a missing or unfinished hurdle never lets a buy through.
  const hurdleStatus = hurdle?.status ?? 'unavailable'
  if (BUY_FAMILY.has(action) && hurdleStatus !== 'pass' && hurdleStatus !== 'not_applicable') {
    adjustments.push({
      layer: 'index_hurdle',
      from: action,
      to: 'hold',
      reason: hurdleStatus === 'unavailable' ? 'index_hurdle_unavailable' : 'index_hurdle_failed',
      detail: hurdleDetail(hurdle),
    })
    action = 'hold'
  }

  return { technical, fundamentals: fundamentalsView, final_action: action, adjustments }
}

export function buildConsolidatedDecision({ technical = null, fundamentals = null, hurdle = null, errors = null } = {}) {
  const horizons = Object.fromEntries(
    config.horizons.map((horizon) => [horizon, composeHorizon(horizon, technical?.horizons?.[horizon] ?? null, fundamentals, hurdle)]),
  )
  return {
    version: config.version,
    producer: technical?.producer ?? null,
    generated_at: new Date().toISOString(),
    current_price: technical?.currentPrice ?? null,
    horizons,
    index_hurdle: hurdle,
    fundamentals,
    data_quality: technical?.dataQuality ?? null,
    market_structure: technical?.marketStructure ?? null,
    errors,
  }
}
