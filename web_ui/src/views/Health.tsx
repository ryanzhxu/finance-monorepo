import { useQuery } from '@tanstack/react-query'
import { fetchAnalystHealth, fetchScreenerHealth } from '../api/client'
import type { AnalystHealthResponse, ScreenerHealthResponse } from '../api/types'

function ServiceCard({
  title,
  data,
  error,
  loading,
}: {
  title: string
  data: AnalystHealthResponse | ScreenerHealthResponse | undefined
  error: Error | null
  loading: boolean
}) {
  const isUp = !!data && data.status === 'ok'

  return (
    <article className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">{title}</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">
            {data?.service ?? title}
          </h2>
        </div>
        <div className="flex flex-wrap gap-2">
          <span
            className={[
              'rounded-full px-3 py-1 text-sm font-semibold',
              isUp ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700',
            ].join(' ')}
          >
            {isUp ? 'UP' : 'DOWN'}
          </span>
          <span className="rounded-full bg-stone-50 px-3 py-1 text-sm text-slate-700">
            LLM available {typeof data?.llm_available === 'boolean' ? String(data.llm_available) : '—'}
          </span>
        </div>
      </div>

      {loading ? <p className="mt-4 text-sm text-slate-500">Refreshing status...</p> : null}
      {error ? (
        <p className="mt-4 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700">{error.message}</p>
      ) : null}

      <div className="mt-5 grid gap-4 lg:grid-cols-[180px_1fr]">
        <div className="rounded-2xl bg-stone-50 px-4 py-3 text-sm text-slate-600">
          <p>Status {data?.status ?? 'unreachable'}</p>
          <p>Config valid {typeof data?.config_valid === 'boolean' ? String(data.config_valid) : '—'}</p>
          <p>Cache {data?.cache_backend ?? '—'}</p>
        </div>
        <div className="rounded-2xl border border-slate-200">
          <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
            <thead className="bg-stone-50 text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Provider</th>
                <th className="px-4 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {Object.entries(data?.providers ?? {}).map(([provider, status]) => (
                <tr key={provider}>
                  <td className="px-4 py-3 font-medium text-slate-900">{provider}</td>
                  <td className="px-4 py-3 text-slate-700">{status}</td>
                </tr>
              ))}
              {!data?.providers || Object.keys(data.providers).length === 0 ? (
                <tr>
                  <td colSpan={2} className="px-4 py-3 text-slate-500">
                    No provider data available.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
    </article>
  )
}

function Health() {
  const analystQuery = useQuery({
    queryKey: ['health', 'analyst'],
    queryFn: fetchAnalystHealth,
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
  })

  const screenerQuery = useQuery({
    queryKey: ['health', 'screener'],
    queryFn: fetchScreenerHealth,
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
  })

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-200 bg-[linear-gradient(135deg,rgba(15,23,42,0.96),rgba(51,65,85,0.96))] p-6 text-white shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-300">Health</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">Service heartbeat</h1>
        <p className="mt-2 max-w-2xl text-sm text-slate-300">
          Analyst and screener health checks refresh every 30 seconds without requiring a page reload.
        </p>
      </section>

      <div className="grid gap-6 xl:grid-cols-2">
        <ServiceCard
          title="Analyst"
          data={analystQuery.data}
          error={analystQuery.error ?? null}
          loading={analystQuery.isLoading}
        />
        <ServiceCard
          title="Screener"
          data={screenerQuery.data}
          error={screenerQuery.error ?? null}
          loading={screenerQuery.isLoading}
        />
      </div>
    </div>
  )
}

export default Health
