import { useState, type FormEvent } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { cancelResearchJob, fetchResearchJob, startResearchJob } from '../api/client'
import type { ResearchDecisionSupport, ResearchJobRequest, ResearchPoint } from '../api/types'
import { useI18n } from '../i18n'
import { formatResearchStage, formatReviewVerdict } from '../formatters'

const terminalStatuses = new Set(['completed', 'failed', 'cancelled'])
const researchUniverses = [
  { labelKey: 'usCommon', value: 'US-listed common stocks' },
  {
    labelKey: 'usCommonAbove10b',
    value: 'US-listed common stocks with market capitalization above USD 10 billion',
  },
  { labelKey: 'sp500', value: 'S&P 500 constituents' },
  { labelKey: 'nasdaq100', value: 'Nasdaq-100 constituents' },
  { labelKey: 'russell1000', value: 'Russell 1000 constituents' },
  { labelKey: 'russell2000', value: 'Russell 2000 constituents' },
  { labelKey: 'dowJones', value: 'Dow Jones Industrial Average constituents' },
] as const

function PointList({ title, points }: { title: string; points: ResearchPoint[] }) {
  const { t } = useI18n()
  return (
    <section>
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
        {title}
      </p>
      {points.length ? (
        <ul className="mt-2 space-y-2">
          {points.map((point, index) => (
            <li key={`${title}-${index}`} className="rounded-xl bg-slate-50 px-3 py-2 text-sm leading-relaxed text-slate-700 dark:bg-[#161a23] dark:text-slate-300">
              {point.statement}
              {point.evidence_ids.length ? (
                <span className="mt-1 block text-[11px] font-medium text-slate-400 dark:text-slate-500">
                  {t('evidence')}: {point.evidence_ids.join(', ')}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">{t('noSupportedItems')}</p>
      )}
    </section>
  )
}

function DecisionCard({ decision }: { decision: ResearchDecisionSupport }) {
  const { t, locale } = useI18n()
  return (
    <article className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-[#0d0f14]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">
            {t('rank')} {decision.candidate_rank} · {decision.symbol}
          </p>
          <h3 className="mt-1 text-xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">
            {t('decisionSupport')}
          </h3>
        </div>
        <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-amber-800 dark:bg-amber-950 dark:text-amber-300">
          {formatReviewVerdict(decision.review_verdict, locale)}
        </span>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <div className="space-y-4">
          {decision.analogy_comparison ? (
            <section className="rounded-2xl border border-blue-100 bg-blue-50 p-4 dark:border-blue-900 dark:bg-blue-950/40">
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-blue-700 dark:text-blue-300">
                {t('analogyComparison')}
              </p>
              <p className="mt-2 text-sm leading-relaxed text-blue-950 dark:text-blue-100">
                {decision.analogy_comparison.statement}
              </p>
            </section>
          ) : null}
          <section>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
              {t('thesis')}
            </p>
            <p className="mt-2 text-sm leading-relaxed text-slate-700 dark:text-slate-300">{decision.thesis}</p>
          </section>
          <PointList title={t('catalysts')} points={decision.catalysts} />
          <PointList title={t('risks')} points={decision.risks} />
        </div>
        <div className="space-y-4">
          <PointList title={t('entryConditions')} points={decision.entry_conditions} />
          <PointList title={t('reasonsToAvoid')} points={decision.reasons_to_avoid} />
          <section className="rounded-2xl bg-stone-50 p-4 dark:bg-[#161a23]">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
              {t('reviewRisk')}
            </p>
            <p className="mt-2 text-sm leading-relaxed text-slate-600 dark:text-slate-400">
              {decision.review_risk_summary}
            </p>
          </section>
          {decision.unknowns.length ? (
            <section>
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
                {t('unknowns')}
              </p>
              <p className="mt-2 text-sm leading-relaxed text-slate-600 dark:text-slate-400">
                {decision.unknowns.join(' ')}
              </p>
            </section>
          ) : null}
          <section>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
              {t('sources')}
            </p>
            <div className="mt-2 space-y-2">
              {decision.evidence.length ? decision.evidence.map((source) => (
                <a
                  key={source.id}
                  href={source.url}
                  target="_blank"
                  rel="noreferrer"
                  className="block truncate text-sm font-medium text-blue-700 hover:underline dark:text-blue-300"
                >
                  {source.title ?? source.id}
                </a>
              )) : <p className="text-sm text-slate-500 dark:text-slate-400">{t('noSources')}</p>}
            </div>
          </section>
        </div>
      </div>
    </article>
  )
}

function Research() {
  const { t, locale } = useI18n()
  const [jobId, setJobId] = useState<string | null>(null)
  const [question, setQuestion] = useState('Find companies with durable demand growth and explain what could invalidate the thesis.')
  const [universe, setUniverse] = useState('US-listed common stocks')
  const [mode, setMode] = useState<ResearchJobRequest['mode']>('upside_discovery')
  const [maxCandidates, setMaxCandidates] = useState(3)
  const [riskProfile, setRiskProfile] = useState('')

  const jobQuery = useQuery({
    queryKey: ['research-job', jobId],
    queryFn: () => fetchResearchJob(jobId!),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && terminalStatuses.has(status) ? false : 2000
    },
    refetchOnWindowFocus: false,
  })

  const startMutation = useMutation({
    mutationFn: startResearchJob,
    onSuccess: (job) => setJobId(job.id),
  })

  const cancelMutation = useMutation({
    mutationFn: cancelResearchJob,
    onSuccess: () => void jobQuery.refetch(),
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    startMutation.mutate({
      question: question.trim(),
      mode,
      universe: universe.trim(),
      max_candidates: maxCandidates,
      ...(riskProfile.trim() ? { risk_profile: riskProfile.trim() } : {}),
    })
  }

  const job = jobQuery.data
  const isActive = Boolean(job && !terminalStatuses.has(job.status))

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-[#0d0f14] sm:p-6">
        <div className="max-w-3xl">
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
            {t('researchLab')}
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">
            {t('evidenceBeforeConviction')}
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-slate-600 dark:text-slate-400">
            {t('researchDescription')}
          </p>
        </div>

        <form onSubmit={submit} className="mt-6 space-y-4">
          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{t('question')}</span>
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              rows={3}
              maxLength={2000}
              className="mt-2 w-full rounded-2xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-slate-900 focus:ring-2 focus:ring-slate-200 dark:border-slate-700 dark:bg-[#11151d] dark:text-slate-100 dark:focus:border-slate-300 dark:focus:ring-slate-800"
            />
          </label>
          <div className="grid gap-4 md:grid-cols-2">
            <label className="block">
              <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{t('universeLabel')}</span>
              <select
                value={universe}
                onChange={(event) => setUniverse(event.target.value)}
                className="mt-2 w-full rounded-2xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-slate-900 focus:ring-2 focus:ring-slate-200 dark:border-slate-700 dark:bg-[#11151d] dark:text-slate-100 dark:focus:border-slate-300 dark:focus:ring-slate-800"
              >
                {researchUniverses.map((option) => (
                  <option key={option.value} value={option.value}>{t(option.labelKey)}</option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{t('triggerContext')}</span>
              <input
                value={riskProfile}
                onChange={(event) => setRiskProfile(event.target.value)}
                maxLength={500}
                placeholder={t('optionalTrigger')}
                className="mt-2 w-full rounded-2xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-slate-900 focus:ring-2 focus:ring-slate-200 dark:border-slate-700 dark:bg-[#11151d] dark:text-slate-100 dark:focus:border-slate-300 dark:focus:ring-slate-800"
              />
            </label>
          </div>
          <div className="flex flex-wrap items-end gap-4">
            <label className="block">
              <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{t('mode')}</span>
              <select
                value={mode}
                onChange={(event) => setMode(event.target.value as ResearchJobRequest['mode'])}
                className="mt-2 rounded-2xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-[#11151d] dark:text-slate-100"
              >
                <option value="upside_discovery">{t('upsideDiscovery')}</option>
                <option value="downside_risk_scan">{t('downsideRiskScan')}</option>
              </select>
            </label>
            <label className="block">
              <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{t('candidates')}</span>
              <select
                value={maxCandidates}
                onChange={(event) => setMaxCandidates(Number(event.target.value))}
                className="mt-2 rounded-2xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-[#11151d] dark:text-slate-100"
              >
                {[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
            <button
              type="submit"
              disabled={startMutation.isPending || isActive || !question.trim() || !universe.trim()}
              className="rounded-2xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-slate-100 dark:text-slate-950 dark:hover:bg-white"
            >
              {startMutation.isPending ? t('starting') : t('runResearch')}
            </button>
            {isActive ? (
              <button
                type="button"
                onClick={() => cancelMutation.mutate(job!.id)}
                disabled={cancelMutation.isPending}
                className="rounded-2xl border border-slate-300 px-5 py-3 text-sm font-semibold text-slate-700 transition hover:border-red-400 hover:text-red-700 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300"
              >
                {t('cancel')}
              </button>
            ) : null}
          </div>
        </form>

        {startMutation.isError ? <p className="mt-4 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">{startMutation.error.message}</p> : null}
        {jobQuery.isError ? <p className="mt-4 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">{jobQuery.error.message}</p> : null}
      </section>

      {job ? (
        <section className="rounded-3xl border border-slate-200 bg-stone-50 p-5 shadow-sm dark:border-slate-800 dark:bg-[#0d0f14]">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">{t('job')} {job.id}</p>
              <p className="mt-1 text-sm font-medium text-slate-900 dark:text-slate-100">{formatResearchStage(job.current_stage, locale)}</p>
            </div>
            <span className="text-sm font-semibold text-slate-600 dark:text-slate-300">{job.progress}% · {formatResearchStage(job.status, locale)}</span>
          </div>
          <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
            <div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${job.progress}%` }} />
          </div>
          {job.error ? <p className="mt-4 text-sm text-red-700 dark:text-red-300">{job.error}</p> : null}
        </section>
      ) : null}

      {job?.status === 'completed' && job.result ? (
        <div className="space-y-4">
          {job.result.results.map((candidate) => <DecisionCard key={candidate.symbol} decision={candidate.decision_support} />)}
        </div>
      ) : null}
    </div>
  )
}

export default Research
