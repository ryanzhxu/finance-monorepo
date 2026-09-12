import { useEffect, useMemo, useState } from 'react'
import { fetchDecisions } from '../api/client'
import type { ConsolidatedHorizon, DecisionRow } from '../api/types'
import { useI18n, type MessageKey } from '../i18n'

// Matches the Worker's DECISIONS_MAX_SYMBOLS (cloudflare-api/src/index.js) —
// the subrequest budget for one /decisions request.
const CHUNK_SIZE = 3

const HORIZONS = [
  { key: 'short', title: 'horizonShort' },
  { key: 'mid', title: 'horizonMid' },
  { key: 'long', title: 'horizonLong' },
] as const

const ACTION_TONE: Record<string, string> = {
  strong_buy: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-500/20 dark:text-emerald-200',
  buy: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-500/20 dark:text-emerald-200',
  accumulate: 'bg-emerald-50 text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-300',
  hold: 'bg-amber-100 text-amber-900 dark:bg-amber-500/20 dark:text-amber-200',
  trim: 'bg-orange-100 text-orange-900 dark:bg-orange-500/20 dark:text-orange-200',
  sell: 'bg-rose-100 text-rose-900 dark:bg-rose-500/20 dark:text-rose-200',
  avoid: 'bg-slate-200 text-slate-700 dark:bg-slate-700/50 dark:text-slate-300',
}
const NEUTRAL_TONE = 'bg-slate-200 text-slate-700 dark:bg-slate-700/50 dark:text-slate-300'

const ACTION_KEYS: Record<string, MessageKey> = {
  strong_buy: 'actionStrongBuy',
  buy: 'actionBuy',
  accumulate: 'actionAccumulate',
  hold: 'actionHold',
  trim: 'actionTrim',
  sell: 'actionSell',
  avoid: 'actionAvoid',
}
const STANCE_KEYS: Record<string, MessageKey> = {
  supportive: 'stanceSupportive',
  neutral: 'stanceNeutral',
  weak: 'stanceWeak',
  unavailable: 'stanceUnavailable',
}
const STATUS_KEYS: Record<string, MessageKey> = {
  pass: 'hurdlePass',
  fail: 'hurdleFail',
  not_applicable: 'hurdleNotApplicable',
  unavailable: 'hurdleUnavailable',
}
const STATUS_TONE: Record<string, string> = {
  pass: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-500/20 dark:text-emerald-200',
  fail: 'bg-rose-100 text-rose-900 dark:bg-rose-500/20 dark:text-rose-200',
  not_applicable: NEUTRAL_TONE,
  unavailable: NEUTRAL_TONE,
}

// Sort order for the Decision Board: final buys first, then hold, then
// trim/sell/avoid. A row still loading or with no final action yet sorts
// after every resolved action but before an outright fetch error, so it does
// not jump ahead of a row we already know is a hold or worse.
const BUY_ACTIONS = new Set(['strong_buy', 'buy', 'accumulate'])
const TRIM_OR_WORSE_ACTIONS = new Set(['trim', 'sell', 'avoid'])
const RANK_UNRESOLVED = 3
const RANK_ERROR = 4

function actionRank(row: DecisionRow | undefined): number {
  if (!row) return RANK_UNRESOLVED
  if (row.error) return RANK_ERROR
  const action = row.consolidated_decision.horizons.mid.final_action
  if (action == null) return RANK_UNRESOLVED
  if (BUY_ACTIONS.has(action)) return 0
  if (TRIM_OR_WORSE_ACTIONS.has(action)) return 2
  return 1 // hold
}

// A row still loading passes the filter provisionally so it does not vanish
// and reappear once its data arrives.
function passesIndexHurdle(row: DecisionRow | undefined): boolean {
  if (!row) return true
  if (row.error) return false
  const status = row.consolidated_decision.index_hurdle?.status ?? 'unavailable'
  return status === 'pass' || status === 'not_applicable'
}

const money = (value: number | null | undefined): string =>
  value == null || Number.isNaN(value) ? '—' : `$${value.toFixed(2)}`

const readable = (value: string | null | undefined): string =>
  value ? value.toLowerCase().replace(/_/g, ' ') : '—'

const actionLabel = (t: (key: MessageKey, values?: Record<string, string | number>) => string, value: string | null | undefined): string => {
  if (!value) return '—'
  const key = ACTION_KEYS[value]
  return key ? t(key) : readable(value)
}

type DecisionBoardProps = {
  symbols: string[]
  onSelectSymbol?: (symbol: string) => void
}

function HorizonBadge({ entry, titleKey }: { entry: ConsolidatedHorizon; titleKey: MessageKey }) {
  const { t } = useI18n()
  const finalAction = entry.final_action
  const technicalAction = entry.technical?.action ?? null
  const changed = technicalAction != null && finalAction !== technicalAction

  return (
    <div className="flex flex-col items-start gap-0.5">
      <span className="text-[9px] uppercase tracking-wide text-slate-500 dark:text-slate-400">{t(titleKey)}</span>
      <span
        className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ${finalAction ? (ACTION_TONE[finalAction] ?? NEUTRAL_TONE) : NEUTRAL_TONE}`}
      >
        {finalAction ? actionLabel(t, finalAction) : t('unavailable')}
      </span>
      {changed ? <span className="text-[9px] text-slate-400 line-through">{actionLabel(t, technicalAction)}</span> : null}
    </div>
  )
}

function AnalyzeButton({ symbol, onSelectSymbol }: { symbol: string; onSelectSymbol?: (symbol: string) => void }) {
  const { t } = useI18n()
  if (!onSelectSymbol) return null
  return (
    <button
      type="button"
      onClick={() => onSelectSymbol(symbol)}
      className="rounded-full border border-slate-300 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-700 transition hover:border-slate-900 hover:text-slate-950 dark:border-slate-600 dark:text-slate-300 dark:hover:border-slate-300 dark:hover:text-white"
    >
      {t('analyze')} →
    </button>
  )
}

function DecisionRowView({ row, onSelectSymbol }: { row: DecisionRow; onSelectSymbol?: (symbol: string) => void }) {
  const { t } = useI18n()

  if (row.error) {
    return (
      <tr>
        <td className="px-3 py-2 font-semibold text-slate-800 dark:text-slate-100">{row.symbol}</td>
        <td colSpan={6} className="px-3 py-2 text-[11px] text-rose-700 dark:text-rose-400">
          {t('decisionBoardRowError', { symbol: row.symbol, message: row.error.message })}
        </td>
        <td className="px-3 py-2">
          <AnalyzeButton symbol={row.symbol} onSelectSymbol={onSelectSymbol} />
        </td>
      </tr>
    )
  }

  const decision = row.consolidated_decision
  const hurdleStatus = decision.index_hurdle?.status ?? 'unavailable'
  const stance = decision.fundamentals?.stance ?? 'unavailable'

  return (
    <tr>
      <td className="px-3 py-2">
        <div className="font-semibold text-slate-800 dark:text-slate-100">{row.symbol}</div>
        {row.company_name ? <div className="text-[11px] text-slate-500 dark:text-slate-400">{row.company_name}</div> : null}
        {decision.errors ? (
          <div className="text-[10px] text-rose-600 dark:text-rose-400">
            {t('consolidatedDecisionUnavailable', {
              reason: decision.errors.technical ?? decision.errors.index_hurdle ?? '',
            })}
          </div>
        ) : null}
      </td>
      <td className="px-3 py-2 tabular-nums text-slate-700 dark:text-slate-300">{money(row.current_price)}</td>
      {HORIZONS.map(({ key, title }) => (
        <td key={key} className="px-3 py-2">
          <HorizonBadge entry={decision.horizons[key]} titleKey={title} />
        </td>
      ))}
      <td className="px-3 py-2">
        <span className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ${STATUS_TONE[hurdleStatus] ?? NEUTRAL_TONE}`}>
          {t(STATUS_KEYS[hurdleStatus] ?? 'hurdleUnavailable')}
        </span>
      </td>
      <td className="px-3 py-2 text-[11px] text-slate-600 dark:text-slate-400">
        {t(STANCE_KEYS[stance] ?? 'stanceUnavailable')}
      </td>
      <td className="px-3 py-2">
        <AnalyzeButton symbol={row.symbol} onSelectSymbol={onSelectSymbol} />
      </td>
    </tr>
  )
}

/**
 * One row per watched symbol: current price, the consolidated Short/Mid/Long
 * action (Vincent's own action struck through when the final one differs),
 * the index hurdle chip, and the fundamentals stance. Fetches `/decisions` in
 * chunks of CHUNK_SIZE symbols, matching the Worker's subrequest budget, and
 * renders each row as soon as its chunk resolves. Rows sort buy-first, then
 * hold, then trim/sell/avoid (by the mid horizon's final action), with an
 * optional toggle to show only rows that pass the index hurdle.
 */
export function DecisionBoard({ symbols, onSelectSymbol }: DecisionBoardProps) {
  const { t } = useI18n()
  const [rows, setRows] = useState<Record<string, DecisionRow>>({})
  const [hurdleOnly, setHurdleOnly] = useState(false)
  const key = symbols.join('|')

  // Stable sort: ties keep the input order, so a symbol's position only moves
  // once its own chunk resolves, not because some other row's data arrived.
  const orderedSymbols = useMemo(() => {
    const visible = hurdleOnly ? symbols.filter((symbol) => passesIndexHurdle(rows[symbol])) : symbols
    return [...visible].sort((a, b) => actionRank(rows[a]) - actionRank(rows[b]))
  }, [symbols, rows, hurdleOnly])

  useEffect(() => {
    setRows({})
    if (!symbols.length) return

    const controller = new AbortController()
    const chunks: string[][] = []
    for (let i = 0; i < symbols.length; i += CHUNK_SIZE) chunks.push(symbols.slice(i, i + CHUNK_SIZE))

    chunks.forEach((chunk) => {
      fetchDecisions(chunk, controller.signal)
        .then((response) => {
          setRows((prev) => {
            const next = { ...prev }
            for (const row of response.results) next[row.symbol] = row
            return next
          })
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return
          const message = error instanceof Error ? error.message : String(error)
          setRows((prev) => {
            const next = { ...prev }
            for (const symbol of chunk) next[symbol] = { symbol, error: { code: 'request_failed', message } }
            return next
          })
        })
    })

    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  if (!symbols.length) {
    return <p className="text-[12px] text-slate-500 dark:text-slate-400">{t('decisionBoardEmpty')}</p>
  }

  return (
    <div className="space-y-2">
      <label className="flex w-fit items-center gap-2 text-[11px] text-slate-600 dark:text-slate-400">
        <input
          type="checkbox"
          checked={hurdleOnly}
          onChange={(event) => setHurdleOnly(event.target.checked)}
          className="h-3.5 w-3.5 rounded border-slate-300 dark:border-slate-600"
        />
        {t('decisionBoardHurdleFilter')}
      </label>
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-[#0d0f14]">
        <table className="w-full min-w-[720px] text-left text-[12px]">
          <thead className="text-slate-500 dark:text-slate-400">
            <tr>
              <th className="px-3 py-2 font-medium">{t('symbol')}</th>
              <th className="px-3 py-2 font-medium">{t('currentPrice')}</th>
              {HORIZONS.map(({ key: horizonKey, title }) => (
                <th key={horizonKey} className="px-3 py-2 font-medium">
                  {t(title)}
                </th>
              ))}
              <th className="px-3 py-2 font-medium">{t('indexHurdle')}</th>
              <th className="px-3 py-2 font-medium">{t('fundamentals')}</th>
              <th className="px-3 py-2 font-medium">{t('actions')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {orderedSymbols.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-3 py-2 text-[11px] text-slate-400 dark:text-slate-500">
                  {t('decisionBoardEmpty')}
                </td>
              </tr>
            ) : (
              orderedSymbols.map((symbol) => {
                const row = rows[symbol]
                if (!row) {
                  return (
                    <tr key={symbol}>
                      <td className="px-3 py-2 font-semibold text-slate-800 dark:text-slate-100">{symbol}</td>
                      <td colSpan={7} className="px-3 py-2 text-[11px] text-slate-400 dark:text-slate-500">
                        {t('decisionBoardLoading')}
                      </td>
                    </tr>
                  )
                }
                return <DecisionRowView key={symbol} row={row} onSelectSymbol={onSelectSymbol} />
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
