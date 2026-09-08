import type { Direction, Recommendation } from '../api/types'
import { formatDirection } from '../formatters'
import { useI18n } from '../i18n'

type TechnicalByHorizonPanelProps = {
  recommendation: Recommendation
}

const directionTone: Record<Direction, string> = {
  BUY: 'text-green-700 dark:text-green-400',
  HOLD: 'text-amber-700 dark:text-amber-400',
  SELL: 'text-red-700 dark:text-red-400',
}

/**
 * Shows Vincent's short/mid/long verdicts side by side.
 *
 * His engine emits these independently, with no overall action (AGENTS.md).
 * Rendering them as three columns, rather than one blended number, is what
 * keeps that independence visible instead of collapsing it in the UI.
 */
export function TechnicalByHorizonPanel({ recommendation }: TechnicalByHorizonPanelProps) {
  const { locale } = useI18n()
  const entries = recommendation.technical_by_horizon
  if (!entries || entries.length === 0) {
    return null
  }

  return (
    <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/40">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-600 dark:text-slate-300">
        Technical by horizon
      </p>
      <p className="mt-1 text-[12px] text-slate-600 dark:text-slate-400">
        Vincent's engine, short/mid/long. Independent calls, never averaged.
      </p>

      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
        {entries.map(({ horizon, verdict }) => (
          <div
            key={horizon}
            className="rounded-md border border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-[#0d0f14]"
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                {horizon}
              </span>
              <span className={`text-sm font-medium ${directionTone[verdict.direction]}`}>
                {formatDirection(verdict.direction, locale)}
              </span>
            </div>
            <p className="mt-1 text-[12px] text-slate-600 dark:text-slate-400">
              {(verdict.confidence * 100).toFixed(0)}% confidence
              {verdict.price_state ? ` · ${verdict.price_state.toLowerCase().replace(/_/g, ' ')}` : ''}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
