// The seam where an external technical engine replaces the local one.
//
// Mirrors analyst_service/core/technical_provider.py. Ryan and Vincent agreed on
// 2026-08-28 that Vincent's technical analysis system supplies the technical
// layer while every other layer stays here. Keep the two files in step: the
// action map, the legality table and the confidence rescale must match exactly,
// or the Worker and the Python service will disagree about the same payload.

// decision.v1 has seven actions; Direction has three. accumulate and trim have
// no local source at all, which is why they arrive from Vincent's side.
export const ACTION_TO_DIRECTION = {
  strong_buy: 'BUY',
  buy: 'BUY',
  accumulate: 'BUY',
  hold: 'HOLD',
  trim: 'SELL',
  sell: 'SELL',
  // NOT SELL. His AGENTS.md: "Avoid is not Sell and must not produce a fake
  // exit plan." Avoid means do not enter; projecting it onto SELL would tell an
  // existing holder to exit. The distinction survives in `action` and
  // `execution_intent`, which the three-way Direction cannot express.
  avoid: 'HOLD',
}

// His executionIntent mapping, transcribed from execution-engine.js.
export const ACTION_TO_EXECUTION_INTENT = {
  strong_buy: 'enter',
  buy: 'enter',
  accumulate: 'add',
  hold: 'hold',
  trim: 'reduce',
  sell: 'exit',
  avoid: 'avoid',
}

// The legality table from the decision.v1 contract.
export const LEGAL_ACTIONS = {
  IN_OPPORTUNITY_ZONE: ['strong_buy', 'buy', 'accumulate'],
  NEAR_OPPORTUNITY_ZONE: ['hold'],
  NEUTRAL_ZONE: ['hold'],
  NEAR_REDUCE_ZONE: ['hold'],
  IN_REDUCE_ZONE: ['trim', 'sell'],
  BEYOND_REDUCE_ZONE: ['trim', 'sell'],
  BREAKDOWN_ZONE: ['sell', 'avoid'],
  INVALID_LANDSCAPE: ['hold', 'avoid'],
}

// Dimension keys that belong to the technical block in signal_weights.yaml.
export const LOCAL_TECHNICAL_DIMENSIONS = [
  'RSI_14',
  'MACD',
  'Bollinger_Bands',
  'Volume',
  'MA_50_200',
  'RSI_Weekly',
  'Support_Resistance',
]

export const EXTERNAL_TECHNICAL_DIMENSION = 'Technical_External'

// Vincent's engine emits independent short/mid/long verdicts. These three
// Horizon values are what "short/mid/long" mean here; 1D is Ryan's day-trade
// horizon and has no decision.v1 counterpart, so it is excluded.
export const SHORT_MID_LONG_HORIZONS = ['1W', '2-4W', '3-6M']

// Sum of the technical entries in signal_weights.yaml. Keeping the total
// identical means swapping the technical producer does not also change the
// technical-to-fundamental balance.
export const EXTERNAL_TECHNICAL_WEIGHT = 7.6

export class TechnicalVerdictError extends Error {}

function readRange(raw, label) {
  if (raw == null) return null
  const low = Number(raw.low)
  const high = Number(raw.high)
  if (!Number.isFinite(low) || !Number.isFinite(high)) {
    throw new TechnicalVerdictError(`${label} needs numeric low and high`)
  }
  if (low >= high) {
    throw new TechnicalVerdictError(`${label}.low must be below ${label}.high`)
  }
  return { low, high }
}

// `null`/undefined means "no invalidation level", matching Python's
// `invalidation: float | None`. Number(null) is 0, so that case must be
// checked explicitly or a real level gets fabricated where none was given.
function readInvalidation(raw) {
  if (raw === null || raw === undefined) return null
  const value = Number(raw)
  if (!Number.isFinite(value)) {
    throw new TechnicalVerdictError('invalidation must be a number')
  }
  return value
}

// Python's `reasons: list[str]` rejects a non-list or a list with a non-string
// item outright; it does not quietly drop what does not fit.
function readReasons(raw) {
  if (raw === undefined) return []
  if (!Array.isArray(raw) || raw.some((item) => typeof item !== 'string')) {
    throw new TechnicalVerdictError('reasons must be an array of strings')
  }
  return raw
}

// Normalize a decision.v1 payload, or refuse it. Refusing matters more than
// accepting: a malformed payload that silently became a confident HOLD would be
// indistinguishable from a real opinion.
export function verdictFromExternal(payload) {
  if (payload == null || typeof payload !== 'object') {
    throw new TechnicalVerdictError('external technical verdict must be an object')
  }

  const action = payload.action
  if (typeof action !== 'string' || !(action in ACTION_TO_DIRECTION)) {
    throw new TechnicalVerdictError(`unknown decision.v1 action: ${String(action)}`)
  }

  const confidence = Number(payload.confidence)
  if (!Number.isFinite(confidence) || confidence < 0 || confidence > 100) {
    throw new TechnicalVerdictError('confidence must be a number between 0 and 100')
  }

  const priceState = payload.priceState ?? payload.price_state ?? null
  if (priceState != null) {
    const permitted = LEGAL_ACTIONS[priceState]
    if (permitted == null) {
      throw new TechnicalVerdictError(`unknown decision.v1 priceState: ${String(priceState)}`)
    }
    if (!permitted.includes(action)) {
      throw new TechnicalVerdictError(
        `action ${action} is not legal for ${priceState}; allowed: ${permitted.join(', ')}`,
      )
    }
  }

  const opportunityRange = readRange(payload.opportunityRange ?? payload.opportunity_range, 'opportunityRange')
  const reduceRange = readRange(payload.reduceRange ?? payload.reduce_range, 'reduceRange')
  if (opportunityRange && reduceRange && opportunityRange.high >= reduceRange.low) {
    throw new TechnicalVerdictError('opportunityRange.high must be below reduceRange.low')
  }

  // Python's `producer: str` has no length constraint, so an empty string is a
  // valid (if useless) value there. Rejecting it here would treat a payload as
  // malformed when analyst_service would have accepted it.
  if (typeof payload.producer !== 'string') {
    throw new TechnicalVerdictError('producer is required')
  }
  const producer = payload.producer

  const dataQualityRaw = payload.dataQuality ?? payload.data_quality
  let dataQuality = null
  if (dataQualityRaw != null) {
    dataQuality = Number(dataQualityRaw)
    // The contract's dataQuality is an integer, unlike confidence which is a
    // float: a fractional value like 88.5 is a producer bug, not a rounding
    // choice for this seam to make silently.
    if (!Number.isInteger(dataQuality) || dataQuality < 0 || dataQuality > 100) {
      throw new TechnicalVerdictError('dataQuality must be a whole number between 0 and 100')
    }
  }

  return {
    direction: ACTION_TO_DIRECTION[action],
    action,
    execution_intent: ACTION_TO_EXECUTION_INTENT[action],
    // decision.v1 is 0-100 and recommendation.confidence is 0.0-1.0. Skipping
    // this division yields 0.7 where 70 was meant, and looks plausible.
    confidence: confidence / 100,
    source: 'external',
    producer,
    price_state: priceState,
    opportunity_range: opportunityRange,
    reduce_range: reduceRange,
    invalidation: readInvalidation(payload.invalidation),
    reasons: readReasons(payload.reasons),
    data_quality: dataQuality,
  }
}

// Normalize a batch of per-horizon payloads for side-by-side reporting. Each
// horizon stands alone: a payload that fails decision.v1 validation is
// dropped rather than defaulted, so a partial engine outage yields fewer
// horizons rather than a fabricated one. Nothing here ranks or blends them.
export function resolveTechnicalVerdictsByHorizon(payloadsByHorizon) {
  const resolved = []
  for (const horizon of SHORT_MID_LONG_HORIZONS) {
    const payload = payloadsByHorizon[horizon]
    if (payload == null) continue
    try {
      resolved.push({ horizon, verdict: verdictFromExternal(payload) })
    } catch (error) {
      if (!(error instanceof TechnicalVerdictError)) throw error
      console.warn(`Rejected external technical verdict for ${horizon}, omitting: ${error.message}`)
    }
  }
  return resolved
}

export function isLocalTechnical(signal) {
  return LOCAL_TECHNICAL_DIMENSIONS.includes(signal.dimension)
}

// Summarize the locally computed technical signals. Returns null when there are
// none, so "no technical opinion" stays distinct from "the opinion is HOLD".
export function verdictFromLocal(signals) {
  const technical = signals.filter(isLocalTechnical)
  if (technical.length === 0) return null

  const totalWeight = technical.reduce((sum, signal) => sum + signal.weight, 0)
  if (totalWeight <= 0) return null

  const votes = { BUY: 0, HOLD: 0, SELL: 0 }
  for (const signal of technical) {
    votes[signal.signal] = (votes[signal.signal] ?? 0) + signal.weight
  }
  const direction = ['BUY', 'HOLD', 'SELL'].reduce((best, candidate) =>
    votes[candidate] > votes[best] ? candidate : best,
  )

  return {
    direction,
    confidence: votes[direction] / totalWeight,
    source: 'local',
    producer: null,
    reasons: technical.map((signal) => signal.note),
  }
}

export function synthesizeTechnicalSignal(verdict) {
  // `||`, not `??`: an empty-string producer is falsy in Python's
  // `verdict.producer or "external engine"` too, so both sides fall back the
  // same way instead of labeling a signal with an empty producer name.
  const producer = verdict.producer || 'external engine'
  const note = verdict.price_state
    ? `${producer}: ${verdict.direction} in ${verdict.price_state}`
    : `${producer}: ${verdict.direction}`
  return {
    dimension: EXTERNAL_TECHNICAL_DIMENSION,
    signal: verdict.direction,
    weight: EXTERNAL_TECHNICAL_WEIGHT,
    note,
  }
}

// Swap the local technical signals for the external verdict. Substitution, not
// averaging: when Vincent's verdict is present it is the technical vote.
export function substituteTechnicalSignals(signals, verdict) {
  const displaced = verdictFromLocal(signals)
  const retained = signals.filter((signal) => !isLocalTechnical(signal))
  return { signals: [...retained, synthesizeTechnicalSignal(verdict)], displaced }
}

// Normalize a supplied verdict, or degrade to local technicals visibly. A bad
// payload must not take the analysis down, and must not pass unnoticed either.
export function resolveTechnicalVerdict(supplied) {
  if (supplied == null) return { verdict: null, riskFlags: [] }
  try {
    return { verdict: verdictFromExternal(supplied), riskFlags: [] }
  } catch (error) {
    if (error instanceof TechnicalVerdictError) {
      console.warn(`Rejected external technical verdict, using local technicals: ${error.message}`)
      return { verdict: null, riskFlags: ['external_technical_rejected'] }
    }
    throw error
  }
}
