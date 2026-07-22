import { useState, type FormEvent } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { cancelResearchJob, fetchResearchJob, startResearchJob } from '../api/client'
import type { ResearchDecisionSupport, ResearchJobRequest, ResearchPoint } from '../api/types'

const terminalStatuses = new Set(['completed', 'failed', 'cancelled'])

function PointList({ title, points }: { title: string; points: ResearchPoint[] }) {
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
                  Evidence: {point.evidence_ids.join(', ')}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">No supported items returned.</p>
      )}
    </section>
  )
}

function DecisionCard({ decision }: { decision: ResearchDecisionSupport }) {
  return (
    <article className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-[#0d0f14]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">
            Rank {decision.candidate_rank} · {decision.symbol}
          </p>
          <h3 className="mt-1 text-xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">
            Decision support
          </h3>
        </div>
        <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-amber-800 dark:bg-amber-950 dark:text-amber-300">
          {decision.review_verdict.replaceAll('_', ' ')}
        </span>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <div className="space-y-4">
          {decision.analogy_comparison ? (
            <section className="rounded-2xl border border-blue-100 bg-blue-50 p-4 dark:border-blue-900 dark:bg-blue-950/40">
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-blue-700 dark:text-blue-300">
                Analogy comparison
              </p>
              <p className="mt-2 text-sm leading-relaxed text-blue-950 dark:text-blue-100">
                {decision.analogy_comparison.statement}
              </p>
            </section>
          ) : null}
          <section>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
              Thesis
            </p>
            <p className="mt-2 text-sm leading-relaxed text-slate-700 dark:text-slate-300">{decision.thesis}</p>
          </section>
          <PointList title="Catalysts" points={decision.catalysts} />
          <PointList title="Risks" points={decision.risks} />
        </div>
        <div className="space-y-4">
          <PointList title="Entry conditions" points={decision.entry_conditions} />
          <PointList title="Reasons to avoid" points={decision.reasons_to_avoid} />
          <section className="rounded-2xl bg-stone-50 p-4 dark:bg-[#161a23]">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
              Review risk
            </p>
            <p className="mt-2 text-sm leading-relaxed text-slate-600 dark:text-slate-400">
              {decision.review_risk_summary}
            </p>
          </section>
          {decision.unknowns.length ? (
            <section>
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
                Unknowns
              </p>
              <p className="mt-2 text-sm leading-relaxed text-slate-600 dark:text-slate-400">
                {decision.unknowns.join(' ')}
              </p>
            </section>
          ) : null}
          <section>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
              Sources
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
              )) : <p className="text-sm text-slate-500 dark:text-slate-400">No sources returned.</p>}
            </div>
          </section>
        </div>
      </div>
    </article>
  )
}

function Research() {
  const [jobId, setJobId] = useState<string | null>(null)
  const [question, setQuestion] = useState('Find companies with durable demand growth and explain what could invalidate the thesis.')
  const [analogy, setAnalogy] = useState('')
  const [universe, setUniverse] = useState('US-listed common stocks')
  const [mode, setMode] = useState<ResearchJobRequest['mode']>('upside_discovery')
  const [maxCandidates, setMaxCandidates] = useState(3)

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
      ...(analogy.trim() ? { analogy: analogy.trim() } : {}),
      max_candidates: maxCandidates,
    })
  }

  const job = jobQuery.data
  const isActive = Boolean(job && !terminalStatuses.has(job.status))

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-[#0d0f14]">
        <div className="max-w-3xl">
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
            Research lab
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">
            Evidence before conviction
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-slate-600 dark:text-slate-400">
            Ask for ranked candidates, analogy comparisons, catalysts, risks, entry conditions, and reasons to avoid. Research output is decision support, not guaranteed returns or personalized allocation advice.
          </p>
        </div>

        <form onSubmit={submit} className="mt-6 space-y-4">
          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Question</span>
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
              <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Analogy lens</span>
              <input
                value={analogy}
                onChange={(event) => setAnalogy(event.target.value)}
                maxLength={240}
                placeholder="Optional: Sandisk"
                className="mt-2 w-full rounded-2xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-slate-900 focus:ring-2 focus:ring-slate-200 dark:border-slate-700 dark:bg-[#11151d] dark:text-slate-100 dark:focus:border-slate-300 dark:focus:ring-slate-800"
              />
            </label>
            <label className="block">
              <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Universe</span>
              <input
                value={universe}
                onChange={(event) => setUniverse(event.target.value)}
                maxLength={500}
                className="mt-2 w-full rounded-2xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-slate-900 focus:ring-2 focus:ring-slate-200 dark:border-slate-700 dark:bg-[#11151d] dark:text-slate-100 dark:focus:border-slate-300 dark:focus:ring-slate-800"
              />
            </label>
          </div>
          <div className="flex flex-wrap items-end gap-4">
            <label className="block">
              <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Mode</span>
              <select
                value={mode}
                onChange={(event) => setMode(event.target.value as ResearchJobRequest['mode'])}
                className="mt-2 rounded-2xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-[#11151d] dark:text-slate-100"
              >
                <option value="upside_discovery">Upside discovery</option>
                <option value="downside_risk_scan">Downside risk scan</option>
              </select>
            </label>
            <label className="block">
              <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Candidates</span>
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
              {startMutation.isPending ? 'Starting…' : 'Run research'}
            </button>
            {isActive ? (
              <button
                type="button"
                onClick={() => cancelMutation.mutate(job!.id)}
                disabled={cancelMutation.isPending}
                className="rounded-2xl border border-slate-300 px-5 py-3 text-sm font-semibold text-slate-700 transition hover:border-red-400 hover:text-red-700 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300"
              >
                Cancel
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
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">Job {job.id}</p>
              <p className="mt-1 text-sm font-medium text-slate-900 dark:text-slate-100">{job.current_stage.replaceAll('_', ' ')}</p>
            </div>
            <span className="text-sm font-semibold text-slate-600 dark:text-slate-300">{job.progress}% · {job.status}</span>
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
