const MAX_CANDIDATES = 5
const DAILY_RUN_LIMIT = 3
const MAX_ESTIMATED_COST_USD = 1
const ALLOWED_MODELS = new Set(['claude-sonnet-5', 'claude-haiku-4-5'])
const STAGES = ['discovering', 'verifying', 'reviewing', 'calculating']

function researchJson(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
    },
  })
}

function envBoolean(value) {
  return String(value ?? '').trim().toLowerCase() === 'true'
}

function modelStatus(env) {
  return String(env.RESEARCH_MODEL_STATUS ?? 'unavailable').trim().toLowerCase()
}

function researchGate(env) {
  if (!envBoolean(env.RESEARCH_DECISION_SUPPORT_ENABLED)) {
    return { ok: false, status: 503, detail: 'Research decision support is disabled' }
  }
  return { ok: true }
}

function configuredModels(env) {
  const models = {
    discovery: String(env.CURSOR_RESEARCH_DISCOVERY_MODEL ?? '').trim(),
    verification: String(env.CURSOR_RESEARCH_VERIFICATION_MODEL ?? '').trim(),
    review: String(env.CURSOR_RESEARCH_REVIEW_MODEL ?? '').trim(),
  }
  if (!env.CURSOR_API_KEY || Object.values(models).some((model) => !ALLOWED_MODELS.has(model))) {
    return null
  }
  return models
}

function estimateCost(maxCandidates) {
  return Number((0.2 + maxCandidates * 0.08 + 0.2).toFixed(2))
}

function validateJobInput(body) {
  const question = String(body?.question ?? '').trim()
  const mode = String(body?.mode ?? '').trim()
  const universe = String(body?.universe ?? '').trim()
  const analogy = body?.analogy == null ? null : String(body.analogy).trim()
  const maxCandidates = Number(body?.max_candidates ?? 5)
  if (!question || question.length > 2_000) return { error: 'question is required and must be at most 2000 characters' }
  if (!['upside_discovery', 'downside_risk_scan'].includes(mode)) {
    return { error: 'mode must be upside_discovery or downside_risk_scan' }
  }
  if (!universe || universe.length > 500) return { error: 'universe is required and must be at most 500 characters' }
  if (analogy && analogy.length > 240) return { error: 'analogy must be at most 240 characters' }
  if (!Number.isInteger(maxCandidates) || maxCandidates < 1 || maxCandidates > MAX_CANDIDATES) {
    return { error: `max_candidates must be an integer from 1 to ${MAX_CANDIDATES}` }
  }
  const capital = body?.capital == null ? null : Number(body.capital)
  if (capital != null && (!Number.isFinite(capital) || capital <= 0)) return { error: 'capital must be positive' }
  const estimatedCostUsd = estimateCost(maxCandidates)
  if (estimatedCostUsd > MAX_ESTIMATED_COST_USD) return { error: 'estimated research usage exceeds the $1 limit' }
  return {
    value: {
      question,
      mode,
      universe,
      analogy,
      max_candidates: maxCandidates,
      capital,
      risk_profile: body?.risk_profile == null ? null : String(body.risk_profile).slice(0, 500),
      estimated_usage_usd: estimatedCostUsd,
    },
  }
}

function clientIp(request) {
  return request.headers.get('cf-connecting-ip') || request.headers.get('x-forwarded-for')?.split(',')[0]?.trim() || 'unknown'
}

async function hashClientIp(request) {
  const bytes = new TextEncoder().encode(clientIp(request))
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, '0')).join('')
}

async function callQuota(namespace, ipHash, operation, jobId = '') {
  if (!namespace) return { ok: false, reason: 'Research quota storage is not configured' }
  const stub = namespace.get(namespace.idFromName(ipHash))
  const response = await stub.fetch('https://research-quota.local/', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ operation, job_id: jobId }),
  })
  return response.json()
}

async function getJobStub(namespace, jobId) {
  if (!namespace) throw new Error('Research job storage is not configured')
  return namespace.get(namespace.idFromName(jobId))
}

export async function handleResearchRoute(pathname, request, env = {}) {
  if (pathname === '/research/jobs' && request.method === 'POST') {
    const gate = researchGate(env)
    if (!gate.ok) return researchJson({ detail: gate.detail, model_status: modelStatus(env) }, gate.status)
    const body = await request.json().catch(() => null)
    const parsed = validateJobInput(body)
    if (parsed.error) return researchJson({ detail: parsed.error }, 400)
    if (!configuredModels(env)) return researchJson({ detail: 'Allowed Cursor research models are not configured' }, 503)

    const ipHash = await hashClientIp(request)
    const jobId = crypto.randomUUID()
    const quota = await callQuota(env.RESEARCH_RATE_LIMITER, ipHash, 'acquire', jobId)
    if (!quota.ok) return researchJson({ detail: quota.reason ?? 'Research quota exceeded' }, 429)

    try {
      const stub = await getJobStub(env.RESEARCH_JOBS, jobId)
      const response = await stub.fetch('https://research-job.local/start', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ job_id: jobId, ip_hash: ipHash, input: parsed.value }),
      })
      if (!response.ok) {
        await callQuota(env.RESEARCH_RATE_LIMITER, ipHash, 'release', jobId)
        return researchJson({ detail: 'Research job could not be started' }, 500)
      }
      return researchJson(await response.json(), 202)
    } catch {
      await callQuota(env.RESEARCH_RATE_LIMITER, ipHash, 'release', jobId)
      return researchJson({ detail: 'Research job could not be started' }, 500)
    }
  }

  const match = pathname.match(/^\/research\/jobs\/([^/]+)(?:\/(cancel))?$/)
  if (!match) return researchJson({ detail: `Unhandled research route ${pathname}` }, 404)
  const jobId = decodeURIComponent(match[1])
  const stub = await getJobStub(env.RESEARCH_JOBS, jobId)
  if (match[2] === 'cancel') {
    if (request.method !== 'POST') return researchJson({ detail: 'Method not allowed' }, 405)
    return researchJson(await (await stub.fetch('https://research-job.local/cancel', { method: 'POST' })).json())
  }
  if (request.method !== 'GET') return researchJson({ detail: 'Method not allowed' }, 405)
  return researchJson(await (await stub.fetch('https://research-job.local/status')).json())
}

export class ResearchRateLimiter {
  constructor(state) {
    this.state = state
  }

  async fetch(request) {
    const body = await request.json().catch(() => null)
    const currentDay = new Date().toISOString().slice(0, 10)
    const current = (await this.state.storage.get('quota')) ?? { day: currentDay, runs: 0, activeJobId: null }
    if (current.day !== currentDay) {
      current.day = currentDay
      current.runs = 0
      current.activeJobId = null
    }
    if (body?.operation === 'acquire') {
      if (current.activeJobId) return researchJson({ ok: false, reason: 'Only one active research run is allowed per IP' }, 429)
      if (current.runs >= DAILY_RUN_LIMIT) return researchJson({ ok: false, reason: 'Daily research quota exceeded' }, 429)
      current.runs += 1
      current.activeJobId = body.job_id ?? 'pending'
      await this.state.storage.put('quota', current)
      return researchJson({ ok: true })
    }
    if (body?.operation === 'release' && (!body.job_id || current.activeJobId === body.job_id)) {
      current.activeJobId = null
      await this.state.storage.put('quota', current)
      return researchJson({ ok: true })
    }
    return researchJson({ ok: false, reason: 'Invalid quota operation' }, 400)
  }
}

function initialJobState(input) {
  return {
    status: 'queued',
    progress: 0,
    current_stage: 'queued',
    candidate_progress: { completed: 0, total: input.max_candidates },
    elapsed_seconds: 0,
    estimated_usage_usd: input.estimated_usage_usd,
    input,
    result: null,
    error: null,
  }
}

function textValue(value, fallback = '') {
  const text = typeof value === 'string' ? value.trim() : ''
  return text || fallback
}

function evidenceIds(value, fallback = []) {
  const ids = Array.isArray(value) ? value.filter((item) => typeof item === 'string' && item.trim()).map((item) => item.trim()) : []
  return ids.length ? [...new Set(ids)] : fallback
}

function researchPoint(value, fallbackStatement, fallbackEvidenceIds) {
  if (typeof value === 'string' && value.trim()) {
    return { statement: value.trim(), evidence_ids: fallbackEvidenceIds }
  }
  if (!value || typeof value !== 'object') {
    return fallbackStatement ? { statement: fallbackStatement, evidence_ids: fallbackEvidenceIds } : null
  }
  const statement = textValue(value.statement, fallbackStatement)
  if (!statement) return null
  return {
    statement,
    evidence_ids: evidenceIds(value.evidence_ids, fallbackEvidenceIds),
  }
}

function researchPoints(value, fallbacks, fallbackEvidenceIds) {
  const values = Array.isArray(value) ? value : []
  const points = values.map((item) => researchPoint(item, '', fallbackEvidenceIds)).filter(Boolean)
  if (points.length) return points
  return fallbacks.map((item) => researchPoint(item, item, fallbackEvidenceIds)).filter(Boolean)
}

function statementValue(value, fallback) {
  return typeof value === 'object' && value !== null
    ? textValue(value.statement, fallback)
    : textValue(value, fallback)
}

function normalizeDiscovery(discovery) {
  const evidence = Array.isArray(discovery?.evidence) ? discovery.evidence : []
  const candidates = Array.isArray(discovery?.candidates)
    ? discovery.candidates
        .map((candidate, index) => ({
          ...candidate,
          rank: Number.isInteger(candidate?.rank) && candidate.rank > 0 ? candidate.rank : index + 1,
          symbol: textValue(candidate?.symbol).toUpperCase(),
          company_name: textValue(candidate?.company_name, textValue(candidate?.symbol)),
          thesis: textValue(candidate?.thesis, 'No thesis supplied.'),
          demand_driver: textValue(candidate?.demand_driver, 'No demand driver supplied.'),
          evidence_ids: evidenceIds(candidate?.evidence_ids),
          disqualifiers: Array.isArray(candidate?.disqualifiers)
            ? candidate.disqualifiers.filter((item) => typeof item === 'string' && item.trim())
            : [],
        }))
        .filter((candidate) => candidate.symbol)
        .sort((left, right) => left.rank - right.rank)
    : []
  return { ...(discovery && typeof discovery === 'object' ? discovery : {}), candidates, evidence }
}

function candidateReviewFor(candidate, verification, review) {
  const matchesCandidate = (item) => String(item?.symbol ?? '').toUpperCase() === candidate.symbol
  const verificationReviews = Array.isArray(verification?.candidate_reviews) ? verification.candidate_reviews : []
  const reviewReviews = Array.isArray(review?.candidate_reviews) ? review.candidate_reviews : []
  const verificationReview = verificationReviews.find(matchesCandidate)
    ?? (verification?.candidate_review && matchesCandidate(verification.candidate_review) ? verification.candidate_review : null)
  const reviewReview = reviewReviews.find(matchesCandidate)
  const analysisVerdict = review?.analysis_verdict
    && String(review.analysis_verdict?.candidate?.symbol ?? '').toUpperCase() === candidate.symbol
    ? review.analysis_verdict
    : null
  return { ...(verificationReview ?? {}), ...(reviewReview ?? {}), ...(analysisVerdict ?? {}) }
}

function buildDecisionSupport(candidate, discovery, verification, review) {
  const candidateReview = candidateReviewFor(candidate, verification, review)
  const candidateEvidence = Array.isArray(discovery.evidence)
    ? discovery.evidence.filter((item) => candidate.evidence_ids.includes(item?.id))
    : []
  const knownEvidenceIds = candidate.evidence_ids
  const reviewData = candidateReview
  return {
    contract_version: 'stock_research_v1',
    candidate_rank: candidate.rank,
    symbol: candidate.symbol,
    analogy_comparison: researchPoint(reviewData.analogy_comparison, '', knownEvidenceIds),
    thesis: statementValue(reviewData.thesis, candidate.thesis),
    catalysts: researchPoints(reviewData.catalysts, [candidate.demand_driver], knownEvidenceIds),
    risks: researchPoints(reviewData.risks, candidate.disqualifiers, knownEvidenceIds),
    entry_conditions: researchPoints(reviewData.entry_conditions, [], knownEvidenceIds),
    reasons_to_avoid: researchPoints(reviewData.reasons_to_avoid, candidate.disqualifiers, knownEvidenceIds),
    evidence: candidateEvidence,
    unknowns: Array.isArray(reviewData.unknowns) ? reviewData.unknowns.filter((item) => typeof item === 'string') : [],
    review_verdict: textValue(reviewData.verdict, textValue(review?.verdict, 'needs_more_evidence')),
    review_risk_summary: textValue(reviewData.risk_summary, textValue(review?.risk_summary, 'Review details unavailable.')),
    entry_assessment: 'unavailable',
  }
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds))
}

async function cursorJson(env, stage, prompt, requireWebSearch) {
  const models = configuredModels(env)
  if (!models) throw new Error('Allowed Cursor research models are not configured')
  const response = await fetch('https://api.cursor.com/v1/agents', {
    method: 'POST',
    headers: { authorization: `Bearer ${env.CURSOR_API_KEY}`, 'content-type': 'application/json' },
    body: JSON.stringify({
      prompt: {
        text: [
          'talk like caveman: You are a no-repo equity research agent.',
          requireWebSearch ? 'Use public web research and include source URLs.' : 'Use only the supplied evidence.',
          'Return valid JSON only. Do not give price targets or direct trading instructions.',
          prompt,
        ].join('\n\n'),
      },
      model: { id: models[stage] },
      repos: [],
      mode: 'agent',
    }),
  })
  if (!response.ok) throw new Error(`Cursor request failed with HTTP ${response.status}`)
  const created = await response.json()
  const agentId = created?.agent?.id
  const runId = created?.run?.id
  if (!agentId || !runId) throw new Error('Cursor response did not include a run')
  const deadline = Date.now() + 240_000
  while (Date.now() < deadline) {
    await sleep(2_000)
    const runResponse = await fetch(`https://api.cursor.com/v1/agents/${agentId}/runs/${runId}`, {
      headers: { authorization: `Bearer ${env.CURSOR_API_KEY}` },
    })
    if (!runResponse.ok) throw new Error(`Cursor polling failed with HTTP ${runResponse.status}`)
    const run = await runResponse.json()
    if (run.status === 'FINISHED') {
      if (typeof run.result !== 'string') throw new Error('Cursor returned no final result')
      try {
        return JSON.parse(run.result.replace(/^```(?:json)?\s*|\s*```$/g, '').trim())
      } catch {
        throw new Error('Cursor returned invalid JSON')
      }
    }
    if (['ERROR', 'CANCELLED', 'EXPIRED'].includes(run.status)) throw new Error(`Cursor run ended with status ${run.status}`)
  }
  throw new Error('Cursor research run timed out')
}

async function runResearch(state, env, jobId, ipHash, input) {
  const startedAt = Date.now()
  const update = async (next) => {
    const current = (await state.storage.get('job')) ?? initialJobState(input)
    await state.storage.put('job', { ...current, ...next, elapsed_seconds: Math.floor((Date.now() - startedAt) / 1000) })
  }
  const ensureNotCancelled = async () => {
    const current = await state.storage.get('job')
    if (current?.status === 'cancelled') throw new Error('Research cancelled')
  }
  try {
    await update({ status: 'discovering', progress: 10, current_stage: STAGES[0] })
    const discovery = normalizeDiscovery(
      await cursorJson(
        env,
        'discovery',
        JSON.stringify({
          ...input,
          output_contract: {
            contract_version: 'stock_research_v1',
            candidates: 'ranked 1..N; each has symbol, company_name, thesis, demand_driver, evidence_ids, disqualifiers',
            evidence: 'source records with id, title, url, evidence_type, excerpt',
            unknowns: 'explicit unresolved questions',
          },
        }),
        true,
      ),
    )
    await ensureNotCancelled()
    const candidates = Array.isArray(discovery?.candidates) ? discovery.candidates.slice(0, input.max_candidates) : []
    if (!candidates.length) throw new Error('Discovery returned no candidates')

    await update({ status: 'verifying', progress: 35, current_stage: STAGES[1], candidate_progress: { completed: 0, total: candidates.length } })
    const verification = await cursorJson(
      env,
      'verification',
      JSON.stringify({
        input,
        candidates,
        evidence: discovery.evidence ?? [],
        output_contract: {
          candidate_reviews: 'one per candidate with symbol, thesis, analogy_comparison, catalysts, risks, entry_conditions, reasons_to_avoid, unknowns',
          all_points: 'objects with statement and evidence_ids from supplied evidence',
          no_personalized_allocation: true,
        },
      }),
      false,
    )
    await ensureNotCancelled()
    await update({ status: 'reviewing', progress: 65, current_stage: STAGES[2], candidate_progress: { completed: candidates.length, total: candidates.length } })
    const review = await cursorJson(
      env,
      'review',
      JSON.stringify({
        input,
        candidates,
        verification,
        output_contract: {
          verdict: 'supported, needs_more_evidence, or reject',
          candidate_reviews: 'one per candidate with symbol, verdict, unsupported_claims, missing_evidence, risk_summary',
        },
      }),
      false,
    )
    await ensureNotCancelled()
    await update({ status: 'calculating', progress: 85, current_stage: STAGES[3] })

    const artifact = (() => {
      try {
        return env.RESEARCH_MODEL_ARTIFACT ? JSON.parse(env.RESEARCH_MODEL_ARTIFACT) : null
      } catch {
        return null
      }
    })()
    const forecasts = artifact?.calibration_status === 'validated' && artifact?.predictions && typeof artifact.predictions === 'object' ? artifact.predictions : {}
    const results = candidates.map((candidate) => ({
      ...candidate,
      decision_support: buildDecisionSupport(candidate, discovery, verification, review),
      forecast: forecasts[candidate.symbol] ?? null,
      forecast_status: forecasts[candidate.symbol] ? 'validated' : 'unavailable',
      verification,
      review,
    }))
    await update({
      status: 'completed',
      progress: 100,
      current_stage: 'completed',
      result: { model_status: modelStatus(env), model_version: artifact?.model_version ?? null, results },
    })
  } catch (error) {
    if (error instanceof Error && error.message === 'Research cancelled') return
    await update({ status: 'failed', progress: 100, current_stage: 'failed', error: error instanceof Error ? error.message : 'Research failed' })
  } finally {
    await callQuota(env.RESEARCH_RATE_LIMITER, ipHash, 'release', jobId).catch(() => null)
  }
}

export class ResearchJob {
  constructor(state, env) {
    this.state = state
    this.env = env
  }

  async fetch(request) {
    const pathname = new URL(request.url).pathname.replace(/\/+$/, '') || '/'
    if (pathname === '/start' && request.method === 'POST') {
      const payload = await request.json().catch(() => null)
      const input = payload?.input
      if (!payload?.job_id || !payload?.ip_hash || !input) return researchJson({ detail: 'Invalid research job payload' }, 400)
      const job = { ...initialJobState(input), id: payload.job_id, ip_hash: payload.ip_hash }
      await this.state.storage.put('job', job)
      const runner = runResearch(this.state, this.env, payload.job_id, payload.ip_hash, input)
      if (typeof this.state.waitUntil === 'function') this.state.waitUntil(runner)
      else await runner
      return researchJson({ id: payload.job_id, ...job })
    }
    if (pathname === '/cancel' && request.method === 'POST') {
      const job = await this.state.storage.get('job')
      if (!job) return researchJson({ detail: 'Research job not found' }, 404)
      if (['completed', 'failed', 'cancelled'].includes(job.status)) return researchJson(job)
      const cancelled = { ...job, status: 'cancelled', progress: 100, current_stage: 'cancelled', error: 'Cancelled by user' }
      await this.state.storage.put('job', cancelled)
      await callQuota(this.env.RESEARCH_RATE_LIMITER, job.ip_hash, 'release', job.id).catch(() => null)
      return researchJson(cancelled)
    }
    if (pathname === '/status' && request.method === 'GET') {
      const job = await this.state.storage.get('job')
      return researchJson(job ?? { detail: 'Research job not found' }, job ? 200 : 404)
    }
    return researchJson({ detail: 'Unhandled research job route' }, 404)
  }
}

export const __researchTestOnly = {
  MAX_CANDIDATES,
  DAILY_RUN_LIMIT,
  MAX_ESTIMATED_COST_USD,
  buildDecisionSupport,
  normalizeDiscovery,
  researchGate,
  validateJobInput,
}
